"""Práce na pozadí: čtení routeru, speedtest, kontrola a stažení aktualizace.

Všechno běží v obyčejných **daemon vláknech** (ne QThread) – při ukončení
aplikace tak nic nečeká na zaseknutý síťový požadavek. Výsledky se do GUI
posílají přes Qt signály objektů žijících v hlavním vlákně; emit z cizího
vlákna Qt automaticky doručí frontou (thread-safe).
"""

import threading
import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import QObject, Signal

import bts
import config
import device
import metered
import netgear as n
import speedtest as st
import updater
import usage

HISTORY_LEN = 120                           # vzorků RSRP/SINR pro graf


class Poller(QObject):
    """Pravidelně čte model.json z routeru a vysílá snímek stavu."""

    updated = Signal(object)                # dict snímku (viz _snapshot)
    roamingChanged = Signal(bool, object)   # roaming, {via_router, ssid, metered}
    usageAlert = Signal(str, int, object)   # druh (home/roam), úroveň %, stav

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roaming = None                # poslední známý stav roamingu
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._reconfigure = False
        self._bts_busy = False
        self.history = deque(maxlen=HISTORY_LEN)   # (čas, rsrp, sinr)
        self.snapshot = {"ok": False, "sig": None, "data": None, "ts": None,
                         "err": None, "bts": ("none", ""), "starting": True}

    # --- API z GUI vlákna ---
    def start(self):
        threading.Thread(target=self._run, name="poller", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def poll_now(self):
        self._wake.set()

    def reconfigure(self):
        """Po uložení nastavení: znovu načíst IP/heslo a přihlásit se.
        Provede se ve vlákně polleru, ať se nepere o sdílenou session."""
        self._reconfigure = True
        self._wake.set()

    # --- vlákno ---
    def _run(self):
        n.login_to_router()
        while not self._stop.is_set():
            if self._reconfigure:
                self._reconfigure = False
                n.apply_config()
                n.login_to_router()
            self._poll_once()
            try:
                interval = max(5, int(config.get("poll_s")))
            except (TypeError, ValueError):
                interval = 30
            self._wake.wait(interval)
            self._wake.clear()

    def _poll_once(self):
        snap = dict(self.snapshot, starting=False)
        fresh_usage = None
        try:
            data = n.get_model()
            sig = n.collect_signal(data) if data else None
            if sig is None and config.get("password"):   # session vypršela?
                n.login_to_router()
                data = n.get_model()
                sig = n.collect_signal(data) if data else None
            if data:
                snap["device"] = device.identify(data)
                self._remember_device(snap["device"])
            if sig is not None:
                mcc, mnc = sig.get("mcc"), sig.get("mnc")
                self._maybe_update_bts(mcc, mnc)
                snap.update(ok=True, sig=sig, data=data, ts=datetime.now(), err=None,
                            bts=bts.lookup(sig["cell_id"], sig["lac"], mcc, mnc))
                self.history.append((time.time(), _f(sig.get("rsrp")),
                                     _f(sig.get("sinr"))))
                try:
                    fresh_usage = usage.update(data)
                except Exception:           # noqa: BLE001 – kniha nesmí shodit poll
                    fresh_usage = None
                if fresh_usage:
                    snap["usage"] = fresh_usage
                self._check_roaming(sig.get("roaming") is True)
            else:
                snap.update(ok=False, err="no_router")
        except Exception as e:              # noqa: BLE001 – vlákno nesmí spadnout
            snap.update(ok=False, err=str(e))
        snap["need_password"] = not config.get("password")
        snap["router_changed"] = n.last_login_error == "unknown_router"
        self.snapshot = snap
        self.updated.emit(snap)
        for kind, level in (fresh_usage or {}).get("new_alerts") or []:  # jen z tohoto čtení
            self.usageAlert.emit(kind, level, fresh_usage)

    def _check_roaming(self, roaming):
        """Při změně roamingu (i při startu rovnou v roamingu) zjistí, jestli jde
        internet tohoto PC přes router a jestli je jeho Wi-Fi měřená; v režimu
        „auto" měřené připojení rovnou přepne (a po návratu domů vrátí)."""
        prev, self._roaming = self._roaming, roaming
        owned = config.get("metered_owned") or ""
        if prev == roaming or (prev is None and not roaming and not owned):
            return
        via = config.get("router_ip") in device.default_gateways()
        ssid = metered.current_ssid() if via else None
        info = {"via_router": via, "ssid": ssid, "metered": metered.is_metered(ssid),
                "action": None}
        if config.get("metered_mode") == "auto":
            if roaming and via and info["metered"] is False:
                ok = metered.set_metered(ssid, True)
                info["action"] = "set" if ok else "failed"
                if ok:
                    info["metered"] = True
                    config.save({"metered_owned": ssid})
            elif not roaming and owned:
                # Vrátit jen síť, kterou jsme přepnuli my (i když teď není připojená).
                ok = metered.set_metered(owned, False)
                info.update(action="reverted" if ok else "failed", ssid=owned)
                if ok:
                    config.save({"metered_owned": ""})
        self.roamingChanged.emit(roaming, info)

    @staticmethod
    def _remember_device(info):
        """Uloží název modelu, ať se po příštím startu ukáže hned (jen při změně)."""
        name = info.get("name") or ""
        if name and name != config.get("device_name"):
            config.save({"device_name": name})

    def _maybe_update_bts(self, mcc, mnc):
        """BTS databáze sítě, ve které router je (stáhne max 1× týdně, v pozadí)."""
        if self._bts_busy or not bts.needs_update(mcc, mnc):
            return
        self._bts_busy = True

        def work():
            try:
                bts.update(False, mcc, mnc)
            finally:
                self._bts_busy = False
        threading.Thread(target=work, name="bts-update", daemon=True).start()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class DeviceFinder(QObject):
    """Najde router Netgear v síti (výchozí brána + obvyklé adresy) ve vlákně."""

    found = Signal(object, object)          # ip|None, info|None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def start(self, extra=()):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                ip, info = device.discover(extra)
            except Exception:               # noqa: BLE001
                ip, info = None, None
            self.busy = False
            self.found.emit(ip, info)
        threading.Thread(target=work, name="discover", daemon=True).start()


class SpeedTester(QObject):
    """Ruční speedtest (~75 MB) ve vlákně. Guard na roaming řeší volající."""

    started = Signal()
    finished = Signal(object)               # dict výsledku
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.last = st.last_result()

    def start(self):
        if self.running:
            return False
        self.running = True
        self.started.emit()
        threading.Thread(target=self._run, name="speedtest", daemon=True).start()
        return True

    def _run(self):
        try:
            res = st.measure()
        except Exception as e:              # noqa: BLE001
            self.running = False
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.last = res
        self.running = False                # před emitem – GUI už vidí konec
        self.finished.emit(res)

    @staticmethod
    def history(limit=50):
        """Posledních `limit` měření ze speed_log.csv (nejnovější první)."""
        import csv
        try:
            with open(st.SPEED_LOG, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except OSError:
            return []
        return list(reversed(rows))[:limit]


class UpdateWorker(QObject):
    """Kontrola a stažení aktualizace ve vlákně."""

    checked = Signal(object, bool)          # info|None, manual
    check_failed = Signal(str, bool)
    progress = Signal(int, int)
    downloaded = Signal(str)
    download_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._cancel = False

    def check(self, manual=False):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                self.checked.emit(updater.check(), manual)
            except Exception as e:          # noqa: BLE001
                self.check_failed.emit(f"{type(e).__name__}", manual)
            finally:
                self.busy = False
        threading.Thread(target=work, name="update-check", daemon=True).start()

    def download(self, info):
        if self.busy:
            return
        self.busy = True
        self._cancel = False

        def work():
            try:
                path = updater.download(info, progress=self.progress.emit,
                                        cancelled=lambda: self._cancel)
                self.downloaded.emit(path)
            except Exception as e:          # noqa: BLE001
                self.download_failed.emit(str(e))
            finally:
                self.busy = False
        threading.Thread(target=work, name="update-download", daemon=True).start()

    def cancel(self):
        self._cancel = True
