"""Živý dashboard Netgear M3 v terminálu.

Obnovuje se v intervalu, čte data přes netgear.py (login + model.json).
Ukazuje síť, signál, carrier aggregation, pásma, baterii, teplotu a klienty.

Klávesa `s` spustí měření rychlosti (speedtest.py) v pozadí; výsledek se
zobrazí v řádku „Rychlost" a uloží do speed_log.csv.

Spuštění:
    python dashboard.py            # obnova po 3 s
    python dashboard.py 1          # obnova po 1 s
"""

import sys
import threading
import time
from datetime import datetime

import bts
import netgear as n
import speedtest as st

CLEAR = "\033[2J\033[H"   # ANSI: smaž obrazovku + kurzor doleva nahoru
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
GREEN, YELLOW, RED, CYAN = "\033[32m", "\033[33m", "\033[31m", "\033[36m"

# Sdílený stav speedtestu mezi vláknem měření a překreslováním.
_speed = {"running": False, "last": st.last_result()}

# Stav automatické aktualizace BTS databáze (běží v pozadí, max 1×/týden).
_dbupd = {"running": False, "msg": None}


# ── Cross-platform čtení kláves (Windows msvcrt / Linux termios) ──────────────
# Pi Zero 2 běží na Linuxu, kde se neblokující stisk řeší přes termios+select;
# na Windows přes msvcrt. Když výstup není terminál (systemd), klávesy se vypnou.
if sys.platform == "win32":
    import msvcrt

    def term_setup():
        return True

    def term_restore():
        pass

    def read_key():
        return msvcrt.getwch().lower() if msvcrt.kbhit() else None
else:
    import select
    import termios
    import tty

    _saved_term = None

    def term_setup():
        global _saved_term
        if not sys.stdin.isatty():
            return False
        _saved_term = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return True

    def term_restore():
        if _saved_term is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _saved_term)

    def read_key():
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1).lower()
        return None


