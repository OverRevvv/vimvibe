#!/usr/bin/env bash
# Build the Debian / Ubuntu package from the release tarball in dist/ (run packaging/make-tarball.sh first).
# Output: dist/vimvibe_<version>_amd64.deb. Uses dpkg-deb directly when it is installed (Debian, Ubuntu, the GitHub
# runner), otherwise a debian:stable container (podman or docker). Nothing is compiled: the tarball's core is static.
set -euo pipefail
cd "$(dirname "$0")/../.."
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' core/Cargo.toml | head -1)"
NAME="vimvibe-$VERSION-linux-x86_64"
[ -f "dist/$NAME.tar.gz" ] || { echo "missing dist/$NAME.tar.gz: run packaging/make-tarball.sh first"; exit 1; }

if ! command -v dpkg-deb >/dev/null; then
  RUNNER="$(command -v podman || command -v docker)" || { echo "need dpkg-deb, or podman/docker"; exit 1; }
  exec "$RUNNER" run --rm -v "$PWD:/src:Z" -w /src docker.io/library/debian:stable bash packaging/deb/make-deb.sh
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
tar -C "$work" -xzf "dist/$NAME.tar.gz"
root="$work/root"
"$work/$NAME/packaging/stage.sh" "$work/$NAME" "$root" /usr
# Debian keeps licence texts in the doc directory (copyright file), not /usr/share/licenses
mkdir -p "$root/usr/share/doc/vimvibe"
{ echo "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
  echo "Upstream-Name: vimvibe"; echo "Source: https://github.com/OverRevvv/vimvibe"; echo
  echo "Files: *"; echo "License: MIT"; sed 's/^/ /; s/^ $/ ./' "$work/$NAME/LICENSE"; } > "$root/usr/share/doc/vimvibe/copyright"
rm -rf "$root/usr/share/licenses"

size="$(du -sk "$root" | cut -f1)"
mkdir -p "$root/DEBIAN"
# Dependencies by Debian / Ubuntu package name (checked on Debian 13 and Ubuntu 24.04, see docs/packaging.md):
# PySide6 is split per Qt module; layer-shell-qt keeps the overlay above popups; gdbus is in libglib2.0-bin.
cat > "$root/DEBIAN/control" <<CONTROL
Package: vimvibe
Version: $VERSION
Architecture: amd64
Maintainer: OverRevvv <rdude1612@gmail.com>
Installed-Size: $size
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, python3-pyside6.qtdbus, liblayershellqtinterface6 | layer-shell-qt, libglib2.0-bin
Recommends: kde-spectacle, tesseract-ocr, tesseract-ocr-eng
Section: utils
Priority: optional
Homepage: https://github.com/OverRevvv/vimvibe
Description: click anything on the desktop by typing its name
 vimvibe labels every button, tab, link and menu item of the focused window
 on KDE Plasma (Wayland); type a few letters of its name or its label and
 press Enter to click it. Also: a keyboard mouse, scrolling, text-field
 jumping like Vimium, a text mode to copy anything on screen with Vim keys,
 and OCR / grid fallbacks for apps without an accessibility tree.
CONTROL
chmod -R u=rwX,go=rX "$root"
dpkg-deb --root-owner-group --build "$root" "dist/vimvibe_${VERSION}_amd64.deb" >/dev/null
echo "built dist/vimvibe_${VERSION}_amd64.deb"
