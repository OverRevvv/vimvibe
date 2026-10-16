"""vimvibe Settings window (opened with `vimvibe_palette.py --settings`, or `vimvibe settings`).

Edits ~/.config/vimvibe/config.toml. The overlay and the daemon re-read that file every time the overlay opens, so
changes apply on the next use without restarting anything. Mirrors Shortcat's Preferences where it makes sense on
Linux (shortcut, launch at login, label delay, continuous mode) and adds what vimvibe needs (excluded apps,
accessibility setup, pointer permission, label colour).
"""
import os, shutil, subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

DELAYS = [("Immediately", 0), ("After 200 ms", 200), ("After 500 ms", 500), ("After 1 second", 1000),
          ("After 2 seconds (Shortcat's default)", 2000), ("After 5 seconds", 5000), ("After input", -1)]
PRESETS = [("Blue", "#3b82f6"), ("Shortcat yellow", "#facc15"), ("Green", "#22c55e"), ("Purple", "#a855f7"),
           ("Orange", "#f97316"), ("Pink", "#ec4899"), ("Red", "#ef4444"), ("Teal", "#14b8a6")]
AUTOSTART = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart", "vimvibe.desktop")


def core_binary():
    """Path of vimvibe-core: $VIMVIBE_CORE, then $PATH, then ~/.local/bin."""
    return os.environ.get("VIMVIBE_CORE") or shutil.which("vimvibe-core") or os.path.expanduser("~/.local/bin/vimvibe-core")


def launcher():
    """Path of the `vimvibe` launcher script (used for the autostart entry)."""
    return shutil.which("vimvibe") or os.path.expanduser("~/.local/bin/vimvibe")


