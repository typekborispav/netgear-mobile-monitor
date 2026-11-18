"""Flyout u hodin – rychlý přehled po kliknutí na ikonu v liště.

Vypadá jako systémové flyouty Windows 11 (Rychlé nastavení): bezrámečkové okno
se zaoblenými rohy a pozadím **Acrylic** (DWM system backdrop), karty s údaji,
spodní lišta s akcemi. Zavře se kliknutím mimo (Qt.Popup) nebo Esc.

Pozice se bere z `availableGeometry()` obrazovky pod kurzorem, takže sedí nad
hlavním panelem v jakékoli poloze. Otevření má krátkou animaci „vyjetí" zdola.
"""

import ctypes
import sys
import time

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt,
                            Signal)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF,
                            IconWidget, ProgressBar,
                            StrongBodyLabel, SubtitleLabel, ToolTipFilter,
                            TransparentToolButton, isDarkTheme)

import config
from gui import common as c
from gui.icons import app_icon
from gui.widgets import GlassCard, Pill, SignalBars, StatTile
from i18n import t

WIDTH = 384


# ── DWM (Windows 11): zaoblené rohy + Acrylic pozadí ──────────────────────────
class _MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int),
                ("t", ctypes.c_int), ("b", ctypes.c_int)]


class _ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


# Průhlednost panelu (config "flyout_style"):
#   system – systémový Acrylic Windows 11 (DWMSBT_TRANSIENTWINDOW), jako Rychlé
#            nastavení; má silnější „luminosity" vrstvu, je nejméně průhledný,
#   high   – rozostření pozadí s jemným odstínem (výchozí),
#   max    – rozostření téměř bez odstínu, nejvíc prosvítá tapeta/okna.
# Hodnoty = krytivost odstínu (0–255) pro (světlý, tmavý) motiv.
STYLE_ALPHA = {"high": (0x90, 0x78), "max": (0x48, 0x38)}
STYLES = ("system", "high", "max")


def _dwm_int(dwm, hwnd, attr, value):
    v = ctypes.c_int(value)
    return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)


def _apply_backdrop(hwnd, dark, style):
    """Zapne průhledné pozadí panelu. Vrací True při úspěchu (jinak se kreslí
    neprůhledné pozadí – Windows 10 / starší build / vypnuté efekty)."""
    if sys.platform != "win32" or sys.getwindowsversion().build < 22000:
        return False
    try:
        dwm = ctypes.windll.dwmapi
        hwnd = int(hwnd)
        _dwm_int(dwm, hwnd, 20, 1 if dark else 0)        # IMMERSIVE_DARK_MODE
        _dwm_int(dwm, hwnd, 33, 2)                       # DWMWCP_ROUND – zaoblené rohy
        _dwm_int(dwm, hwnd, 34, 0xFFFFFFFE)              # BORDER_COLOR = výchozí

        if style == "system":
            if sys.getwindowsversion().build < 22621:
                return False
            m = _MARGINS(-1, -1, -1, -1)
            dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
            return _dwm_int(dwm, hwnd, 38, 3) == 0       # DWMSBT_TRANSIENTWINDOW

        _dwm_int(dwm, hwnd, 38, 1)                       # systémový backdrop vypnout
        light_a, dark_a = STYLE_ALPHA.get(style, STYLE_ALPHA["high"])
        r, g, b, a = (32, 32, 32, dark_a) if dark else (243, 243, 243, light_a)
        accent = _ACCENTPOLICY(4, 0, (a << 24) | (b << 16) | (g << 8) | r, 0)  # ACRYLICBLURBEHIND
        data = _WINCOMPATTRDATA(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
                                ctypes.sizeof(accent))           # WCA_ACCENT_POLICY
        return bool(ctypes.windll.user32.SetWindowCompositionAttribute(
            hwnd, ctypes.byref(data)))
    except Exception:
        return False


