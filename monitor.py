"""Hlídač událostí Netgear M3 -> WhatsApp upozornění.

Periodicky čte stav a posílá zprávu jen při ZMĚNĚ (žádný spam):
  • výpadek / obnovení připojení k síti,
  • přechod do/z roamingu,
  • změna typu sítě (5G <-> 4G ...),
  • přehřátí zařízení (s hysterezí) nebo kritická teplota.

Spuštění:
    python monitor.py            # kontrola po 30 s
    python monitor.py 60         # po 60 s

Vyžaduje běžící Baileys most (whatsapp-bridge) a nastavené WA_TO v notifier.py.
"""

import sys
import time

import bts
import netgear as n
from notifier import notify, wa_connected

INTERVAL = 30           # s mezi kontrolami
TEMP_WARN = 50          # °C – práh přehřátí zařízení
TEMP_CLEAR = 45         # °C – pod tím se přehřátí "odhlásí" (hystereze)


def snapshot():
    """Sebere stav relevantní pro alerty, nebo None při výpadku spojení."""
    data = n.get_model()
    if not data:
        return None
    wwan = data.get("wwan", {})
    adv = data.get("wwanadv", {})
    return {
        "connected": wwan.get("connection") == "Connected",
        "roaming": bool(wwan.get("roaming")),
        "net": wwan.get("connectionText", "?"),
        "operator": (wwan.get("registerNetworkDisplay")
                     or data.get("sim", {}).get("SPN") or "?"),
        "temp": data.get("general", {}).get("devTemperature"),
        "temp_crit": bool(data.get("power", {}).get("deviceTempCritical")),
        "cell": adv.get("cellId"),
        "lac": adv.get("LAC"),
        "mcc": adv.get("MCC"),
        "mnc": adv.get("MNC"),
    }


def _bts_text(snap):
    """Popis BTS pro alert: 'cell <id> – <umístění>' (nebo jen oblast/holé ID)."""
    kind, loc = bts.lookup(snap.get("cell"), snap.get("lac"),
                           snap.get("mcc"), snap.get("mnc"))
    if kind == "exact":
        return f"cell {snap['cell']} – {loc}"
    if kind == "oblast":
        return f"cell {snap['cell']} (oblast {loc})"
    return f"cell {snap['cell']}"


def run(interval=INTERVAL):
    if not n.login_to_router():
        return
    print(f"Most připojen k WhatsApp: {wa_connected()}")

    # Výchozí stav načteme hned, ať start nepůsobí jako "obnovení spojení".
    prev = snapshot()
    # BTS databáze pro síť, ve které router právě je (CZ: T-Mobile/O2/Vodafone).
    net = (prev.get("mcc"), prev.get("mnc")) if prev else (bts.DEFAULT_MCC, bts.DEFAULT_MNC)
    if bts.needs_update(*net):
        print(f"Aktualizuji BTS databázi… {bts.update(False, *net)[1]}")
    if prev:
        notify(f"🟢 Netgear monitor spuštěn: {prev['net']} ({prev['operator']}). "
               f"{_bts_text(prev)}.")
    else:
        notify("🟢 Netgear monitor spuštěn (router zatím nedostupný).")
    overheating = False
    print(f"Hlídám každých {interval} s (Ctrl+C ukončí)…")

    try:
        while True:
            cur = snapshot()

            # Výpadek / obnovení spojení s routerem samotným.
            if cur is None:
                if prev is not None:
                    notify("🔴 Router nedostupný – ztráta spojení.")
                    prev = None
                n.login_to_router()
                time.sleep(interval)
                continue
            if prev is None:
                notify(f"🟢 Spojení s routerem obnoveno: {cur['net']} "
                       f"({cur['operator']}). {_bts_text(cur)}.")

            # Mobilní síť (router běží, ale ztratil/chytil signál sítě).
            if prev and cur["connected"] != prev["connected"]:
                if cur["connected"]:
                    notify(f"🟢 Mobilní síť obnovena: {cur['net']} "
                           f"({cur['operator']}). {_bts_text(cur)}.")
                else:
                    notify("🔴 Ztráta mobilní sítě (router běží, síť odpojena).")

            # Roaming.
            if prev and cur["roaming"] != prev["roaming"]:
                if cur["roaming"]:
                    notify(f"✈️ ROAMING: přepnuto na {cur['operator']} ({cur['net']}).")
                else:
                    notify(f"🏠 Konec roamingu, zpět doma: {cur['operator']}.")

            # Změna typu sítě (5G <-> 4G ...).
            if prev and cur["net"] != prev["net"]:
                notify(f"📶 Změna sítě: {prev['net']} → {cur['net']}.")

            # Handover – přechod na jinou buňku (s lokalizací BTS).
            if prev and cur["cell"] and cur["cell"] != prev["cell"]:
                notify(f"📡 Handover na novou BTS: {_bts_text(cur)}.")

            # Přehřátí (s hysterezí) + kritická teplota.
            t = cur["temp"]
            if cur["temp_crit"]:
                if not overheating:
                    notify(f"🌡️ KRITICKÁ teplota zařízení ({t}°C)!")
                    overheating = True
            elif isinstance(t, (int, float)):
                if not overheating and t >= TEMP_WARN:
                    notify(f"🌡️ Zařízení se zahřívá: {t}°C (práh {TEMP_WARN}°C).")
                    overheating = True
                elif overheating and t <= TEMP_CLEAR:
                    notify(f"❄️ Teplota zpět v normě: {t}°C.")
                    overheating = False

            prev = cur
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitor ukončen.")


if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else INTERVAL
    run(sec)
