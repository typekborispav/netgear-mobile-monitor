"""Hlavní okno ve stylu Nastavení Windows 11 (stejně jako Printer Switch).

Vlevo pevný panel – nezasouvá se a nemá tlačítko „hamburger“: nahoře ikona
aplikace s názvem a stavem routeru, pod ní položky navigace (jemná výplň při
najetí, barevná svislá čárka u vybrané). Vpravo stránky přímo na pozadí Mica.

Zavření křížkem okno jen schová (aplikace žije dál v oznamovací oblasti);
úplné ukončení je v menu ikony → Ukončit.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF, getFont,
                            isDarkTheme, qconfig, setFont, themeColor)
from qfluentwidgets.window.fluent_window import FluentWindowBase

from gui import common as c
from gui.icons import app_icon, app_pixmap
from gui.pages import AboutPage, DetailsPage, OverviewPage, SettingsPage, SpeedPage
from i18n import t
from version import APP_NAME

SIDEBAR_W = 280


class NavItem(QAbstractButton):
    """Položka navigace jako v Nastavení Windows 11."""

    def __init__(self, icon, text, parent=None):
        super().__init__(parent)
        self.icon_ = icon
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(42)                 # 38 px položka + 2 px nahoře a dole
        self.setFont(getFont(14))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._kbd = False

    def sizeHint(self):
        return QSize(SIDEBAR_W - 24, 42)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def focusInEvent(self, e):
        self._kbd = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd = False
        super().focusOutEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        dark = isDarkTheme()
        box = QRectF(self.rect()).adjusted(0, 2, 0, -2)

        a = 0
        if self.isDown():
            a = 0.042 if dark else 0.024
        elif self.isChecked() or self.underMouse():
            a = 0.061 if dark else 0.037
        if a:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, round(a * 255)) if dark
                       else QColor(0, 0, 0, round(a * 255)))
            p.drawRoundedRect(box, 4, 4)

        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(themeColor())
            h = 16
            p.drawRoundedRect(QRectF(0, box.center().y() - h / 2, 3, h), 1.5, 1.5)

        if self._kbd and self.hasFocus():
            p.setPen(QColor(255, 255, 255) if dark else QColor(0, 0, 0, 228))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(1, 1, -1, -1), 4, 4)

        self.icon_.render(p, QRectF(16, box.center().y() - 8, 16, 16))
        p.setPen(QColor(255, 255, 255) if dark else QColor(0, 0, 0, 228))
        p.setFont(self.font())
        p.drawText(QRectF(48, box.top(), box.width() - 56, box.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())


class Sidebar(QWidget):
    """Pevný levý panel: hlavička aplikace + navigace."""

    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 8, 16)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(4, 4, 0, 20)
        head.setSpacing(14)
        logo = QLabel(self)
        ratio = self.devicePixelRatioF()
        pm = app_pixmap(round(56 * ratio))
        pm.setDevicePixelRatio(ratio)
        logo.setPixmap(pm)
        logo.setFixedSize(56, 56)
        head.addWidget(logo, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = BodyLabel(APP_NAME, self)
        setFont(name, 15, QFont.DemiBold)
        name.setWordWrap(True)
        self.state = CaptionLabel("", self)
        self.state.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(self.state)
        head.addLayout(text, 1)
        lay.addLayout(head)

        self.items = {}
        self.nav = QVBoxLayout()
        self.nav.setSpacing(0)
        lay.addLayout(self.nav)
        lay.addStretch(1)
        qconfig.themeChangedFinished.connect(self.update_items)

    def add_item(self, key, icon, text):
        item = NavItem(icon, text, self)
        item.clicked.connect(lambda: self.clicked.emit(key))
        self.nav.addWidget(item)
        self.items[key] = item
        return item

    def setCurrentItem(self, key):
        for k, item in self.items.items():
            item.setChecked(k == key)

    def update_items(self):
        for item in self.items.values():
            item.update()

    def set_state(self, text):
        self.state.setText(text)


def status_text(snap):
    """Řádek pod názvem aplikace: router a stav připojení."""
    name = c.device_name(snap)
    if snap.get("starting"):
        return t("connecting")
    sig = snap.get("sig")
    if not snap.get("ok") or sig is None:
        return f"{name} · {t('offline')}"
    if sig.get("roaming") is True:
        return f"{name} · {c.net_label(sig)} · {t('roaming')}"
    return f"{name} · {c.net_label(sig)}"


class MainWindow(FluentWindowBase):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1100, 760)
        self.setMinimumSize(QSize(960, 600))

        self._fitted = False
        self.sidebar = Sidebar(self)
        self.navigationInterface = self.sidebar     # FluentWindowBase volá setCurrentItem()
        self.hBoxLayout.setContentsMargins(0, self.titleBar.height(), 0, 0)
        self.hBoxLayout.addWidget(self.sidebar)
        self.hBoxLayout.addWidget(self.stackedWidget, 1)
        self.titleBar.raise_()

        self.overview = OverviewPage(self)
        self.details = DetailsPage(self)
        self.speed = SpeedPage(self)
        self.settings = SettingsPage(self)
        self.about = AboutPage(self)
        self.pages = {"overview": self.overview, "details": self.details,
                      "speed": self.speed, "settings": self.settings, "about": self.about}
        for key, icon in (("overview", FIF.HOME), ("details", FIF.DOCUMENT),
                          ("speed", FIF.SPEED_HIGH), ("settings", FIF.SETTING),
                          ("about", FIF.INFO)):
            page = self.pages[key]
            page.setProperty("isStackedTransparent", True)
            self.stackedWidget.addWidget(page)
            self.sidebar.add_item(key, icon, t(f"nav_{key}"))
        self.sidebar.clicked.connect(self.show_page)
        self.stackedWidget.currentChanged.connect(self._onCurrentInterfaceChanged)
        self.sidebar.setCurrentItem("overview")
        self._updateStackedBackground()

        self._center()

    def _center(self):
        scr = self.screen().availableGeometry()
        self.move(scr.center().x() - self.width() // 2,
                  scr.center().y() - self.height() // 2)

    def fit_overview(self, final=True):
        """Výška okna tak, aby se Přehled (včetně grafu) vešel bez posuvníku.

        Volá se při vytvoření okna a znovu po prvních datech z routeru
        (`final=True`), protože naplněný Přehled je vyšší. Okno se jen
        zvětšuje a nikdy přes dostupnou plochu obrazovky.
        """
        if self._fitted:
            return
        self._fitted = final
        lay = self.overview.view.layout()
        lay.activate()
        need = self.titleBar.height() + lay.totalMinimumSize().height() + 8
        scr = self.screen().availableGeometry()
        h = min(max(self.height(), need), scr.height() - 40)
        if h == self.height():
            return
        self.resize(self.width(), h)
        if not self.isVisible():
            self._center()
        elif self.geometry().bottom() > scr.bottom():   # už otevřené: neskákat, jen se vejít
            self.move(self.x(), max(scr.top(), scr.bottom() - self.frameGeometry().height()))

    def _onCurrentInterfaceChanged(self, index):
        w = self.stackedWidget.widget(index)
        if w is not None:
            self.sidebar.setCurrentItem(w.objectName())
            self._updateStackedBackground()

    def set_status(self, snap):
        self.sidebar.set_state(status_text(snap))

    def show_page(self, name):
        page = self.pages.get(name)
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
