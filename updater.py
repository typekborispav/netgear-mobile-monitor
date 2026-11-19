"""Aktualizace aplikace z GitHub Releases (bez závislosti na Qt).

Postup:
1. `check()` se zeptá GitHub API na poslední release repozitáře
   (`version.GITHUB_REPO`) a porovná jeho tag `vX.Y.Z` s `version.__version__`.
2. `download(info)` stáhne instalátor (`NetgearMonitor-Setup-X.Y.Z.exe`) do %TEMP%
   a **ověří podpis** `.sig` (ECDSA P-256) veřejným klíčem `SIGNING_KEY`
   zabudovaným v aplikaci. Podepsaný text obsahuje verzi, název souboru a
   SHA-256 instalátoru (`signed_text`). Soukromý klíč je jen na počítači
   autora (tools/release-key.ps1), takže ani převzatý GitHub účet nepodstrčí
   falešnou verzi. Bez platného podpisu se instalátor nespustí. Ověřený soubor
   zůstane otevřený se zákazem zápisu, dokud se aplikace neukončí – nikdo ho
   mezi ověřením a spuštěním nezamění.
3. `install(path)` spustí instalátor potichu (`/SILENT`) s potvrzením UAC
   (aplikace je v Program Files) a aplikace se hned ukončí. Instalátor
   přepíše soubory a aplikaci znovu spustí pod původním uživatelem.

Instalace funguje jen v zabaleném běhu (`sys.frozen`); ze zdrojáků se jen
nabídne odkaz na stránku release.

CLI test:  python updater.py
"""

import base64
import hashlib
import os
import re
import struct
import subprocess
import sys
import tempfile

import requests

from version import GITHUB_REPO, __version__

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_REPO}/releases/download/"

# Veřejná část klíče, kterým autor podepisuje vydání (ECDSA P-256,
# SubjectPublicKeyInfo v base64). Vypíše ji: pwsh tools/release-key.ps1 -Public
SIGNING_KEY = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAElrgTYY5o8PIVGvScDlCHy8IiT7A1AIGqvCbmoqg2WCSbGgD6V/g+o3uHWvVNESq9DP11tdc8rft6bOVB+mApLw=="
_P256_SPKI_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")
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

    assets = rel.get("assets", [])
    setup = next((a for a in assets if a.get("name", "").lower().endswith(".exe")
                  and "setup" in a.get("name", "").lower()), None)
    sig = next((a for a in assets if setup
                and a.get("name") == setup.get("name") + ".sig"), None)

    def url(a):
        u = (a or {}).get("browser_download_url") or ""
        return u if u.startswith(DOWNLOAD_PREFIX) else None

    return {
        "version": ".".join(map(str, parse_version(tag))),
        "notes": (rel.get("body") or "").strip(),
        "html_url": rel.get("html_url") or "",
        "asset_url": url(setup),
        "asset_name": setup.get("name") if setup else None,
        "asset_size": setup.get("size", 0) if setup else 0,
        "sig_url": url(sig),
    }


def signed_text(version, file_name, sha256):
    """Přesně tento text podepisuje tools/release.ps1 (Get-SignedText). Verze
    a název souboru v něm brání vydávat starý podepsaný instalátor za nový."""
    return (f"netgear-mobile-monitor release\nversion={version}\n"
            f"file={file_name}\nsha256={sha256.lower()}\n")


def verify_signature(message, signature, key_b64=None):
    """Ověří podpis ECDSA P-256/SHA-256 (formát r||s, 64 B) přes Windows CNG."""
    if sys.platform != "win32" or len(signature) != 64:
        return False
    try:
        spki = base64.b64decode(key_b64 or SIGNING_KEY, validate=True)
    except ValueError:
        return False
    if len(spki) != 91 or not spki.startswith(_P256_SPKI_PREFIX):
        return False
    import ctypes
    blob = struct.pack("<II", 0x31534345, 32) + spki[27:]   # BCRYPT_ECCPUBLIC_BLOB „ECS1“
    bc = ctypes.windll.bcrypt
    bc.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                               ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    bc.BCryptImportKeyPair.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p,
                                       ctypes.c_ulong, ctypes.c_ulong]
    bc.BCryptVerifySignature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                                         ctypes.c_ulong, ctypes.c_char_p, ctypes.c_ulong,
                                         ctypes.c_ulong]
    for f in (bc.BCryptOpenAlgorithmProvider, bc.BCryptImportKeyPair, bc.BCryptVerifySignature):
        f.restype = ctypes.c_long
    alg, key = ctypes.c_void_p(), ctypes.c_void_p()
    if bc.BCryptOpenAlgorithmProvider(ctypes.byref(alg), "ECDSA_P256", None, 0) != 0:
        return False
    try:
        if bc.BCryptImportKeyPair(alg, None, "ECCPUBLICBLOB", ctypes.byref(key),
                                  blob, len(blob), 0) != 0:
            return False
        try:
            digest = hashlib.sha256(message).digest()
            return bc.BCryptVerifySignature(key, None, digest, len(digest),
                                            signature, len(signature), 0) == 0
        finally:
            bc.BCryptDestroyKey(key)
    finally:
        bc.BCryptCloseAlgorithmProvider(alg, 0)


_locked = None                              # otevřený ověřený instalátor (zámek)


def _release_lock():
    global _locked
    if _locked is not None:
        try:
            _locked.close()
        except OSError:
            pass
        _locked = None


def _open_locked(path):
    """Otevře soubor jen pro čtení a ZAKÁŽE ostatním zápis i smazání, dokud
    je otevřený (Windows share mode FILE_SHARE_READ)."""
    if sys.platform != "win32":
        return open(path, "rb")
    import ctypes
    import msvcrt
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    k32.CreateFileW.restype = ctypes.c_void_p
    h = k32.CreateFileW(path, 0x80000000, 0x1, None, 3, 0x80, None)   # GENERIC_READ, SHARE_READ, OPEN_EXISTING
    if h in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.GetLastError(), "instalátor nelze zamknout", path)
    return os.fdopen(msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY), "rb")


def _signature(info):
    r = requests.get(info["sig_url"], headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        return base64.b64decode(r.text.strip(), validate=True)
    except ValueError as e:
        raise ValueError("podpis vydání je poškozený") from e


def download(info, progress=None, cancelled=None):
    """Stáhne instalátor a ověří podpis. Vrací cestu k ověřenému souboru.

    progress(done_bytes, total_bytes) – volitelný callback (z vlákna stahování),
    cancelled() → True přeruší stahování (vyhodí InterruptedError).
    """
    global _locked
    if not info.get("asset_url"):
        raise ValueError("vydání neobsahuje instalátor")
    if not info.get("sig_url"):
        raise ValueError("vydání není podepsané – instalátor se nespustí")
    _release_lock()
    signature = _signature(info)

    folder = os.path.join(tempfile.gettempdir(), "NetgearMonitor-update")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(info["asset_name"]))
    part = path + ".part"

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
                done += len(chunk)
                if progress:
                    progress(done, total)

    os.replace(part, path)
    f = _open_locked(path)                  # od teď soubor nikdo nezmění
    try:
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
        text = signed_text(info["version"], os.path.basename(path), h.hexdigest())
        if not verify_signature(text.encode("utf-8"), signature):
            raise ValueError("podpis nesedí – instalátor se nespustí")
    except BaseException:
        f.close()
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    _locked = f                             # zámek drží do konce aplikace
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
        _release_lock()
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
