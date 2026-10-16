"""vimvibe Settings window. Opens with Ctrl+Shift+, from anywhere (Ctrl+, while the overlay is open), like Shortcat's
Preferences, or with `vimvibe settings` / `vimvibe_palette.py --settings`.

Edits ~/.config/vimvibe/config.toml. The overlay and the daemon re-read that file every time the overlay opens, so
changes apply on the next use without restarting anything. Covers Shortcat's preferences that make sense on Linux
(shortcut, launch at login, label delay, continuous mode, hide the query pane, HJKL/IJKL scroll keys) plus vimvibe's
own: label/flag theme (colours, font, sizes), panel look, excluded apps, accessibility and pointer setup.
"""
import json, os, shutil, subprocess

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialogButtonBox, QDoubleSpinBox, QFontComboBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from vimvibe_style import CONFIG, PRESETS, PROFILE, Theme

DELAYS = [("Immediately", 0), ("After 200 ms", 200), ("After 500 ms", 500), ("After 1 second", 1000),
          ("After 2 seconds (Shortcat's default)", 2000), ("After 5 seconds", 5000), ("After input", -1)]
AUTOSTART = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart", "vimvibe.desktop")


def core_binary():
    """Path of vimvibe-core: $VIMVIBE_CORE, then $PATH, then ~/.local/bin."""
    return os.environ.get("VIMVIBE_CORE") or shutil.which("vimvibe-core") or os.path.expanduser("~/.local/bin/vimvibe-core")


def launcher():
    """Path of the `vimvibe` launcher script (used for the autostart entry)."""
    return shutil.which("vimvibe") or os.path.expanduser("~/.local/bin/vimvibe")


class ColorField(QWidget):
    """A colour setting: text field (a colour name/#hex, or "auto" where allowed), a swatch, and a picker button."""

    def __init__(self, allow_auto, on_change):
        """`allow_auto` adds an Automatic checkbox; `on_change` is called on every edit (for the live preview)."""
        super().__init__()
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.auto = QCheckBox("Automatic") if allow_auto else None
        self.text = QLineEdit(); self.text.setMaximumWidth(110)
        self.swatch = QPushButton(); self.swatch.setFixedWidth(40); self.swatch.setToolTip("Pick a colour")
        self.swatch.clicked.connect(self.pick)
        self.text.textChanged.connect(lambda _: (self.paint_swatch(), on_change()))
        if self.auto:
            self.auto.toggled.connect(lambda on: (self.text.setEnabled(not on), self.swatch.setEnabled(not on), on_change()))
            lay.addWidget(self.auto)
        lay.addWidget(self.text); lay.addWidget(self.swatch); lay.addStretch()

    def paint_swatch(self):
        """Show the current colour on the swatch button."""
        c = QColor(self.text.text())
        self.swatch.setStyleSheet(f"background: {c.name() if c.isValid() else 'transparent'}; border: 1px solid #888;")

    def pick(self):
        """Choose a colour with the colour dialog."""
        c = QColorDialog.getColor(QColor(self.text.text()), self, "Colour")
        if c.isValid():
            self.text.setText(c.name())

    def set(self, value):
        """Show a setting value ("auto" ticks Automatic)."""
        is_auto = value in ("", "auto")
        if self.auto:
            self.auto.setChecked(is_auto)
        self.text.setText("" if is_auto and self.auto else str(value))
        self.paint_swatch()

    def value(self):
        """The setting value: "auto", or the colour text."""
        if self.auto and self.auto.isChecked():
            return "auto"
        return self.text.text().strip()

    def valid(self):
        """Whether the field holds something usable."""
        return self.value() == "auto" or QColor(self.value()).isValid()