class SettingsWindow(QWidget):
    def __init__(self, read_config, write_config, defaults):
        """Build the five tabs and load the current settings into them."""
        super().__init__()
        self.read_config, self.write_config, self.defaults = read_config, write_config, defaults
        self.setWindowTitle("vimvibe Settings")
        self.resize(620, 560)
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

    # --- tabs -----------------------------------------------------------------------
    def general_tab(self):
        """Shortcut info, launch at login, and which extra results to offer."""
        w = QWidget(); f = QFormLayout(w)
        shortcut = QHBoxLayout()
        shortcut.addWidget(QLabel("<b>Meta+Shift+Space</b> by default"))
        b = QPushButton("Change in System Settings…")
        b.clicked.connect(lambda: self.run_detached(["systemsettings", "kcm_keys"]))
        shortcut.addWidget(b)
        f.addRow("Activation shortcut:", shortcut)
        f.addRow("", QLabel("<small>KDE keeps the shortcut under Shortcuts → <i>vimvibe</i> → Toggle palette. "
                            "Other desktops: bind any key to<br><code>gdbus call --session --dest org.vimvibe.Daemon "
                            "--object-path /org/vimvibe/Daemon --method org.vimvibe.Daemon.Trigger</code></small>",
                            textFormat=Qt.RichText, wordWrap=True))
        self.login = QCheckBox("Start vimvibe when I log in")
        f.addRow("Launch at login:", self.login)
        self.windows = QCheckBox("Also offer my other open windows as results (window switching)")
        f.addRow("Search:", self.windows)
        self.apps_search = QCheckBox("Also offer installed applications (type a name, Enter launches it)")
        f.addRow("", self.apps_search)
        return w

    def appearance_tab(self):
        """Label colour (with presets), label size and panel position."""
        w = QWidget(); f = QFormLayout(w)
        row = QHBoxLayout()
        self.accent = QLineEdit(); self.accent.setMaximumWidth(110)
        self.swatch = QPushButton(); self.swatch.setFixedWidth(40)
        self.swatch.clicked.connect(self.pick_colour)
        self.accent.textChanged.connect(self.update_swatch)
        row.addWidget(self.accent); row.addWidget(self.swatch)
        self.preset = QComboBox(); self.preset.addItem("Presets…")
        for name, hexv in PRESETS:
            self.preset.addItem(name, hexv)
        self.preset.activated.connect(lambda i: i and self.accent.setText(self.preset.itemData(i)))
        row.addWidget(self.preset); row.addStretch()
        f.addRow("Label & highlight colour:", row)
        self.scale = QDoubleSpinBox(); self.scale.setRange(0.6, 2.0); self.scale.setSingleStep(0.1); self.scale.setSuffix("×")
        f.addRow("Label size:", self.scale)
        self.panel = QComboBox()
        for label, v in [("Automatic (where it hides the fewest labels)", "auto"), ("Top of the window", "top"),
                         ("Centre of the window", "center"), ("Bottom of the window", "bottom")]:
            self.panel.addItem(label, v)
        f.addRow("Search panel position:", self.panel)
        return w

    def labels_tab(self):
        """When labels appear, Vimium-style auto-click, continuous mode."""
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
        box2 = QGroupBox("Pointer (for controls apps can't activate, right click, hover)"); pl = QVBoxLayout(box2)
        pl.addWidget(QLabel("Uses the desktop's Remote Control permission. Your desktop asks once; revoke it any time "
                            "in System Settings → Security & Privacy → Remote Control.", wordWrap=True))
        b4 = QPushButton("Allow pointer control…"); b4.clicked.connect(lambda: self.show_cmd([core_binary(), "pointer-setup"]))
        pl.addWidget(b4)
        v.addWidget(box2)
        self.output = QPlainTextEdit(readOnly=True); self.output.setPlaceholderText("Command output appears here")
        v.addWidget(self.output)
        return w

    # --- helpers --------------------------------------------------------------------
    def update_swatch(self, text):
        """Show the typed colour next to the field."""
        c = QColor(text)
        self.swatch.setStyleSheet(f"background: {c.name() if c.isValid() else 'transparent'}; border: 1px solid #888;")

    def pick_colour(self):
        """Pick the label colour with the colour dialog."""
        c = QColorDialog.getColor(QColor(self.accent.text()), self, "Label colour")
        if c.isValid():
            self.accent.setText(c.name())

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

    # --- load / save ------------------------------------------------------------------
    def load(self, cfg):
        """Fill every control from a settings dict."""
        ui, hints, beh = cfg.get("ui", {}), cfg.get("hints", {}), cfg.get("behavior", {})
        self.accent.setText(ui.get("accent", "#3b82f6"))
        self.scale.setValue(float(ui.get("label_scale", 1.0)))
        self.panel.setCurrentIndex(max(0, self.panel.findData(ui.get("panel", "auto"))))
        delay = -1 if hints.get("after_input") else int(hints.get("delay_ms", 0))
        i = self.delay.findData(delay)
        if i < 0:
            self.delay.addItem(f"After {delay} ms", delay); i = self.delay.count() - 1
        self.delay.setCurrentIndex(i)
        self.auto.setChecked(bool(hints.get("auto_activate", False)))
        self.continuous.setChecked(bool(beh.get("continuous", False)))
        self.cdelay.setValue(int(beh.get("continuous_delay_ms", 500)))
        self.windows.setChecked(bool(cfg.get("search", {}).get("windows", True)))
        self.apps_search.setChecked(bool(cfg.get("search", {}).get("apps", True)))
        self.apps.clear()
        self.apps.addItems([str(a) for a in cfg.get("apps", {}).get("exclude", [])])
        self.login.setChecked(os.path.exists(AUTOSTART))

    def save(self):
        """Write the controls back to config.toml (keeping keys this window doesn't know) and update autostart."""
        if not QColor(self.accent.text()).isValid():
            QMessageBox.warning(self, "vimvibe", f"“{self.accent.text()}” is not a colour."); return
        cfg = self.read_config()
        delay = self.delay.currentData()
        cfg["ui"].update(accent=self.accent.text(), label_scale=round(self.scale.value(), 2), panel=self.panel.currentData())
        cfg["hints"].update(delay_ms=max(0, delay), after_input=delay < 0, auto_activate=self.auto.isChecked())
        cfg["behavior"].update(continuous=self.continuous.isChecked(), continuous_delay_ms=self.cdelay.value())
        cfg["search"]["windows"] = self.windows.isChecked()
        cfg["search"]["apps"] = self.apps_search.isChecked()
        cfg["apps"]["exclude"] = [self.apps.item(i).text() for i in range(self.apps.count())]
        self.write_config(cfg)
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