def _rsrp_q(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return DIM + "?" + RESET
    if v >= -80:
        return GREEN + "výborný" + RESET
    if v >= -90:
        return GREEN + "dobrý" + RESET
    if v >= -100:
        return YELLOW + "slabší" + RESET
    return RED + "špatný" + RESET


def _sinr_q(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return DIM + "?" + RESET
    if v >= 20:
        return GREEN + "výborná" + RESET
    if v >= 13:
        return GREEN + "dobrá" + RESET
    if v >= 0:
        return YELLOW + "průměr" + RESET
    return RED + "rušení" + RESET


def _bars(n_bars):
    try:
        n_bars = int(n_bars)
    except (TypeError, ValueError):
        n_bars = 0
    return GREEN + "▮" * n_bars + DIM + "▯" * (5 - n_bars) + RESET


def _uptime(seconds):
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "?"
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return (f"{d}d " if d else "") + f"{h}h {m}m"


def parse_ca(data):
    """Z wwan.lteBandInfo poskládá čitelný popis agregace nosných."""
    parts = []
    for c in data.get("wwan", {}).get("lteBandInfo", []) or []:
        band = c.get("band") if isinstance(c, dict) else None
        if not band:                       # přeskoč prázdné a junk (band 0)
            continue
        tag = "PCC" if c.get("isPcc") else "SCC"
        parts.append(f"B{band}@{c.get('dlBandwidth', '?')} ({tag})")
    return parts


def band_region(data):
    """Aktuálně zvolený režim sítě (název z bandRegion s current=true)."""
    for r in data.get("wwan", {}).get("bandRegion", []) or []:
        if isinstance(r, dict) and r.get("current"):
            return r.get("name", "?")
    return "?"


def _age(iso):
    """Lidsky čitelné stáří timestampu ('před 12 min', 'před 2 h')."""
    try:
        delta = datetime.now() - datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return "?"
    s = int(delta.total_seconds())
    if s < 60:
        return "teď"
    if s < 3600:
        return f"před {s // 60} min"
    if s < 86400:
        return f"před {s // 3600} h"
    return f"před {s // 86400} d"


def _run_speedtest():
    """Změří rychlost v pozadí (volá tiché speedtest.measure) a uloží výsledek."""
    try:
        _speed["last"] = st.measure()
    except Exception:                  # síťová chyba: nech předchozí výsledek být
        pass
    finally:
        _speed["running"] = False


def trigger_speedtest(roaming):
    """Spustí speedtest ve vlákně – jen doma a když právě neběží jiný."""
    if _speed["running"] or roaming is True:
        return
    _speed["running"] = True
    threading.Thread(target=_run_speedtest, daemon=True).start()


def _db_update():
    """Stáhne čerstvou BTS DB (volá bts.update) – běží v pozadí."""
    try:
        _, _dbupd["msg"] = bts.update()
    finally:
        _dbupd["running"] = False


def maybe_update_db():
    """Když je DB starší než týden a neběží stahování, spustí ho ve vlákně."""
    if _dbupd["running"] or not bts.needs_update():
        return
    _dbupd["running"] = True
    threading.Thread(target=_db_update, daemon=True).start()


def _db_status():
    """Krátký stav BTS databáze do patičky (stáří / aktualizuji / chybí)."""
    if _dbupd["running"]:
        return f"{YELLOW}BTS DB: aktualizuji…{RESET}"
    age = bts.db_age_s()
    if age is None:
        return f"{RED}BTS DB: chybí{RESET}"
    txt = f"{age / 86400:.0f} d" if age >= 86400 else f"{age / 3600:.0f} h"
    return f"{DIM}BTS DB: {txt}{RESET}"


def _speed_line(roaming):
    """Řádek 'Rychlost' podle stavu (běží / poslední výsledek / roaming / nikdy)."""
    if _speed["running"]:
        return f"{YELLOW}⏳ měřím… (~75 MB){RESET}"
    if roaming is True:
        return f"{DIM}— (roaming, vypnuto){RESET}"
    r = _speed["last"]
    if not r:
        return f"{DIM}— (stiskni 's' pro test){RESET}"
    return (f"{GREEN}↓ {r.get('download_mbps', '?')}{RESET}  "
            f"{GREEN}↑ {r.get('upload_mbps', '?')}{RESET} Mbit/s   "
            f"{DIM}{r.get('latence_ms', '?')} ms   ({_age(r.get('cas'))}){RESET}")


def render(data, sig):
    w = data.get("wwan", {})
    power = data.get("power", {})
    gen = data.get("general", {})
    diag = (w.get("diagInfo") or [{}])[0]

    roam = f"{RED}ROAMING{RESET}" if sig["roaming"] else f"{GREEN}domácí{RESET}"
    chrg = (f"{YELLOW}nabíjí{RESET}" if power.get("charging")
            else f"{DIM}{power.get('battChargeSource', '?')}{RESET}")
    nr5g = (f"{GREEN}připojeno{RESET}" if diag.get("nr5gAttached")
            else f"{DIM}ne (NSA {'zap' if diag.get('endcEnabledConfig') else 'vyp'}){RESET}")
    ca = parse_ca(data)

    # Lokalizace BTS z kombinované databáze gsmweb (2G i LTE/5G ECI) – přesná
    # adresa vyjde i na 4G+/5G; když buňka v DB není, aspoň region podle LAC.
    bts_kind, bts_loc = bts.lookup(sig["cell_id"], sig["lac"],
                                  sig.get("mcc"), sig.get("mnc"))
    if bts_kind == "exact":
        bts_line = f"{GREEN}{bts_loc}{RESET}"
    elif bts_kind == "oblast":
        bts_line = f"{YELLOW}oblast {bts_loc}{RESET}  {DIM}(přibližně dle LAC){RESET}"
    else:
        bts_line = f"{DIM}neznámá (mimo databázi){RESET}"

    out = [
        f"{CLEAR}{BOLD}{CYAN}  📡 {gen.get('deviceName', 'Netgear M3')} "
        f"— {sig['cas'].replace('T', ' ')}{RESET}",
        f"  {DIM}{'─'*54}{RESET}",
        f"  Síť         {BOLD}{sig['sit']}{RESET}  ({sig['typ_sluzby']})   {roam}",
        f"  Operátor    {sig['operator']}   {DIM}MCC/MNC {sig['mcc']}/{sig['mnc']}{RESET}",
        f"  Režim       {band_region(data)}",
        f"  5G NR       {nr5g}",
        f"  {DIM}{'─'*54}{RESET}",
        f"  Signál      {_bars(sig['bars'])}   "
        f"RSRP {sig['rsrp']} dBm [{_rsrp_q(sig['rsrp'])}]  "
        f"SINR {sig['sinr']} dB [{_sinr_q(sig['sinr'])}]",
        f"  Agregace    {' + '.join(ca) if ca else DIM+'jedna nosná'+RESET}",
        f"  Buňka       cell {sig['cell_id']}   LAC {sig['lac']}   "
        f"{DIM}band {sig['band']}{RESET}",
        f"  BTS         {bts_line}",
        f"  {DIM}{'─'*54}{RESET}",
        f"  Baterie     {power.get('battChargeLevel', '?')}%  ({chrg})   "
        f"{power.get('batteryVoltage', '?')} mV   bat {power.get('batteryTemperature', '?')}°C",
        f"  Teplota     zařízení {gen.get('devTemperature', '?')}°C   "
        f"stav {w.get('thermalState', '?')}",
        f"  Klienti     {data.get('wifi', {}).get('clientCount', '?')} WiFi   "
        f"{DIM}uptime {_uptime(gen.get('upTime'))}{RESET}",
        f"  Rychlost    {_speed_line(sig['roaming'])}",
        f"  {DIM}{'─'*54}{RESET}",
        f"  {DIM}s = speedtest{RESET} · {_db_status()} {DIM}· Ctrl+C ukončí{RESET}",
    ]
    print("\n".join(out))


def _wait(interval, roaming):
    """Čeká `interval` s, ale průběžně poll-uje klávesy ('s' = speedtest)."""
    end = time.monotonic() + interval
    while time.monotonic() < end:
        key = read_key()
        if key == "s":
            trigger_speedtest(roaming)
            return                     # hned překresli, ať se ukáže „měřím…"
        if key in ("q", "\x03"):       # q nebo Ctrl+C
            raise KeyboardInterrupt
        time.sleep(0.1)


def run(interval=3):
    if not n.login_to_router():
        return
    keys = term_setup()
    if not keys:
        print(f"{DIM}(bez terminálu – klávesa 's' pro speedtest nedostupná){RESET}")
    last_roaming = False
    try:
        while True:
            maybe_update_db()          # 1×/týden stáhne čerstvou BTS DB v pozadí
            data = n.get_model()
            sig = n.collect_signal(data) if data else None
            if sig is None:
                n.login_to_router()
                _wait(interval, last_roaming)
                continue
            last_roaming = sig["roaming"]
            render(data, sig)
            _wait(interval, last_roaming)
    except KeyboardInterrupt:
        print(f"\n{RESET}Dashboard ukončen.")
    finally:
        term_restore()


if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run(sec)
