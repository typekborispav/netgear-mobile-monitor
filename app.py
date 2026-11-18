"""Netgear M3 Monitor – vstupní bod Windows aplikace (ikona v liště + okno).

    python app.py               # otevře okno + ikonu v liště
    python app.py --background  # jen ikona v liště (autostart)

Zabalení do instalátoru: build.ps1 (PyInstaller + Inno Setup).
"""

import sys

from gui.app import main

if __name__ == "__main__":
    sys.exit(main())
