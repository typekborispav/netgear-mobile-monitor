"""Měření rychlosti internetu přes Netgear M3 — RUČNÍ, jen v domácí síti.

Záměrně **NEběží automaticky** (nemá smyčku ani interval) — měří se jen na
vyžádání: buď `python speedtest.py`, nebo stiskem `s` v dashboardu. Test stahuje
a nahrává data přes Cloudflare (`speed.cloudflare.com`), takže **spotřebuje
mobilní data** (default ~50 MB down + ~25 MB up). Žádná nová závislost — `requests`.

**Guard na roaming:** `run()` čte stav z routeru (`netgear`); v roamingu nebo při
nedostupném routeru se test NESPUSTÍ. (Dashboard si roaming hlídá sám a volá
přímo tiché `measure()`, aby se nepral o globální session netgearu.)

Výsledek se ukládá do `speed_log.csv` (čte ho dashboard pro zobrazení).

Spuštění:
    python speedtest.py            # plný test (~75 MB)
    python speedtest.py 10 5       # jen 10 MB down + 5 MB up (MB)
"""

import csv
import os
import sys
import time
from datetime import datetime

import requests

import config
import netgear as n

DOWN_URL = "https://speed.cloudflare.com/__down"
UP_URL = "https://speed.cloudflare.com/__up"

DOWNLOAD_BYTES = 50_000_000   # ~50 MB stahování
UPLOAD_BYTES = 25_000_000     # ~25 MB nahrávání
PING_COUNT = 6                # počet měření latence
TIMEOUT = 120                 # s na request

# V zabaleném exe se loguje do %APPDATA% (vedle exe zapisovat nelze/nezmizí).
if getattr(sys, "frozen", False):
    SPEED_LOG = os.path.join(config.data_dir(), "speed_log.csv")
else:
    SPEED_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "speed_log.csv")
LOG_FIELDS = ["cas", "download_mbps", "upload_mbps", "latence_ms"]

GREEN, YELLOW, RED, DIM, BOLD, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")


def _mbps(num_bytes, seconds):
    """Bajty + čas → Mbit/s (0 při nesmyslném čase)."""
    if not seconds or seconds <= 0:
        return 0.0
    return num_bytes * 8 / seconds / 1_000_000


def _latency(sess):
    """Změří RTT několika malými dotazy; vrátí (min, avg) v ms nebo (None, None)."""
    times = []
    for _ in range(PING_COUNT):
        try:
            t0 = time.perf_counter()
            sess.get(DOWN_URL, params={"bytes": 0}, timeout=10).content
            times.append((time.perf_counter() - t0) * 1000)
        except requests.RequestException:
            pass
    if not times:
        return None, None
    return min(times), sum(times) / len(times)


def _download(sess, num_bytes):
    """Stáhne num_bytes a vrátí (Mbit/s, skutečně přeneseno)."""
    t0 = time.perf_counter()
    total = 0
    r = sess.get(DOWN_URL, params={"bytes": num_bytes}, stream=True, timeout=TIMEOUT)
    r.raise_for_status()               # chybovou odpověď neměř jako download
    for chunk in r.iter_content(65536):
        if total == 0:                 # start měř až po prvním bajtu (vynech TTFB)
            t0 = time.perf_counter()
        total += len(chunk)
    return _mbps(total, time.perf_counter() - t0), total


def _upload(sess, num_bytes):
    """Nahraje num_bytes a vrátí (Mbit/s, přeneseno)."""
    payload = b"\0" * num_bytes
    t0 = time.perf_counter()
    r = sess.post(UP_URL, data=payload, timeout=TIMEOUT)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()               # odmítnutý upload není platné měření
    return _mbps(num_bytes, elapsed), num_bytes


def measure(down_bytes=DOWNLOAD_BYTES, up_bytes=UPLOAD_BYTES):
    """Tiché měření (BEZ tisku, BEZ kontroly roamingu). Vrátí slovník výsledku.

    Vlastní `requests.Session` (keep-alive) – nesahá na globální session netgearu,
    takže je bezpečné volat z vlákna dashboardu. Výsledek rovnou uloží do CSV.
    """
    sess = requests.Session()
    lat_min, _ = _latency(sess)
    down_mbps, _ = _download(sess, down_bytes)
    up_mbps, _ = _upload(sess, up_bytes)
    res = {
        "cas": datetime.now().isoformat(timespec="seconds"),
        "download_mbps": round(down_mbps, 1),
        "upload_mbps": round(up_mbps, 1),
        "latence_ms": round(lat_min) if lat_min is not None else "",
    }
    save_result(res)
    return res


def save_result(res):
    """Připojí výsledek do speed_log.csv (hlavička jen do nového souboru)."""
    new = not os.path.exists(SPEED_LOG) or os.path.getsize(SPEED_LOG) == 0
    with open(SPEED_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(res)


def last_result():
    """Poslední řádek ze speed_log.csv jako slovník, nebo None."""
    try:
        with open(SPEED_LOG, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return rows[-1] if rows else None
    except OSError:
        return None


def _home_ok():
    """True jen když je router dostupný a NEjsme v roamingu (guard pro CLI)."""
    if not n.login_to_router():
        print(f"{RED}✗ Router nedostupný – nelze ověřit roaming. Test zrušen.{RESET}")
        return False
    sig = n.collect_signal()
    if sig is None:
        print(f"{RED}✗ Stav sítě nedostupný. Test zrušen.{RESET}")
        return False
    if sig.get("roaming") is True:
        print(f"{RED}✗ Jsi v ROAMINGU ({sig.get('operator')}). "
              f"Speedtest se v zahraničí nespouští.{RESET}")
        return False
    print(f"{DIM}Domácí síť: {sig.get('sit')} ({sig.get('operator')}), "
          f"signál {sig.get('bars')}/5.{RESET}")
    return True


def run(down_bytes=DOWNLOAD_BYTES, up_bytes=UPLOAD_BYTES):
    """CLI běh: guard na roaming + měření + výpis."""
    if not _home_ok():
        return None
    print(f"{DIM}Měřím (~{(down_bytes + up_bytes) // 1_000_000} MB dat)…{RESET}")
    res = measure(down_bytes, up_bytes)
    lat = f"{res['latence_ms']} ms" if res["latence_ms"] != "" else "?"
    print(f"  Latence    {lat}")
    print(f"  Download   {GREEN}{BOLD}{res['download_mbps']} Mbit/s{RESET}")
    print(f"  Upload     {GREEN}{BOLD}{res['upload_mbps']} Mbit/s{RESET}")
    return res


if __name__ == "__main__":
    d = int(sys.argv[1]) * 1_000_000 if len(sys.argv) > 1 else DOWNLOAD_BYTES
    u = int(sys.argv[2]) * 1_000_000 if len(sys.argv) > 2 else UPLOAD_BYTES
    print(f"{BOLD}📊 Speedtest přes Netgear M3{RESET}")
    try:
        run(d, u)
    except requests.RequestException as e:
        print(f"{RED}✗ Chyba sítě během testu: {e}{RESET}")
    except KeyboardInterrupt:
        print(f"\n{DIM}Přerušeno.{RESET}")
