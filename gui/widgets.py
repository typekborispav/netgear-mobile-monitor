"""Vlastní widgety ve Fluent stylu: sloupečky signálu, dlaždice s údajem,
graf historie signálu a stavový „pill" štítek."""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, IconWidget, SimpleCardWidget,
                            StrongBodyLabel, isDarkTheme, qconfig, themeColor)

from gui.common import NONE, level_color


def _fg(alpha=1.0):
    c = QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0)
    c.setAlphaF(alpha)
    return c


class SignalBars(QWidget):
    """5 rostoucích sloupečků; aktivní v barvě zvýraznění (nebo úrovně)."""

    def __init__(self, parent=None, size=QSize(44, 32)):
        super().__init__(parent)
        self._bars = 0
        self._level = None
        self.setFixedSize(size)
        qconfig.themeChanged.connect(self.update)

    def set_bars(self, bars, level=None):
        self._bars, self._level = bars, level
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        n, gap = 5, w * 0.08
        bw = (w - gap * (n - 1)) / n
        on = level_color(self._level) if self._level not in (None, NONE) else themeColor()
        for i in range(n):
            bh = h * (0.28 + 0.72 * i / (n - 1))
            r = QRectF(i * (bw + gap), h - bh, bw, bh)
            p.setBrush(on if i < self._bars else _fg(0.16))
            p.drawRoundedRect(r, 2, 2)


class Pill(QLabel):
    """Zaoblený štítek (typ sítě, ROAMING, offline…)."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._level = "accent"
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(10, 2, 10, 2)
        qconfig.themeChanged.connect(self._restyle)
        self._restyle()

    def set_state(self, text, level="accent"):
        self.setText(text)
        self._level = level
        self._restyle()

    def _restyle(self):
        if self._level == "accent":
            bg = themeColor()
            fg = QColor(0, 0, 0) if isDarkTheme() else QColor(255, 255, 255)
        else:
            bg = level_color(self._level)
            fg = QColor(0, 0, 0) if isDarkTheme() else QColor(255, 255, 255)
        self.setStyleSheet(
            f"QLabel {{ background: {bg.name()}; color: {fg.name()};"
            f" border-radius: 10px; font: 600 12px 'Segoe UI Variable Text',"
            f" 'Segoe UI'; padding: 2px 10px; }}")


def paint_glass(widget, radius=8):
    """Průsvitná „skleněná" karta (Fluent Layer) – nechá prosvítat rozostřené
    pozadí panelu, okraj je jemně světlejší než výplň."""
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    if isDarkTheme():
        fill, edge = QColor(255, 255, 255, 16), QColor(255, 255, 255, 26)
    else:
        fill, edge = QColor(255, 255, 255, 120), QColor(255, 255, 255, 170)
    p.setPen(edge)
    p.setBrush(fill)
    p.drawRoundedRect(r, radius, radius)


class GlassCard(QWidget):
    """Karta se skleněným pozadím pro průhledný panel u hodin."""

    def paintEvent(self, e):
        paint_glass(self)


class StatTile(SimpleCardWidget):
    """Karta: ikona + popisek nahoře, hodnota velkým písmem, detail pod ní.
    `glass=True` = průsvitná varianta pro panel u hodin."""

    def __init__(self, icon, title, parent=None, extra=None, glass=False):
        super().__init__(parent)
        self.glass = glass
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon = IconWidget(icon, self)
        self.icon.setFixedSize(16, 16)
        self.title = CaptionLabel(title, self)
        self.title.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        head.addWidget(self.icon)
        head.addWidget(self.title, 1)
        lay.addLayout(head)

        self.value = StrongBodyLabel("—", self)
        self.value.setWordWrap(True)
        f = self.value.font()
        f.setPixelSize(18)
        self.value.setFont(f)
        lay.addWidget(self.value)

        if extra is not None:
            lay.addWidget(extra)
        self.detail = CaptionLabel("", self)
        self.detail.setWordWrap(True)
        self.detail.setTextColor(QColor(96, 96, 96), QColor(170, 170, 170))
        lay.addWidget(self.detail)
        lay.addStretch(1)

    def paintEvent(self, e):
        if self.glass:
            paint_glass(self)
        else:
            super().paintEvent(e)

    def set(self, value, detail="", level=None):
        self.value.setText(str(value))
        if level and level != NONE:
            c = level_color(level)
            self.value.setTextColor(c, c)
        else:
            self.value.setTextColor(QColor(0, 0, 0), QColor(255, 255, 255))
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))


class InfoRow(QWidget):
    """Řádek „popisek … hodnota" pro detailní tabulku v přehledu."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        self.label = BodyLabel(label, self)
        self.label.setTextColor(QColor(96, 96, 96), QColor(190, 190, 190))
        self.label.setFixedWidth(150)
        self.value = BodyLabel("—", self)
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.label, 0, Qt.AlignTop)
        lay.addWidget(self.value, 1)

    def set(self, text, level=None):
        self.value.setText(str(text))
        if level and level != NONE:
            c = level_color(level)
            self.value.setTextColor(c, c)
        else:
            self.value.setTextColor(QColor(0, 0, 0), QColor(255, 255, 255))


class SignalChart(QWidget):
    """Jednoduchý čárový graf historie RSRP (s výplní v barvě zvýraznění)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pts = []                       # [(t, rsrp, sinr)]
        self.setMinimumHeight(140)
        qconfig.themeChanged.connect(self.update)

    def set_history(self, pts):
        self._pts = [p for p in pts if p[1] is not None]
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 44, 8, 8, 18
        cw, ch = w - left - right, h - top - bottom
        lo, hi = -120.0, -60.0               # rozsah RSRP v dBm

        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        for v in (-60, -80, -100, -120):
            y = top + ch * (hi - v) / (hi - lo)
            p.setPen(QPen(_fg(0.08), 1))
            p.drawLine(left, int(y), w - right, int(y))
            p.setPen(_fg(0.55))
            p.drawText(QRectF(0, y - 8, left - 6, 16),
                       Qt.AlignRight | Qt.AlignVCenter, str(v))

        if len(self._pts) < 2:
            p.setPen(_fg(0.5))
            p.drawText(QRectF(left, top, cw, ch), Qt.AlignCenter, "…")
            return

        t0, t1 = self._pts[0][0], self._pts[-1][0]
        span = max(1.0, t1 - t0)

        def xy(pt):
            x = left + cw * (pt[0] - t0) / span
            v = min(hi, max(lo, pt[1]))
            return x, top + ch * (hi - v) / (hi - lo)

        line = QPainterPath()
        for i, pt in enumerate(self._pts):
            x, y = xy(pt)
            line.moveTo(x, y) if i == 0 else line.lineTo(x, y)
        fill = QPainterPath(line)
        fill.lineTo(xy(self._pts[-1])[0], top + ch)
        fill.lineTo(xy(self._pts[0])[0], top + ch)
        fill.closeSubpath()

        acc = themeColor()
        fc = QColor(acc)
        fc.setAlphaF(0.18)
        p.fillPath(fill, fc)
        p.setPen(QPen(acc, 2))
        p.drawPath(line)
