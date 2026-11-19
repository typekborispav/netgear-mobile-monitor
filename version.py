"""Jediný zdroj verze aplikace a adresy GitHub repozitáře.

Verzi čte aplikace (O aplikaci, kontrola aktualizací), build skript
(PyInstaller version info + Inno Setup) i GitHub Actions (kontrola, že tag
`vX.Y.Z` sedí s touto hodnotou). Při vydání nové verze stačí změnit
`__version__`, commitnout a pushnout tag `v<verze>`.
"""

__version__ = "2.5.0"

APP_NAME = "Netgear Mobile Monitor"
APP_ID = "NetgearMonitor"                  # název exe, složek, mutexu
GITHUB_REPO = "typekborispav/netgear-mobile-monitor"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