class Preview(QWidget):
    """Live preview of the current Appearance settings: three mock buttons with labels (one selected) and a result row,
    drawn with the overlay's own Theme code."""

    def __init__(self, settings_window):
        """`settings_window.collect()` supplies the settings to preview."""
        super().__init__()
        self.sw = settings_window
        self.setMinimumHeight(150)

    def paintEvent(self, _):
        """Draw the mock window, its labelled buttons and one panel row."""
        cfg = self.sw.collect()
        t = Theme(cfg)
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        win = QRectF(8, 8, self.width() - 16, 70)
        p.fillRect(win, QColor(60, 63, 70)); p.setPen(QColor(210, 212, 218))
        x = win.x() + 14
        for i, (name, hint) in enumerate([("Save", "SA"), ("Cancel", "CA"), ("Open folder", "OF")]):
            r = QRectF(x, win.y() + 18, 30 + 9 * len(name), 34)
            path = QPainterPath(); path.addRoundedRect(r, 5, 5)
            p.fillPath(path, QColor(84, 88, 98)); p.setPen(QColor(230, 232, 238)); p.setFont(t.row_font)
            p.drawText(r.adjusted(8, 0, 0, 0), Qt.AlignVCenter, name)
            if i == 1:  # the selected element
                fill = QColor(t.selected); fill.setAlpha(80)
                p.setPen(QPen(t.selected, 2)); p.setBrush(fill); p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 4, 4); p.setBrush(Qt.NoBrush)
            w, h = t.label_size(hint)
            lr = QRectF(r.right() - w - 1, r.center().y() - h / 2, w, h)
            t.draw_label(p, lr, hint, typed=1 if i == 2 else 0, selected=(i == 1))
            x = r.right() + 24
        panel = QRectF(8, win.bottom() + 10, min(self.width() - 16, t.panel_width), t.row_h + 16)
        path = QPainterPath(); path.addRoundedRect(panel, 10, 10)
        p.fillPath(path, t.panel_bg); p.setPen(QPen(t.panel_border, 1)); p.drawPath(path)
        row = panel.adjusted(8, 8, -8, -8)
        sel = QColor(t.selected); sel.setAlpha(75)
        rp = QPainterPath(); rp.addRoundedRect(row, 7, 7); p.fillPath(rp, sel)
        p.setFont(t.row_font); p.setPen(t.panel_text); p.drawText(row.adjusted(10, 0, 0, 0), Qt.AlignVCenter, "Cancel")
        w, h = t.label_size("CA")
        t.draw_label(p, QRectF(row.right() - 70 - w, row.center().y() - h / 2, w, h), "CA")
        p.setFont(t.small_font); p.setPen(t.panel_role)
        p.drawText(QRectF(row.right() - 70 - w - 70, row.y(), 60, row.height()), Qt.AlignVCenter | Qt.AlignRight, "Button")
        kr = QRectF(row.right() - 54, row.y() + 4, 22, row.height() - 8)
        for r_, s in ((kr, "⌃"), (kr.translated(26, 0), "1")):
            kp = QPainterPath(); kp.addRoundedRect(r_, 5, 5); p.fillPath(kp, t.key_bg)
            p.setFont(t.key_font); p.setPen(t.key_fg); p.drawText(r_, Qt.AlignCenter, s)


