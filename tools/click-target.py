#!/usr/bin/env python3
"""A throwaway Qt window for testing clicks by hand without touching your real apps: a plain button, a menu button, a
combo box and a button that reports double clicks. Every event is appended to a log file (default
/tmp/vimvibe-click-target.log), so you can check what an action really did.

    python3 tools/click-target.py [LOGFILE]       # then open vimvibe over the "click-target" window

See CONTRIBUTING.md → "Testing by hand" for the busctl commands that drive it."""
import os, sys, time

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QComboBox, QMenu, QPushButton, QVBoxLayout, QWidget

LOG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/vimvibe-click-target.log"
log = open(LOG, "w", buffering=1)


def note(what):
    """Append one timestamped event to the log."""
    log.write(f"{time.time():.3f} {what}\n")


class Window(QWidget):
    def event(self, e):
        """Log activation changes: a popup that closes on focus churn shows up here."""
        if e.type() in (QEvent.WindowActivate, QEvent.WindowDeactivate):
            note(f"window {e.type().name}")
        return super().event(e)


class DoubleButton(QPushButton):
    def mousePressEvent(self, e):
        """Log every press (a double click is two)."""
        note("press"); super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        """Log a real double click as the toolkit recognised it."""
        note("DOUBLE")


def main():
    """Build the window and run until it is closed."""
    app = QApplication(sys.argv)
    w = Window(); w.setWindowTitle("click-target"); lay = QVBoxLayout(w)
    plain = QPushButton("Plain"); plain.clicked.connect(lambda: note("plain clicked")); lay.addWidget(plain)
    menu_button = QPushButton("Menu"); m = QMenu(menu_button)
    m.addAction("One", lambda: note("menu one")); m.addAction("Two", lambda: note("menu two"))
    m.aboutToShow.connect(lambda: note("menu show")); m.aboutToHide.connect(lambda: note("menu hide"))
    menu_button.setMenu(m); lay.addWidget(menu_button)
    combo = QComboBox(); combo.addItems(["a", "b", "c"]); combo.currentTextChanged.connect(lambda t: note(f"combo {t}")); lay.addWidget(combo)
    lay.addWidget(DoubleButton("Dbl"))
    w.resize(260, 220); w.show(); note(f"started pid {os.getpid()}")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
