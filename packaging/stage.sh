#!/usr/bin/env bash
# Lay vimvibe's files out under DESTDIR for a system package (.deb, .rpm, Arch). Every package format calls this, so
# they all install the same files in the same places:
#   PREFIX/bin/vimvibe-core                    the core (static binary from the release tarball)
#   PREFIX/bin/vimvibe                         the launcher, pointing at the two paths below
#   PREFIX/share/vimvibe/                      the overlay and Settings (Python) and the window icon
#   PREFIX/share/icons/hicolor/*/apps/         the app icon
#   PREFIX/share/applications/vimvibe.desktop  "vimvibe Settings" in the app menu
#   PREFIX/share/doc/vimvibe/README.md, PREFIX/share/licenses/vimvibe/LICENSE
#
# Usage: packaging/stage.sh SRC DESTDIR [PREFIX]
#   SRC      an unpacked release tarball (vimvibe-core, palette/, packaging/, README.md, LICENSE) or the source tree
#            after `cargo build --release` (the core is then taken from core/target/release)
#   PREFIX   defaults to /usr
set -euo pipefail
SRC=${1:?usage: stage.sh SRC DESTDIR [PREFIX]}
DEST=${2:?usage: stage.sh SRC DESTDIR [PREFIX]}
PREFIX=${3:-/usr}

core="$SRC/vimvibe-core"
[ -x "$core" ] || core="$SRC/${CARGO_TARGET_DIR:-core/target}/release/vimvibe-core"
[ -x "$core" ] || { echo "stage.sh: no vimvibe-core in $SRC" >&2; exit 1; }

install -Dm755 "$core" "$DEST$PREFIX/bin/vimvibe-core"
# the launcher template names where the core and the overlay ended up
sed -e "s|@CORE@|$PREFIX/bin/vimvibe-core|" -e "s|@PALETTE_DIR@|$PREFIX/share/vimvibe|" "$SRC/packaging/vimvibe" > "$DEST.vimvibe.tmp"
install -Dm755 "$DEST.vimvibe.tmp" "$DEST$PREFIX/bin/vimvibe"
rm -f "$DEST.vimvibe.tmp"
for f in "$SRC"/palette/vimvibe_*.py; do
  install -Dm644 "$f" "$DEST$PREFIX/share/vimvibe/$(basename "$f")"
done
install -Dm644 "$SRC/packaging/icons/vimvibe.svg" "$DEST$PREFIX/share/vimvibe/vimvibe.svg"
mkdir -p "$DEST$PREFIX/share/icons"
cp -r "$SRC/packaging/icons/hicolor" "$DEST$PREFIX/share/icons/"
chmod -R u=rwX,go=rX "$DEST$PREFIX/share/icons/hicolor"
mkdir -p "$DEST$PREFIX/share/applications"
printf '[Desktop Entry]\nType=Application\nName=vimvibe Settings\nComment=Click anything by typing its name\nExec=vimvibe settings\nIcon=vimvibe\nCategories=Utility;Accessibility;\n' \
  > "$DEST$PREFIX/share/applications/vimvibe.desktop"
chmod 644 "$DEST$PREFIX/share/applications/vimvibe.desktop"
install -Dm644 "$SRC/README.md" "$DEST$PREFIX/share/doc/vimvibe/README.md"
install -Dm644 "$SRC/LICENSE" "$DEST$PREFIX/share/licenses/vimvibe/LICENSE"
