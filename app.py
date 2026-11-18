"""Netgear M3 Monitor – vstupní bod Windows aplikace (ikona v liště + okno).

    python app.py               # otevře okno + ikonu v liště
    python app.py --background  # jen ikona v liště (autostart)
    app.py --set-autostart      # zapne autostart a skončí (volá instalátor
    app.py --unset-autostart    #   pod původním uživatelem – HKCU je jeho)

Zabalení do instalátoru: build.ps1 (PyInstaller + Inno Setup).
"""

import sys


def _autostart_cli():
    """Bez GUI: jen nastaví autostart v registru aktuálního uživatele."""
    from gui.common import set_autostart
    set_autostart("--set-autostart" in sys.argv)
    return 0


if __name__ == "__main__":
    if "--set-autostart" in sys.argv or "--unset-autostart" in sys.argv:
        sys.exit(_autostart_cli())
    from gui.app import main
    sys.exit(main())
