"""Průvodce nastavením – 3 kroky ve stylu Windows 11 ContentDialog.

1. uvítání + jazyk; hned na začátku se na pozadí **vyhledá router** (výchozí
   brána + obvyklé adresy) a ukáže se jeho model (Nighthawk M1/M2/M3/M5/M6/M7…),
2. adresa (předvyplněná z detekce) a heslo routeru, test spojení,
3. interval, autostart, automatické aktualizace.

Kroky se staví až při přechodu, takže po volbě jazyka v kroku 1 jsou další
kroky rovnou v novém jazyce. Hlavní okno (rodič dialogu) se přestaví až po
dokončení průvodce – signál `finished_ok(lang_changed)`.
"""

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF,
                            IconWidget, IndeterminateProgressRing, LineEdit,
                            MessageBoxBase, PasswordLineEdit, PushButton,
                            SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
                            SwitchButton, TransparentToolButton)

import config
import i18n
import device
from gui import common as c
from gui.icons import app_icon
from gui.pages import interval_box
from gui.workers import DeviceFinder
from i18n import t


class SetupWizard(MessageBoxBase):
    finished_ok = Signal(bool)              # lang_changed
    _test_done = Signal(bool, str)

    def __init__(self, parent):
        super().__init__(parent)
        cfg = config.load(force=True)
        self.v = {
            "lang": i18n.lang(),
            "router_ip": cfg.get("router_ip") or "192.168.1.1",
            "password": cfg.get("password", ""),
            "poll_s": int(cfg.get("poll_s", 30)),
            "autostart": c.autostart_enabled(),
            "check_updates": bool(cfg.get("check_updates", True)),
        }
        self._orig_lang = self.v["lang"]
        self.step = 1
        self.page = None
        self.widget.setMinimumWidth(520)

        self.yesButton.clicked.disconnect()
        self.cancelButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._next)
        self.cancelButton.clicked.connect(self._back)
        self._test_done.connect(self._on_test_done)

        # Detekce routeru běží hned od otevření průvodce.
        self.detect = {"state": "searching", "ip": None, "info": None}
        self._ip_touched = False
        self.finder = DeviceFinder(self)
        self.finder.found.connect(self._on_found)
        self.finder.start([cfg.get("router_ip")])
        self._show_step()

    # ── navigace ──
    def _collect(self):
        if self.step == 1:
            self.v["lang"] = self.lang_box.currentData()
        elif self.step == 2:
            self.v["router_ip"] = self.ip.text().strip()
            self.v["password"] = self.pw.text()
        elif self.step == 3:
            self.v["poll_s"] = int(self.poll.currentData())
            self.v["autostart"] = self.auto.isChecked()
            self.v["check_updates"] = self.upd.isChecked()

    def _next(self):
        self._collect()
        if self.step == 1 and self.v["lang"] != i18n.lang():
            i18n.set_lang(self.v["lang"])   # další kroky už v novém jazyce
        if self.step == 2:
            if not self.v["router_ip"]:
                return self._status(t("st_ip_required"), c.BAD)
            if not self.v["password"]:
                return self._status(t("wz_pw_required"), c.BAD)
        if self.step == 3:
            return self._finish()
        self.step += 1
        self._show_step()

    def _back(self):
        if self.step == 1:
            self.reject()
            return
        self._collect()
        self.step -= 1
        self._show_step()

    def _finish(self):
        vals = {k: self.v[k] for k in ("router_ip", "password", "poll_s", "check_updates")}
        if self.detect["info"]:
            vals["device_name"] = self.detect["info"].get("name", "")
        config.save(vals)
        try:
            c.set_autostart(self.v["autostart"])
        except OSError:
            pass
        self.accept()
        self.finished_ok.emit(self.v["lang"] != self._orig_lang)

    # ── kroky ──
    def _show_step(self):
        if self.page is not None:
            self.viewLayout.removeWidget(self.page)
            self.page.deleteLater()
        self.page = QWidget(self.widget)
        lay = QVBoxLayout(self.page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        head = QHBoxLayout()
        ic = IconWidget(app_icon(), self.page)
        ic.setFixedSize(28, 28)
        head.addWidget(ic)
        head.addSpacing(8)
        head.addWidget(SubtitleLabel(t("wz_title"), self.page), 1)
        step = CaptionLabel(t("wz_step", self.step), self.page)
        head.addWidget(step, 0, Qt.AlignVCenter)
        lay.addLayout(head)
        lay.addSpacing(6)

        getattr(self, f"_step{self.step}")(lay)

        self.status = CaptionLabel("", self.page)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.viewLayout.addWidget(self.page)

        self.yesButton.setText(t("btn_finish") if self.step == 3 else t("btn_next"))
        self.cancelButton.setText(t("btn_cancel") if self.step == 1 else t("btn_back"))

    def _row(self, lay, label, widget):
        row = QHBoxLayout()
        lbl = BodyLabel(label, self.page)
        lbl.setFixedWidth(190)
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        lay.addLayout(row)

    def _text(self, lay, key):
        lbl = BodyLabel(t(key), self.page)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

    def _step1(self, lay):
        self._text(lay, "wz_welcome")
        self._device_card(lay)
        self.lang_box = ComboBox(self.page)
        for code, name in (("cs", "Čeština"), ("en", "English")):
            self.lang_box.addItem(name, userData=code)
        self.lang_box.setCurrentIndex(0 if self.v["lang"] == "cs" else 1)
        self._row(lay, t("set_lang"), self.lang_box)

    def _step2(self, lay):
        self._device_card(lay)
        self._text(lay, "wz_conn_info")
        self.ip = LineEdit(self.page)
        if self.detect["ip"] and not self._ip_touched:
            self.v["router_ip"] = self.detect["ip"]
        self.ip.setText(self.v["router_ip"])
        self.ip.textEdited.connect(lambda _: setattr(self, "_ip_touched", True))
        self.ip.setPlaceholderText("192.168.1.1")
        self._row(lay, t("set_ip"), self.ip)
        self.pw = PasswordLineEdit(self.page)
        self.pw.setText(self.v["password"])
        self._row(lay, t("set_pw"), self.pw)
        btn = PushButton(FIF.CONNECT, t("btn_test"), self.page)
        btn.clicked.connect(self._do_test)
        lay.addWidget(btn, 0, Qt.AlignLeft)

    def _step3(self, lay):
        self._text(lay, "wz_opts_info")
        self.poll = interval_box(self.page, self.v["poll_s"])
        self._row(lay, t("set_interval"), self.poll)
        self.auto = SwitchButton(self.page)
        self.auto.setChecked(self.v["autostart"])
        self.auto.setOnText(t("on"))
        self.auto.setOffText(t("off"))
        self._row(lay, t("set_autostart"), self.auto)
        self.upd = SwitchButton(self.page)
        self.upd.setChecked(self.v["check_updates"])
        self.upd.setOnText(t("on"))
        self.upd.setOffText(t("off"))
        self._row(lay, t("set_upd_auto"), self.upd)

    # ── detekce routeru ──
    def _device_card(self, lay):
        card = SimpleCardWidget(self.page)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 8, 10)
        row.setSpacing(12)
        self.dev_ring = IndeterminateProgressRing(card)
        self.dev_ring.setFixedSize(20, 20)
        self.dev_ring.setStrokeWidth(3)
        self.dev_icon = IconWidget(FIF.IOT, card)
        self.dev_icon.setFixedSize(20, 20)
        row.addWidget(self.dev_ring)
        row.addWidget(self.dev_icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.dev_title = StrongBodyLabel("", card)
        self.dev_sub = CaptionLabel("", card)
        self.dev_sub.setWordWrap(True)
        col.addWidget(self.dev_title)
        col.addWidget(self.dev_sub)
        row.addLayout(col, 1)
        btn = TransparentToolButton(FIF.SYNC, card)
        btn.setToolTip(t("wz_search_again"))
        btn.clicked.connect(self._search_again)
        row.addWidget(btn)
        lay.addWidget(card)
        self._render_device()

    def _render_device(self):
        if not hasattr(self, "dev_title"):
            return
        try:
            d = self.detect
            searching = d["state"] == "searching"
            self.dev_ring.setVisible(searching)
            self.dev_icon.setVisible(not searching)
            if searching:
                self.dev_title.setText(t("wz_searching"))
                self.dev_sub.setText(t("wz_searching_sub"))
            elif d["info"]:
                self.dev_icon.setIcon(FIF.ACCEPT_MEDIUM)
                self.dev_title.setText(t("wz_found", d["info"].get("name", "Netgear")))
                info = d["info"]
                model = " · ".join(x for x in (info.get("model") or info.get("sku"),
                                               info.get("fw") and f"fw {info['fw']}") if x)
                self.dev_sub.setText(t("wz_found_sub", model or "—", d["ip"]))
            else:
                self.dev_icon.setIcon(FIF.QUESTION)
                self.dev_title.setText(t("wz_not_found"))
                self.dev_sub.setText(t("wz_not_found_sub"))
        except RuntimeError:                # widget už smazaný (přechod mezi kroky)
            pass

    def _search_again(self):
        extra = [self.ip.text().strip()] if self.step == 2 else [self.v["router_ip"]]
        self.detect = {"state": "searching", "ip": None, "info": None}
        self._render_device()
        self.finder.start(extra)

    def _on_found(self, ip, info):
        self.detect = {"state": "found" if info else "none", "ip": ip, "info": info}
        if ip and self.step == 2 and not self._ip_touched:
            self.ip.setText(ip)
        self._render_device()

    # ── test spojení ──
    def _status(self, text, level=c.NONE):
        col = c.level_color(level)
        self.status.setTextColor(col, col)
        self.status.setText(text)

    def _do_test(self):
        self._status(t("st_testing"), c.WARN)
        ip, pw = self.ip.text().strip(), self.pw.text()
        if ip != self.detect.get("ip"):     # jiná IP → ověř i model na ní
            self.detect = {"state": "searching", "ip": None, "info": None}
            self._render_device()
            self.finder.start([ip])
        threading.Thread(target=lambda: self._test_done.emit(*c.test_connection(ip, pw)),
                         daemon=True).start()

    def _on_test_done(self, ok, msg):
        if self.step == 2:
            self._status(msg, c.GOOD if ok else c.BAD)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)
