"""Detekce mobilního routeru Netgear (Nighthawk M1/M2/M3/M5/M6/M7…).

Všechny mobilní routery Netgear z rodiny Nighthawk mají stejné webové API
(`GET /api/model.json`, login přes `/Forms/config`). Model se pozná z
`model.json` → `general`:

- bez přihlášení: `deviceName` („Nighthawk M3"), `productSKU` („MH3150-100EUS"),
  `companyName`, `apiVersion`;
- po přihlášení navíc `model` („MH3150"), `FWversion`, `HWversion`.

`identify(data)` z model.json vytáhne popis zařízení, `probe(ip)` ověří, že na
adrese běží router Netgear, a `discover()` ho najde sám: zkusí výchozí bránu
počítače (když je PC připojené k Wi-Fi routeru, je to právě on) a obvyklé
adresy 192.168.1.1 / 192.168.0.1.
"""

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

# Záložní názvy podle čísla modelu – použijí se jen když router sám neposlal
# `deviceName`. Neznámý model se zobrazí svým kódem (API je stejné).
MODEL_NAMES = {
    "MR1100": "Nighthawk M1",
    "MR2100": "Nighthawk M2",
    "MH3150": "Nighthawk M3",
    "MR5100": "Nighthawk M5",
    "MR5200": "Nighthawk M5",
    "MR6110": "Nighthawk M6",
    "MR6150": "Nighthawk M6",
    "MR6500": "Nighthawk M6 Pro",
    "MR6550": "Nighthawk M6 Pro",
}

DEFAULT_IPS = ("192.168.1.1", "192.168.0.1", "192.168.5.1")
PROBE_TIMEOUT = 4


def identify(data):
    """Popis zařízení z model.json (funguje s přihlášením i bez něj).

    Vrací dict: name, model, sku, fw, hw, api. Chybějící hodnoty = "".
    """
    g = (data or {}).get("general", {}) or {}
    sku = str(g.get("productSKU") or "")
    model = str(g.get("model") or (sku.split("-")[0] if sku else ""))
    name = str(g.get("deviceName") or MODEL_NAMES.get(model.upper()) or model or "Netgear")
    return {
        "name": name,
        "model": model,
        "sku": sku,
        "fw": str(g.get("FWversion") or ""),
        "hw": str(g.get("HWversion") or ""),
        "api": str(g.get("apiVersion") or ""),
    }


def describe(info):
    """Krátký jednořádkový popis: 'Nighthawk M3 · MH3150 · fw NTGX65_12.01…'."""
    if not info:
        return ""
    parts = [info.get("name") or "Netgear"]
    if info.get("model") and info["model"] not in parts[0]:
        parts.append(info["model"])
    if info.get("fw"):
        parts.append(f"fw {info['fw']}")
    return " · ".join(parts)


def probe(ip, timeout=PROBE_TIMEOUT):
    """Je na adrese mobilní router Netgear? Vrací identify() nebo None."""
    try:
        r = requests.get(f"http://{ip}/api/model.json", timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    g = data.get("general") or {}
    company = str(g.get("companyName") or g.get("manufacturer") or "").upper()
    has_token = bool((data.get("session") or {}).get("secToken"))
    if "NETGEAR" not in company and not has_token:
        return None
    return identify(data)


def default_gateways():
    """Výchozí brány IPv4 tohoto počítače (bez zobrazení okna konzole)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["route", "print", "-4", "0.0.0.0"], capture_output=True, text=True,
                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout
            ips = re.findall(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)",
                             out, re.M)
        else:
            out = subprocess.run(["ip", "-4", "route", "show", "default"],
                                 capture_output=True, text=True, timeout=5).stdout
            ips = re.findall(r"via (\d+\.\d+\.\d+\.\d+)", out)
    except (OSError, subprocess.SubprocessError):
        ips = []
    seen = []
    for ip in ips:
        if ip not in seen and ip != "0.0.0.0":
            seen.append(ip)
    return seen


def discover(extra=()):
    """Najde router v síti. Vrací (ip, info) nebo (None, None).

    Pořadí kandidátů: zadané `extra` (např. IP z configu), výchozí brány,
    obvyklé adresy. Zkouší se paralelně, vyhrává první kandidát v pořadí.
    """
    cands = []
    for ip in list(extra) + default_gateways() + list(DEFAULT_IPS):
        if ip and ip not in cands:
            cands.append(ip)
    with ThreadPoolExecutor(max_workers=len(cands) or 1) as ex:
        results = list(ex.map(probe, cands))
    for ip, info in zip(cands, results):
        if info:
            return ip, info
    return None, None


if __name__ == "__main__":
    ip, info = discover()
    print(f"Nalezen: {describe(info)} na {ip}" if ip else "Router Netgear nenalezen.")
