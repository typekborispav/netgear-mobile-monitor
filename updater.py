"""Aktualizace aplikace z GitHub Releases (bez závislosti na Qt).

Postup:
1. `check()` se zeptá GitHub API na poslední release repozitáře
   (`version.GITHUB_REPO`) a porovná jeho tag `vX.Y.Z` s `version.__version__`.
2. `download(info)` stáhne instalátor (`NetgearMonitor-Setup-X.Y.Z.exe`) do %TEMP%
   a **ověří SHA-256** proti souboru `.sha256` z téhož release. Bez kontrolního
   součtu nebo při neshodě se instalátor nespustí.
3. `install(path)` spustí instalátor potichu (`/SILENT`) s potvrzením UAC
   (aplikace je v Program Files) a aplikace se hned ukončí. Instalátor
   přepíše soubory a aplikaci znovu spustí pod původním uživatelem.

Instalace funguje jen v zabaleném běhu (`sys.frozen`); ze zdrojáků se jen
nabídne odkaz na stránku release.

CLI test:  python updater.py
"""

import hashlib
import os
import re
import subprocess
import sys
import tempfile

import requests

from version import GITHUB_REPO, __version__

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
TIMEOUT = 15
HEADERS = {"Accept": "application/vnd.github+json",
           "User-Agent": "NetgearMobileMonitor-Updater"}


def parse_version(text):
    """'v2.1.0' / '2.1' → (2, 1, 0). Neparsovatelné → (0,)."""
    m = re.search(r"(\d+(?:\.\d+)*)", str(text or ""))
    if not m:
        return (0,)
    parts = [int(p) for p in m.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def can_self_install():
    """Samoinstalace dává smysl jen u nainstalovaného exe (ne ze zdrojáků)."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def check():
    """Vrátí dict s informacemi o NOVĚJŠÍ verzi, nebo None (aktuální).

    Při chybě sítě/API vyhodí výjimku (volající ji zobrazí nebo zahodí).
    Klíče: version, notes, html_url, asset_url, asset_name, asset_size,
    sha256_url.
    """
    r = requests.get(API_LATEST, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        return None                        # zatím žádný release
    r.raise_for_status()
    rel = r.json()
    tag = rel.get("tag_name", "")
    if rel.get("draft") or rel.get("prerelease") or not is_newer(tag):
        return None

    setup = sha = None
    for a in rel.get("assets", []):
        name = a.get("name", "")
        low = name.lower()
        if low.endswith(".exe") and "setup" in low:
            setup = a
        elif low.endswith(".sha256"):
            sha = a
    return {
        "version": ".".join(map(str, parse_version(tag))),
        "notes": (rel.get("body") or "").strip(),
        "html_url": rel.get("html_url") or "",
        "asset_url": setup.get("browser_download_url") if setup else None,
        "asset_name": setup.get("name") if setup else None,
        "asset_size": setup.get("size", 0) if setup else 0,
        "sha256_url": sha.get("browser_download_url") if sha else None,
    }


def _expected_sha256(info):
    """Načte očekávaný hash z .sha256 assetu ('<hex>  <soubor>' nebo jen hex)."""
    r = requests.get(info["sha256_url"], headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    for line in r.text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        name = parts[-1].lstrip("*") if len(parts) > 1 else None
        if name is None or name == info["asset_name"]:
            h = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", h):
                return h
    raise ValueError("kontrolní součet v .sha256 nenalezen")


def download(info, progress=None, cancelled=None):
    """Stáhne instalátor a ověří SHA-256. Vrací cestu k ověřenému souboru.

    progress(done_bytes, total_bytes) – volitelný callback (z vlákna stahování),
    cancelled() → True přeruší stahování (vyhodí InterruptedError).
    """
    if not info.get("asset_url") or not info.get("sha256_url"):
        raise ValueError("release neobsahuje instalátor nebo kontrolní součet")
    expected = _expected_sha256(info)

    folder = os.path.join(tempfile.gettempdir(), "NetgearMonitor-update")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(info["asset_name"]))
    part = path + ".part"

    h = hashlib.sha256()
    done = 0
    with requests.get(info["asset_url"], headers=HEADERS, stream=True,
                      timeout=TIMEOUT) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or info.get("asset_size") or 0)
        with open(part, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if cancelled and cancelled():
                    raise InterruptedError("stahování zrušeno")
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)

    if h.hexdigest() != expected:
        os.remove(part)
        raise ValueError("kontrolní součet nesedí – stažený soubor zahozen")
    os.replace(part, path)
    return path


class Cancelled(Exception):
    """Uživatel nepotvrdil oprávnění správce (UAC)."""


def install(path):
    """Spustí ověřený instalátor potichu, s oprávněním správce (UAC).

    Aplikace je v Program Files, takže instalátor potřebuje práva správce.
    Spouští se přes ShellExecute „runas": dotaz UAC proběhne HNED tady – když
    ho uživatel odmítne, vyhodí se `Cancelled` a aplikace běží dál (nic se
    neukončí naprázdno). Po úspěšném spuštění se má volající ukončit;
    instalátor aplikaci po dokončení znovu spustí pod původním uživatelem
    (viz [Run] v packaging/installer.iss).
    """
    args = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"
    if sys.platform != "win32":
        subprocess.Popen([path] + args.split(), close_fds=True)
        return
    try:
        os.startfile(path, "runas", args)
    except OSError as e:
        if getattr(e, "winerror", None) == 1223:        # ERROR_CANCELLED
            raise Cancelled() from e
        raise


if __name__ == "__main__":
    print(f"Lokální verze: {__version__}  (repo {GITHUB_REPO})")
    try:
        info = check()
    except Exception as e:                  # noqa: BLE001 – jen diagnostika
        print(f"Kontrola selhala: {e}")
    else:
        print(f"Nová verze: {info['version']} – {info['html_url']}" if info
              else "Aplikace je aktuální.")
