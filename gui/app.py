"""Řízení aplikace: ikona v liště, flyout, hlavní okno, motiv, aktualizace.

Spuštění:  python app.py [--background]
  --background  jen ikona v liště (autostart po přihlášení, restart po aktualizaci)
  bez přepínače se navíc otevře hlavní okno (spuštění z nabídky Start)

Běží vždy jen jedna instance: druhé spuštění pošle první instanci zprávu
„show" přes QLocalServer a skončí – první instance otevře okno.
"""

import getpass
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import (Action, BodyLabel, FluentIcon as FIF, InfoBar,
                            InfoBarPosition, MessageBoxBase, ProgressBar,
                            SubtitleLabel, SystemThemeListener, SystemTrayMenu,
                            Theme, isDarkTheme, setTheme, setThemeColor)

import config
import i18n
import updater
from gui import common as c
from gui.flyout import Flyout
from gui.icons import app_icon, tray_icon
from gui.main_window import MainWindow
from gui.workers import Poller, SpeedTester, UpdateWorker
from gui.wizard import SetupWizard
from i18n import t
from version import APP_ID, APP_NAME, __version__

UPDATE_INTERVAL_MS = 24 * 3600 * 1000
SERVER_NAME = f"{APP_ID}-{getpass.getuser()}"


# ── Dialog aktualizace (ContentDialog) ────────────────────────────────────────
class UpdateDialog(MessageBoxBase):
    def __init__(self, info, worker, parent):
        super().__init__(parent)
        self.info, self.worker = info, worker
        self.widget.setMinimumWidth(480)
        self.viewLayout.addWidget(SubtitleLabel(t("upd_title", info["version"]), self.widget))
        notes = info.get("notes") or t("upd_no_notes")
        if len(notes) > 900:
            notes = notes[:900] + "…"
        self.body = BodyLabel(t("upd_body", __version__, info["version"]) + "\n\n" + notes,
                              self.widget)
        self.body.setWordWrap(True)
        self.viewLayout.addWidget(self.body)
        self.bar = ProgressBar(self.widget)
        self.bar.setRange(0, 100)
        self.bar.hide()
        self.viewLayout.addWidget(self.bar)

        self.yesButton.setText(t("upd_install") if updater.can_self_install()
                               else t("upd_open_page"))
        self.cancelButton.setText(t("btn_later"))
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._go)
        worker.progress.connect(self._progress)
        worker.downloaded.connect(self._downloaded)
        worker.download_failed.connect(self._failed)

    def _go(self):
        if not updater.can_self_install() or not self.info.get("asset_url"):
            QDesktopServices.openUrl(QUrl(self.info["html_url"]))
            self.accept()
            return
        self.yesButton.setEnabled(False)
        self.bar.show()
        self.body.setText(t("upd_downloading"))
        self.worker.download(self.info)

    def _progress(self, done, total):
        if total:
            self.bar.setValue(int(done * 100 / total))

    def _downloaded(self, path):
        self.body.setText(t("upd_installing"))
        QApplication.processEvents()        # text ukázat dřív, než se objeví UAC
        try:
            updater.install(path)           # čeká na potvrzení UAC
        except updater.Cancelled:
            self._failed(t("upd_uac_cancelled"))
            return
        except OSError as e:
            self._failed(str(e))
            return
        QTimer.singleShot(300, QApplication.instance().quit)

    def _failed(self, msg):
        self.bar.hide()
        self.yesButton.setEnabled(True)
        self.body.setText(t("upd_failed", msg))

    def reject(self):
        self.worker.cancel()
        super().reject()


