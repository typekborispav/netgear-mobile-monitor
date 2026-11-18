"""Spotřeba mobilních dat za zúčtovací období – domácí síť a roaming zvlášť.

Zdroj jsou počítadla **routeru** (`model.json` → `wwan.dataUsage.generic`, jen
po přihlášení), takže zahrnují **všechna připojená zařízení**, ne jen tento PC:

- `dataTransferred`         data v domácí síti v aktuálním období routeru,
- `dataTransferredRoaming`  data v roamingu (samostatné počítadlo),
- `billingDay`              den v měsíci, kdy router počítadla nuluje.

Že jde o dvě oddělená počítadla, vyplývá z webového rozhraní routeru: limit
hlídá v roamingu `dataTransferredRoaming` proti `billingCycleLimitRoaming`,
jinak `dataTransferred` proti `billingCycleLimit`. Celkem = součet obou.

Tarif (EU, „roaming jako doma"):
- `home_plan="unlimited"` – doma bez limitu, počítadlo jen informuje;
- `home_plan="limited"` – limit `home_limit_gb`; s `roam_counts_home=True`
  (obvyklé) se roaming v EU čerpá ze stejného balíku → domácí limit se
  porovnává s domácí + roamingovou spotřebou;
- `roam_limit_gb` – limit spravedlivého užívání (FUP) pro roaming v EU,
  hlídá se vždy zvlášť jen proti roamingu.

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
from datetime import date

import config

LEDGER = "usage.json"
LEDGER_VERSION = 2
KINDS = ("home", "roam")
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
    home, roam = _int(g.get("dataTransferred")), _int(g.get("dataTransferredRoaming"))
    if home is None or roam is None:
        return None
    return {"home": home, "roam": roam, "router_day": _int(g.get("billingDay")) or 1}


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
        return d if isinstance(d, dict) and d.get("v") == LEDGER_VERSION else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, _path())


def update(data, today=None):
    """Zapracuje aktuální počítadla routeru a vrátí stav spotřeby, nebo None.

    Vrací dict: home, roam, total (bajty v období), start, end (date),
    days_left, since (od kdy se v období skutečně počítá), billing_day,
    limits {home, roam} v GB (0 = bez limitu), pct {home, roam} (% limitu
    nebo None), new_alerts [(druh, úroveň %)] právě překročené.
    """
    cnt = read_counters(data)
    if cnt is None:
        return None
    today = today or date.today()
    day = _int(config.get("billing_day")) or 0
    eff_day = day if 1 <= day <= 31 else cnt["router_day"]
    start, end = period_bounds(eff_day, today)

    led = _load()
    if led.get("start") != start.isoformat():
        # Nové období (nebo první spuštění). Když se den shoduje s routerem,
        # jeho počítadla už jsou zarovnaná na období → základ 0 (bez ztráty dat).
        aligned = eff_day == cnt["router_day"]
        led = {
            "v": LEDGER_VERSION,
            "start": start.isoformat(),
            "since": (start if aligned else today).isoformat(),
            "base": {k: 0 if aligned else cnt[k] for k in KINDS},
            "acc": {k: 0 for k in KINDS},
            "last": {k: cnt[k] for k in KINDS},
            "alerted": {k: [] for k in KINDS},
            "alert_limit": {},
        }
    used = {}
    for k in KINDS:
        last, cur = led["last"][k], cnt[k]
        if cur < last:                       # router počítadlo vynuloval
            led["acc"][k] += max(0, last - led["base"][k])
            led["base"][k] = 0
        led["last"][k] = cur
        used[k] = led["acc"][k] + max(0, cur - led["base"][k])

    plan = plan_settings()
    # Co se porovnává s limitem: doma (u omezeného tarifu) i roaming v EU, pokud
    # se čerpá ze stejného balíku; roaming vždy jen proti FUP limitu.
    counted = {"home": used["home"] + (used["roam"] if plan["roam_counts_home"] else 0),
               "roam": used["roam"]}
    limits = {"home": plan["home_limit"], "roam": plan["roam_limit"]}
    pct, new_alerts = {}, []
    for k in KINDS:
        pct[k] = counted[k] * 100 / (limits[k] * GB) if limits[k] else None
        alert_key = f"{limits[k]}|{plan['roam_counts_home']}"
        if led["alert_limit"].get(k) != alert_key:   # změněný tarif → přepočítat
            led["alert_limit"][k] = alert_key
            led["alerted"][k] = [lv for lv in WARN_LEVELS
                                 if pct[k] is not None and pct[k] >= lv]
        if pct[k] is not None:
            for lv in WARN_LEVELS:
                if pct[k] >= lv and lv not in led["alerted"][k]:
                    led["alerted"][k].append(lv)
                    new_alerts.append((k, lv))
    try:
        _save(led)
    except OSError:
        pass
    return {
        "home": used["home"], "roam": used["roam"], "total": used["home"] + used["roam"],
        "counted": counted, "plan": plan["home_plan"],
        "roam_counts_home": plan["roam_counts_home"],
        "start": start, "end": end, "days_left": (end - today).days,
        "since": date.fromisoformat(led["since"]), "billing_day": eff_day,
        "limits": limits, "pct": pct, "new_alerts": new_alerts,
    }


def plan_settings():
    """Tarif z nastavení: home_plan, home_limit (GB, 0 = bez), roam_limit
    (FUP v GB, 0 = bez), roam_counts_home (platí jen u omezeného tarifu)."""
    limited = config.get("home_plan") == "limited"
    home_limit = max(0, _int(config.get("home_limit_gb")) or 0) if limited else 0
    return {
        "home_plan": "limited" if limited else "unlimited",
        "home_limit": home_limit,
        "roam_limit": max(0, _int(config.get("roam_limit_gb")) or 0),
        "roam_counts_home": bool(limited and home_limit and config.get("roam_counts_home")),
    }


def fmt_gb(n_bytes):
    """Bajty → '8.65 GB' / '512 MB' (desetinnou čárku řeší GUI)."""
    if n_bytes is None:
        return "—"
    if n_bytes >= GB:
        return f"{n_bytes / GB:.2f} GB"
    return f"{n_bytes / 1000 ** 2:.0f} MB"


if __name__ == "__main__":
    for d in (16, 31, 1):
        print(d, period_bounds(d, date(2026, 11, 18)), period_bounds(d, date(2026, 2, 28)))
