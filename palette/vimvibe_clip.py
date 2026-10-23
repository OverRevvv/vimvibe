"""vimvibe's clipboard access: the history shown by the picker and setting the clipboard. KDE's Klipper keeps the
history (it already records everything copied anywhere), so vimvibe asks it over D-Bus instead of watching the
clipboard itself; without Klipper the picker offers just the current clipboard. Clipboard contents are never logged."""
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import QGuiApplication

MAX_ITEMS = 50


def klipper():
    """The Klipper D-Bus interface, or None when it isn't running."""
    iface = QDBusInterface("org.kde.klipper", "/klipper", "org.kde.klipper.klipper", QDBusConnection.sessionBus())
    return iface if iface.isValid() else None


def history():
    """Clipboard entries, newest first, without empty ones or duplicates (at most MAX_ITEMS)."""
    items = []
    k = klipper()
    if k is not None:
        reply = k.call("getClipboardHistoryMenu").arguments()
        items = [str(x) for x in (reply[0] if reply else [])]
    if not items:
        items = [QGuiApplication.clipboard().text()]
    out = []
    for text in items:
        if text.strip() and text not in out:
            out.append(text)
    return out[:MAX_ITEMS]


def set_text(text):
    """Put `text` on the clipboard (through Klipper, so it lands in the history too, and is owned by a process that
    keeps running after the overlay hides)."""
    k = klipper()
    if k is not None:
        k.call("setClipboardContents", text)
    else:
        QGuiApplication.clipboard().setText(text)


def one_line(text, limit=200):
    """An entry as one line for the picker: whitespace runs (and line breaks) become single spaces."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
