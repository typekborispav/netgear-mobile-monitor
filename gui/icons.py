"""Kreslení ikon přes QPainter (žádné soubory obrázků).

- `tray_icon(snap)` – ikona do oznamovací oblasti ve stylu Windows 11: jednobarevné
  sloupečky signálu (bílé na tmavém hlavním panelu, černé na světlém), neaktivní
  sloupečky ztlumené. Odznak vlevo nahoře: „R" = roaming, červený křížek = bez
  spojení s routerem (stejná řeč jako systémová ikona mobilní sítě).
- `app_icon()` – barevná ikona aplikace (okna, exe, instalátor): zaoblený čtverec
  s přechodem v modré Windows a bílými sloupečky.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)

from gui.common import bars_int, taskbar_is_dark

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


def _tray_pixmap(size, bars, ok, roaming, dark_taskbar):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    fg = QColor(255, 255, 255) if dark_taskbar else QColor(0, 0, 0)
    dim = QColor(fg)
    dim.setAlphaF(0.32)

    pad = size * 0.06
    radius = max(0.8, size * 0.045)
    for i, r in enumerate(_bar_rects(pad, pad, size - 2 * pad, size - 2 * pad)):
        p.setPen(Qt.NoPen)
        p.setBrush(fg if (ok and i < bars) else dim)
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
    icon = QIcon()
    for s in _TRAY_SIZES:
        icon.addPixmap(_tray_pixmap(s, bars_int(sig), ok, roaming, dark))
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


def app_icon():
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(s))
    return icon
