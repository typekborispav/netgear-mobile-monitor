import csv
import os
import sys
import time
from datetime import datetime

import requests

import config

# Windows konzole bývá cp1250 a padala by na emoji ve výpisech – vynutíme UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- KONFIGURACE ---
# IP a heslo se berou z config.py (uživatelský JSON v %APPDATA%). Když soubor
# chybí, použijí se výchozí hodnoty z config.DEFAULTS – chování zůstává stejné.
ROUTER_IP = config.get("router_ip")
ADMIN_PASSWORD = config.get("password")

BASE_URL = f"http://{ROUTER_IP}"


def apply_config():
    """Znovu načte IP/heslo z config.py a resetuje session.

    Volá se po změně nastavení (okno Nastavení v tray.py), aby se další dotazy
    rozběhly na novou adresu s novým heslem. Po volání je potřeba login_to_router().
    """
    global ROUTER_IP, ADMIN_PASSWORD, BASE_URL, session, sec_token
    config.load(force=True)
    ROUTER_IP = config.get("router_ip")
    ADMIN_PASSWORD = config.get("password")
    BASE_URL = f"http://{ROUTER_IP}"
    session = requests.Session()             # čerstvé spojení bez starých cookies
    sec_token = None

# Session si automaticky pamatuje cookies, token si držíme zvlášť,
# protože ho Netgear vyžaduje jak v hlavičce, tak v těle SMS požadavku.
session = requests.Session()
sec_token = None


def get_model():
    """Vrátí celý stavový strom routeru (model.json), nebo None při chybě.

    Router občas zavře recyklované keep-alive spojení (RemoteDisconnected).
    Při výpadku spojení proto jednou zkusíme znovu – Session otevře čerstvé
    spojení a re-login (s blikem operátora) tím pádem většinou není potřeba.
    """
    for attempt in range(2):
        try:
            res = session.get(f"{BASE_URL}/api/model.json", timeout=10)
            if res.status_code == 200:
                return res.json()
            print(f"❌ Selhalo načtení model.json. Kód: {res.status_code}")
            return None
        except requests.exceptions.ConnectionError:
            if attempt == 0:
                continue  # tiše zkus znovu s novým spojením
            print("❌ Spojení s routerem opakovaně selhalo.")
        except Exception as e:
            print(f"❌ Chyba při čtení model.json: {e}")
            return None
    return None


def login_to_router():
    """Přihlásí se do routeru a uloží secToken do globální session."""
    global sec_token
    if not ADMIN_PASSWORD:
        print("❌ Není nastaveno heslo routeru – doplňte ho v Nastavení (tray) "
              "nebo v config.json.")
        return False
    try:
        # KROK 1: Získání prvotního tokenu
        print("Získávám úvodní bezpečnostní token...")
        init_data = get_model()
        if not init_data:
            return False

        sec_token = init_data.get("session", {}).get("secToken")
        if not sec_token:
            print("❌ V JSONu nebyl nalezen secToken.")
            return False

        # KROK 2: Odeslání přihlašovacího formuláře
        # Posíláme jako surový urlencoded řetězec, který Netgear preferuje.
        print("Posílám přihlašovací údaje (zvýšený timeout)...")
        payload = (
            f"token={sec_token}"
            f"&session.password={ADMIN_PASSWORD}"
            f"&ok_redirect=%2Findex.html"
            f"&err_redirect=%2Findex.html"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-XSRF-TOKEN": sec_token,
        }
        # Zvýšen timeout na 15 s, router potřebuje čas na zpracování hesla.
        session.post(f"{BASE_URL}/Forms/config", data=payload, headers=headers, timeout=15)

        # Token přidáme do session pro všechny další požadavky.
        session.headers.update({"X-XSRF-TOKEN": sec_token})

        # POST vrací 200 i se špatným heslem – úspěch poznáme až podle role.
        # Správné heslo povýší session na Admin (stejná kontrola jako
        # test_connection v tray.py).
        check = get_model()
        role = str(((check or {}).get("session") or {}).get("userRole", "")).lower()
        if role != "admin":
            print(f"❌ Přihlášení selhalo – heslo nesedí (role: {role or '—'}).")
            return False

        print("✅ Přihlášení proběhlo.\n")
        return True

    except requests.exceptions.Timeout:
        print("❌ Chyba: Routeru trvalo zpracování hesla příliš dlouho (Timeout). Zkuste ho restartovat.")
        return False
    except Exception as e:
        print(f"❌ Chyba během přihlašování: {e}")
        return False


