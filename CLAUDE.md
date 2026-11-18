# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Přehled

**Netgear Mobile Monitor** – Windows 11 aplikace (PySide6 + PySide6-Fluent-Widgets, Fluent Design) pro mobilní routery **Netgear Nighthawk** (M1/M2/M3/M5/M6/M7…), plus CLI toolkit (dashboard, logování, WhatsApp alerty, speedtest). Přes neoficiální JSON API routeru čte stav (signál, síť, roaming, baterie, teplota, klienti). Vývojový kus: Nighthawk M3 (MH3150, fw NTGX65), SIM Vodafone CZ (230/03).

Repozitář: `github.com/typekborispav/netgear-mobile-monitor` (veřejný, GPLv3 – kvůli licenci Fluent Widgets). Vydání = GitHub Release s instalátorem; aplikace se z něj sama aktualizuje.

## Spuštění

```powershell
python app.py [--background]  # GUI: okno + ikona v liště (--background = jen lišta)
python device.py              # najde router v síti a vypíše model
python netgear.py             # stav + SMS jednorázově
python netgear.py log [s]     # logování signálu do signal_log.csv (default 60 s)
python dashboard.py [s]       # živý terminálový dashboard (default 3 s)
python monitor.py [s]         # hlídač událostí -> WhatsApp alerty (default 30 s)
python speedtest.py [d] [u]   # RUČNÍ test rychlosti (default ~50 MB down + 25 up)
python notifier.py "text"     # ruční test odeslání WhatsApp zprávy
python updater.py             # ověří, zda je na GitHubu novější verze
powershell -ExecutionPolicy Bypass -File build.ps1   # → dist\NetgearMonitor-Setup-<verze>.exe
```

Závislosti: `requirements.txt` (requests, PySide6, PySide6-Fluent-Widgets), build `requirements-build.txt` (+ pyinstaller, pillow) a Inno Setup 6.5+ (`winget install JRSoftware.InnoSetup`). `pyserial` jen pro `at_sms.py`. Node most: `cd whatsapp-bridge && npm install`. Žádné testy.

## Build, instalátor, vydání, aktualizace

- `version.py` = jediný zdroj verze (`__version__`), `APP_NAME`, `APP_ID="NetgearMonitor"`, `GITHUB_REPO`.
- `build.ps1` (uložený jako **UTF-8 s BOM**, jinak ho Windows PowerShell 5.1 rozbije na české znaky): `packaging/make_assets.py` (icon.ico kreslená `gui.icons.app_pixmap` + version info) → PyInstaller `--onedir --windowed` s excludy (numpy/scipy/PIL/WebEngine…; Fluent Widgets je importují jen volitelně) → Inno Setup `packaging/installer.iss` → `dist\NetgearMonitor-Setup-<v>.exe` + `.sha256`.
- Instalátor instaluje do **`C:\Program Files\Netgear Mobile Monitor`** (`PrivilegesRequired=admin`, `{autopf}`, `UsePreviousAppDir=no` – v2.0.0 byla ještě per-user v `%LOCALAPPDATA%`). Instalace i aktualizace = UAC. Všechny `[Run]` mají **`runasoriginaluser`** (aplikace nesmí běžet jako správce). Autostart (HKCU) zapisuje `NetgearMonitor.exe --set-autostart` pod původním uživatelem, jen při interaktivní instalaci (`Check: not WizardSilent`); tichá instalace po dokončení spustí `--background`. Odinstalace maže Run hodnotu `NetgearMonitor` + `taskkill`.
- **Vydání:** zvýšit `__version__`, commit, `git tag vX.Y.Z && git push origin vX.Y.Z` → `.github/workflows/release.yml` (kontrola tag == version.py, build, `gh release create`).
- **Updater** (`updater.py`): `releases/latest` → porovná tag, stáhne `*Setup*.exe`, **povinně ověří SHA-256** z `.sha256` assetu, spustí ho přes `os.startfile(path, "runas", "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS")` – UAC proběhne synchronně, odmítnutí = `updater.Cancelled` a aplikace běží dál; po spuštění se aplikace ukončí. Ověřeno E2E (1.9.9 → 2.0.0 ještě s per-user instalátorem). Samoinstalace jen při `sys.frozen`; ze zdrojáků jen odkaz na release. Kontrola při startu (po 15 s) a 1× denně, vypínatelná (`check_updates`).
- V zabaleném běhu jdou data do `config.data_dir()` (`%APPDATA%\NetgearMonitor`): BTS DB, `speed_log.csv`.

## Architektura

### Komunikace s routerem (`netgear.py`)
Vše stojí na jednom stromu **`GET /api/model.json`** (helper `get_model()`, při zavřeném keep-alive jednou tiše opakuje). Přihlášení má tři kroky:
1. `GET /api/model.json` → `session.secToken`.
2. `POST /Forms/config` s tokenem + heslem jako **surový urlencoded řetězec** (Netgear je na formátu citlivý), token i v hlavičce `X-XSRF-TOKEN`.
3. Token se přidá do `session.headers`. POST vrací 200 i se špatným heslem – úspěch = `session.userRole == "Admin"`.