class Flyout(QWidget):
    openApp = Signal()
    openSettings = Signal()
    speedRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH)
        self._acrylic = False
        self._style = "high"
        self._hidden_at = 0.0
        self._anim = None
        self._build()

    # ── stavba ──
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget(self)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)

        # hlavička: ikona + název + štítek sítě
        head = QHBoxLayout()
        head.setSpacing(10)
        ic = IconWidget(app_icon(), body)
        ic.setFixedSize(20, 20)
        head.addWidget(ic)
        self.title = StrongBodyLabel(c.device_name(), body)
        head.addWidget(self.title)
        head.addStretch(1)
        self.pill = Pill("…", body)
        head.addWidget(self.pill)
        lay.addLayout(head)

        # karta signálu
        card = GlassCard(body)
        cl = QHBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(16)
        self.bars = SignalBars(card)
        cl.addWidget(self.bars, 0, Qt.AlignVCenter)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self.operator = SubtitleLabel("—", card)
        self.net = BodyLabel("", card)
        self.quality = CaptionLabel("", card)
        self.quality.setWordWrap(True)
        for w in (self.operator, self.net, self.quality):
            txt.addWidget(w)
        cl.addLayout(txt, 1)
        lay.addWidget(card)

        # dlaždice 2×2
        grid = QGridLayout()
        grid.setSpacing(8)
        self.batt_bar = ProgressBar(body)
        self.batt_bar.setRange(0, 100)
        self.batt = StatTile(FIF.CALORIES, t("row_batt"), body, extra=self.batt_bar, glass=True)
        self.temp = StatTile(FIF.FRIGID, t("row_temp"), body, glass=True)
        self.clients = StatTile(FIF.WIFI, t("row_clients"), body, glass=True)
        self.speed = StatTile(FIF.SPEED_HIGH, t("row_speed"), body, glass=True)
        grid.addWidget(self.batt, 0, 0)
        grid.addWidget(self.temp, 0, 1)
        grid.addWidget(self.clients, 1, 0)
        grid.addWidget(self.speed, 1, 1)
        self.data_bar = ProgressBar(body)
        self.data_bar.setRange(0, 100)
        self.data = StatTile(FIF.GLOBE, t("row_roam_data"), body, extra=self.data_bar,
                             glass=True)
        grid.addWidget(self.data, 2, 0, 1, 2)
        lay.addLayout(grid)

        # BTS
        bts_row = QHBoxLayout()
        bts_row.setSpacing(8)
        pin = IconWidget(FIF.PIN, body)
        pin.setFixedSize(14, 14)
        self.pin = pin
        self.bts = CaptionLabel("", body)
        self.bts.setWordWrap(True)
        bts_row.addWidget(pin, 0, Qt.AlignTop)
        bts_row.addWidget(self.bts, 1)
        lay.addLayout(bts_row)
        root.addWidget(body)

        # spodní lišta s akcemi (jako v Rychlém nastavení)
        self.footer = QWidget(self)
        self.footer.setFixedHeight(48)
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(16, 0, 8, 0)
        self.updated = CaptionLabel("", self.footer)
        fl.addWidget(self.updated, 1)
        for icon, tip, sig in ((FIF.SPEED_HIGH, t("menu_speed"), self.speedRequested),
                               (FIF.SETTING, t("nav_settings"), self.openSettings),
                               (FIF.APPLICATION, t("menu_open"), self.openApp)):
            b = TransparentToolButton(icon, self.footer)
            b.setToolTip(tip)
            b.installEventFilter(ToolTipFilter(b))
            b.clicked.connect(self.hide)
            b.clicked.connect(sig.emit)
            fl.addWidget(b)
        root.addWidget(self.footer)

    # ── data ──
    def update_state(self, snap, speed_last=None, speed_running=False):
        sig, data = snap.get("sig"), snap.get("data")
        self.title.setText(c.device_name(snap))
        if not snap.get("ok") or sig is None:
            if snap.get("starting"):
                self.pill.set_state("…", c.NONE)
                self.operator.setText(t("connecting"))
                self.net.setText("")
            else:
                self.pill.set_state(t("offline"), c.BAD)
                self.operator.setText(t("no_conn"))
                self.net.setText(t("hint_password") if snap.get("need_password")
                                 else t("hint_offline"))
            self.bars.set_bars(0)
            self.quality.setText("")
            for tile in (self.batt, self.temp, self.clients):
                tile.set("—")
            self.batt_bar.setValue(0)
            self.bts.setText("")
            self.pin.hide()
            self.updated.setText("")
            self._set_speed(speed_last, speed_running)
            return

        roaming = sig.get("roaming") is True
        if roaming:
            self.pill.set_state(f"{c.net_label(sig)} · {t('roaming')}", c.BAD)
        else:
            self.pill.set_state(c.net_label(sig))
        self.bars.set_bars(c.bars_int(sig))
        self.operator.setText(str(sig.get("operator") or "—"))
        self.net.setText(f"{sig.get('typ_sluzby', '')} · "
                         f"{t('roaming') if roaming else t('home_net')}")
        rq, _ = c.rsrp_quality(sig.get("rsrp"))
        sq, _ = c.sinr_quality(sig.get("sinr"))
        self.quality.setText(f"RSRP {c.fmt(sig.get('rsrp'), 'dBm')} ({rq}) · "
                             f"SINR {c.fmt(sig.get('sinr'), 'dB')} ({sq})")

        pct, src = c.battery(data)
        self.batt.set(c.fmt(pct, "%"), src, c.battery_level(pct))
        self.batt_bar.setValue(pct or 0)
        gen = (data or {}).get("general", {}) or {}
        self.temp.set(c.fmt(gen.get("devTemperature"), "°C"))
        wifi = (data or {}).get("wifi", {}) or {}
        self.clients.set(c.fmt(wifi.get("clientCount")),
                         f"{t('uptime')} {c.uptime(data)}")
        self._set_speed(speed_last, speed_running)
        view = c.usage_view(snap.get("usage"))
        self.data.setVisible(view is not None)
        if view:
            value, detail, pct, level = view
            self.data.set(value, detail, level if level != c.GOOD else None)
            c.apply_usage_bar(self.data_bar, pct)

        kind, loc = snap.get("bts") or ("none", "")
        self.bts.setText(loc if kind == "exact" else
                         t("bts_area", loc) if kind == "oblast" else t("bts_unknown"))
        self.pin.show()
        ts = snap.get("ts")
        self.updated.setText(t("updated_at", ts.strftime("%H:%M:%S")) if ts else "")

    def _set_speed(self, last, running):
        if running:
            self.speed.set(t("speed_measuring_short"), t("speed_data_note"), c.WARN)
        elif last:
            self.speed.set(f"↓ {last.get('download_mbps', '?')}",
                           f"↑ {last.get('upload_mbps', '?')} Mbit/s · "
                           f"{last.get('latence_ms', '?')} ms")
        else:
            self.speed.set("—", t("speed_never"))

    # ── zobrazení ──
    def toggle(self):
        # Klik na ikonu, když je flyout otevřený: Qt.Popup se nejdřív sám zavře
        # (klik mimo) a hned potom přijde signál z ikony → neotvírat znovu.
        if self.isVisible():
            self.hide()
        elif time.monotonic() - self._hidden_at > 0.35:
            self.show_at_tray()

    def show_at_tray(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.adjustSize()
        w, h = self.width(), self.sizeHint().height()
        self.resize(w, h)
        gap = 12
        full = screen.geometry()
        # Hlavní panel může být dole / nahoře / vlevo / vpravo.
        if area.bottom() < full.bottom():
            x, y = area.right() - w - gap, area.bottom() - h - gap
            start = QPoint(x, y + 24)
        elif area.top() > full.top():
            x, y = area.right() - w - gap, area.top() + gap
            start = QPoint(x, y - 24)
        elif area.right() < full.right():
            x, y = area.right() - w - gap, area.bottom() - h - gap
            start = QPoint(x + 24, y)
        else:
            x, y = area.left() + gap, area.bottom() - h - gap
            start = QPoint(x - 24, y)
        end = QPoint(x, y)

        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        style = config.get("flyout_style")
        self._style = style if style in STYLES else "high"
        self._acrylic = _apply_backdrop(self.winId(), isDarkTheme(), self._style)
        self.update()
        self.activateWindow()
        self._animate(start, end)

    def _animate(self, start, end):
        pos = QPropertyAnimation(self, b"pos", self)
        pos.setStartValue(start)
        pos.setEndValue(end)
        pos.setDuration(220)
        pos.setEasingCurve(QEasingCurve.OutCubic)
        op = QPropertyAnimation(self, b"windowOpacity", self)
        op.setStartValue(0.0)
        op.setEndValue(1.0)
        op.setDuration(160)
        self._anim = (pos, op)
        pos.start()
        op.start()

    def hideEvent(self, e):
        self._hidden_at = time.monotonic()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = isDarkTheme()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        glass = self._acrylic and self._style != "system"
        if not self._acrylic:
            # Bez efektu (Windows 10 / vypnutá průhlednost): neprůhledné pozadí.
            p.fillPath(path, QColor(44, 44, 44) if dark else QColor(243, 243, 243))
        elif not glass:
            # Systémový akryl: jen jemný tint pro čitelnost nad pestrou tapetou.
            p.fillPath(path, QColor(32, 32, 32, 40) if dark else QColor(243, 243, 243, 40))
        # Spodní lišta – o odstín tmavší vrstva jako u systémových flyoutů.
        fr = QRectF(self.footer.geometry())
        if not self._acrylic:
            foot = QColor(32, 32, 32) if dark else QColor(235, 235, 235)
        elif glass:
            foot = QColor(0, 0, 0, 55) if dark else QColor(0, 0, 0, 14)
        else:
            foot = QColor(28, 28, 28, 170) if dark else QColor(238, 238, 238, 190)
        p.save()
        p.setClipPath(path)                  # spodní rohy zůstanou zaoblené
        p.fillRect(fr, foot)
        p.restore()
        p.setPen(QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 15))
        p.drawLine(int(fr.left()), int(fr.top()), int(fr.right()), int(fr.top()))
        # tenký okraj
        p.setPen(QColor(255, 255, 255, 28) if dark else QColor(0, 0, 0, 25))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
