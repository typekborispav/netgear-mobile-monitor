# Netgear Mobile Monitor

Aplikace pro Windows 11, která hlídá mobilní 5G/LTE router **Netgear Nighthawk**
(M1, M2, M3, M5, M6, M6 Pro, M7…). Sedí v oznamovací oblasti vedle hodin. Kliknutím
na ikonu otevřete průhledný panel s přehledem, z něj pak celé okno ve stylu
Windows 11 (Fluent Design, Mica, světlý i tmavý motiv).

**[⬇ Stáhnout instalátor (poslední verze)](https://github.com/typekborispav/netgear-mobile-monitor/releases/latest)**

## Co umí

- **Automatická detekce routeru.** Při prvním spuštění najde router v síti
  (výchozí brána a obvyklé adresy) a pozná model, například „Nighthawk M3 · MH3150“.
- **Signál a síť:** RSRP, SINR, RSRQ, 4G/5G (NSA), agregace nosných, buňka a pásmo,
  roaming. K tomu graf historie signálu.
- **Poloha vysílače (BTS)** v sítích T-Mobile, O2 a Vodafone CZ. Data o poloze
  pocházejí z databáze [gsmweb.cz](https://gsmweb.cz/), používáme je se svolením
  provozovatele.
- **Spotřeba dat za zúčtovací období** zvlášť pro domácí síť a roaming, plus
  celkový součet. Zobrazuje se vždy to počítadlo, které právě platí. Počítá router,
  takže čísla zahrnují všechna připojená zařízení, ne jen tento počítač. V Nastavení
  zvolíte tarif: **neomezená data** (počítadlo jen informuje), nebo **omezená data**
  s limitem balíku, do kterého se podle pravidla „roaming jako doma“ započítá
  i roaming v EU. Zvlášť nastavíte limit spravedlivého užívání (FUP) pro roaming
  v EU a den zúčtování. Upozornění přijde při 80 a 100 %.
- **Měřené připojení v roamingu:** při vstupu do roamingu aplikace automaticky
  přepne Wi-Fi routeru na „Měřené připojení“, takže Windows zbytečně nestahují
  aktualizace. Po návratu domů nastavení vrátí, ale jen pokud ho přepnula ona.
  V Nastavení jde zvolit i režim „Jen upozornit“ nebo funkci vypnout.
- **Baterie, teplota, počet klientů Wi-Fi, doba běhu.**
- **Test rychlosti** na vyžádání (Cloudflare, ~75 MB dat). V roamingu je
  automaticky vypnutý.
- **Ikona v liště** ukazuje sílu signálu sloupečky obarvenými podle kvality
  (zelená, žlutá, červená). Odznak „R“ znamená roaming, červený křížek výpadek
  spojení.
- **Automatické aktualizace z GitHubu.** Aplikace nabídne novou verzi, stáhne ji,
  ověří digitální podpis autora a nainstaluje se. Stačí potvrdit oprávnění správce.
  Instalátor bez platného podpisu odmítne.
- Čeština a angličtina, spouštění po přihlášení do Windows.

## Instalace

1. Stáhněte `NetgearMonitor-Setup-X.Y.Z.exe` z
   [Releases](https://github.com/typekborispav/netgear-mobile-monitor/releases/latest).
2. Spusťte ho a potvrďte oprávnění správce. Aplikace se nainstaluje do
   `C:\Program Files\Netgear Mobile Monitor`. Běží ale pod vaším běžným účtem
   bez práv správce.
   - Instalátor zatím není digitálně podepsaný, takže Windows SmartScreen může
     zobrazit „Systém Windows ochránil váš počítač“. Klikněte na **Další
     informace → Přesto spustit**.
3. Připojte počítač k Wi-Fi routeru. Průvodce najde router a zeptá se na heslo do
   administrace (bývá na štítku zařízení).

Nastavení se ukládá do `%APPDATA%\NetgearMonitor\config.json`. Heslo je tam
zašifrované (Windows DPAPI, přečíst ho jde jen pod vaším účtem). Aplikace ho
posílá jen routeru, ke kterému se poprvé úspěšně přihlásila (pozná ho podle
SIM karty). Na cizí síti s jiným zařízením na stejné adrese se heslo neodešle.

Odinstalace: *Nastavení Windows → Aplikace → Netgear Mobile Monitor*.

## Pro vývojáře

```powershell
pip install -r requirements.txt
python app.py                 # okno + ikona v liště
python app.py --background    # jen ikona v liště
```

Sestavení instalátoru (PyInstaller + [Inno Setup](https://jrsoftware.org/isinfo.php)):

```powershell
pip install -r requirements-build.txt
winget install JRSoftware.InnoSetup
powershell -ExecutionPolicy Bypass -File build.ps1   # → dist\NetgearMonitor-Setup-<verze>.exe
```

**Vydání nové verze:** zvyšte `__version__` ve `version.py`, commitněte a spusťte
`pwsh tools\release.ps1 -Version <verze>`. Skript instalátor sestaví lokálně,
podepíše ho klíčem autora (`tools\release-key.ps1`) a vytvoří Release.
Nainstalované aplikace přijmou jen takto podepsaný instalátor. GitHub Actions
dělá jen kontrolní sestavení.

Kromě aplikace obsahuje repozitář i skripty pro příkazovou řádku, fungují
i na Linuxu/Raspberry Pi: `dashboard.py` (živý přehled v terminálu), `netgear.py log`
(logování signálu do CSV), `monitor.py` + `whatsapp-bridge/` (upozornění na
WhatsApp), `speedtest.py`.

### Jak to funguje

Mobilní routery Netgear Nighthawk mají stejné neoficiální webové API: stav celého
zařízení vrací `GET /api/model.json`, přihlášení jde přes `POST /Forms/config`
s tokenem `secToken`. Model se pozná z `general.deviceName` / `general.productSKU`,
které jsou dostupné i bez přihlášení. Odesílání SMS firmware novějších modelů
(NTGX65) blokuje, čtení funguje.

## English

Windows 11 tray app for **Netgear Nighthawk mobile routers** (M1/M2/M3/M5/M6/M7…).
It auto-detects the router model, shows signal, network, roaming, battery,
temperature and cell tower location (Czech networks), runs an on-demand speed test
and updates itself from GitHub Releases. Download the installer from
[Releases](https://github.com/typekborispav/netgear-mobile-monitor/releases/latest).

## Licence

[GNU GPL v3](LICENSE). Uživatelské rozhraní používá
[PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) (GPLv3).
Neoficiální projekt bez vazby na společnost NETGEAR. Data o poloze vysílačů
pocházejí z databáze [gsmweb.cz](https://gsmweb.cz/) a aplikace je používá se
svolením jejího provozovatele. Děkujeme! GSMweb je nekomerční projekt, pokud vám
lokalizace vysílačů pomáhá, zvažte podporu jeho provozu (kontakt na webu
gsmweb.cz). Aplikace databázi stahuje přímo odtud (max. 1× týdně, jen pro síť,
ve které je router) a v repozitáři ji nešíří.