# ══════════════════════════════════════════════════════════════════════════════
class Controller:
    def __init__(self, app, background):
        self.app = app
        self.win = None
        self.flyout = None
        self._notified_version = None
        self._wizard_open = False

        self.poller = Poller()
        self.speed = SpeedTester()
        self.upd = UpdateWorker()
        self.poller.updated.connect(self._on_state)
        self.poller.roamingChanged.connect(self._on_roaming)
        self.poller.usageAlert.connect(self._on_usage_alert)
        self.speed.started.connect(self._on_speed_changed)
        self.speed.finished.connect(self._on_speed_finished)
        self.speed.failed.connect(self._on_speed_failed)
        self.upd.checked.connect(self._on_update_checked)
        self.upd.check_failed.connect(self._on_update_failed)

        self.apply_theme(config.get("theme"))
        self.theme_listener = SystemThemeListener(app)
        self.theme_listener.systemThemeChanged.connect(self._on_system_theme)
        self.theme_listener.start()

        self.tray = QSystemTrayIcon(tray_icon(self.poller.snapshot), app)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self._on_tray_activated)
        self._toast_action = None
        self.tray.messageClicked.connect(self._on_toast_clicked)
        self._build_menu()
        self.tray.show()

        self.flyout = Flyout()
        self._wire_flyout()

        c.repair_autostart()
        self.poller.start()

        first_run = not config.get("password")
        if first_run or not background:
            self.show_window("overview")
        if first_run:
            QTimer.singleShot(400, self.open_wizard)

        self.upd_timer = QTimer(app)
        self.upd_timer.timeout.connect(self._auto_check)
        self.upd_timer.start(UPDATE_INTERVAL_MS)
        QTimer.singleShot(15000, self._auto_check)

    # ── motiv ──
    def apply_theme(self, mode):
        setTheme({"light": Theme.LIGHT, "dark": Theme.DARK}.get(mode, Theme.AUTO),
                 save=False)
        acc = c.system_accent(isDarkTheme())
        if acc is not None:
            setThemeColor(acc, save=False)
        if getattr(self, "tray", None):
            self.tray.setIcon(tray_icon(self.poller.snapshot))

    def _on_system_theme(self):
        if config.get("theme") in (None, "", "auto"):
            QTimer.singleShot(200, lambda: self.apply_theme("auto"))
        else:
            self.tray.setIcon(tray_icon(self.poller.snapshot))

    # ── lišta ──
    def _build_menu(self):
        menu = SystemTrayMenu(parent=None)
        menu.addActions([
            Action(FIF.HOME, t("menu_open"), triggered=lambda: self.show_window("overview")),
            Action(FIF.SPEED_HIGH, t("menu_speed"), triggered=self.start_speedtest),
        ])
        menu.addSeparator()
        menu.addActions([
            Action(FIF.SETTING, t("nav_settings"), triggered=lambda: self.show_window("settings")),
            Action(FIF.UPDATE, t("btn_check_now"), triggered=lambda: self.check_updates(True)),
        ])
        menu.addSeparator()
        menu.addAction(Action(FIF.POWER_BUTTON, t("menu_quit"), triggered=self.quit))
        old = getattr(self, "menu", None)
        self.menu = menu
        self.tray.setContextMenu(menu)
        if old is not None:
            old.deleteLater()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.flyout.toggle()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.flyout.hide()
            self.show_window("overview")

    # ── okna ──
    def _wire_flyout(self):
        self.flyout.openApp.connect(lambda: self.show_window("overview"))
        self.flyout.openSettings.connect(lambda: self.show_window("settings"))
        self.flyout.speedRequested.connect(self.start_speedtest)
        self.flyout.update_state(self.poller.snapshot, self.speed.last, self.speed.running)

    def _ensure_window(self):
        if self.win is not None:
            return self.win
        w = MainWindow()
        s = w.settings
        s.routerSaved.connect(self.poller.reconfigure)
        s.languageChanged.connect(self.set_language)
        s.themeChanged.connect(self._set_theme)
        s.checkUpdates.connect(lambda: self.check_updates(True))
        s.openWizard.connect(self.open_wizard)
        s.notify.connect(self._info_bar)
        s.dataSettingsChanged.connect(self.poller.poll_now)
        w.about.checkUpdates.connect(lambda: self.check_updates(True))
        w.speed.startRequested.connect(self.start_speedtest)
        self.win = w
        self._refresh_window(self.poller.snapshot)
        self._on_speed_changed()
        w.fit_overview()
        return w

    def show_window(self, page=None):
        self._ensure_window().bring_to_front(page)

    def _info_bar(self, level, title, text):
        if self.win is None:
            return
        fn = {"success": InfoBar.success, "error": InfoBar.error,
              "warning": InfoBar.warning}.get(level, InfoBar.info)
        fn(title, text, parent=self.win, position=InfoBarPosition.TOP_RIGHT,
           duration=4000 if level == "success" else 6000)
        if self.win is not None:
            self.win.settings.on_notify_done()

    def open_wizard(self):
        if self._wizard_open:
            return
        w = self._ensure_window()
        w.bring_to_front()
        self._wizard_open = True
        dlg = SetupWizard(w)
        self.wizard = dlg
        dlg.finished_ok.connect(self._on_wizard_done)
        dlg.exec()
        self.wizard = None
        self._wizard_open = False

    def _on_wizard_done(self, lang_changed):
        # Přestavět vždy: jazyk se mohl změnit a stránka Nastavení drží
        # hodnoty z doby před průvodcem.
        self.poller.reconfigure()
        QTimer.singleShot(0, lambda: self._rebuild("overview"))

    def set_language(self, code):
        if code == i18n.lang():
            return
        i18n.set_lang(code)
        QTimer.singleShot(0, lambda: self._rebuild("settings"))

    def _rebuild(self, page):
        """Přestaví okna s novými texty (po změně jazyka / průvodci)."""
        was_visible = self.win is not None and self.win.isVisible()
        geo = self.win.geometry() if self.win is not None else None
        if self.win is not None:
            self.win.hide()
            self.win.deleteLater()
            self.win = None
        self.flyout.hide()
        self.flyout.deleteLater()
        self.flyout = Flyout()
        self._wire_flyout()
        self._build_menu()
        if was_visible:
            w = self._ensure_window()
            if geo is not None:
                w.setGeometry(geo)
            w.bring_to_front(page)

    def _set_theme(self, mode):
        config.save({"theme": mode})
        self.apply_theme(mode)

    # ── data ──
    def _on_state(self, snap):
        self.tray.setIcon(tray_icon(snap))
        self.tray.setToolTip(c.tooltip_text(snap))
        if self.flyout is not None:
            self.flyout.update_state(snap, self.speed.last, self.speed.running)
        self._refresh_window(snap)

    def _refresh_window(self, snap):
        if self.win is None:
            return
        self.win.set_status(snap)
        self.win.overview.update_state(snap, self.poller.history)
        self.win.details.update_state(snap)
        self.win.settings.set_device(snap.get("device"))
        roaming = (snap.get("sig") or {}).get("roaming") is True
        if not self.speed.running:
            self.win.speed.btn.setEnabled(not roaming)
            self.win.speed.set_roaming(roaming)

    def _roaming(self):
        return (self.poller.snapshot.get("sig") or {}).get("roaming") is True

    def start_speedtest(self):
        if self._roaming():
            self.toast(APP_NAME, t("speed_roaming"), icon=QSystemTrayIcon.Warning, ms=5000)
            return
        if not self.speed.start():
            return

    def _on_speed_changed(self):
        running = self.speed.running
        if self.flyout is not None:
            self.flyout.update_state(self.poller.snapshot, self.speed.last, running)
        if self.win is not None:
            self.win.speed.set_running(running)
            if not running:
                self.win.speed.show_result(self.speed.last, SpeedTester.history())
                self._refresh_window(self.poller.snapshot)

    def _on_speed_finished(self, r):
        self._on_speed_changed()
        if not (self.win and self.win.isVisible()):   # okno výsledek ukazuje samo
            self.toast(t("speed_done"),
                       f"↓ {r.get('download_mbps')}  ↑ {r.get('upload_mbps')} Mbit/s"
                       f" · {r.get('latence_ms')} ms",
                       on_click=lambda: self.show_window("speed"), ms=6000)

    def _on_speed_failed(self, msg):
        self._on_speed_changed()
        self.toast(APP_NAME, t("speed_failed", msg), icon=QSystemTrayIcon.Warning, ms=6000)

    # ── aktualizace ──
    def _auto_check(self):
        if config.get("check_updates"):
            self.check_updates(False)

    def check_updates(self, manual):
        if manual and self.win is not None:
            self.win.settings.set_update_status(t("upd_checking"))
        self.upd.check(manual)

    def _on_update_checked(self, info, manual):
        if self.win is not None:
            self.win.settings.set_update_status(
                t("upd_available", info["version"]) if info
                else t("upd_uptodate", __version__))
        if info is None:
            if manual:
                self._info_bar("success", t("set_upd_check"), t("upd_uptodate", __version__))
            return
        if manual:
            self._show_update_dialog(info)
        elif self._notified_version != info["version"]:
            self._notified_version = info["version"]
            self.toast(t("upd_title", info["version"]), t("upd_toast"),
                       on_click=lambda: self._show_update_dialog(info), ms=10000)

    # ── upozornění v liště ──
    def toast(self, title, text, on_click=None, icon=QSystemTrayIcon.Information, ms=8000):
        """Upozornění Windows z ikony v liště; klik spustí `on_click`
        (výchozí = otevřít aplikaci). Platí vždy jen pro poslední upozornění."""
        self._toast_action = on_click or (lambda: self.show_window("overview"))
        self.tray.showMessage(title, text, icon, ms)

    def _on_toast_clicked(self):
        action, self._toast_action = self._toast_action, None
        if action:
            action()

    def _on_roaming(self, roaming, info):
        """Roaming začal/skončil: oznámit automatické přepnutí měřeného
        připojení, nebo (režim „hint" / selhání) nabídnout ruční přepnutí."""
        import metered
        mode, action = config.get("metered_mode"), info.get("action")
        ssid = info.get("ssid") or "Wi-Fi"
        if action == "set":
            self.toast(t("met_set_title"), t("met_set_text", ssid),
                       on_click=metered.open_settings, ms=8000)
            return
        if action == "reverted":
            self.toast(t("met_home_title"), t("met_reverted_text", ssid),
                       on_click=metered.open_settings, ms=8000)
            return
        if mode == "off" or not info.get("via_router"):
            return
        if mode == "auto" and action is None:
            return                          # nebylo co přepínat (už měřené apod.)
        if roaming and info.get("metered") is False:
            self.toast(t("met_roam_title"), t("met_roam_text", info.get("ssid") or "Wi-Fi"),
                       on_click=metered.open_settings, icon=QSystemTrayIcon.Warning, ms=15000)
        elif not roaming and info.get("metered") is True:
            self.toast(t("met_home_title"), t("met_home_text", info.get("ssid") or "Wi-Fi"),
                       on_click=metered.open_settings, ms=10000)

    def _on_usage_alert(self, kind, level, u):
        view = c.usage_view(u, kind)
        if not view:
            return
        self.toast(t(f"usage_alert_title_{kind}", level), t("usage_alert_text", view[1]),
                   icon=QSystemTrayIcon.Critical if level >= 100 else QSystemTrayIcon.Warning,
                   ms=15000)

    def _on_update_failed(self, err, manual):
        if self.win is not None:
            self.win.settings.set_update_status(t("upd_check_failed", err))
        if manual:
            self._info_bar("error", t("set_upd_check"), t("upd_check_failed", err))

    def _show_update_dialog(self, info):
        w = self._ensure_window()
        w.bring_to_front()
        UpdateDialog(info, self.upd, w).exec()

    # ── konec ──
    def quit(self):
        self.poller.stop()
        self.tray.hide()
        try:
            self.theme_listener.terminate()
            self.theme_listener.deleteLater()
        except RuntimeError:
            pass
        self.app.quit()


# ══════════════════════════════════════════════════════════════════════════════
def _enable_app_id():
    """Vlastní AppUserModelID – Windows pak ikonu na hlavním panelu a toasty
    přiřadí této aplikaci (ne obecnému python.exe)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"{APP_ID}.Monitor")
        except Exception:
            pass


def _already_running():
    """True, když už instance běží (a poslali jsme jí „show")."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        # Tento proces spustil uživatel (má právo na popředí) – předáme ho
        # běžící instanci, jinak by Windows její okno nechal jen blikat.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            except Exception:
                pass
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main():
    background = "--background" in sys.argv
    _enable_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)    # žijeme v liště

    if _already_running():
        return 0

    QLocalServer.removeServer(SERVER_NAME)  # po pádu mohl zůstat starý soket
    server = QLocalServer()
    server.listen(SERVER_NAME)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        background = False

    ctl = Controller(app, background)

    def on_conn():
        s = server.nextPendingConnection()
        if s is None:
            return
        s.waitForReadyRead(300)
        if bytes(s.readAll()).startswith(b"show"):
            ctl.show_window()
        s.disconnectFromServer()
    server.newConnection.connect(on_conn)

    return app.exec()
