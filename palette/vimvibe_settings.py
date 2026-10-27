"""vimvibe Settings window. Opens with Ctrl+Shift+, from anywhere (Ctrl+, while the overlay is open), like Shortcat's
Preferences, or with `vimvibe settings` / `vimvibe_palette.py --settings`.

Edits ~/.config/vimvibe/config.toml. The overlay and the daemon re-read that file every time the overlay opens, so
changes apply on the next use without restarting anything. Covers Shortcat's preferences that make sense on Linux
(shortcut, launch at login, label delay, continuous mode, hide the query pane, HJKL/IJKL scroll keys) plus vimvibe's
own: label/flag theme (colours, font, sizes), panel look, excluded apps, accessibility and pointer setup.
"""
import json, os, shutil, subprocess

from PySide6.QtCore import QEvent, QProcess, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QGridLayout, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

import vimvibe_keys as keys
from vimvibe_style import AUTOSTART, CONFIG, PRESETS, PROFILE, Theme, export_settings, icon_path, import_settings

DELAYS = [("Immediately", 0), ("After 200 ms", 200), ("After 500 ms", 500), ("After 1 second", 1000),
          ("After 2 seconds (Shortcat's default)", 2000), ("After 5 seconds", 5000), ("After input", -1)]


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


class KeyCapture(QDialog):
    """"Press the new key": a small modal dialog that records the next key combination (Esc cancels)."""

    def __init__(self, parent, title):
        """`title` names the action being rebound; the pressed combination ends up in `self.result_text`."""
        super().__init__(parent)
        self.setWindowTitle("New key")
        self.result_text = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{title}</b><br>Press the key combination you want, e.g. Ctrl+Space.<br>"
                           "<small>Esc cancels (the Reset button brings Esc back for “Close”).</small>", textFormat=Qt.RichText))
        self.shown = QLabel("…"); self.shown.setAlignment(Qt.AlignCenter)
        f = self.shown.font(); f.setPointSizeF(f.pointSizeF() * 1.6); f.setBold(True); self.shown.setFont(f)
        v.addWidget(self.shown)
        b = QDialogButtonBox(QDialogButtonBox.Cancel); b.rejected.connect(self.reject)
        v.addWidget(b)

    def event(self, ev):
        """Take every key press (Tab and the like would otherwise move focus); modifiers alone only show."""
        if ev.type() == QEvent.ShortcutOverride:
            ev.accept(); return True
        if ev.type() == QEvent.KeyPress:
            k, mods = ev.key(), ev.modifiers()
            if keys.iv(k) in keys.MOD_KEYS:
                self.shown.setText(keys.format_mods(keys.iv(mods) & keys.MOD_MASK) + "+…")
                return True
            if k == Qt.Key_Escape and not keys.iv(mods) & keys.MOD_MASK:
                self.reject(); return True
            key, m = keys.canon(k, mods)
            self.result_text = keys.format_key(key, m)
            self.accept(); return True
        return super().event(ev)


