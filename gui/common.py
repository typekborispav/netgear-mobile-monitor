"""Sdílené pomůcky GUI: hodnocení signálu, formátování, autostart, test spojení,
motiv a barva zvýraznění převzaté z Windows.

Nic z toho nekreslí okna – jen čistá logika, kterou používá flyout, hlavní okno
i ikona v liště.
"""

import os
import sys

import requests
from PySide6.QtGui import QColor
from qfluentwidgets import isDarkTheme

import dashboard as dash
from i18n import t

# ── Stavové úrovně a jejich barvy (paleta Windows 11 „status" barev) ─────────
GOOD, WARN, BAD, NONE = "good", "warn", "bad", "none"

_LEVEL_COLORS = {
    #        světlý motiv  tmavý motiv
    GOOD: ("#0F7B0F", "#6CCB5F"),
    WARN: ("#9D5D00", "#FCE100"),
    BAD: ("#C42B1C", "#FF99A4"),
    NONE: ("#5D5D5D", "#9E9E9E"),
}


def level_color(level):
    light, dark = _LEVEL_COLORS.get(level, _LEVEL_COLORS[NONE])
    return QColor(dark if isDarkTheme() else light)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rsrp_quality(v):
    """RSRP (dBm) → (text, úroveň)."""
    v = _num(v)
    if v is None:
        return "—", NONE
    if v >= -80:
        return t("q_excellent"), GOOD
    if v >= -90:
        return t("q_good"), GOOD
    if v >= -100:
        return t("q_weak"), WARN
    return t("q_bad"), BAD


def sinr_quality(v):
    """SINR (dB) → (text, úroveň)."""
    v = _num(v)
    if v is None:
        return "—", NONE
    if v >= 20:
        return t("q_excellent"), GOOD
    if v >= 13:
        return t("q_good"), GOOD
    if v >= 0:
        return t("q_avg"), WARN
    return t("q_noise"), BAD


def bars_int(sig):
    try:
        return max(0, min(5, int((sig or {}).get("bars", 0))))
    except (TypeError, ValueError):
        return 0


def signal_level(sig):
    """Celková úroveň signálu – dle RSRP, fallback dle počtu čárek."""
    _, lvl = rsrp_quality((sig or {}).get("rsrp"))
    if lvl != NONE:
        return lvl
    b = bars_int(sig)
    return GOOD if b >= 4 else WARN if b >= 2 else BAD


def net_label(sig):
    """Krátký štítek typu sítě (5G / 4G+ / …)."""
    return ((sig or {}).get("sit") or "?").replace("Reg", "").strip() or "?"


def fmt(v, unit="", dash_="—"):
    """Hodnota s jednotkou, prázdné/None → pomlčka."""
    if v in (None, "", "N/A"):
        return dash_
    return f"{v} {unit}".strip()


def battery(data):
    """(procenta:int|None, popis zdroje) z model.json."""
    p = (data or {}).get("power", {}) or {}
    try:
        pct = int(p.get("battChargeLevel"))
    except (TypeError, ValueError):
        pct = None
    raw = str(p.get("battChargeSource") or "")
    src = {"charger": t("src_charger"), "battery": t("src_battery"),
           "usb": "USB"}.get(raw.lower(), raw)
    if p.get("charging"):
        src = t("charging")
    return pct, src


def battery_charging(data):
    return bool(((data or {}).get("power") or {}).get("charging"))


def battery_level(pct):
    if pct is None:
        return NONE
    return GOOD if pct > 40 else WARN if pct > 15 else BAD


def uptime(data):
    return dash._uptime(((data or {}).get("general") or {}).get("upTime"))


def ca_text(data):
    ca = dash.parse_ca(data or {})
    return " + ".join(ca) if ca else t("single_carrier")


def band_region(data):
    try:
        return dash.band_region(data or {})
    except Exception:
        return "—"


def nr_state(data):
    """5G NR (NSA) stav → (text, úroveň)."""
    w = (data or {}).get("wwan", {}) or {}
    diag = (w.get("diagInfo") or [{}])[0] or {}
    if diag.get("nr5gAttached"):
        return t("nr_connected"), GOOD
    nsa = t("on") if diag.get("endcEnabledConfig") else t("off")
    return t("nr_no", nsa), NONE


def gb(n_bytes):
    """Bajty → '8,65 GB' (v češtině s desetinnou čárkou)."""
    import i18n
    import usage
    s = usage.fmt_gb(n_bytes)
    return s.replace(".", ",") if i18n.lang() == "cs" else s


def _short_date(d):
    import i18n
    return f"{d.day}. {d.month}." if i18n.lang() == "cs" else d.strftime("%b %d")


def active_usage_kind(snap):
    """Počítadlo, které právě platí: v roamingu roaming, jinak domácí síť."""
    return "roam" if ((snap or {}).get("sig") or {}).get("roaming") is True else "home"


