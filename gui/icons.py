"""Kreslení ikon přes QPainter (žádné soubory obrázků).

- `tray_icon(snap)` – ikona do oznamovací oblasti ve stylu Windows 11: aktivní
  sloupečky obarvené podle síly signálu (zelená / žlutá / červená, odstíny dle
  motivu hlavního panelu), neaktivní ztlumené. Odznak vlevo nahoře: „R" = roaming, červený křížek = bez
  spojení s routerem (stejná řeč jako systémová ikona mobilní sítě).
- `app_icon()` – barevná ikona aplikace (okna, exe, instalátor): zaoblený čtverec
  s přechodem v modré Windows a bílými sloupečky.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)

from qfluentwidgets import FluentIconBase, Theme, isDarkTheme

from gui.common import BAD, GOOD, NONE, WARN, bars_int, signal_level, taskbar_is_dark

# Barvy sloupečků podle síly signálu – zvlášť pro tmavý a světlý hlavní panel
# (motiv hlavního panelu se může lišit od motivu aplikací), sytější než UI
# barvy, ať jsou v malé ikoně dobře vidět.
_TRAY_LEVEL = {
    #       tmavý panel  světlý panel
    GOOD: ("#4CC764", "#0E7A0D"),
    WARN: ("#FFD02E", "#B86E00"),
    BAD: ("#FF6B5E", "#C42B1C"),
}

_TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)


def _bar_rects(x0, y0, w, h, n=5):
    """Obdélníky n rostoucích sloupečků v oblasti (x0, y0, w, h)."""
    gap = w * 0.08
    bw = (w - gap * (n - 1)) / n
    rects = []
    for i in range(n):
        bh = h * (0.28 + 0.72 * i / (n - 1))
        x = x0 + i * (bw + gap)
        rects.append(QRectF(x, y0 + h - bh, bw, bh))
    return rects


def _tray_pixmap(size, bars, ok, roaming, dark_taskbar, level=None):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    fg = QColor(255, 255, 255) if dark_taskbar else QColor(0, 0, 0)
    dim = QColor(fg)
    dim.setAlphaF(0.32)
    on = fg
    if level in _TRAY_LEVEL:                 # aktivní sloupečky v barvě kvality
        on = QColor(_TRAY_LEVEL[level][0 if dark_taskbar else 1])

    pad = size * 0.06
    radius = max(0.8, size * 0.045)
    for i, r in enumerate(_bar_rects(pad, pad, size - 2 * pad, size - 2 * pad)):
        p.setPen(Qt.NoPen)
        p.setBrush(on if (ok and i < bars) else dim)
        p.drawRoundedRect(r, radius, radius)

    # Odznak v prázdném levém horním rohu (nad nízkými sloupečky).
    b = size * 0.46
    badge = QRectF(0, 0, b, b)
    if not ok:
        p.setBrush(QColor("#E81123") if dark_taskbar else QColor("#C42B1C"))
        p.drawEllipse(badge)
        pen = QPen(QColor(255, 255, 255), max(1.2, size * 0.065))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = b * 0.3
        p.drawLine(QPointF(m, m), QPointF(b - m, b - m))
        p.drawLine(QPointF(b - m, m), QPointF(m, b - m))
    elif roaming:
        f = QFont("Segoe UI Variable Display", 1)
        f.setPixelSize(max(7, int(size * 0.5)))
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(badge, Qt.AlignCenter, "R")
    p.end()
    return pm


def tray_icon(snap):
    sig = (snap or {}).get("sig")
    ok = bool((snap or {}).get("ok")) and sig is not None
    roaming = bool(sig and sig.get("roaming") is True)
    dark = taskbar_is_dark()
    level = signal_level(sig) if ok else NONE
    icon = QIcon()
    for s in _TRAY_SIZES:
        icon.addPixmap(_tray_pixmap(s, bars_int(sig), ok, roaming, dark, level))
    return icon


def app_pixmap(size=256):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    m = size * 0.06
    rect = QRectF(m, m, size - 2 * m, size - 2 * m)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#4CC2FF"))
    grad.setColorAt(1.0, QColor("#0050A0"))
    path = QPainterPath()
    path.addRoundedRect(rect, size * 0.22, size * 0.22)
    p.fillPath(path, grad)
    # jemný horní odlesk (Fluent „depth")
    hl = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    hl.setColorAt(0.0, QColor(255, 255, 255, 60))
    hl.setColorAt(0.5, QColor(255, 255, 255, 0))
    p.fillPath(path, hl)

    inner = size * 0.24
    area = QRectF(inner, inner * 1.05, size - 2 * inner, size - 2 * inner)
    p.setPen(Qt.NoPen)
    rad = size * 0.025
    for i, r in enumerate(_bar_rects(area.x(), area.y(), area.width(), area.height())):
        c = QColor(255, 255, 255, 255 if i < 4 else 140)
        p.setBrush(c)
        p.drawRoundedRect(r, rad, rad)
    p.end()
    return pm


class GlyphIcon(FluentIconBase):
    """Ikona z písma Windows 11 „Segoe Fluent Icons" (Win10: Segoe MDL2 Assets).

    Chová se jako FluentIcon: IconWidget ji kreslí přes render(), barva se řídí
    aktuálním motivem (černá/bílá), takže se při přepnutí motivu nemusí nic dělat.
    """

    FAMILIES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

    def __init__(self, code):
        self.code = code

    def path(self, theme=Theme.AUTO):
        return ""                            # nepoužívá se (není to SVG)

    def _color(self, theme):
        dark = isDarkTheme() if theme == Theme.AUTO else theme == Theme.DARK
        return QColor(255, 255, 255) if dark else QColor(0, 0, 0)

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes):
        painter.save()
        f = QFont()
        f.setFamilies(list(self.FAMILIES))
        f.setPixelSize(max(1, int(QRectF(rect).height())))
        painter.setFont(f)
        painter.setPen(self._color(theme))
        painter.drawText(QRectF(rect), Qt.AlignCenter, chr(self.code))
        painter.restore()

    def icon(self, theme=Theme.AUTO, color=None):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        self.render(p, QRectF(0, 0, 64, 64), theme)
        p.end()
        return QIcon(pm)


def battery_glyph(pct=None, charging=False):
    """Baterie z písma Windows 11 v 11 úrovních nabití (s bleskem při nabíjení);
    bez údaje = baterie s křížkem."""
    if pct is None:
        return GlyphIcon(0xEC02)
    level = max(0, min(10, round(pct / 10)))
    return GlyphIcon((0xEBAB if charging else 0xEBA0) + level)


def app_icon():
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(s))
    return icon
