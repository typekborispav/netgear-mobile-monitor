# Sestaví Windows instalátor:  dist\NetgearMonitor-Setup-<verze>.exe (+ .sha256)
#
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
# Kroky: 1) ikona + version info (packaging\make_assets.py)
#        2) PyInstaller --onedir  -> dist\NetgearMonitor\NetgearMonitor.exe
#        3) Inno Setup            -> dist\NetgearMonitor-Setup-<verze>.exe
#        4) SHA-256 kontrolní součet (ověřuje ho updater v aplikaci)
#
# Vyžaduje: Python + pip install -r requirements-build.txt, Inno Setup 6.5+
# (winget install JRSoftware.InnoSetup). Stejný skript používá GitHub Actions.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (python -c "import version; print(version.__version__)").Trim()
if (-not $version) { throw "Nelze zjistit verzi z version.py" }
Write-Host "== Netgear Mobile Monitor $version ==" -ForegroundColor Cyan

$assets = Join-Path $PSScriptRoot "build\assets"
$dist = Join-Path $PSScriptRoot "dist"
$app = Join-Path $dist "NetgearMonitor"

# 1) podklady
python packaging\make_assets.py $assets
if ($LASTEXITCODE -ne 0) { throw "make_assets selhal" }

# 2) PyInstaller (onedir = rychlý start; instalátor to stejně zabalí do 1 souboru)
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
$excludes = @("tkinter", "numpy", "scipy", "PIL", "colorthief", "serial",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtWebChannel", "PySide6.QtPdf", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
              "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql",
              "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtPositioning")
$exArgs = $excludes | ForEach-Object { "--exclude-module"; $_ }
python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name NetgearMonitor `
    --icon (Join-Path $assets "icon.ico") `
    --version-file (Join-Path $assets "version_info.txt") `
    --distpath $dist --workpath (Join-Path $PSScriptRoot "build\pyinstaller") `
    --specpath (Join-Path $PSScriptRoot "build") `
    @exArgs `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller selhal" }

# Nepotřebné Qt překlady (desítky MB) – aplikace má vlastní cs/en texty.
Get-ChildItem "$app\_internal\PySide6\translations" -Filter *.qm -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notmatch '^qtbase_(cs|en)\.qm$' } | Remove-Item -Force

# 3) Inno Setup
$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup (ISCC.exe) nenalezen – winget install JRSoftware.InnoSetup" }

& $iscc /Q "/DAppVersion=$version" "/DSourceDir=$app" "/DOutputDir=$dist" `
    "/DIconFile=$(Join-Path $assets 'icon.ico')" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup selhal" }

# 4) kontrolní součet
$setup = Join-Path $dist "NetgearMonitor-Setup-$version.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
"$hash  NetgearMonitor-Setup-$version.exe" | Out-File "$setup.sha256" -Encoding ascii -NoNewline

$mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
Write-Host "`nHotovo: $setup ($mb MB)" -ForegroundColor Green
Write-Host "SHA-256: $hash"
