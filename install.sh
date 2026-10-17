#!/usr/bin/env bash
# Build vimvibe and install it for the current user (no root needed):
#   ~/.local/bin/vimvibe-core        the Rust core / daemon
#   ~/.local/bin/vimvibe             launcher (start | stop | settings | doctor | ...)
#   ~/.local/share/vimvibe/          the overlay and Settings window (Python + PySide6)
# Usage: ./install.sh            build + install (an upgrade in place: a running installed vimvibe is restarted)
#        ./install.sh --uninstall remove those files (your settings in ~/.config/vimvibe are kept)
set -euo pipefail
cd "$(dirname "$0")"
BIN="$HOME/.local/bin"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/vimvibe"

if [ "${1:-}" = "--uninstall" ]; then
  "$BIN/vimvibe" stop 2>/dev/null || true
  rm -f "$BIN/vimvibe-core" "$BIN/vimvibe" "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/vimvibe.desktop" \
        "${XDG_DATA_HOME:-$HOME/.local/share}/applications/vimvibe.desktop"
  find "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" -name 'vimvibe.*' -delete 2>/dev/null || true
  rm -rf "$SHARE"
  echo "vimvibe removed (settings kept in ${XDG_CONFIG_HOME:-$HOME/.config}/vimvibe)"
  exit 0
fi

missing=0
command -v cargo >/dev/null || { echo "missing: Rust (cargo). Install from https://rustup.rs or: sudo dnf install cargo"; missing=1; }
python3 -c "import PySide6" 2>/dev/null || { echo "missing: PySide6. Fedora: sudo dnf install python3-pyside6   (others: pip install --user PySide6)"; missing=1; }
command -v gdbus >/dev/null || { echo "missing: gdbus (glib2). Fedora: sudo dnf install glib2"; missing=1; }
[ "$missing" = 0 ] || exit 1

# upgrade in place: stop a running installed copy first (the development copy, if any, is a different profile and is
# left alone), and start it again afterwards
was_running=0
if [ -x "$BIN/vimvibe" ] && [ -n "$(busctl --user status org.vimvibe.Daemon 2>/dev/null | sed -n 's/^PID=//p')" ]; then
  was_running=1
  echo "stopping the installed vimvibe for the upgrade…"
  VIMVIBE_PROFILE= "$BIN/vimvibe" stop >/dev/null 2>&1 || true
fi

echo "building the core (release)…"
cargo build --release --manifest-path core/Cargo.toml
TARGET="${CARGO_TARGET_DIR:-core/target}"

install -Dm755 "$TARGET/release/vimvibe-core" "$BIN/vimvibe-core"
install -Dm644 palette/vimvibe_palette.py "$SHARE/vimvibe_palette.py"
install -Dm644 palette/vimvibe_settings.py "$SHARE/vimvibe_settings.py"
install -Dm644 palette/vimvibe_style.py "$SHARE/vimvibe_style.py"
install -Dm644 palette/vimvibe_keys.py "$SHARE/vimvibe_keys.py"
install -Dm644 packaging/icons/vimvibe.svg "$SHARE/vimvibe.svg"   # for the overlay's and Settings' window icon
sed -e "s|@CORE@|$BIN/vimvibe-core|" -e "s|@PALETTE_DIR@|$SHARE|" packaging/vimvibe > "$BIN/vimvibe"
chmod 755 "$BIN/vimvibe"
# the icon, in the standard places the desktop looks (app menu, task manager, notifications)
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$DATA/icons/hicolor"
cp -r packaging/icons/hicolor/. "$DATA/icons/hicolor/"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true
# app menu entry for the Settings window; also lets the overlay register its app id ("vimvibe") with the desktop
APPS="$DATA/applications"
mkdir -p "$APPS"
printf '[Desktop Entry]\nType=Application\nName=vimvibe Settings\nComment=Click anything by typing its name\nExec=%s settings\nIcon=vimvibe\nCategories=Utility;Accessibility;\n' "$BIN/vimvibe" > "$APPS/vimvibe.desktop"

if [ "$was_running" = 1 ]; then
  echo "starting the upgraded vimvibe again…"
  VIMVIBE_PROFILE= "$BIN/vimvibe" start >/dev/null 2>&1 || echo "could not restart it; run: vimvibe start"
fi

echo
echo "installed $("$BIN/vimvibe-core" --version):"
echo "  $BIN/vimvibe-core"
echo "  $BIN/vimvibe"
echo "  $SHARE/"
case ":$PATH:" in *":$BIN:"*) ;; *) echo; echo "note: $BIN is not on your PATH; add it, or call $BIN/vimvibe directly";; esac
echo
echo "next:  vimvibe start            # start daemon + overlay (turns desktop accessibility on)"
echo "       ./dev.sh start           # developing? run the source tree as a separate 'dev' copy next to this one"
echo "       vimvibe settings         # colour, label delay, excluded apps, launch at login, ..."