def get_router_data():
    """Vypíše vybraná stavová data routeru."""
    data = get_model()
    if not data:
        return

    wwan = data.get("wwan", {})
    power = data.get("power", {})

    print("=" * 40)
    print(f" Typ sítě: {wwan.get('currentPSserviceType', 'N/A')}")
    print(f" Operátor: {wwan.get('registerNetworkDisplay', 'N/A')}")
    print(f" Baterie:  {power.get('battChargeLevel', 'N/A')}%")
    print("=" * 40)


def send_sms(receiver, text):
    """Pokusí se odeslat SMS přes endpoint Forms/smsSendMsg.

    POZOR: U firmwaru platformy NTGX65 (M3 MH31xx, M6 Pro / MR6500) Netgear
    odebral oficiální možnost ODESÍLAT SMS. Endpoint proto pravděpodobně vrátí
    chybu nebo SMS tiše neodejde. Čtení (read_sms) funguje dál. Spolehlivé
    odeslání na tomto firmware vyžaduje root + AT příkazy přes /dev/smdX
    (viz samostatné projekty, např. JeffWDH/MR6500-SMS-Server).

    Vyžaduje předchozí úspěšné login_to_router() (kvůli sec_token).
    Vrací True při HTTP 200 (neznamená to zaručeně doručení).
    """
    if not sec_token:
        print("❌ Nejdřív se přihlaste (chybí secToken).")
        return False

    # Firmware NTGX65 hlásí podporu odesílání v model.json. Pokud je vypnutá,
    # endpoint požadavek stejně odmítne – nemá smysl ho volat.
    model = get_model()
    sms_cfg = model.get("sms", {}) if model else {}
    if not sms_cfg.get("sendSupported", False):
        print("❌ Zařízení hlásí sendSupported=false – firmware odesílání SMS nepodporuje.")
        print("   (Ověřeno na M3 MH3150 fw 12.x; obejít jde jen rootem, viz at_sms.py.)")
        return False

    try:
        # Pole odpovídají reverse-engineered Netgear API (knihovna eternalegypt).
        # requests slovník sám zakóduje (urlencode) – ošetří mezery i diakritiku.
        payload = {
            "token": sec_token,
            "sms.sendMsg.receiver": receiver,
            "sms.sendMsg.text": text,
            "sms.sendMsg.clientId": "netgear.py",
            "action": "send",
        }
        res = session.post(f"{BASE_URL}/Forms/smsSendMsg", data=payload, timeout=15)
        if res.status_code == 200:
            print(f"✅ SMS na {receiver} odeslána.")
            return True
        print(f"❌ Odeslání SMS selhalo. Kód: {res.status_code}")
    except Exception as e:
        print(f"❌ Chyba při odesílání SMS: {e}")
    return False


def read_sms():
    """Vypíše přijaté SMS uložené v routeru (model.json -> sms.msgs)."""
    data = get_model()
    if not data:
        return

    msgs = data.get("sms", {}).get("msgs", [])
    if not msgs:
        print("Žádné SMS.")
        return

    print(f"\n--- Přijaté SMS ({len(msgs)}) ---")
    for msg in msgs:
        unread = "" if msg.get("read") else "🔵 "
        print(f"{unread}[{msg.get('rxTime', '?')}] {msg.get('sender', '?')}: {msg.get('text', '')}")
    print("-" * 40)


# Router používá -32768 jako "hodnota nedostupná" u některých signálových polí.
_NA = -32768


def _clean(value):
    """Sentinel -32768 převede na prázdno, jinak vrátí hodnotu beze změny."""
    return "" if value == _NA else value


# Pořadí sloupců v CSV i v hlavičce (zároveň klíče slovníku z collect_signal).
SIGNAL_FIELDS = [
    "cas", "sit", "typ_sluzby", "operator", "roaming", "roaming_typ",
    "bars", "rssi", "rsrp", "rsrq", "sinr",
    "nr5g_rsrp", "nr5g_rsrq", "nr5g_sinr",
    "band", "radio_quality", "cell_id", "lac", "mcc", "mnc",
]