Globální `requests.Session` + `sec_token`. `apply_config()` po změně nastavení resetuje session.

`collect_signal()` sbírá plochý slovník (klíče = `SIGNAL_FIELDS`): typ sítě `wwan.connectionText`/`currentPSserviceType`, roaming `wwan.roaming`, **operátor** z `wwan.registerNetworkDisplay` s fallbackem na MCC/MNC (záměrně NE `sim.SPN`, v roamingu by mátl), signál `wwan.signalStrength` (+ 5G `nr5g*`), `wwanadv` (`curBand`, `radioQuality`, `cellId`, `LAC`, `MCC`, `MNC`). Sentinel **`-32768` = nedostupné** (`_clean()`). Bez přihlášení model.json vrací signál, ale `registerNetworkDisplay` je prázdný (operátor pak = „MCC230/MNC03").

### Detekce modelu (`device.py`)
Všechny Nighthawk mobilní routery mají stejné API. `identify(data)`: bez loginu `general.deviceName` („Nighthawk M3") + `productSKU` („MH3150-100EUS"), po loginu i `model`, `FWversion`. `MODEL_NAMES` je jen záloha, když chybí `deviceName`. `discover()` paralelně zkouší výchozí bránu (`route print`, `CREATE_NO_WINDOW`) + 192.168.1.1/0.1/5.1; `probe()` ověřuje `companyName` NETGEAR / `secToken`.

### Lokalizace BTS (`bts.py`)
Databáze gsmweb.cz **podle sítě**: `https://gsmweb.cz/android/combined/<MCC><MNC>.clf` pro 23001 T-Mobile, 23002 O2, 23003 Vodafone (jiné → `none`). UTF-8, `;`, sloupce `MCC;MNC;LAC;CID;;;Umisteni`; obsahuje i LTE/5G ECI → přesná adresa i na 5G. `lookup(cell, lac, mcc, mnc)` → `exact` / `oblast` (okresy dle LAC) / `none`. `update(force, mcc, mnc)` max 1×/týden, atomicky přes `.tmp`. Výchozí síť funkcí = 230/03 kvůli CLI. DB se **nešíří v repozitáři** (gitignore `*.clf`), aplikace ji stahuje. GUI poller stahuje DB pro aktuální síť.

### Spotřeba dat (`usage.py`) a měřené připojení (`metered.py`)
- Počítadla routeru `wwan.dataUsage.generic` (**jen po přihlášení**): `dataTransferred`, `dataTransferredRoaming`, `billingDay` – zahrnují **všechna zařízení** na routeru. Hodiny routeru M3 ukazují rok 2016 → období se počítá podle hodin Windows.
- `usage.update(data)` vede knihu `usage.json` (datová složka): období od `billing_day` (0 = den routeru); na začátku období základ = stav počítadel (při shodě dne s routerem základ 0), reset počítadla routeru uprostřed období se přičte do `acc`. Když aplikace začne uprostřed období s jiným dnem než router, vrací `since` > `start` („počítáno od“). Upozornění 80/100 % limitu `roam_limit_gb` jednou za období (`alerted`, při změně limitu se přepočítá).
- `metered.py`: čte `netsh wlan show interfaces/profile` (Cost Unrestricted/Fixed/Variable) a přepíná `netsh wlan set profileparameter name=<SSID> cost=Fixed|Unrestricted` – **ověřeno, že na Win11 jde bez práv správce**. `metered_mode`: `auto` (výchozí) / `hint` / `off`. Poller při změně roamingu (i start v roamingu, i start doma s nevráceným `metered_owned`) v režimu auto přepne Wi-Fi, přes kterou jde internet (`via_router` = `router_ip` je výchozí brána PC), na měřenou a SSID uloží do `metered_owned`; po návratu domů vrátí **jen tuto** síť. Selhání → upozornění s odkazem `ms-settings:network-wifi`.
- Upozornění v liště jdou přes `Controller.toast(title, text, on_click)` (klik = akce posledního upozornění). Zástupce v nabídce Start má `AppUserModelID: NetgearMonitor.Monitor` (shodné s `SetCurrentProcessExplicitAppUserModelID`), aby upozornění nesla název aplikace.

### GUI (`app.py` → `gui/`)
- `gui/app.py` – `Controller`: `QSystemTrayIcon` + `SystemTrayMenu`, flyout, hlavní okno (líně), motiv (`setTheme` + barva zvýraznění z registru `AccentPalette`: světlý → AccentDark1, tmavý → AccentLight2; `SystemThemeListener` pro „Podle Windows"), aktualizace (`UpdateDialog`), **jedna instance** přes `QLocalServer` (druhé spuštění pošle „show" + `AllowSetForegroundWindow`). `app.setQuitOnLastWindowClosed(False)`; křížek okna jen schová.
- `gui/workers.py` – vše v **daemon vláknech** (ne QThread → konec aplikace nečeká na síť), výsledky přes Qt signály: `Poller` (snímek `{ok, sig, data, ts, err, bts, device, need_password, starting}`, historie RSRP, `reconfigure()` provede re-login ve vlákně polleru), `DeviceFinder`, `SpeedTester`, `UpdateWorker`.
- `gui/flyout.py` – panel u hodin (`Qt.Popup`, slide animace, pozice z `availableGeometry` obrazovky pod kurzorem). Pozadí dle `flyout_style`: `system` = DWM `DWMSBT_TRANSIENTWINDOW` (systémový akryl), `high`/`max` = `SetWindowCompositionAttribute` ACCENT_ENABLE_ACRYLICBLURBEHIND s nízkou krytivostí odstínu (`STYLE_ALPHA`); zaoblení `DWMWCP_ROUND`. Karty „skleněné“ (`widgets.paint_glass`).
- `gui/main_window.py` + `gui/pages.py` – `FluentWindow` (Mica): Přehled (dlaždice, graf `SignalChart`, detaily), Rychlost (historie ze speed_log.csv), Nastavení (`SettingCardGroup`; Zařízení + Vyhledat router, IP/heslo s testem, interval, autostart, motiv, průhlednost panelu, jazyk, průvodce, aktualizace), O aplikaci.
- `gui/wizard.py` – průvodce jako ContentDialog (`MessageBoxBase`, vlastní obsluha tlačítek): 1 jazyk + **detekce routeru hned na začátku**, 2 IP (předvyplněná) + heslo + test, 3 interval/autostart/aktualizace. Otevře se, když v configu chybí heslo.
- `gui/icons.py` – ikona do lišty monochromní dle motivu **hlavního panelu** (`SystemUsesLightTheme`), odznak „R" = roaming, červený křížek = offline; barevná ikona aplikace.
- `i18n.py` – všechny texty GUI přes `t(key)` (cs/en); změna jazyka = `Controller._rebuild()` (přestaví okna, flyout, menu). CLI zůstává česky.

**Známé quirky:** `SpinBox` z Fluent Widgets 1.11.3 je s PySide6 6.12 vykreslený prázdný (vnitřní lineEdit má šířku 1 px) → interval je `ComboBox` (`pages.interval_box`). Okno z procesu na pozadí Windows nepustí do popředí (foreground lock) – z kliku na ikonu to funguje.

### Dashboard (`dashboard.py`), test rychlosti (`speedtest.py`)
Dashboard: ANSI překreslování, `parse_ca` (carrier aggregation z `wwan.lteBandInfo`), `band_region`, `_uptime`; klávesa `s` = speedtest v daemon vlákně; klávesy cross-platform (`msvcrt`/`termios`). Speedtest je **ruční** (Cloudflare `__down`/`__up`, ~75 MB), `measure()` má vlastní Session; CLI guard `_home_ok()` odmítne v roamingu. GUI guard na roaming řeší Controller.

### Upozornění na WhatsApp (Baileys)
`whatsapp-bridge/` (Node ESM, `@whiskeysockets/baileys`, `POST /send`, `GET /status`, **nutné `fetchLatestBaileysVersion()`**, relace v `auth_info/` – nikdy nesdílet) ← `notifier.py` (env `WA_TO`) ← `monitor.py` (alerty jen při ZMĚNĚ: výpadek, roaming, typ sítě, handover s BTS, přehřátí s hysterezí 50/45 °C).

## Odesílání SMS — nefunkční

`model.json` hlásí **`sms.sendSupported=false`**; firmware NTGX65 odesílání blokuje (endpoint `/Forms/smsSendMsg` existuje). `send_sms()` příznak kontroluje. **Čtení SMS (`sms.msgs`) funguje.** Bezrootové cesty vyčerpané (žádný AT/telnet port, USB-C jen napájení); `at_sms.py` je zbytek průzkumu.

## Konfigurace a citlivé soubory

`config.py` → `%APPDATA%\NetgearMonitor\config.json` (Linux `~/.config/netgear-monitor/`), mimo repozitář. Klíče: `router_ip`, `password` (**plaintext**; v `DEFAULTS` záměrně prázdné – nesmí do zdrojáku), `poll_s`, `lang`, `theme`, `flyout_style`, `check_updates`, `device_name`, `roam_limit_gb` (60), `billing_day` (0 = podle routeru), `metered_mode` (auto/hint/off), `metered_owned`. Autostart: `HKCU\…\Run` hodnota `NetgearMonitor` (`gui.common.set_autostart`; `repair_autostart()` v zabaleném běhu přepíše starou cestu). Commity do veřejného repa s noreply e-mailem (lokální `git config user.email`).
