"""Trvalé nastavení aplikace (router IP, heslo, interval) v JSON souboru.

Heslo je na Windows na disku zašifrované (DPAPI, viz `_protect`).

Soubor je per-uživatel **mimo repozitář** (`%APPDATA%\\NetgearMonitor\\config.json`
na Windows, `~/.config/netgear-monitor/config.json` na Linuxu/Pi), takže si každý
nastaví svoje údaje a heslo se neukládá do gitu. Když soubor chybí, použijí se
DEFAULTS – původní natvrdo zadané hodnoty – takže stávající chování je stejné.

Použití:
    import config
    ip = config.get("router_ip")
    config.save({"router_ip": "192.168.1.1", "password": "…", "poll_s": 30})
"""

import base64
import json
import os
import sys

# Výchozí hodnoty. Heslo záměrně prázdné – skutečné heslo patří JEN do
# uživatelského config.json (%APPDATA%), nikdy do zdrojáku/repozitáře.
DEFAULTS = {
    "router_ip": "192.168.1.1",
    "password": "",
    "poll_s": 30,
    "lang": "cs",
    "theme": "auto",            # auto (dle Windows) | light | dark
    "flyout_style": "high",     # průhlednost panelu u hodin: system | high | max
    "check_updates": True,      # při startu a 1× denně zkontrolovat GitHub
    "device_name": "",          # naposledy zjištěný model (zobrazí se hned po startu)
    "home_plan": "unlimited",   # tarif doma: unlimited | limited
    "home_limit_gb": 0,         # limit balíku u omezeného tarifu (GB)
    "roam_counts_home": True,   # roaming v EU se čerpá z domácího balíku (omezený tarif)
    "roam_limit_gb": 60,        # limit spravedlivého užívání (FUP) roamingu v EU (0 = bez)
    "billing_day": 0,           # den zúčtování 1–31 (0 = podle routeru)
    "metered_mode": "auto",     # měřené připojení v roamingu: auto | hint | off
    "metered_owned": "",        # SSID, které na měřené přepnula aplikace (vrátí ho)
    "pending_update": None,     # {"from", "to"} – spuštěný instalátor; po startu se ohlásí výsledek
    "router_id": "",            # otisk SIM routeru (hash ICCID) – heslo se posílá jen „svému“ routeru
}

# Na Windows se heslo ukládá na disk zašifrované přes DPAPI (dešifrovat ho jde
# jen pod stejným účtem Windows) v klíči "password_dpapi"; v paměti (load/get)
# je dál jako "password". Starý čitelný zápis se při načtení převede.
_ENC_KEY = "password_dpapi"
_ENTROPY = b"NetgearMonitor config password"


def _config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "NetgearMonitor")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "netgear-monitor")


CONFIG_PATH = os.path.join(_config_dir(), "config.json")


def data_dir():
    """Zapisovatelná složka pro data aplikace (BTS databáze, speed log…).

    Zabalené exe (PyInstaller) nemá vlastní složku na zápis – soubory vedle
    `__file__` by skončily v dočasném rozbalovacím adresáři a po ukončení
    zmizely. Proto data patří sem (= vedle config.json). Složku vytvoří.
    """
    d = _config_dir()
    os.makedirs(d, exist_ok=True)
    return d

_cache = None


def load(force=False):
    """Vrátí slovník nastavení (DEFAULTS přebité hodnotami ze souboru). Cachuje."""
    global _cache
    if _cache is not None and not force:
        return _cache
    cfg = dict(DEFAULTS)
    data = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        else:
            data = {}
    except (FileNotFoundError, ValueError, OSError):
        pass                                 # chybí/poškozený soubor → DEFAULTS
    if data.get(_ENC_KEY):
        cfg["password"] = _unprotect(data[_ENC_KEY])
    _cache = cfg
    if sys.platform == "win32" and data.get("password"):
        try:
            save({})                         # převod starého čitelného hesla na šifrované
        except OSError:
            pass
    return cfg


def get(key):
    return load().get(key, DEFAULTS.get(key))


def save(values):
    """Sloučí `values` do nastavení a atomicky zapíše na disk. Vrátí nový dict."""
    global _cache
    cfg = dict(load())
    cfg.update({k: v for k, v in values.items() if k in DEFAULTS})
    disk = dict(cfg)
    if sys.platform == "win32":
        pw = disk.get("password") or ""
        disk["password"] = ""                # na disku jen zašifrované
        if pw:
            disk[_ENC_KEY] = _protect(pw)
    os.makedirs(_config_dir(), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(disk, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)             # atomická výměna
    _cache = cfg
    return cfg


# ── DPAPI (CryptProtectData) přes ctypes – bez další závislosti ───────────────
def _crypt(func, blob):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def mk(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    src, _keep1 = mk(blob)
    ent, _keep2 = mk(_ENTROPY)
    out = BLOB()
    fn = getattr(ctypes.windll.crypt32, func)
    fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.POINTER(BLOB),
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    # 1 = CRYPTPROTECT_UI_FORBIDDEN
    if not fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 1, ctypes.byref(out)):
        raise OSError(ctypes.GetLastError(), func)
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _protect(text):
    return base64.b64encode(_crypt("CryptProtectData", text.encode("utf-8"))).decode("ascii")


def _unprotect(b64):
    """Dešifruje heslo; jiný účet / jiný počítač → prázdné (průvodce se zeptá znovu)."""
    try:
        return _crypt("CryptUnprotectData", base64.b64decode(b64)).decode("utf-8")
    except (OSError, ValueError):
        return ""