class SettingsWindow(QWidget):
    def __init__(self, read_config, write_config, defaults):
        """Build the tabs and load the current settings into them."""
        super().__init__()
        self.read_config, self.write_config, self.defaults = read_config, write_config, defaults
        self.loading = False
        self.setWindowTitle(f"vimvibe Settings ({PROFILE} profile)" if PROFILE else "vimvibe Settings")
        self.resize(760, 680)
        tabs = QTabWidget()
        tabs.addTab(self.general_tab(), "General")
        tabs.addTab(self.appearance_tab(), "Appearance")
        tabs.addTab(self.labels_tab(), "Labels && behaviour")
        tabs.addTab(self.apps_tab(), "Excluded apps")
        tabs.addTab(self.system_tab(), "Accessibility && setup")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda: self.load(self.defaults))
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)
        self.load(self.read_config())

    def changed(self):
        """Any appearance control changed: refresh the preview."""
        if not self.loading and hasattr(self, "preview"):
            self.preview.update()

    # --- tabs -----------------------------------------------------------------------
    def general_tab(self):
        """Shortcuts, launch at login, and which extra results to offer."""
        w = QWidget(); f = QFormLayout(w)
        keys = QLabel("<b>Meta+Shift+Space</b> open / close &nbsp;·&nbsp; <b>Meta+Shift+Q</b> quit vimvibe "
                      "&nbsp;·&nbsp; <b>Ctrl+Shift+,</b> these settings", textFormat=Qt.RichText, wordWrap=True)
        f.addRow("Shortcuts:", keys)
        b = QPushButton("Change them in System Settings…")
        b.clicked.connect(lambda: self.run_detached(["systemsettings", "kcm_keys"]))
        f.addRow("", b)
        f.addRow("", QLabel("<small>KDE keeps them under Shortcuts → <i>vimvibe</i>. Other desktops: bind any key to "
                            "<code>gdbus call --session --dest org.vimvibe.Daemon --object-path /org/vimvibe/Daemon "
                            "--method org.vimvibe.Daemon.Trigger</code></small>", textFormat=Qt.RichText, wordWrap=True))
        self.login = QCheckBox("Start vimvibe when I log in")
        if PROFILE:  # only the installed vimvibe starts at login
            self.login.setEnabled(False)
            self.login.setToolTip("Only the installed vimvibe starts at login")
        f.addRow("Launch at login:", self.login)
        f.addRow("Settings file:", QLabel(f"<small><code>{CONFIG}</code></small>", textFormat=Qt.RichText))
        self.windows = QCheckBox("Also offer my other open windows as results (window switching)")
        f.addRow("Search:", self.windows)
        self.apps_search = QCheckBox("Also offer installed applications (type a name, Enter launches it)")
        f.addRow("", self.apps_search)
        self.panel_labels = QCheckBox("Label the taskbar and other panels too (only while they are visible)")
        f.addRow("", self.panel_labels)
        return w

    def appearance_tab(self):
        """Theme presets, label (flag) colours, font and sizes, the search panel's look, and a live preview."""
        outer = QWidget(); ov = QVBoxLayout(outer)
        self.preview = Preview(self)
        ov.addWidget(self.preview)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); v = QVBoxLayout(inner)
        ch = self.changed

        theme = QGroupBox("Theme"); tf = QFormLayout(theme)
        self.preset = QComboBox(); self.preset.addItem("Choose a preset…")
        for name in PRESETS:
            self.preset.addItem(name)
        self.preset.activated.connect(self.apply_preset)
        tf.addRow("Preset:", self.preset)
        v.addWidget(theme)

        labels = QGroupBox("Labels (flags)"); lf = QFormLayout(labels)
        self.accent = ColorField(False, ch); lf.addRow("Background:", self.accent)
        self.label_text = ColorField(True, ch); lf.addRow("Text:", self.label_text)
        self.label_border = ColorField(True, ch); lf.addRow("Outline:", self.label_border)
        self.selected = ColorField(True, ch); lf.addRow("Selected highlight:", self.selected)
        frow = QHBoxLayout()
        self.font_default = QCheckBox("Desktop font")
        self.font = QFontComboBox()
        self.font_default.toggled.connect(lambda on: (self.font.setEnabled(not on), ch()))
        self.font.currentFontChanged.connect(lambda _: ch())
        frow.addWidget(self.font_default); frow.addWidget(self.font, 1)
        lf.addRow("Font:", frow)
        self.label_font_size = QSpinBox(); self.label_font_size.setRange(0, 40); self.label_font_size.setSpecialValueText("Automatic")
        self.label_font_size.setSuffix(" pt"); self.label_font_size.valueChanged.connect(lambda _: ch())
        lf.addRow("Text size:", self.label_font_size)
        self.scale = QDoubleSpinBox(); self.scale.setRange(0.6, 2.0); self.scale.setSingleStep(0.1); self.scale.setSuffix("×")
        self.scale.valueChanged.connect(lambda _: ch())
        lf.addRow("Overall label size:", self.scale)
        self.radius = QSpinBox(); self.radius.setRange(0, 12); self.radius.setSuffix(" px"); self.radius.valueChanged.connect(lambda _: ch())
        lf.addRow("Corner radius:", self.radius)
        self.uppercase = QCheckBox("Show labels in capitals (SA instead of sa)"); self.uppercase.toggled.connect(lambda _: ch())
        lf.addRow("", self.uppercase)
        v.addWidget(labels)

        panel = QGroupBox("Search panel"); pf = QFormLayout(panel)
        self.panel_theme = QComboBox(); self.panel_theme.addItem("Dark", "dark"); self.panel_theme.addItem("Light", "light")
        self.panel_theme.currentIndexChanged.connect(lambda _: ch())
        pf.addRow("Style:", self.panel_theme)
        self.opacity = QSlider(Qt.Horizontal); self.opacity.setRange(50, 100); self.opacity.valueChanged.connect(lambda _: ch())
        pf.addRow("Opacity:", self.opacity)
        self.panel_width = QSpinBox(); self.panel_width.setRange(420, 1200); self.panel_width.setSingleStep(20); self.panel_width.setSuffix(" px")
        self.panel_width.valueChanged.connect(lambda _: ch())
        pf.addRow("Width:", self.panel_width)
        self.rows = QSpinBox(); self.rows.setRange(3, 15); self.rows.valueChanged.connect(lambda _: ch())
        pf.addRow("Result rows:", self.rows)
        self.panel_font_size = QSpinBox(); self.panel_font_size.setRange(0, 40); self.panel_font_size.setSpecialValueText("Automatic")
        self.panel_font_size.setSuffix(" pt"); self.panel_font_size.valueChanged.connect(lambda _: ch())
        pf.addRow("Text size:", self.panel_font_size)
        self.panel = QComboBox()
        for label, val in [("Automatic (where it hides the fewest labels)", "auto"), ("Top of the window", "top"),
                           ("Centre of the window", "center"), ("Bottom of the window", "bottom")]:
            self.panel.addItem(label, val)
        pf.addRow("Position:", self.panel)
        self.hint_line = QCheckBox("Show the key hints under the search field")
        pf.addRow("", self.hint_line)
        self.hide_panel = QCheckBox("Hide the panel until I type (labels only at first, like Shortcat's option)")
        pf.addRow("", self.hide_panel)
        self.dim = QSlider(Qt.Horizontal); self.dim.setRange(0, 60)
        pf.addRow("Darken the screen behind:", self.dim)
        v.addWidget(panel)
        v.addStretch()
        scroll.setWidget(inner)
        ov.addWidget(scroll, 1)
        return outer

    def labels_tab(self):
        """When labels appear, Vimium-style auto-click, continuous mode, and scrolling keys."""
        w = QWidget(); f = QFormLayout(w)
        self.delay = QComboBox()
        for label, v in DELAYS:
            self.delay.addItem(label, v)
        f.addRow("Show labels:", self.delay)
        self.auto = QCheckBox("Click as soon as a label is fully typed (Vimium-style, no Enter)")
        f.addRow("Labels:", self.auto)
        self.continuous = QCheckBox("Continuous mode: come back after each click, ready for the next one")
        f.addRow("Continuous mode:", self.continuous)
        self.cdelay = QSpinBox(); self.cdelay.setRange(100, 5000); self.cdelay.setSingleStep(100); self.cdelay.setSuffix(" ms")
        f.addRow("Wait before re-reading:", self.cdelay)
        f.addRow("", QLabel("<small>Continuous mode stops when you press Esc, after typing into a text field, or when "
                            "a menu or another window takes over. Shortcat recommends “Show labels: After input” with "
                            "it.</small>", textFormat=Qt.RichText, wordWrap=True))
        box = QGroupBox("Scrolling and arrow keys (hold Space while the overlay is open)"); sf = QFormLayout(box)
        self.hjkl_action = QComboBox()
        self.hjkl_action.addItem("Scroll the page (Space + Ctrl + key sends arrow keys)", "scroll")
        self.hjkl_action.addItem("Send arrow keys (Space + Ctrl + key scrolls)", "arrows")
        sf.addRow("Space + H J K L:", self.hjkl_action)
        self.scroll_keys = QComboBox()
        self.scroll_keys.addItem("H J K L (Vim: left, down, up, right)", "hjkl")
        self.scroll_keys.addItem("I J K L (arrow layout: up, left, down, right)", "ijkl")
        sf.addRow("Direction keys:", self.scroll_keys)
        self.scroll_step = QSpinBox(); self.scroll_step.setRange(1, 40); self.scroll_step.setSuffix(" wheel clicks per press")
        sf.addRow("Scroll distance:", self.scroll_step)
        self.scroll_fast = QSpinBox(); self.scroll_fast.setRange(1, 20); self.scroll_fast.setPrefix("×")
        sf.addRow("With Shift held:", self.scroll_fast)
        self.scroll_smooth = QCheckBox("Smooth animation (ease the scroll instead of jumping)")
        sf.addRow("Animation:", self.scroll_smooth)
        self.scroll_smooth_ms = QSpinBox(); self.scroll_smooth_ms.setRange(20, 1000); self.scroll_smooth_ms.setSingleStep(20)
        self.scroll_smooth_ms.setSuffix(" ms per press")
        self.scroll_smooth.toggled.connect(self.scroll_smooth_ms.setEnabled)
        sf.addRow("Animation length:", self.scroll_smooth_ms)
        self.scroll_natural = QCheckBox("Natural direction (like a touchpad: the content follows your finger)")
        sf.addRow("Direction:", self.scroll_natural)
        self.scroll_invert_h = QCheckBox("Swap left and right (H scrolls right, L scrolls left)")
        sf.addRow("", self.scroll_invert_h)
        sf.addRow("", QLabel("<small><b>Space + D / U</b> always scroll down / up. <b>Space + H J K L</b> scroll (or send "
                             "arrow keys, per the first option); hold <b>Ctrl</b> to get the other one. Release Space "
                             "for fresh labels; Esc stops. Scrolling works in every app and needs the pointer "
                             "permission; arrow keys need the keyboard permission and work in KDE/Qt and GTK 3 apps "
                             "(Accessibility &amp; setup tab).</small>", textFormat=Qt.RichText, wordWrap=True))
        f.addRow(box)
        return w

    def apps_tab(self):
        """The list of apps vimvibe must never touch."""
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("vimvibe never reads or clicks anything in these apps (good for password managers, banking, "
                           "terminals). Use the app's name, window class or process name, e.g. <code>keepassxc</code>, "
                           "<code>org.kde.konsole</code>, <code>1password</code>.", textFormat=Qt.RichText, wordWrap=True))
        self.apps = QListWidget()
        v.addWidget(self.apps)
        row = QHBoxLayout()
        self.app_in = QLineEdit(); self.app_in.setPlaceholderText("app name or window class")
        self.app_in.returnPressed.connect(self.add_app)
        add = QPushButton("Add"); add.clicked.connect(self.add_app)
        rm = QPushButton("Remove selected"); rm.clicked.connect(lambda: [self.apps.takeItem(self.apps.row(i)) for i in self.apps.selectedItems()])
        row.addWidget(self.app_in); row.addWidget(add); row.addWidget(rm)
        v.addLayout(row)
        return w

    def system_tab(self):
        """Buttons for the setup check, accessibility and pointer permission, with their output."""
        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox("Accessibility (how vimvibe sees elements)"); bl = QVBoxLayout(box)
        bl.addWidget(QLabel("Apps only expose their elements while desktop accessibility is on, and only apps started "
                            "after turning it on. Chrome/Electron apps also need <code>--force-renderer-accessibility</code>.",
                            textFormat=Qt.RichText, wordWrap=True))
        r = QHBoxLayout()
        b1 = QPushButton("Run setup check"); b1.clicked.connect(lambda: self.show_cmd([core_binary(), "doctor"]))
        b2 = QPushButton("Turn accessibility on"); b2.clicked.connect(lambda: self.show_cmd([core_binary(), "doctor", "--fix"]))
        b3 = QPushButton("Keep it on after login"); b3.clicked.connect(lambda: self.show_cmd([core_binary(), "doctor", "--fix-env"]))
        r.addWidget(b1); r.addWidget(b2); r.addWidget(b3)
        bl.addLayout(r)
        v.addWidget(box)
        box2 = QGroupBox("Pointer and keyboard (scrolling, arrow keys, right click, hover)"); pl = QVBoxLayout(box2)
        pl.addWidget(QLabel("Uses the desktop's Remote Control permission. Your desktop asks once: allow the pointer "
                            "and the keyboard (the keyboard is only used for Space + H/J/K/L arrow keys). Revoke it any "
                            "time in System Settings → Security & Privacy → Remote Control.", wordWrap=True))
        b4 = QPushButton("Allow pointer and keyboard control…"); b4.clicked.connect(lambda: self.show_cmd([core_binary(), "pointer-setup"]))
        pl.addWidget(b4)
        v.addWidget(box2)
        self.output = QPlainTextEdit(readOnly=True); self.output.setPlaceholderText("Command output appears here")
        v.addWidget(self.output)
        return w

    # --- helpers --------------------------------------------------------------------
    def apply_preset(self, index):
        """Fill the colour controls (and panel style) from a theme preset."""
        if index <= 0:
            return
        name = self.preset.itemText(index)
        pr = PRESETS[name]
        self.loading = True
        self.accent.set(pr["accent"]); self.label_text.set(pr["label_text"])
        self.label_border.set(pr["label_border"]); self.selected.set(pr["selected"])
        self.panel_theme.setCurrentIndex(max(0, self.panel_theme.findData(pr["panel_theme"])))
        self.loading = False
        self.preset_name = name
        self.changed()

    def add_app(self):
        """Add the typed app name to the exclusion list (no duplicates)."""
        t = self.app_in.text().strip()
        if t and not self.apps.findItems(t, Qt.MatchFixedString):
            self.apps.addItem(t)
        self.app_in.clear()

    def run_detached(self, cmd):
        """Start a program without waiting for it."""
        try:
            subprocess.Popen(cmd)
        except OSError as e:
            QMessageBox.warning(self, "vimvibe", f"Could not run {cmd[0]}: {e}")

    def show_cmd(self, cmd):
        """Run a vimvibe-core command and show its output in the tab."""
        self.output.setPlainText("$ " + " ".join(cmd) + "\n")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.output.appendPlainText(r.stdout + r.stderr)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.output.appendPlainText(str(e))

    # --- load / collect / save --------------------------------------------------------
    def load(self, cfg):
        """Fill every control from a settings dict."""
        self.loading = True
        d = self.defaults
        ui = {**d["ui"], **cfg.get("ui", {})}
        hints, beh = {**d["hints"], **cfg.get("hints", {})}, {**d["behavior"], **cfg.get("behavior", {})}
        scroll, search = {**d["scroll"], **cfg.get("scroll", {})}, {**d["search"], **cfg.get("search", {})}
        self.preset_name = ui.get("theme", "")
        self.accent.set(ui["accent"]); self.label_text.set(ui["label_text"])
        self.label_border.set(ui["label_border"]); self.selected.set(ui["selected"])
        self.font_default.setChecked(not ui["font"])
        if ui["font"]:
            self.font.setCurrentFont(ui["font"])
        self.font.setEnabled(bool(ui["font"]))
        self.label_font_size.setValue(int(ui["label_font_size"]))
        self.scale.setValue(float(ui["label_scale"]))
        self.radius.setValue(int(ui["label_radius"]))
        self.uppercase.setChecked(bool(ui["uppercase"]))
        self.panel_theme.setCurrentIndex(max(0, self.panel_theme.findData(ui["panel_theme"])))
        self.opacity.setValue(int(round(float(ui["panel_opacity"]) * 100)))
        self.panel_width.setValue(int(ui["panel_width"]))
        self.rows.setValue(int(ui["rows"]))
        self.panel_font_size.setValue(int(ui["panel_font_size"]))
        self.panel.setCurrentIndex(max(0, self.panel.findData(ui["panel"])))
        self.hint_line.setChecked(bool(ui["hint_line"]))
        self.hide_panel.setChecked(bool(ui["hide_panel_until_typing"]))
        self.dim.setValue(int(ui["dim"]))
        delay = -1 if hints.get("after_input") else int(hints.get("delay_ms", 0))
        i = self.delay.findData(delay)
        if i < 0:
            self.delay.addItem(f"After {delay} ms", delay); i = self.delay.count() - 1
        self.delay.setCurrentIndex(i)
        self.auto.setChecked(bool(hints.get("auto_activate", False)))
        self.continuous.setChecked(bool(beh.get("continuous", False)))
        self.cdelay.setValue(int(beh.get("continuous_delay_ms", 500)))
        self.scroll_keys.setCurrentIndex(max(0, self.scroll_keys.findData(scroll.get("keys", "hjkl"))))
        self.hjkl_action.setCurrentIndex(max(0, self.hjkl_action.findData(scroll.get("hjkl", "scroll"))))
        self.scroll_step.setValue(int(scroll.get("step", 5)))
        self.scroll_fast.setValue(int(scroll.get("fast", 4)))
        self.scroll_smooth.setChecked(bool(scroll.get("smooth", True)))
        self.scroll_smooth_ms.setValue(int(scroll.get("smooth_ms", 140)))
        self.scroll_smooth_ms.setEnabled(self.scroll_smooth.isChecked())
        self.scroll_natural.setChecked(bool(scroll.get("natural", False)))
        self.scroll_invert_h.setChecked(bool(scroll.get("invert_horizontal", False)))
        self.windows.setChecked(bool(search["windows"]))
        self.apps_search.setChecked(bool(search["apps"]))
        self.panel_labels.setChecked(bool(search["panel"]))
        self.apps.clear()
        self.apps.addItems([str(a) for a in cfg.get("apps", {}).get("exclude", [])])
        self.login.setChecked(os.path.exists(AUTOSTART))
        self.loading = False
        self.changed()

    def collect(self):
        """The settings as currently shown in the controls (the stored file merged with the controls)."""
        cfg = json.loads(json.dumps(self.read_config()))
        delay = self.delay.currentData()
        cfg["ui"].update(
            theme=self.preset_name, accent=self.accent.value() or "#3b82f6", label_text=self.label_text.value(),
            label_border=self.label_border.value(), selected=self.selected.value(),
            font="" if self.font_default.isChecked() else self.font.currentFont().family(),
            label_font_size=self.label_font_size.value(), label_scale=round(self.scale.value(), 2),
            label_radius=self.radius.value(), uppercase=self.uppercase.isChecked(),
            panel_theme=self.panel_theme.currentData(), panel_opacity=round(self.opacity.value() / 100, 2),
            panel_width=self.panel_width.value(), rows=self.rows.value(), panel_font_size=self.panel_font_size.value(),
            panel=self.panel.currentData(), hint_line=self.hint_line.isChecked(),
            hide_panel_until_typing=self.hide_panel.isChecked(), dim=self.dim.value())
        cfg["hints"].update(delay_ms=max(0, delay), after_input=delay < 0, auto_activate=self.auto.isChecked())
        cfg["behavior"].update(continuous=self.continuous.isChecked(), continuous_delay_ms=self.cdelay.value())
        cfg["scroll"].update(keys=self.scroll_keys.currentData(), hjkl=self.hjkl_action.currentData(), step=self.scroll_step.value(),
                             fast=self.scroll_fast.value(), smooth=self.scroll_smooth.isChecked(), smooth_ms=self.scroll_smooth_ms.value(),
                             natural=self.scroll_natural.isChecked(), invert_horizontal=self.scroll_invert_h.isChecked())
        cfg["search"].update(windows=self.windows.isChecked(), apps=self.apps_search.isChecked(), panel=self.panel_labels.isChecked())
        cfg["apps"]["exclude"] = [self.apps.item(i).text() for i in range(self.apps.count())]
        return cfg

    def save(self):
        """Write the controls to config.toml (keeping keys this window doesn't know) and update autostart."""
        for field, what in ((self.accent, "Label background"), (self.label_text, "Label text"),
                            (self.label_border, "Label outline"), (self.selected, "Selected highlight")):
            if not field.valid():
                QMessageBox.warning(self, "vimvibe", f"{what}: “{field.value()}” is not a colour."); return
        self.write_config(self.collect())
        if not PROFILE:
            self.set_autostart(self.login.isChecked())
        self.close()

    def set_autostart(self, on):
        """Create or remove the XDG autostart entry that runs `vimvibe start` at login."""
        if not on:
            if os.path.exists(AUTOSTART):
                os.remove(AUTOSTART)
            return
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=vimvibe\nComment=Click anything by typing its name\n"
                    f"Exec={launcher()} start\nIcon=input-keyboard\nX-KDE-autostart-phase=2\nNoDisplay=true\n")