def collect_signal(data=None):
    """Sebere aktuální stav sítě, signálu a roamingu do plochého slovníku.

    Klíče odpovídají SIGNAL_FIELDS. Při nedostupných datech vrací None.
    """
    if data is None:
        data = get_model()
    if not data:
        return None

    wwan = data.get("wwan", {})
    adv = data.get("wwanadv", {})
    sig = wwan.get("signalStrength", {})

    # "operator" = živě registrovaná síť (v roamingu navštívená cizí síť!).
    # Když je jméno chvíli prázdné, zálohujeme MCC/MNC – to odpovídá SKUTEČNÉ
    # síti i v zahraničí. Záměrně NE sim.SPN: ten drží domácí jméno (Vodafone CZ)
    # a v roamingu by maskoval, že jsi v cizí síti.
    operator = (
        wwan.get("registerNetworkDisplay")
        or (f"MCC{adv.get('MCC')}/MNC{adv.get('MNC')}" if adv.get("MCC") else "N/A")
    )

    return {
        "cas": datetime.now().isoformat(timespec="seconds"),
        "sit": wwan.get("connectionText", "N/A"),            # 5G / 4G / 3G ...
        "typ_sluzby": wwan.get("currentPSserviceType", "N/A"),  # 5GSUB6, LTE ...
        "operator": operator,
        "roaming": wwan.get("roaming", "N/A"),               # True/False
        "roaming_typ": wwan.get("roamingType", "N/A"),       # Home / Roaming
        "bars": sig.get("bars", "N/A"),
        "rssi": _clean(sig.get("rssi", "")),
        "rsrp": _clean(sig.get("rsrp", "")),
        "rsrq": _clean(sig.get("rsrq", "")),
        "sinr": _clean(sig.get("sinr", "")),
        "nr5g_rsrp": _clean(sig.get("nr5gRsrp", "")),
        "nr5g_rsrq": _clean(sig.get("nr5gRsrq", "")),
        "nr5g_sinr": _clean(sig.get("nr5gSinr", "")),
        "band": adv.get("curBand", "N/A"),                   # např. "LTE B20"
        "radio_quality": adv.get("radioQuality", "N/A"),
        "cell_id": adv.get("cellId", "N/A"),                 # ID buňky (změna = handover)
        "lac": adv.get("LAC", "N/A"),                        # Location Area Code
        "mcc": adv.get("MCC", "N/A"),                        # kód země (CZ=230)
        "mnc": adv.get("MNC", "N/A"),                        # kód sítě (Vodafone CZ=03)
    }


def log_signal_loop(interval=60, path="signal_log.csv"):
    """Periodicky zapisuje stav signálu do CSV (interval v sekundách).

    Hlavičku zapíše jen do nového/prázdného souboru, jinak připojuje řádky.
    Při výpadku session se zkusí znovu přihlásit. Ukončení: Ctrl+C.
    """
    print(f"Loguji signál každých {interval} s do '{path}' (Ctrl+C ukončí)…")
    try:
        while True:
            row = collect_signal()
            if row is None:
                print("⚠️  Data nedostupná, zkouším znovu přihlásit…")
                login_to_router()
                row = collect_signal()

            if row:
                write_header = not os.path.exists(path) or os.path.getsize(path) == 0
                with open(path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=SIGNAL_FIELDS)
                    if write_header:
                        writer.writeheader()
                    writer.writerow(row)
                print(
                    f"{row['cas']}  {row['sit']:<4} {row['operator']:<12} "
                    f"bars={row['bars']} rsrp={row['rsrp']} sinr={row['sinr']} "
                    f"roaming={row['roaming']} band={row['band']} "
                    f"cell={row['cell_id']} lac={row['lac']}"
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nLogování ukončeno.")


# --- SPUŠTĚNÍ ---
if __name__ == "__main__":
    # Použití:
    #   python netgear.py            -> stav + SMS jednorázově
    #   python netgear.py log        -> logování signálu po 60 s
    #   python netgear.py log 30     -> logování po 30 s
    if login_to_router():
        if len(sys.argv) > 1 and sys.argv[1] == "log":
            seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 60
            log_signal_loop(interval=seconds)
        else:
            get_router_data()
            read_sms()
            # send_sms("+420123456789", "Ahoj z routeru")
