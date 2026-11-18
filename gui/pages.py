"""Stránky hlavního okna: Přehled, Rychlost, Nastavení, O aplikaci."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QIntValidator
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox,
                            FluentIcon as FIF, HyperlinkCard, IconWidget,
                            IndeterminateProgressRing, LineEdit, PasswordLineEdit,
                            PrimaryPushButton, PrimaryPushSettingCard, ProgressBar,
                            PushButton, PushSettingCard, ScrollArea, SettingCard,
                            SettingCardGroup, SimpleCardWidget,
                            StrongBodyLabel, SubtitleLabel, SwitchSettingCard,
                            TableWidget, TitleLabel)

import config
import device
import i18n
from gui import common as c
from gui.icons import app_pixmap
from gui.widgets import InfoRow, Pill, SignalBars, SignalChart, StatTile
from i18n import t
from version import APP_NAME, GITHUB_URL, __version__


class _Page(ScrollArea):
    """Rolovací stránka s nadpisem a průhledným pozadím (kvůli Mica)."""

    def __init__(self, name, title, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.lay = QVBoxLayout(self.view)
        self.lay.setContentsMargins(36, 28, 36, 36)
        self.lay.setSpacing(12)
        head = QHBoxLayout()
        self.title = TitleLabel(title, self.view)
        head.addWidget(self.title)
        head.addStretch(1)
        self.head = head
        self.lay.addLayout(head)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.enableTransparentBackground()

    def section(self, text):
        lbl = StrongBodyLabel(text, self.view)
        self.lay.addSpacing(8)
        self.lay.addWidget(lbl)
        return lbl


def _card(parent):
    card = SimpleCardWidget(parent)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(2)
    return card, lay


# ══════════════════════════════════════════════════════════════════════════════
class OverviewPage(_Page):
    def __init__(self, parent=None):
        super().__init__("overview", t("nav_overview"), parent)
        self.pill = Pill("…", self.view)
        self.head.insertWidget(1, self.pill, 0, Qt.AlignVCenter)
        self.head.insertSpacing(1, 12)
        self.updated = CaptionLabel("", self.view)
        self.head.addWidget(self.updated, 0, Qt.AlignVCenter)

        # hlavní karta signálu
        hero = SimpleCardWidget(self.view)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(24)
        self.bars = SignalBars(hero, QSize(72, 52))
        hl.addWidget(self.bars, 0, Qt.AlignVCenter)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        self.operator = SubtitleLabel("—", hero)
        f = self.operator.font()
        f.setPixelSize(26)
        self.operator.setFont(f)
        self.net = BodyLabel("", hero)
        self.hint = CaptionLabel("", hero)
        self.hint.setWordWrap(True)
        tl.addWidget(self.operator)
        tl.addWidget(self.net)
        tl.addWidget(self.hint)
        hl.addLayout(tl, 1)
        self.lay.addWidget(hero)

        # dlaždice
        grid = QGridLayout()
        grid.setSpacing(12)
        self.t_rsrp = StatTile(FIF.IOT, "RSRP", self.view)
        self.t_sinr = StatTile(FIF.MIX_VOLUMES, "SINR", self.view)
        self.t_rsrq = StatTile(FIF.ALIGNMENT, "RSRQ", self.view)
        self.batt_bar = ProgressBar(self.view)
        self.batt_bar.setRange(0, 100)
        self.t_batt = StatTile(FIF.CALORIES, t("row_batt"), self.view, extra=self.batt_bar)
        self.t_temp = StatTile(FIF.FRIGID, t("row_temp"), self.view)
        self.t_clients = StatTile(FIF.WIFI, t("row_clients"), self.view)
        for i, tile in enumerate((self.t_rsrp, self.t_sinr, self.t_rsrq,
                                  self.t_batt, self.t_temp, self.t_clients)):
            grid.addWidget(tile, i // 3, i % 3)
        # spotřeba dat (počítadla routeru = všechna zařízení)
        self.t_total = StatTile(FIF.DOWNLOAD, t("row_period_data"), self.view)
        self.data_bar = ProgressBar(self.view)
        self.data_bar.setRange(0, 100)
        self.t_roam = StatTile(FIF.GLOBE, t("row_roam_data"), self.view, extra=self.data_bar)
        grid.addWidget(self.t_total, 2, 0)
        grid.addWidget(self.t_roam, 2, 1, 1, 2)
        self.lay.addLayout(grid)

        # graf
        self.section(t("sec_history"))
        chart_card, cl = _card(self.view)
        self.chart = SignalChart(chart_card)
        cl.addWidget(self.chart)
        cap = CaptionLabel(t("chart_caption"), chart_card)
        cap.setTextColor(QColor(96, 96, 96), QColor(170, 170, 170))
        cl.addWidget(cap)
        self.lay.addWidget(chart_card)

        # detaily
        self.section(t("sec_details"))
        det, dl = _card(self.view)
        self.rows = {}
        for key in ("device", "net", "operator", "mode", "nr", "nr_signal", "ca", "cell",
                    "bts", "batt", "temp", "uptime"):
            row = InfoRow(t(f"row_{key}"), det)
            dl.addWidget(row)
            self.rows[key] = row
        self.lay.addWidget(det)
        self.lay.addStretch(1)

    def update_state(self, snap, history):
        sig, data = snap.get("sig"), snap.get("data")
        self.chart.set_history(list(history))
        if not snap.get("ok") or sig is None:
            starting = snap.get("starting")
            self.pill.set_state("…" if starting else t("offline"),
                                c.NONE if starting else c.BAD)
            self.operator.setText(t("connecting") if starting else t("no_conn"))
            self.net.setText("")
            self.hint.setText("" if starting else
                              t("hint_password") if snap.get("need_password")
                              else t("hint_offline"))
            self.bars.set_bars(0)
            for tile in (self.t_rsrp, self.t_sinr, self.t_rsrq, self.t_batt,
                         self.t_temp, self.t_clients, self.t_total, self.t_roam):
                tile.set("—")
            self.data_bar.hide()
            self.updated.setText("")
            return

        roaming = sig.get("roaming") is True
        self.pill.set_state(f"{c.net_label(sig)} · {t('roaming')}" if roaming
                            else c.net_label(sig), c.BAD if roaming else "accent")
        self.bars.set_bars(c.bars_int(sig))
        self.operator.setText(str(sig.get("operator") or "—"))
        self.net.setText(f"{sig.get('sit', '')} · {sig.get('typ_sluzby', '')} · "
                         f"{t('roaming') if roaming else t('home_net')}")
        self.hint.setText(t("hint_roaming") if roaming else
                          t("hint_password") if snap.get("need_password") else "")

        rq, rl = c.rsrp_quality(sig.get("rsrp"))
        sq, sl = c.sinr_quality(sig.get("sinr"))
        self.t_rsrp.set(c.fmt(sig.get("rsrp"), "dBm"), rq, rl)
        self.t_sinr.set(c.fmt(sig.get("sinr"), "dB"), sq, sl)
        self.t_rsrq.set(c.fmt(sig.get("rsrq"), "dB"), f"RSSI {c.fmt(sig.get('rssi'), 'dBm')}")
        pct, src = c.battery(data)
        self.t_batt.set(c.fmt(pct, "%"), src, c.battery_level(pct))
        self.batt_bar.setValue(pct or 0)
        gen = (data or {}).get("general", {}) or {}
        w = (data or {}).get("wwan", {}) or {}
        self.t_temp.set(c.fmt(gen.get("devTemperature"), "°C"),
                        f"{t('thermal_state')} {w.get('thermalState', '—')}")
        wifi = (data or {}).get("wifi", {}) or {}
        self.t_clients.set(c.fmt(wifi.get("clientCount")), "WiFi")
        u = snap.get("usage")
        view = c.usage_view(u)
        if view:
            value, detail, pct, level = view
            self.t_total.set(c.gb(u["total"]), t("usage_all_devices"))
            self.t_roam.set(value, detail, level if level != c.GOOD else None)
            c.apply_usage_bar(self.data_bar, pct)
        else:
            self.t_total.set("—", t("usage_need_login"))
            self.t_roam.set("—")
            self.data_bar.hide()

        r = self.rows
        r["device"].set(device.describe(snap.get("device")) or "—")
        r["net"].set(f"{sig.get('sit')} ({sig.get('typ_sluzby')}) · "
                     f"{t('roaming') if roaming else t('home_net')}",
                     c.BAD if roaming else c.GOOD)
        r["operator"].set(f"{sig.get('operator')} · MCC/MNC {sig.get('mcc')}/{sig.get('mnc')}")
        r["mode"].set(c.band_region(data))
        nr_txt, nr_lvl = c.nr_state(data)
        r["nr"].set(nr_txt, nr_lvl)
        r["nr_signal"].set(f"RSRP {c.fmt(sig.get('nr5g_rsrp'), 'dBm')} · "
                           f"RSRQ {c.fmt(sig.get('nr5g_rsrq'), 'dB')} · "
                           f"SINR {c.fmt(sig.get('nr5g_sinr'), 'dB')}")
        r["ca"].set(c.ca_text(data))
        r["cell"].set(f"cell {sig.get('cell_id')} · LAC {sig.get('lac')} · "
                      f"{sig.get('band')} · {t('radio_quality')} {sig.get('radio_quality')}")
        kind, loc = snap.get("bts") or ("none", "")
        if kind == "exact":
            r["bts"].set(loc, c.GOOD)
        elif kind == "oblast":
            r["bts"].set(t("bts_area", loc), c.WARN)
        else:
            r["bts"].set(t("bts_unknown"))
        r["batt"].set(f"{c.fmt(pct, '%')} {src}".strip())
        r["temp"].set(f"{c.fmt(gen.get('devTemperature'), '°C')} · "
                      f"{t('thermal_state')} {w.get('thermalState', '—')}")
        r["uptime"].set(c.uptime(data))
        ts = snap.get("ts")
        self.updated.setText(t("updated_at", ts.strftime("%H:%M:%S")) if ts else "")


# ══════════════════════════════════════════════════════════════════════════════
class SpeedPage(_Page):
    startRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("speed", t("nav_speed"), parent)

        intro, il = _card(self.view)
        row = QHBoxLayout()
        row.setSpacing(16)
        txt = QVBoxLayout()
        txt.addWidget(StrongBodyLabel(t("speed_intro_title"), intro))
        note = BodyLabel(t("speed_intro"), intro)
        note.setWordWrap(True)
        txt.addWidget(note)
        row.addLayout(txt, 1)
        self.ring = IndeterminateProgressRing(intro)
        self.ring.setFixedSize(36, 36)
        self.ring.hide()
        row.addWidget(self.ring, 0, Qt.AlignVCenter)
        self.btn = PrimaryPushButton(FIF.SPEED_HIGH, t("btn_speed_start"), intro)
        self.btn.clicked.connect(self.startRequested.emit)
        row.addWidget(self.btn, 0, Qt.AlignVCenter)
        il.addLayout(row)
        self.status = CaptionLabel("", intro)
        il.addWidget(self.status)
        self.lay.addWidget(intro)

        grid = QHBoxLayout()
        grid.setSpacing(12)
        self.t_down = StatTile(FIF.DOWNLOAD, "Download", self.view)
        self.t_up = StatTile(FIF.SEND, "Upload", self.view)
        self.t_lat = StatTile(FIF.STOP_WATCH, t("latency"), self.view)
        for tile in (self.t_down, self.t_up, self.t_lat):
            grid.addWidget(tile)
        self.lay.addLayout(grid)

        self.section(t("sec_speed_history"))
        self.table = TableWidget(self.view)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [t("col_time"), "Download (Mbit/s)", "Upload (Mbit/s)", t("latency") + " (ms)"])
        self.table.verticalHeader().hide()
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(300)
        self.lay.addWidget(self.table)
        self.lay.addStretch(1)

    def set_running(self, running):
        self.btn.setEnabled(not running)
        self.ring.setVisible(running)
        if running:
            self.status.setText(t("speed_measuring"))

    def set_roaming(self, roaming):
        if roaming:
            self.btn.setEnabled(False)
            self.status.setText(t("speed_roaming"))

    def show_result(self, last, history):
        if last:
            self.t_down.set(f"{last.get('download_mbps', '—')} Mbit/s")
            self.t_up.set(f"{last.get('upload_mbps', '—')} Mbit/s")
            self.t_lat.set(f"{last.get('latence_ms', '—')} ms")
            self.status.setText(t("speed_last", str(last.get("cas", "")).replace("T", " ")))
        else:
            for tile in (self.t_down, self.t_up, self.t_lat):
                tile.set("—")
            self.status.setText(t("speed_never"))
        self.table.setRowCount(len(history))
        for i, r in enumerate(history):
            vals = [str(r.get("cas", "")).replace("T", " "), r.get("download_mbps", ""),
                    r.get("upload_mbps", ""), r.get("latence_ms", "")]
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()


# ══════════════════════════════════════════════════════════════════════════════
class _WidgetCard(SettingCard):
    """SettingCard s libovolnými widgety vpravo."""

    def __init__(self, icon, title, content, widgets, parent=None):
        super().__init__(icon, title, content, parent)
        for w in widgets:
            self.hBoxLayout.addWidget(w, 0, Qt.AlignRight)
            self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addSpacing(8)


INTERVALS = (5, 10, 15, 30, 60, 120, 300)


def interval_box(parent, current):
    """ComboBox s intervaly obnovy (místo SpinBoxu – ten je v kombinaci
    Fluent Widgets 1.11 + PySide6 6.12 vykreslený prázdný)."""
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = 30
    values = sorted(set(INTERVALS) | {max(5, current)})
    box = ComboBox(parent)
    for v in values:
        box.addItem(f"{v} s" if v < 60 else f"{v // 60} min" if v % 60 == 0 else f"{v} s",
                    userData=v)
    box.setCurrentIndex(values.index(max(5, current)))
    box.setMinimumWidth(130)
    return box


def _switch_texts(card):
    card.switchButton.setOnText(t("on"))
    card.switchButton.setOffText(t("off"))
    card.switchButton.setChecked(card.switchButton.isChecked())


class SettingsPage(_Page):
    routerSaved = Signal()
    languageChanged = Signal(str)
    themeChanged = Signal(str)
    checkUpdates = Signal()
    openWizard = Signal()
    dataSettingsChanged = Signal()          # limit / den zúčtování → přepočítat
    notify = Signal(str, str, str)          # úroveň, titulek, text

    THEMES = ("auto", "light", "dark")
    LANGS = (("cs", "Čeština"), ("en", "English"))

    def __init__(self, parent=None):
        super().__init__("settings", t("nav_settings"), parent)
        from gui.common import autostart_enabled, set_autostart, test_connection
        self._test = test_connection
        self._set_autostart = set_autostart
        cfg = config.load(force=True)

        # ── Router ──
        g = SettingCardGroup(t("grp_router"), self.view)
        from gui.workers import DeviceFinder
        self.finder = DeviceFinder(self)
        self.finder.found.connect(self._on_found)
        self.find_btn = PushButton(FIF.SEARCH, t("btn_find_router"), self.view)
        self.find_btn.clicked.connect(self._find)
        self.dev_card = _WidgetCard(FIF.IOT, t("set_device"),
                                    cfg.get("device_name") or t("set_device_unknown"),
                                    [self.find_btn], g)
        g.addSettingCard(self.dev_card)
        self.ip = LineEdit(self.view)
        self.ip.setText(cfg.get("router_ip", ""))
        self.ip.setFixedWidth(220)
        self.ip.setPlaceholderText("192.168.1.1")
        self.pw = PasswordLineEdit(self.view)
        self.pw.setText(cfg.get("password", ""))
        self.pw.setFixedWidth(220)
        g.addSettingCard(_WidgetCard(FIF.GLOBE, t("set_ip"), t("set_ip_desc"), [self.ip], g))
        g.addSettingCard(_WidgetCard(FIF.FINGERPRINT, t("set_pw"), t("set_pw_desc"), [self.pw], g))
        test_btn = PushButton(FIF.CONNECT, t("btn_test"), self.view)
        save_btn = PrimaryPushButton(FIF.SAVE, t("btn_save_connect"), self.view)
        self.conn_card = _WidgetCard(FIF.SYNC, t("set_conn"), t("set_conn_desc"),
                                     [test_btn, save_btn], g)
        g.addSettingCard(self.conn_card)
        test_btn.clicked.connect(self._do_test)
        save_btn.clicked.connect(self._do_save)
        self.lay.addWidget(g)

        # ── Mobilní data ──
        gd = SettingCardGroup(t("grp_data"), self.view)
        self.limit = LineEdit(self.view)
        self.limit.setValidator(QIntValidator(0, 100000, self.limit))
        self.limit.setText(str(cfg.get("roam_limit_gb", 60)))
        self.limit.setFixedWidth(90)
        self.limit.editingFinished.connect(self._save_limit)
        gd.addSettingCard(_WidgetCard(FIF.GLOBE, t("set_roam_limit"), t("set_roam_limit_desc"),
                                      [self.limit, BodyLabel("GB", self.view)], gd))
        self.bday = ComboBox(self.view)
        self.bday.addItem(t("billing_router"), userData=0)
        for d in range(1, 32):
            self.bday.addItem(f"{d}.", userData=d)
        try:
            self.bday.setCurrentIndex(max(0, min(31, int(cfg.get("billing_day") or 0))))
        except (TypeError, ValueError):
            self.bday.setCurrentIndex(0)
        self.bday.setMaxVisibleItems(10)
        self.bday.currentIndexChanged.connect(self._save_billing_day)
        gd.addSettingCard(_WidgetCard(FIF.CALENDAR, t("set_billing_day"),
                                      t("set_billing_day_desc"), [self.bday], gd))
        modes = ("auto", "hint", "off")
        self.met = ComboBox(self.view)
        for m in modes:
            self.met.addItem(t(f"metered_{m}"), userData=m)
        cur = cfg.get("metered_mode")
        self.met.setCurrentIndex(modes.index(cur) if cur in modes else 0)
        self.met.currentIndexChanged.connect(
            lambda i: config.save({"metered_mode": modes[i]}))
        gd.addSettingCard(_WidgetCard(FIF.SPEED_OFF, t("set_metered"), t("set_metered_desc"),
                                      [self.met], gd))
        self.lay.addWidget(gd)

        # ── Aplikace ──
        g2 = SettingCardGroup(t("grp_app"), self.view)
        self.poll = interval_box(self.view, cfg.get("poll_s", 30))
        self.poll.currentIndexChanged.connect(
            lambda i: config.save({"poll_s": int(self.poll.currentData())}))
        g2.addSettingCard(_WidgetCard(FIF.STOP_WATCH, t("set_interval"),
                                      t("set_interval_desc"), [self.poll], g2))
        self.auto = SwitchSettingCard(FIF.POWER_BUTTON, t("set_autostart"),
                                      t("set_autostart_desc"), parent=g2)
        self.auto.setChecked(autostart_enabled())
        _switch_texts(self.auto)
        self.auto.checkedChanged.connect(self._toggle_autostart)
        g2.addSettingCard(self.auto)

        self.theme = ComboBox(self.view)
        for key in self.THEMES:
            self.theme.addItem(t(f"theme_{key}"), userData=key)
        self.theme.setCurrentIndex(max(0, list(self.THEMES).index(cfg.get("theme", "auto"))
                                       if cfg.get("theme") in self.THEMES else 0))
        self.theme.currentIndexChanged.connect(
            lambda i: self.themeChanged.emit(self.THEMES[i]))
        g2.addSettingCard(_WidgetCard(FIF.BRUSH, t("set_theme"), t("set_theme_desc"),
                                      [self.theme], g2))

        from gui.flyout import STYLES
        self.fly = ComboBox(self.view)
        for key in STYLES:
            self.fly.addItem(t(f"flyout_{key}"), userData=key)
        cur = cfg.get("flyout_style")
        self.fly.setCurrentIndex(STYLES.index(cur) if cur in STYLES else 1)
        self.fly.currentIndexChanged.connect(
            lambda i: config.save({"flyout_style": STYLES[i]}))
        g2.addSettingCard(_WidgetCard(FIF.TRANSPARENT, t("set_flyout"),
                                      t("set_flyout_desc"), [self.fly], g2))

        self.lang = ComboBox(self.view)
        for code, name in self.LANGS:
            self.lang.addItem(name, userData=code)
        self.lang.setCurrentIndex(0 if i18n.lang() == "cs" else 1)
        self.lang.currentIndexChanged.connect(
            lambda i: self.languageChanged.emit(self.LANGS[i][0]))
        g2.addSettingCard(_WidgetCard(FIF.LANGUAGE, t("set_lang"), t("set_lang_desc"),
                                      [self.lang], g2))
        wiz = PushSettingCard(t("btn_open"), FIF.EDUCATION, t("set_wizard"),
                              t("set_wizard_desc"), g2)
        wiz.clicked.connect(self.openWizard.emit)
        g2.addSettingCard(wiz)
        self.lay.addWidget(g2)

        # ── Aktualizace ──
        g3 = SettingCardGroup(t("grp_updates"), self.view)
        self.upd_auto = SwitchSettingCard(FIF.SYNC, t("set_upd_auto"),
                                          t("set_upd_auto_desc"), parent=g3)
        self.upd_auto.setChecked(bool(cfg.get("check_updates", True)))
        _switch_texts(self.upd_auto)
        self.upd_auto.checkedChanged.connect(
            lambda v: config.save({"check_updates": bool(v)}))
        g3.addSettingCard(self.upd_auto)
        self.upd_card = PrimaryPushSettingCard(t("btn_check_now"), FIF.UPDATE,
                                               t("set_upd_check"),
                                               t("version_current", __version__), g3)
        self.upd_card.clicked.connect(self.checkUpdates.emit)
        g3.addSettingCard(self.upd_card)
        self.lay.addWidget(g3)
        self.lay.addStretch(1)

    def _save_limit(self):
        try:
            v = max(0, int(self.limit.text() or 0))
        except ValueError:
            return
        if v != config.get("roam_limit_gb"):
            config.save({"roam_limit_gb": v})
            self.dataSettingsChanged.emit()

    def _save_billing_day(self, i):
        config.save({"billing_day": int(self.bday.itemData(i) or 0)})
        self.dataSettingsChanged.emit()

    def set_device(self, info):
        if info and not self.finder.busy:
            self.dev_card.setContent(device.describe(info))

    def _find(self):
        self.find_btn.setEnabled(False)
        self.dev_card.setContent(t("wz_searching"))
        self.finder.start([self.ip.text().strip()])

    def _on_found(self, ip, info):
        self.find_btn.setEnabled(True)
        if not info:
            self.dev_card.setContent(t("wz_not_found"))
            self.notify.emit("warning", t("set_device"), t("wz_not_found_sub"))
            return
        self.dev_card.setContent(device.describe(info))
        if ip != self.ip.text().strip():
            self.ip.setText(ip)
            self.notify.emit("info", t("wz_found", info.get("name", "Netgear")),
                             t("set_found_ip", ip))
        else:
            self.notify.emit("success", t("wz_found", info.get("name", "Netgear")), ip)

    def set_update_status(self, text):
        self.upd_card.setContent(text)

    def _toggle_autostart(self, on):
        try:
            self._set_autostart(bool(on))
        except OSError as e:
            self.notify.emit("error", t("set_autostart"), str(e))

    def _do_test(self):
        import threading
        self.conn_card.setContent(t("st_testing"))
        ip, pw = self.ip.text().strip(), self.pw.text()

        def work():
            ok, msg = self._test(ip, pw)
            self.notify.emit("success" if ok else "error", t("set_conn"), msg)
        threading.Thread(target=work, daemon=True).start()

    def on_notify_done(self):
        self.conn_card.setContent(t("set_conn_desc"))

    def _do_save(self):
        ip = self.ip.text().strip()
        if not ip:
            self.notify.emit("warning", t("set_ip"), t("st_ip_required"))
            return
        config.save({"router_ip": ip, "password": self.pw.text()})
        self.routerSaved.emit()
        self.notify.emit("success", t("btn_save_connect"), t("st_saved"))


# ══════════════════════════════════════════════════════════════════════════════
class AboutPage(_Page):
    checkUpdates = Signal()

    def __init__(self, parent=None):
        super().__init__("about", t("nav_about"), parent)
        hero = SimpleCardWidget(self.view)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(20)
        ic = IconWidget(self.view)
        ic.setIcon(QIcon(app_pixmap(128)))
        ic.setFixedSize(64, 64)
        hl.addWidget(ic)
        tl = QVBoxLayout()
        name = SubtitleLabel(APP_NAME, hero)
        tl.addWidget(name)
        tl.addWidget(BodyLabel(t("version_current", __version__), hero))
        desc = CaptionLabel(t("about_desc"), hero)
        desc.setWordWrap(True)
        tl.addWidget(desc)
        hl.addLayout(tl, 1)
        upd = PushButton(FIF.UPDATE, t("btn_check_now"), hero)
        upd.clicked.connect(self.checkUpdates.emit)
        hl.addWidget(upd, 0, Qt.AlignVCenter)
        self.lay.addWidget(hero)

        g = SettingCardGroup(t("grp_links"), self.view)
        g.addSettingCard(HyperlinkCard(GITHUB_URL, t("link_github_btn"), FIF.GITHUB,
                                       t("link_github"), GITHUB_URL, g))
        g.addSettingCard(HyperlinkCard(GITHUB_URL + "/issues", t("link_issues_btn"),
                                       FIF.FEEDBACK, t("link_issues"),
                                       t("link_issues_desc"), g))
        g.addSettingCard(HyperlinkCard("https://gsmweb.cz/", "gsmweb.cz", FIF.PIN,
                                       t("link_bts"), t("link_bts_desc"), g))
        g.addSettingCard(HyperlinkCard(GITHUB_URL + "/blob/main/LICENSE", "GPLv3",
                                       FIF.CERTIFICATE, t("link_license"),
                                       t("link_license_desc"), g))
        self.lay.addWidget(g)

        disc, dl = _card(self.view)
        lbl = CaptionLabel(t("about_disclaimer"), disc)
        lbl.setWordWrap(True)
        dl.addWidget(lbl)
        self.lay.addWidget(disc)
        self.lay.addStretch(1)