def usage_view(u, kind):
    """Počítadlo `kind` (home/roam) → (titulek, hodnota, detail, % limitu, úroveň)."""
    if not u:
        return None
    other = "roam" if kind == "home" else "home"
    lim, pct = u["limits"][kind], u["pct"][kind]
    value = f"{gb(u[kind])} / {lim} GB" if lim else gb(u[kind])
    detail = t("usage_detail", t(f"usage_{other}_short"), gb(u[other]),
               gb(u["total"]), _short_date(u["end"]))
    if u["since"] > u["start"]:
        detail += " · " + t("usage_since", _short_date(u["since"]))
    level = NONE if pct is None else BAD if pct >= 100 else WARN if pct >= 80 else GOOD
    return t(f"row_{kind}_data"), value, detail, pct, level


def apply_usage_bar(bar, pct):
    """ProgressBar limitu: žlutá od 80 %, červená od 100 %."""
    bar.setVisible(pct is not None)
    if pct is None:
        return
    bar.setValue(int(min(100, pct)))
    bar.setError(pct >= 100)
    bar.setPaused(80 <= pct < 100)


def device_name(snap=None):
    """Název routeru: z posledního snímku, jinak naposledy uložený, jinak „Netgear"."""
    import config
    dev = (snap or {}).get("device") or {}
    return dev.get("name") or config.get("device_name") or "Netgear"


def tooltip_text(snap):
    """Text nativního tooltipu ikony v liště (Windows ořízne na ~128 znaků)."""
    sig = snap.get("sig")
    name = device_name(snap)
    if not snap.get("ok") or sig is None:
        return f"{name} — {t('offline')}"[:127]
    roam = f" · {t('roaming')}" if sig.get("roaming") is True else ""
    pct, _ = battery(snap.get("data"))
    lines = [
        f"{name} · {net_label(sig)}{roam}",
        f"{sig.get('operator', '?')} · {bars_int(sig)}/5",
        f"RSRP {fmt(sig.get('rsrp'), 'dBm')} · SINR {fmt(sig.get('sinr'), 'dB')}",
        f"{t('row_batt')} {fmt(pct, '%')}",
    ]
    return "\n".join(lines)[:127]


# ── Autostart po přihlášení (HKCU\…\Run) ──────────────────────────────────────
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "NetgearMonitor"                # stejný název používá instalátor


def _pythonw_path():
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def autostart_cmd():
    """Příkaz pro Run klíč. Po přihlášení se spouští jen do lišty (--background)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "app.py")
    return f'"{_pythonw_path()}" "{entry}" --background'


def _read_run_value():
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_VALUE)[0]
    except OSError:
        return None


def autostart_enabled():
    return _read_run_value() is not None


def set_autostart(enable):
    if sys.platform != "win32":
        return
    import winreg
    if enable:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, autostart_cmd())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, RUN_VALUE)
        except OSError:
            pass


def repair_autostart():
    """Zapnutý autostart, který ukazuje jinam (stará exe/pythonw verze), přepíše
    na aktuálně nainstalované exe. Jen v zabaleném běhu – vývojový běh ze
    zdrojáků nesmí přebít autostart nainstalované aplikace."""
    if not getattr(sys, "frozen", False):
        return
    cur = _read_run_value()
    if cur is not None and cur != autostart_cmd():
        try:
            set_autostart(True)
        except OSError:
            pass


# ── Test spojení s routerem (pro Nastavení a průvodce) ────────────────────────
def test_connection(ip, password):
    """Ověří dostupnost routeru a heslo (role Admin). Vrací (ok, zpráva)."""
    base = f"http://{ip}"
    s = requests.Session()                  # login potřebuje cookie z úvodního GETu
    try:
        r = s.get(f"{base}/api/model.json", timeout=8)
        if r.status_code != 200:
            return False, t("tc_http", r.status_code)
        tok = r.json().get("session", {}).get("secToken")
        if not tok:
            return False, t("tc_no_token")
        payload = (f"token={tok}&session.password={password}"
                   f"&ok_redirect=%2Findex.html&err_redirect=%2Findex.html")
        s.post(f"{base}/Forms/config", data=payload, timeout=12, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-XSRF-TOKEN": tok})
        s.headers.update({"X-XSRF-TOKEN": tok})
        m = s.get(f"{base}/api/model.json", timeout=8).json()
        role = str((m.get("session", {}) or {}).get("userRole", "")).lower()
        if role == "admin":
            return True, t("tc_ok")
        return False, t("tc_bad_pw", role or "—")
    except requests.exceptions.RequestException as e:
        return False, t("tc_unreachable", type(e).__name__)
    except Exception as e:                  # noqa: BLE001
        return False, f"Error: {e}"


# ── Windows: motiv hlavního panelu a barva zvýraznění ─────────────────────────
_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_ACCENT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"


def _reg_dword(path, name):
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def taskbar_is_dark():
    """Hlavní panel má vlastní motiv (může být tmavý i při světlých aplikacích)."""
    v = _reg_dword(_PERSONALIZE, "SystemUsesLightTheme")
    return v != 1


def system_accent(dark):
    """Barva zvýraznění Windows ve variantě, jakou používají systémové aplikace:
    světlý motiv → AccentDark1, tmavý → AccentLight2 (z AccentPalette).
    Vrací QColor nebo None."""
    pal = _reg_dword(_ACCENT, "AccentPalette")
    if isinstance(pal, (bytes, bytearray)) and len(pal) >= 32:
        i = 1 if dark else 4
        r, g, b = pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2]
        return QColor(r, g, b)
    return None
