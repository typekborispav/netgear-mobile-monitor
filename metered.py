"""Měřené připojení Windows pro Wi-Fi routeru (zjištění stavu + přepnutí).

V roamingu aplikace (režim `metered_mode="auto"`) přepne Wi-Fi profil, přes
který jde internet tohoto PC, na měřený (`netsh wlan set profileparameter
cost=Fixed`) a po návratu domů ho vrátí na neměřený – ale jen když ho
přepnula ona (`config.metered_owned`). Ověřeno: na Windows 11 to jde bez práv
správce. Když přepnutí selže, aplikace jen upozorní a nabídne Nastavení Windows.

Na měřeném připojení Windows nestahují automaticky aktualizace, Store
neaktualizuje aplikace a OneDrive může pozastavit synchronizaci. Týká se jen
tohoto počítače – ostatní zařízení na routeru to neovlivní.
"""

import re
import subprocess
import sys

SETTINGS_URI = "ms-settings:network-wifi"   # Wi-Fi → vlastnosti sítě → Měřené připojení


def _netsh(*args):
    if sys.platform != "win32":
        return ""
    try:
        return subprocess.run(["netsh", "wlan", *args], capture_output=True, text=True,
                              timeout=8, creationflags=subprocess.CREATE_NO_WINDOW,
                              errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def current_ssid():
    """SSID právě připojené Wi-Fi, nebo None (kabel / Wi-Fi vypnutá)."""
    m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", _netsh("show", "interfaces"), re.M)
    return m.group(1) if m else None


def profile_cost(ssid):
    """Nastavení nákladů Wi-Fi profilu: 'Unrestricted' (neměřené), 'Fixed' /
    'Variable' (měřené), nebo None když nejde zjistit."""
    if not ssid:
        return None
    out = _netsh("show", "profile", f"name={ssid}")
    m = re.search(r"\b(Unrestricted|Fixed|Variable)\b", out)
    return m.group(1) if m else None


def is_metered(ssid):
    cost = profile_cost(ssid)
    return None if cost is None else cost != "Unrestricted"


def set_metered(ssid, on):
    """Nastaví Wi-Fi profil jako měřený (`on=True`, cost=Fixed) nebo neměřený.
    Vrací True, jen když to po zápisu skutečně tak je."""
    if not ssid:
        return False
    _netsh("set", "profileparameter", f"name={ssid}",
           f"cost={'Fixed' if on else 'Unrestricted'}")
    return is_metered(ssid) is on


def open_settings():
    if sys.platform == "win32":
        import os
        os.startfile(SETTINGS_URI)


if __name__ == "__main__":
    s = current_ssid()
    print(f"Wi-Fi: {s!r}, náklady: {profile_cost(s)}, měřené: {is_metered(s)}")