class SettingsWindow(QWidget):
    def __init__(self, read_config, write_config, defaults):
        """Build the tabs and load the current settings into them."""
        super().__init__()
        self.read_config, self.write_config, self.defaults = read_config, write_config, defaults
        self.loading = False
        self.proc = None  # the command running in the Accessibility & setup tab
        self.setWindowTitle(f"vimvibe Settings ({PROFILE} profile)" if PROFILE else "vimvibe Settings")
        if icon_path():
            self.setWindowIcon(QIcon(icon_path()))
        self.resize(760, 680)
        tabs = QTabWidget()
        tabs.addTab(self.general_tab(), "General")
        tabs.addTab(self.appearance_tab(), "Appearance")
        tabs.addTab(self.scrolled(self.labels_tab()), "Labels && behaviour")
        tabs.addTab(self.scrolled(self.mouse_tab()), "Mouse")
        tabs.addTab(self.keys_tab(), "Keys")
        tabs.addTab(self.apps_tab(), "Excluded apps")
        tabs.addTab(self.system_tab(), "Accessibility && setup")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda: self.load(self.defaults))
        transfer = QHBoxLayout()
        exp = QPushButton("Export settings…"); exp.clicked.connect(self.export_dialog)
        exp.setToolTip("Save every setting (colours, keys, mouse, scrolling, excluded apps, ...) to a JSON file")
        imp = QPushButton("Import settings…"); imp.clicked.connect(self.import_dialog)
        imp.setToolTip("Replace the current settings with ones from an exported JSON file")
        transfer.addWidget(exp); transfer.addWidget(imp); transfer.addStretch()
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addLayout(transfer)
        lay.addWidget(buttons)
        self.load(self.read_config())

    def scrolled(self, page):
        """Wrap a long tab page in a scroll area, so the window keeps its size on small screens."""
        area = QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(page)
        return area

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
        self.start_hidden = QCheckBox("Open with the panel hidden (the “hide / show panel” key brings it back — see Keys)")
        pf.addRow("", self.start_hidden)
        self.remember_panel = QCheckBox("Remember a hidden panel: it stays hidden next time until Space (or the key above) brings it back")
        pf.addRow("", self.remember_panel)
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
        self.double_esc = QCheckBox("Press Esc twice to close vimvibe (one Esc only steps back from the mouse modes)")
        f.addRow("Closing:", self.double_esc)
        self.double_tap = QSpinBox(); self.double_tap.setRange(0, 600); self.double_tap.setSingleStep(50); self.double_tap.setSuffix(" ms")
        self.double_tap.setSpecialValueText("off (Enter clicks at once)")
        f.addRow("Tap Enter twice within:", self.double_tap)
        self.insert_after = QCheckBox("After a text field is clicked, let me type in it and come back with Esc")
        f.addRow("Text fields:", self.insert_after)
        self.keep_focus = QCheckBox("Always keep popups open: never take the keyboard from the app (like Meta+Shift+Alt+Space)")
        self.keep_focus.setToolTip("Chrome closes extension popups, the address bar dropdown and its bubbles when it loses the keyboard.\n"
                                   "With this on, vimvibe takes its keys through KWin instead and reads the popup's text with OCR.\n"
                                   "Not available then: holding Space to scroll, text mode, the mouse modes.")
        f.addRow("Popups:", self.keep_focus)
        self.click_with = QComboBox()
        self.click_with.addItem("A real click, like a mouse (needs the pointer permission)", "pointer")
        self.click_with.addItem("The app's own action first (no pointer move)", "semantic")
        f.addRow("Enter clicks with:", self.click_with)
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
        self.scroll_step = QDoubleSpinBox(); self.scroll_step.setRange(0.1, 20.0); self.scroll_step.setSingleStep(0.1)
        self.scroll_step.setDecimals(1); self.scroll_step.setSuffix(" mouse-wheel notches per press")
        sf.addRow("Scroll distance:", self.scroll_step)
        self.scroll_fast = QSpinBox(); self.scroll_fast.setRange(1, 20); self.scroll_fast.setPrefix("×")
        sf.addRow("With Shift held:", self.scroll_fast)
        self.scroll_smooth = QCheckBox("Smooth scrolling (glide like a smooth-scrolling mouse wheel; held keys flow into one motion)")
        sf.addRow("Animation:", self.scroll_smooth)
        self.scroll_smooth_ms = QSpinBox(); self.scroll_smooth_ms.setRange(20, 1000); self.scroll_smooth_ms.setSingleStep(20)
        self.scroll_smooth_ms.setSuffix(" ms to settle")
        self.scroll_smooth.toggled.connect(self.scroll_smooth_ms.setEnabled)
        sf.addRow("Glide length:", self.scroll_smooth_ms)
        self.edge_keys = QCheckBox("Space + g g jumps to the top, Space + Shift+G to the bottom (like Vimium)")
        sf.addRow("Top / bottom:", self.edge_keys)
        self.edge_notches = QSpinBox(); self.edge_notches.setRange(10, 5000); self.edge_notches.setSingleStep(50)
        self.edge_notches.setSuffix(" notches")
        sf.addRow("Jump distance:", self.edge_notches)
        self.edge_ms = QSpinBox(); self.edge_ms.setRange(150, 3000); self.edge_ms.setSingleStep(50); self.edge_ms.setSuffix(" ms")
        sf.addRow("Jump time:", self.edge_ms)
        self.edge_keys.toggled.connect(self.edge_notches.setEnabled)
        self.edge_keys.toggled.connect(self.edge_ms.setEnabled)
        self.scroll_natural = QCheckBox("Natural direction (like a touchpad: the content follows your finger)")
        sf.addRow("Direction:", self.scroll_natural)
        self.scroll_invert_h = QCheckBox("Swap left and right (H scrolls right, L scrolls left)")
        sf.addRow("", self.scroll_invert_h)
        sf.addRow("", QLabel("<small><b>Space + D / U</b> always scroll down / up; <b>Space + g g</b> and <b>Space + Shift+G</b> jump to the top and bottom. <b>Space + H J K L</b> scroll (or send "
                             "arrow keys, per the first option); hold <b>Ctrl</b> to get the other one. Release Space "
                             "for fresh labels; Esc stops. Scrolling works in every app and needs the pointer "
                             "permission; arrow keys need the keyboard permission and work in KDE/Qt and GTK 3 apps "
                             "(Accessibility &amp; setup tab).</small>", textFormat=Qt.RichText, wordWrap=True))
        f.addRow(box)
        return w

    def mouse_tab(self):
        """The keyboard mouse: master switch, the zooming grid and H J K L pointer movement."""
        w = QWidget(); f = QFormLayout(w)
        self.mouse_on = QCheckBox("Keyboard mouse: move and click the pointer without touching the mouse")
        f.addRow(self.mouse_on)
        box = QGroupBox("Options"); bf = QFormLayout(box)
        self.mouse_widgets = [box]
        self.mouse_open_in = QComboBox()
        self.mouse_open_in.addItem("The search (the grid is one key away)", "search")
        self.mouse_open_in.addItem("The mouse grid", "grid")
        self.mouse_open_in.addItem("Text mode (the screen as a Vim buffer)", "text")
        bf.addRow("vimvibe opens in:", self.mouse_open_in)
        self.mouse_fallback = QCheckBox("Open in the mouse grid when an app has nothing to label (Spotify, games, ...)")
        bf.addRow("", self.mouse_fallback)
        self.mouse_ocr = QCheckBox("Label the text on screen with OCR first (needs tesseract)")
        bf.addRow("", self.mouse_ocr)
        self.ocr_lang = QLineEdit(); self.ocr_lang.setPlaceholderText("eng")
        self.ocr_lang.setToolTip("Tesseract language codes joined with +, e.g. eng+deu (each needs its language data installed)")
        bf.addRow("OCR language:", self.ocr_lang)
        self.ocr_conf = QSpinBox(); self.ocr_conf.setRange(0, 100); self.ocr_conf.setSuffix(" % minimum confidence")
        bf.addRow("OCR accuracy:", self.ocr_conf)
        self.ocr_timeout = QSpinBox(); self.ocr_timeout.setRange(500, 30000); self.ocr_timeout.setSingleStep(500); self.ocr_timeout.setSuffix(" ms")
        bf.addRow("Give up OCR after:", self.ocr_timeout)
        self.screen_width = QSpinBox(); self.screen_width.setRange(0, 16384); self.screen_width.setSuffix(" px")
        self.screen_width.setSpecialValueText("unscaled (1:1)")
        self.screen_width.setToolTip("Only for scaled displays: the screen's logical width, so OCR labels line up")
        bf.addRow("Logical screen width:", self.screen_width)
        self.mouse_ocr.toggled.connect(lambda on: [x.setEnabled(on) for x in (self.ocr_lang, self.ocr_conf, self.ocr_timeout, self.screen_width)])
        self.mouse_stay = QCheckBox("Stay in the mouse mode after a click (leave with Esc Esc or the vimvibe shortcut)")
        bf.addRow("", self.mouse_stay)
        self.mouse_remember = QCheckBox("Instead, open in the mode I used last (search, grid or pointer movement)")
        bf.addRow("", self.mouse_remember)
        self.clip_on = QCheckBox("Clipboard: copy / paste keys and the history picker (Ctrl+Shift+H)")
        bf.addRow("", self.clip_on)
        self.edit_step = QSpinBox(); self.edit_step.setRange(1, 20)
        bf.addRow("Edit mode (Ctrl+E): J / K move", self.edit_step)
        bf.addRow("", QLabel("lines per press while not selecting (H / L and selecting move one step; type a number first, like 5 J, to repeat)"))
        self.mouse_scope = QComboBox()
        self.mouse_scope.addItem("The window vimvibe was opened over", "window")
        self.mouse_scope.addItem("The whole screen", "screen")
        bf.addRow("The grid covers:", self.mouse_scope)
        self.mouse_cols = QSpinBox(); self.mouse_cols.setRange(2, 26); self.mouse_cols.setSuffix(" columns")
        self.mouse_rows = QSpinBox(); self.mouse_rows.setRange(2, 26); self.mouse_rows.setSuffix(" rows")
        size = QHBoxLayout(); size.addWidget(self.mouse_cols); size.addWidget(QLabel("×")); size.addWidget(self.mouse_rows); size.addStretch()
        bf.addRow("Grid size:", size)
        self.mouse_depth = QSpinBox(); self.mouse_depth.setRange(1, 10); self.mouse_depth.setSuffix(" times")
        bf.addRow("A cell can be divided:", self.mouse_depth)
        self.mouse_alphabet = QLineEdit(); self.mouse_alphabet.setPlaceholderText("abcdefghijklmnopqrstuvwxyz")
        bf.addRow("Cell letters:", self.mouse_alphabet)
        self.mouse_keys = QComboBox()
        self.mouse_keys.addItem("H J K L (Vim: left, down, up, right)", "hjkl")
        self.mouse_keys.addItem("I J K L (arrow layout: up, left, down, right)", "ijkl")
        bf.addRow("Movement keys:", self.mouse_keys)
        self.mouse_speed = QSpinBox(); self.mouse_speed.setRange(50, 6000); self.mouse_speed.setSingleStep(50); self.mouse_speed.setSuffix(" px / second")
        bf.addRow("Pointer speed:", self.mouse_speed)
        self.mouse_fast = QSpinBox(); self.mouse_fast.setRange(1, 20); self.mouse_fast.setPrefix("×")
        bf.addRow("With Shift held:", self.mouse_fast)
        self.mouse_accel = QCheckBox("Speed up while a key is held")
        bf.addRow("Acceleration:", self.mouse_accel)
        bf.addRow("", QLabel("<small>Open vimvibe, then press <b>Ctrl+G</b> for the grid: type a cell's two letters (row, then "
                             "column) to zoom into it; the cell is divided again, as deep as you set. <b>Enter</b> clicks the "
                             "middle of what is left, <b>Space</b> only moves the pointer there, <b>Backspace</b> zooms out. "
                             "<b>Ctrl+M</b> moves the pointer with the direction keys (Shift faster, Alt precise). "
                             "These keys can be changed in the Keys tab. Needs the pointer permission "
                             "(Accessibility &amp; setup tab); not available over Plasma popups.</small>", textFormat=Qt.RichText, wordWrap=True))
        f.addRow(box)
        self.mouse_on.toggled.connect(box.setEnabled)
        tbox = QGroupBox("Text mode (Ctrl+T): the words on screen as a Vim buffer, to copy from and paste with"); tf = QFormLayout(tbox)
        self.text_dim = QSpinBox(); self.text_dim.setRange(0, 60); self.text_dim.setSuffix(" %")
        tf.addRow("Darken the screen behind it:", self.text_dim)
        self.text_join = QComboBox()
        self.text_join.addItem("Keep line breaks", "newline")
        self.text_join.addItem("Join lines with a space", "space")
        tf.addRow("Copied lines:", self.text_join)
        self.text_labels = QLineEdit(); self.text_labels.setPlaceholderText("asdfghjklqwertyuiopzxcvbnm")
        tf.addRow("Jump label letters (f):", self.text_labels)
        self.text_line = QDoubleSpinBox(); self.text_line.setRange(0.2, 10.0); self.text_line.setSingleStep(0.5); self.text_line.setSuffix(" wheel notches")
        tf.addRow("Space+J / K, Space+E / Y and j / k past the edge scroll:", self.text_line)
        self.text_page = QDoubleSpinBox(); self.text_page.setRange(1.0, 40.0); self.text_page.setSingleStep(1.0); self.text_page.setSuffix(" wheel notches")
        tf.addRow("Space+F / B scroll (Space+D / U half):", self.text_page)
        tf.addRow("", QLabel("<small>Needs OCR (above). Keys: <b>h j k l w b 0 $ gg G</b> move (counts work: 5w), "
                             "<b>v</b> / <b>V</b> select words / lines, <b>y</b> copy (<b>yy</b> line, <b>yw</b> word), "
                             "<b>p</b> paste into a text field, <b>P</b> paste where the keyboard is, <b>f</b> jump by label, "
                             "<b>/</b> search (<b>n</b> / <b>N</b>), <b>Space + J K E Y D U F B</b> or the wheel scroll the app and read it again, <b>Esc</b> back. <b>Ctrl+Tab</b> goes through all modes.</small>",
                             textFormat=Qt.RichText, wordWrap=True))
        f.addRow(tbox)
        return w

    def keys_tab(self):
        """Every key the overlay reacts to, with Change / Add / Reset per action."""
        self.key_values = {}   # action -> list of binding strings (what is shown and saved)
        self.key_widgets = {}  # action -> (text label or combo)
        w = QWidget(); v = QVBoxLayout(w)
        head = QLabel("Keys used while the overlay is open. Click <b>Change</b> and press the combination you want; "
                      "<b>Add</b> gives an action a second key. The defaults are what vimvibe ships with. The global "
                      "shortcuts that open vimvibe from anywhere (<b>Meta+Shift+Space</b>, quit, settings) are KDE "
                      "shortcuts: <a href='kcm'>change them in System Settings</a>.", textFormat=Qt.RichText, wordWrap=True)
        head.linkActivated.connect(lambda _: self.run_detached(["systemsettings", "kcm_keys"]))
        v.addWidget(head)
        inner = QWidget(); grid = QGridLayout(inner)
        for row, (action, title, default, kind) in enumerate(keys.ACTIONS):
            grid.addWidget(QLabel(title), row, 0)
            if kind == "key":
                shown = QLabel(); shown.setTextFormat(Qt.RichText); shown.setMinimumWidth(190)
                self.key_widgets[action] = shown
                change, add, reset = QPushButton("Change…"), QPushButton("Add…"), QPushButton("Reset")
                change.clicked.connect(lambda _=False, a=action: self.capture_key(a, replace=True))
                add.clicked.connect(lambda _=False, a=action: self.capture_key(a, replace=False))
                reset.clicked.connect(lambda _=False, a=action: self.set_binding(a, list(keys.DEFAULTS[a])))
                grid.addWidget(shown, row, 1)
                for col, b in enumerate((change, add, reset)):
                    grid.addWidget(b, row, 2 + col)
            else:
                combo = QComboBox()
                choices = ["Ctrl", "Alt", "Ctrl+Shift", "Ctrl+Alt", "Alt+Shift"] if kind == "mods" else ["", "Ctrl", "Alt", "Shift"]
                for c in choices:
                    combo.addItem(c or "Off", c)
                combo.activated.connect(lambda _=0, a=action, c=combo: self.set_binding(a, [c.currentData()] if c.currentData() else []))
                self.key_widgets[action] = combo
                grid.addWidget(combo, row, 1)
                reset = QPushButton("Reset"); reset.clicked.connect(lambda _=False, a=action: self.set_binding(a, list(keys.DEFAULTS[a])))
                grid.addWidget(reset, row, 4)
        grid.setColumnStretch(1, 1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(inner)
        v.addWidget(scroll, 1)
        self.key_warning = QLabel(); self.key_warning.setWordWrap(True); self.key_warning.setTextFormat(Qt.RichText)
        v.addWidget(self.key_warning)
        v.addWidget(QLabel("<small>Space + H J K L / D / U (scrolling and arrow keys) are set in <i>Labels &amp; behaviour</i>: "
                           "they follow physical key positions, so they work the same on any keyboard layout. Over start-menu "
                           "and other popups vimvibe cannot see Ctrl/Alt combinations, so the popup keys there stay as "
                           "they are.</small>", textFormat=Qt.RichText, wordWrap=True))
        return w

    def set_binding(self, action, values):
        """Store the bindings of one action and refresh its row."""
        self.key_values[action] = values
        self.show_bindings()

    def capture_key(self, action, replace):
        """Ask for a key combination and bind it to `action` (warning about clashes and keys that would stop typing)."""
        dlg = KeyCapture(self, keys.TITLE[action])
        if dlg.exec() != QDialog.Accepted or not dlg.result_text:
            return
        text = dlg.result_text
        key, mods = keys.parse_key(text)
        if keys.is_plain_text_key(key, mods) and QMessageBox.question(
                self, "vimvibe", f"“{text}” is a typing key: while the overlay is open you could no longer type it into the "
                "search field. Use it anyway?") != QMessageBox.Yes:
            return
        for other, vals in self.key_values.items():
            if other != action and keys.KIND[other] == "key" and any(keys.parse_key(v) == (key, mods) for v in vals):
                if QMessageBox.question(self, "vimvibe", f"“{text}” is already used for “{keys.TITLE[other]}”. "
                                        "Take it over (it is removed from there)?") != QMessageBox.Yes:
                    return
                self.key_values[other] = [v for v in vals if keys.parse_key(v) != (key, mods)]
        have = [] if replace else [v for v in self.key_values.get(action, []) if keys.parse_key(v) != (key, mods)]
        self.set_binding(action, have + [text])

    def show_bindings(self):
        """Redraw every row from `key_values`, and list any problems (unreadable or doubly used keys)."""
        for action, widget in self.key_widgets.items():
            vals = self.key_values.get(action, [])
            changed = vals != keys.DEFAULTS[action]
            if isinstance(widget, QComboBox):
                i = widget.findData(vals[0] if vals else "")
                if i < 0:
                    widget.addItem(vals[0], vals[0]); i = widget.count() - 1
                widget.setCurrentIndex(i)
            else:
                text = "  /  ".join(f"<b>{v.replace('&', '&amp;').replace('<', '&lt;')}</b>" for v in vals) or "<i>not bound</i>"
                widget.setText(text + ("  <small>(changed)</small>" if changed else ""))
        notes = []
        km = keys.KeyMap(self.key_values)
        notes += [f"⚠ {p}" for p in km.problems]
        for (k, m), actions in keys.conflicts(self.key_values).items():
            notes.append(f"⚠ {keys.format_key(k, m)} is used for: " + ", ".join(keys.TITLE[a] for a in actions))
        self.key_warning.setText("<br>".join(notes))

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
        b5 = QPushButton("Make Chrome, Chromium, Brave, Edge and VS Code visible…")
        b5.setToolTip("Adds --force-renderer-accessibility to their launchers (copies in ~/.local/share/applications); restart them afterwards")
        b5.clicked.connect(lambda: self.show_cmd([core_binary(), "doctor", "--fix-chrome"]))
        bl.addWidget(b5)
        self.enable_on_start = QCheckBox("Turn desktop accessibility on whenever vimvibe starts")
        bl.addWidget(self.enable_on_start)
        self.offer_restart = QCheckBox("When Chrome, Brave, Edge or an Electron app shows nothing, offer to restart it with accessibility on")
        bl.addWidget(self.offer_restart)
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
        """Run a vimvibe-core command in the background and show its output in the tab as it arrives (the window must
        stay responsive: some commands wait for the desktop, and one shows a consent dialog)."""
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            self.output.appendPlainText("(still running the previous command)")
            return
        self.output.setPlainText("$ " + " ".join(cmd) + "\n")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(lambda: self.output.appendPlainText(bytes(self.proc.readAll()).decode(errors="replace").rstrip("\n")))
        self.proc.errorOccurred.connect(lambda e: self.output.appendPlainText(f"could not run {cmd[0]}: {self.proc.errorString()}") if e == QProcess.FailedToStart else None)
        self.proc.finished.connect(lambda code, _: self.output.appendPlainText(f"(finished, exit code {code})"))
        QTimer.singleShot(120000, lambda p=self.proc: p.kill() if p.state() != QProcess.NotRunning else None)  # a command that never ends is stopped after two minutes
        self.proc.start(cmd[0], cmd[1:])

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
        self.start_hidden.setChecked(bool(ui.get("start_hidden", False)))
        self.remember_panel.setChecked(bool(ui.get("remember_panel", True)))
        self.dim.setValue(int(ui["dim"]))
        self.key_values = {a: keys.effective(cfg.get("keys"), a) for a in keys.DEFAULTS}
        self.show_bindings()
        delay = -1 if hints.get("after_input") else int(hints.get("delay_ms", 0))
        i = self.delay.findData(delay)
        if i < 0:
            self.delay.addItem(f"After {delay} ms", delay); i = self.delay.count() - 1
        self.delay.setCurrentIndex(i)
        self.auto.setChecked(bool(hints.get("auto_activate", False)))
        self.continuous.setChecked(bool(beh.get("continuous", False)))
        self.double_esc.setChecked(bool(beh.get("double_esc_close", True)))
        self.cdelay.setValue(int(beh.get("continuous_delay_ms", 500)))
        self.double_tap.setValue(int(beh.get("double_tap_ms", 250)))
        self.click_with.setCurrentIndex(max(0, self.click_with.findData(beh.get("click_with", "pointer"))))
        self.insert_after.setChecked(bool(beh.get("insert_after_field", True)))
        self.keep_focus.setChecked(bool(beh.get("keep_focus", False)))
        self.scroll_keys.setCurrentIndex(max(0, self.scroll_keys.findData(scroll.get("keys", "hjkl"))))
        self.hjkl_action.setCurrentIndex(max(0, self.hjkl_action.findData(scroll.get("hjkl", "scroll"))))
        self.scroll_step.setValue(float(scroll.get("distance", 1.0)))
        self.scroll_fast.setValue(int(scroll.get("fast", 4)))
        self.scroll_smooth.setChecked(bool(scroll.get("smooth", True)))
        self.scroll_smooth_ms.setValue(int(scroll.get("smooth_ms", 220)))
        self.edge_keys.setChecked(bool(scroll.get("edge_keys", True)))
        self.edge_notches.setValue(int(scroll.get("edge_notches", 600)))
        self.edge_ms.setValue(int(scroll.get("edge_ms", 600)))
        self.edge_notches.setEnabled(self.edge_keys.isChecked()); self.edge_ms.setEnabled(self.edge_keys.isChecked())
        self.scroll_smooth_ms.setEnabled(self.scroll_smooth.isChecked())
        self.scroll_natural.setChecked(bool(scroll.get("natural", False)))
        self.scroll_invert_h.setChecked(bool(scroll.get("invert_horizontal", False)))
        mouse = {**d["mouse"], **cfg.get("mouse", {})}
        self.mouse_on.setChecked(bool(mouse["enabled"]))
        self.mouse_widgets[0].setEnabled(self.mouse_on.isChecked())
        self.mouse_open_in.setCurrentIndex(max(0, self.mouse_open_in.findData(mouse["open_in"])))
        self.mouse_fallback.setChecked(bool(mouse.get("fallback_grid", True)))
        self.mouse_ocr.setChecked(bool(mouse.get("ocr", True)))
        text = {**d["text"], **cfg.get("text", {})}
        self.text_dim.setValue(int(text["dim"])); self.text_labels.setText(str(text["labels"]))
        self.text_join.setCurrentIndex(max(0, self.text_join.findData(text["join_lines"])))
        self.text_line.setValue(float(text["line_notches"])); self.text_page.setValue(float(text["page_notches"]))
        ocr = {**d["ocr"], **cfg.get("ocr", {})}
        self.ocr_lang.setText(str(ocr["lang"])); self.ocr_conf.setValue(int(ocr["min_confidence"]))
        self.ocr_timeout.setValue(int(ocr["timeout_ms"])); self.screen_width.setValue(int(mouse.get("screen_width", 0)))
        for x in (self.ocr_lang, self.ocr_conf, self.ocr_timeout, self.screen_width):
            x.setEnabled(self.mouse_ocr.isChecked())
        self.mouse_stay.setChecked(bool(mouse.get("stay_after_click", True)))
        self.mouse_remember.setChecked(bool(mouse.get("remember_mode", False)))
        self.edit_step.setValue(int({**d["edit"], **cfg.get("edit", {})}["step"]))
        self.clip_on.setChecked(bool({**d["clipboard"], **cfg.get("clipboard", {})}["enabled"]))
        self.mouse_scope.setCurrentIndex(max(0, self.mouse_scope.findData(mouse["scope"])))
        self.mouse_cols.setValue(int(mouse["cols"])); self.mouse_rows.setValue(int(mouse["rows"]))
        self.mouse_depth.setValue(int(mouse["max_depth"]))
        self.mouse_alphabet.setText(str(mouse["alphabet"]))
        self.mouse_keys.setCurrentIndex(max(0, self.mouse_keys.findData(mouse["keys"])))
        self.mouse_speed.setValue(int(mouse["speed"])); self.mouse_fast.setValue(int(mouse["fast"]))
        self.mouse_accel.setChecked(bool(mouse["accelerate"]))
        acc = {**d["accessibility"], **cfg.get("accessibility", {})}
        self.offer_restart.setChecked(bool(acc["offer_restart"])); self.enable_on_start.setChecked(bool(acc["enable_on_start"]))
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
            hide_panel_until_typing=self.hide_panel.isChecked(), start_hidden=self.start_hidden.isChecked(),
            remember_panel=self.remember_panel.isChecked(),
            dim=self.dim.value())
        # only what differs from the defaults is written, so later releases can improve the defaults
        cfg["keys"] = {a: v for a, v in self.key_values.items() if v != keys.DEFAULTS[a]}
        cfg["hints"].update(delay_ms=max(0, delay), after_input=delay < 0, auto_activate=self.auto.isChecked())
        cfg["behavior"].update(continuous=self.continuous.isChecked(), continuous_delay_ms=self.cdelay.value(),
                               double_esc_close=self.double_esc.isChecked(), double_tap_ms=self.double_tap.value(),
                               click_with=self.click_with.currentData(), insert_after_field=self.insert_after.isChecked(),
                               keep_focus=self.keep_focus.isChecked())
        cfg["scroll"].update(keys=self.scroll_keys.currentData(), hjkl=self.hjkl_action.currentData(), distance=round(self.scroll_step.value(), 1),
                             fast=self.scroll_fast.value(), smooth=self.scroll_smooth.isChecked(), smooth_ms=self.scroll_smooth_ms.value(),
                             edge_keys=self.edge_keys.isChecked(), edge_notches=float(self.edge_notches.value()), edge_ms=self.edge_ms.value(),
                             natural=self.scroll_natural.isChecked(), invert_horizontal=self.scroll_invert_h.isChecked())
        cfg.setdefault("mouse", {}).update(
            enabled=self.mouse_on.isChecked(), open_in=self.mouse_open_in.currentData(), remember_mode=self.mouse_remember.isChecked(), stay_after_click=self.mouse_stay.isChecked(), fallback_grid=self.mouse_fallback.isChecked(), ocr=self.mouse_ocr.isChecked(), screen_width=self.screen_width.value(), scope=self.mouse_scope.currentData(),
            cols=self.mouse_cols.value(), rows=self.mouse_rows.value(), max_depth=self.mouse_depth.value(),
            alphabet=self.mouse_alphabet.text().strip().lower() or self.defaults["mouse"]["alphabet"],
            keys=self.mouse_keys.currentData(), speed=self.mouse_speed.value(), fast=self.mouse_fast.value(),
            accelerate=self.mouse_accel.isChecked())
        cfg.setdefault("edit", {}).update(step=self.edit_step.value())
        cfg.setdefault("clipboard", {}).update(enabled=self.clip_on.isChecked())
        cfg.setdefault("accessibility", {}).update(offer_restart=self.offer_restart.isChecked(), enable_on_start=self.enable_on_start.isChecked())
        cfg.setdefault("text", {}).update(dim=self.text_dim.value(), join_lines=self.text_join.currentData(),
                                          line_notches=round(self.text_line.value(), 1), page_notches=round(self.text_page.value(), 1),
                                          labels=self.text_labels.text().strip().lower() or self.defaults["text"]["labels"])
        cfg.setdefault("ocr", {}).update(lang=self.ocr_lang.text().strip() or "eng", min_confidence=float(self.ocr_conf.value()),
                                         timeout_ms=self.ocr_timeout.value())
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

    def export_dialog(self):
        """Ask where to save, then export every setting as JSON. Unsaved changes in this window are saved first, so
        the file holds what the window shows."""
        path, _ = QFileDialog.getSaveFileName(self, "Export vimvibe settings", os.path.expanduser("~/vimvibe-settings.json"), "JSON (*.json)")
        if not path:
            return
        self.write_config(self.collect())
        try:
            version = subprocess.run([core_binary(), "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = ""
        try:
            export_settings(path, version)
        except OSError as e:
            QMessageBox.warning(self, "vimvibe", f"Could not write {path}: {e}"); return
        QMessageBox.information(self, "vimvibe", f"Settings exported to {path}")

    def import_dialog(self):
        """Pick an exported JSON file, confirm, replace the settings with it and show them in this window."""
        path, _ = QFileDialog.getOpenFileName(self, "Import vimvibe settings", os.path.expanduser("~"), "JSON (*.json)")
        if not path:
            return
        if QMessageBox.question(self, "vimvibe", "Replace all current settings with the ones in this file?") != QMessageBox.Yes:
            return
        try:
            data = import_settings(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "vimvibe", f"Could not import {path}: {e}"); return
        if not PROFILE and isinstance(data.get("launch_at_login"), bool):
            self.set_autostart(data["launch_at_login"])
        self.load(self.read_config())
        QMessageBox.information(self, "vimvibe", "Settings imported. They apply the next time vimvibe opens.")

    def set_autostart(self, on):
        """Create or remove the XDG autostart entry that runs `vimvibe start` at login."""
        if not on:
            if os.path.exists(AUTOSTART):
                os.remove(AUTOSTART)
            return
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=vimvibe\nComment=Click anything by typing its name\n"
                    f"Exec={launcher()} start\nIcon=vimvibe\nX-KDE-autostart-phase=2\nNoDisplay=true\n")
