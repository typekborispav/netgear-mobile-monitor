"""Hlavní okno – FluentWindow (Mica pozadí, navigace vlevo jako aplikace Windows 11).

Zavření křížkem okno jen schová (aplikace žije dál v oznamovací oblasti);
úplné ukončení je v menu ikony → Ukončit.
"""

from PySide6.QtCore import QSize
from qfluentwidgets import FluentIcon as FIF, FluentWindow, NavigationItemPosition

from gui.icons import app_icon
from gui.pages import AboutPage, OverviewPage, SettingsPage, SpeedPage
from i18n import t
from version import APP_NAME


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1060, 760)
        self.setMinimumSize(QSize(760, 560))

        self.overview = OverviewPage(self)
        self.speed = SpeedPage(self)
        self.settings = SettingsPage(self)
        self.about = AboutPage(self)

        self.addSubInterface(self.overview, FIF.HOME, t("nav_overview"))
        self.addSubInterface(self.speed, FIF.SPEED_HIGH, t("nav_speed"))
        self.addSubInterface(self.about, FIF.INFO, t("nav_about"),
                             NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settings, FIF.SETTING, t("nav_settings"),
                             NavigationItemPosition.BOTTOM)
        self.navigationInterface.setExpandWidth(240)

        scr = self.screen().availableGeometry()
        self.move(scr.center().x() - self.width() // 2,
                  scr.center().y() - self.height() // 2)

    def show_page(self, name):
        page = {"overview": self.overview, "speed": self.speed,
                "settings": self.settings, "about": self.about}.get(name)
        if page is not None:
            self.switchTo(page)

    def bring_to_front(self, page=None):
        if page:
            self.show_page(page)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def current_page(self):
        w = self.stackedWidget.currentWidget()
        return w.objectName() if w is not None else "overview"

    def closeEvent(self, e):
        e.ignore()                           # křížek = schovat do lišty
        self.hide()
