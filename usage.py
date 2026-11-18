"""Spotřeba mobilních dat za zúčtovací období – celkem a v roamingu.

Zdroj jsou počítadla **routeru** (`model.json` → `wwan.dataUsage.generic`, jen
po přihlášení), takže zahrnují **všechna připojená zařízení**, ne jen tento PC:

- `dataTransferred`         přeneseno v aktuálním období routeru (bajty),
- `dataTransferredRoaming`  z toho v roamingu,
- `billingDay`              den v měsíci, kdy router počítadla nuluje.

Hodiny routeru nemusí jít správně (M3 ukazuje rok 2016) a uživatel může mít
u operátora jiný den zúčtování, než má router. Proto si aplikace vede vlastní
„knihu" (`usage.json` v datové složce):

- období začíná dnem `billing_day` z Nastavení (0 = podle routeru) a počítá se
  podle hodin Windows,
- na začátku období si zapamatuje stav počítadel routeru (základ) a spotřeba
  = současný stav − základ,
- když router počítadlo vynuluje uprostřed období (jeho vlastní den zúčtování
  nebo reset), dosavadní přírůstek se přičte do `acc` a počítá se dál od nuly.

Pokud aplikace začne počítat uprostřed období a dny zúčtování se liší, část
období před prvním spuštěním chybí – UI to ukáže jako „počítáno od <datum>".
"""

import calendar
import json
import os
from datetime import date, timedelta

import config

LEDGER = "usage.json"
GB = 1000 ** 3                              # operátoři počítají v dekadických GB
WARN_LEVELS = (80, 100)                     # % limitu, kdy upozornit


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def read_counters(data):
    """Počítadla z model.json, nebo None (bez přihlášení nejsou k dispozici)."""
    g = (((data or {}).get("wwan") or {}).get("dataUsage") or {}).get("generic") or {}
    total, roam = _int(g.get("dataTransferred")), _int(g.get("dataTransferredRoaming"))
    if total is None or roam is None:
        return None
    return {"total": total, "roam": roam, "router_day": _int(g.get("billingDay")) or 1}


def _clamp_day(year, month, day):
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def period_bounds(day, today=None):
    """(začátek, začátek dalšího) zúčtovacího období s resetem v `day`."""
    today = today or date.today()
    start = _clamp_day(today.year, today.month, day)
    if start > today:                        # tento měsíc reset ještě nebyl
        y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        start = _clamp_day(y, m, day)
    y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start, _clamp_day(y, m, day)


def _path():
    return os.path.join(config.data_dir(), LEDGER)


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, _path())


def update(data, today=None):
    """Zapracuje aktuální počítadla routeru a vrátí stav spotřeby, nebo None.

    Vrací dict: total, roam (bajty v období), start, end (date), days_left,
    since (date, od kdy se v období skutečně počítá), limit_gb, roam_pct,
    billing_day, new_alerts (seznam právě překročených úrovní %).
    """
    cnt = read_counters(data)
    if cnt is None:
        return None
    today = today or date.today()
    day = _int(config.get("billing_day")) or 0
    eff_day = day if 1 <= day <= 31 else cnt["router_day"]
    start, end = period_bounds(eff_day, today)

    led = _load()
    fresh = led.get("start") != start.isoformat()
    if fresh:
        # Nové období (nebo první spuštění). Když se den shoduje s routerem,
        # jeho počítadla už jsou zarovnaná na období → základ 0 (bez ztráty dat).
        aligned = eff_day == cnt["router_day"]
        led = {
            "start": start.isoformat(),
            "since": (start if aligned else today).isoformat(),
            "base": {"total": 0, "roam": 0} if aligned else
                    {"total": cnt["total"], "roam": cnt["roam"]},
            "acc": {"total": 0, "roam": 0},
            "last": {"total": cnt["total"], "roam": cnt["roam"]},
            "alerted": [],
        }
    for k in ("total", "roam"):
        last, cur = led["last"][k], cnt[k]
        if cur < last:                       # router počítadlo vynuloval
            led["acc"][k] += max(0, last - led["base"][k])
            led["base"][k] = 0
        led["last"][k] = cur

    used = {k: led["acc"][k] + max(0, cnt[k] - led["base"][k]) for k in ("total", "roam")}
    limit = _int(config.get("roam_limit_gb")) or 0
    pct = (used["roam"] * 100 / (limit * GB)) if limit else None
    new_alerts = []
    if led.get("alert_limit") != limit:      # změněný limit → upozornit znovu
        led["alert_limit"] = limit
        led["alerted"] = [lvl for lvl in WARN_LEVELS if pct is not None and pct >= lvl]
    if pct is not None:
        for lvl in WARN_LEVELS:
            if pct >= lvl and lvl not in led["alerted"]:
                led["alerted"].append(lvl)
                new_alerts.append(lvl)
    try:
        _save(led)
    except OSError:
        pass
    return {
        "total": used["total"], "roam": used["roam"],
        "start": start, "end": end, "days_left": (end - today).days,
        "since": date.fromisoformat(led["since"]),
        "limit_gb": limit, "roam_pct": pct, "billing_day": eff_day,
        "new_alerts": new_alerts,
    }


def fmt_gb(n_bytes):
    """Bajty → '8,65 GB' / '512 MB' (české desetinné čárky řeší volající)."""
    if n_bytes is None:
        return "—"
    if n_bytes >= GB:
        return f"{n_bytes / GB:.2f} GB"
    return f"{n_bytes / 1000 ** 2:.0f} MB"


if __name__ == "__main__":
    for d in (16, 31, 1):
        print(d, period_bounds(d, date(2026, 11, 18)), period_bounds(d, date(2026, 2, 28)))
