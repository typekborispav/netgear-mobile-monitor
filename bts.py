"""Lokalizace BTS z databází gsmweb.cz – pro všechny české sítě.

Zdroj: `https://gsmweb.cz/android/combined/<MCC><MNC>.clf` – **kombinované**
databáze, které obsahují i **LTE/5G buňky s velkým cellId (ECI)**, takže přesná
adresa vyjde i na 4G+/5G. Databáze se vybírá podle sítě, ve které je router
právě přihlášený (MCC/MNC z `wwanadv`):

    230/01 T-Mobile CZ · 230/02 O2 CZ · 230/03 Vodafone CZ

Mimo tyto sítě (např. roaming v zahraničí) lokalizace vrací ('none', '').

Formát `.clf` (UTF-8, oddělovač ';', 7 sloupců):  MCC;MNC;LAC;CID;;;Umisteni
Popis umístění začíná zkratkou okresu (např. "OV …").

Výchozí síť funkcí je 230/03 (Vodafone CZ) – kvůli zpětné kompatibilitě
CLI skriptů (dashboard, monitor), které síť nepředávají.
"""

import csv
import os
import sys
import time

import requests

import config

URL_TMPL = "https://gsmweb.cz/android/combined/{plmn}.clf"
SUPPORTED = {"23001": "T-Mobile CZ", "23002": "O2 CZ", "23003": "Vodafone CZ"}
DEFAULT_MCC, DEFAULT_MNC = 230, 3
MAX_AGE_S = 7 * 24 * 3600          # přestáří DB → automaticky stáhnout (1 týden)

# V zabaleném exe (PyInstaller) by cesta vedle __file__ mířila do dočasného
# rozbalovacího adresáře – tam patří DB do %APPDATA%.
if getattr(sys, "frozen", False):
    DB_DIR = config.data_dir()
else:
    DB_DIR = os.path.dirname(os.path.abspath(__file__))

_cache = {}   # plmn -> (by_cell {(cid, lac): loc}, by_lac {lac: {okres: n}})


def _to_int(v):
    """Bezpečně na int (router/CSV občas vrátí prázdno nebo 'N/A')."""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def plmn(mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    """(230, 3) → '23003'; neplatné → None."""
    mcc, mnc = _to_int(mcc), _to_int(mnc)
    if mcc is None or mnc is None:
        return None
    return f"{mcc:03d}{mnc:02d}"


def supported(mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    return plmn(mcc, mnc) in SUPPORTED


def db_path(mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    return os.path.join(DB_DIR, f"{plmn(mcc, mnc)}.clf")


def db_url(mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    return URL_TMPL.format(plmn=plmn(mcc, mnc))


def _okres(loc):
    """Vytáhne zkratku okresu z prefixu popisu ("OV Ostrava…")."""
    head = loc.split(" ", 1)[0]
    return head if 1 <= len(head) <= 3 and head.isupper() else "?"


def _load(p):
    """Líně načte CLF dané sítě do indexů. Chybějící soubor → prázdné indexy."""
    if p in _cache:
        return _cache[p]
    by_cell, by_lac = {}, {}
    try:
        with open(os.path.join(DB_DIR, f"{p}.clf"), encoding="utf-8", newline="") as f:
            for row in csv.reader(f, delimiter=";"):
                if len(row) < 7:
                    continue
                lac, cid = _to_int(row[2]), _to_int(row[3])
                if cid is None or lac is None:
                    continue
                loc = row[6].strip()
                by_cell[(cid, lac)] = loc
                okres = _okres(loc)
                by_lac.setdefault(lac, {})
                by_lac[lac][okres] = by_lac[lac].get(okres, 0) + 1
    except OSError:
        return by_cell, by_lac              # necachovat – po stažení zkusit znovu
    _cache[p] = (by_cell, by_lac)
    return _cache[p]


def lookup(cell_id, lac, mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    """Najde umístění buňky. Vrací (kind, text):

    - ('exact', "…adresa…")     přesná shoda CID+LAC (2G i LTE/5G),
    - ('oblast', "OV, KI, …")   jen region podle LAC (buňka není v DB),
    - ('none', "")              nenalezeno / síť bez databáze.
    """
    p = plmn(mcc, mnc)
    if p not in SUPPORTED:
        return ("none", "")
    by_cell, by_lac = _load(p)
    cid, l = _to_int(cell_id), _to_int(lac)
    if l is None:
        return ("none", "")
    loc = by_cell.get((cid, l))
    if loc:
        return ("exact", loc)
    okresy = by_lac.get(l)
    if okresy:
        top = sorted(okresy, key=okresy.get, reverse=True)
        return ("oblast", ", ".join(o for o in top[:4] if o != "?"))
    return ("none", "")


def db_age_s(mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    """Stáří lokální DB v sekundách, nebo None když soubor chybí."""
    try:
        return time.time() - os.path.getmtime(db_path(mcc, mnc))
    except OSError:
        return None


def needs_update(mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    """True, když DB podporované sítě chybí nebo je starší než týden."""
    if not supported(mcc, mnc):
        return False
    age = db_age_s(mcc, mnc)
    return age is None or age > MAX_AGE_S


def update(force=False, mcc=DEFAULT_MCC, mnc=DEFAULT_MNC):
    """Stáhne čerstvou databázi sítě, je-li starší než týden (nebo chybí/force).

    Stáhne do `.tmp`, ověří rozumnost obsahu a teprve pak atomicky přepíše
    původní soubor. Offline/chyba → ponechá starou DB. Vrací (changed, zpráva).
    """
    if not supported(mcc, mnc):
        return (False, "síť bez databáze")
    if not force and not needs_update(mcc, mnc):
        return (False, "aktuální")
    path = db_path(mcc, mnc)
    tmp = path + ".tmp"
    try:
        r = requests.get(db_url(mcc, mnc), timeout=60)
        r.raise_for_status()
        data = r.content
        # sanity: soubor má stovky kB a CSV strukturu (ne HTML chybovou stránku)
        if len(data) < 100_000 or b";" not in data[:200]:
            return (False, "neplatná odpověď serveru")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except (requests.RequestException, OSError) as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return (False, f"offline/chyba ({type(e).__name__})")
    _cache.pop(plmn(mcc, mnc), None)        # vynuť reload nové DB
    return (True, "aktualizováno")


if __name__ == "__main__":            # rychlý test/diagnostika
    cid = sys.argv[1] if len(sys.argv) > 1 else 1400577
    lac = sys.argv[2] if len(sys.argv) > 2 else 31015
    print(f"cell={cid} lac={lac} -> {lookup(cid, lac)}")
    print(f"neexistujici buňka  -> {lookup(999999999, 31015)}")
