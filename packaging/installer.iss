; Instalátor Netgear Mobile Monitor (Inno Setup 6.5+)
;
; Překládá build.ps1:  ISCC /DAppVersion=X.Y.Z /DSourceDir=... /DOutputDir=... installer.iss
;
; - Instalace do C:\Program Files\Netgear Mobile Monitor (vyžaduje práva správce,
;   instalace i aktualizace zobrazí UAC). Aplikace sama běží BEZ práv správce:
;   všechny [Run] položky mají `runasoriginaluser`.
; - Autostart je v HKCU (registr uživatele), proto ho nezapisuje instalátor běžící
;   jako správce, ale aplikace spuštěná pod původním uživatelem (--set-autostart).
; - Tichá aktualizace (/SILENT z aplikace) po dokončení aplikaci sama znovu spustí
;   do oznamovací oblasti (--background).
; - Odinstalace smaže i autostart; nastavení v %APPDATA%\NetgearMonitor ponechá.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\NetgearMonitor"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\build\assets\icon.ico"
#endif

#define AppName "Netgear Mobile Monitor"
#define AppExe "NetgearMonitor.exe"
#define AppUrl "https://github.com/typekborispav/netgear-mobile-monitor"
#define RunValue "NetgearMonitor"

[Setup]
AppId={{6E2B6C1D-8A4F-4C1B-9E57-3B1F0C9D4A21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Netgear Mobile Monitor (open source)
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=no
PrivilegesRequired=admin
UsedUserAreasWarning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=NetgearMonitor-Setup-{#AppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern dynamic
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=auto
LicenseFile=..\LICENSE

[Languages]
Name: "cs"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
cs.AutoStart=Spouštět po přihlášení do Windows (ikona v oznamovací oblasti)
en.AutoStart=Start when I sign in to Windows (notification area icon)
cs.Group=Další možnosti:
en.Group=Additional options:

[Tasks]
Name: "autostart"; Description: "{cm:AutoStart}"; GroupDescription: "{cm:Group}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Při aktualizaci smazat staré knihovny, ať nezůstávají nepoužívané soubory.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; AppUserModelID = stejné jako SetCurrentProcessExplicitAppUserModelID v gui/app.py –
; upozornění Windows pak nesou název a ikonu aplikace.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "NetgearMonitor.Monitor"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Autostart jen při interaktivní instalaci (tichá aktualizace nesmí přebít volbu,
; kterou si uživatel mezitím změnil v Nastavení). Zapisuje ho aplikace pod
; původním uživatelem – do jeho HKCU, ne do HKCU účtu správce.
Filename: "{app}\{#AppExe}"; Parameters: "--set-autostart"; Flags: runasoriginaluser runhidden waituntilterminated; Tasks: autostart; Check: not WizardSilent
; Interaktivní instalace: zaškrtávátko „Spustit“ na konci průvodce.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; Tichá aktualizace z aplikace: rovnou znovu spustit do lišty.
Filename: "{app}\{#AppExe}"; Parameters: "--background"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Autostart je v HKCU uživatele. Při odinstalaci pod stejným účtem (běžný
    případ – uživatel je správce) ho tímto smažeme; jinak ho po spuštění bez
    aplikace Windows jen tiše přeskočí. }
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#RunValue}');
end;
