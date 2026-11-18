"""Vygeneruje podklady pro build: ikonu (icon.ico) a version info pro exe.

    python packaging/make_assets.py <výstupní složka>

Ikona se kreslí stejnou funkcí jako za běhu (gui.icons.app_pixmap), takže
exe, instalátor i okna aplikace mají totožnou ikonu.
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image                                   # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice           # noqa: E402
from PySide6.QtGui import QGuiApplication               # noqa: E402

from version import APP_NAME, __version__               # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _png(size):
    from gui.icons import app_pixmap
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    app_pixmap(size).save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def make_icon(path):
    # Každá velikost kreslená zvlášť (ostřejší než zmenšování z 256 px).
    imgs = [_png(s) for s in SIZES]
    imgs[-1].save(path, format="ICO", sizes=[(s, s) for s in SIZES],
                  append_images=imgs[:-1])


def make_version_info(path):
    parts = [int(p) for p in __version__.split(".")] + [0] * 4
    v = tuple(parts[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040504B0', [
      StringStruct('CompanyName', 'Netgear Mobile Monitor (open source)'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'NetgearMonitor'),
      StringStruct('LegalCopyright', 'GNU GPL v3'),
      StringStruct('OriginalFilename', 'NetgearMonitor.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0x0405, 1200])])
  ]
)
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "assets")
    os.makedirs(out, exist_ok=True)
    app = QGuiApplication(sys.argv)
    make_icon(os.path.join(out, "icon.ico"))
    make_version_info(os.path.join(out, "version_info.txt"))
    print(f"assets -> {out} (verze {__version__})")
