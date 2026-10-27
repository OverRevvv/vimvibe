#!/usr/bin/env bash
# Build vimvibe (or, from a release tarball, use the shipped binary) and install it for the current user (no root needed):
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

# a release tarball ships the compiled core next to this script: then no Rust is needed and nothing is built
PREBUILT=""
[ -x ./vimvibe-core ] && PREBUILT=./vimvibe-core

# What to install, by distro family (/etc/os-release ID and ID_LIKE); the names are checked in docs/packaging.md
distro="$( . /etc/os-release 2>/dev/null; echo "${ID:-} ${ID_LIKE:-}" )"
case " $distro " in
  *" fedora "*)             need="sudo dnf install python3-pyside6 layer-shell-qt glib2 spectacle tesseract" ; rust="sudo dnf install cargo" ;;
  *" suse "*|*" opensuse"*) need="sudo zypper install python3-pyside6 libLayerShellQtInterface6 glib2-tools spectacle tesseract-ocr" ; rust="sudo zypper install cargo" ;;
  *" arch "*)               need="sudo pacman -S pyside6 layer-shell-qt glib2 spectacle tesseract tesseract-data-eng" ; rust="sudo pacman -S rust" ;;
  *" debian "*|*" ubuntu "*) need="sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtdbus liblayershellqtinterface6 libglib2.0-bin kde-spectacle tesseract-ocr" ; rust="sudo apt install cargo" ;;
  *)                        need="install PySide6, layer-shell-qt, gdbus (glib2), spectacle and tesseract from your distro" ; rust="https://rustup.rs" ;;
esac
missing=0
[ -n "$PREBUILT" ] || command -v cargo >/dev/null || { echo "missing: Rust (cargo): $rust   (or use a release package / tarball: no Rust needed)"; missing=1; }
python3 -c "import PySide6.QtWidgets, PySide6.QtDBus" 2>/dev/null || { echo "missing: PySide6"; missing=1; }
command -v gdbus >/dev/null || { echo "missing: gdbus (glib2)"; missing=1; }
[ "$missing" = 0 ] || { echo "install with: $need"; exit 1; }
python3 -c 'import ctypes; ctypes.CDLL("libLayerShellQtInterface.so.6")' 2>/dev/null \
  || echo "note: layer-shell-qt (Qt 6) is not installed: vimvibe works, but popups close when it opens. Install with: $need"

# upgrade in place: stop a running installed copy first (the development copy, if any, is a different profile and is
# left alone), and start it again afterwards
was_running=0
if [ -x "$BIN/vimvibe" ] && [ -n "$(busctl --user status org.vimvibe.Daemon 2>/dev/null | sed -n 's/^PID=//p')" ]; then
  was_running=1
  echo "stopping the installed vimvibe for the upgrade…"
  VIMVIBE_PROFILE= "$BIN/vimvibe" stop >/dev/null 2>&1 || true
fi

if [ -n "$PREBUILT" ]; then
  CORE_BIN="$PREBUILT"
else
  echo "building the core (release)…"
  cargo build --release --manifest-path core/Cargo.toml
  CORE_BIN="${CARGO_TARGET_DIR:-core/target}/release/vimvibe-core"
fi

install -Dm755 "$CORE_BIN" "$BIN/vimvibe-core"
# every palette module (a missing one stops the overlay at import), not a hand-kept list
for f in palette/vimvibe_*.py; do install -Dm644 "$f" "$SHARE/$(basename "$f")"; done
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
