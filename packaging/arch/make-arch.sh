#!/usr/bin/env bash
# Arch Linux: build and check the package in an archlinux container (podman or docker) from the release tarball in
# dist/ (run packaging/make-tarball.sh first), and write what the AUR needs:
#   dist/vimvibe-bin-<version>-1-x86_64.pkg.tar.zst   the package (also installable with `pacman -U`)
#   dist/aur/PKGBUILD, dist/aur/.SRCINFO               for the AUR repository vimvibe-bin, with the real checksum
# The AUR PKGBUILD downloads the tarball from the GitHub release, so publish the release before pushing to the AUR.
set -euo pipefail
cd "$(dirname "$0")/../.."
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' core/Cargo.toml | head -1)"
TARBALL="vimvibe-$VERSION-linux-x86_64.tar.gz"
[ -f "dist/$TARBALL" ] || { echo "missing dist/$TARBALL: run packaging/make-tarball.sh first"; exit 1; }
SUM="$(sha256sum "dist/$TARBALL" | cut -d' ' -f1)"
mkdir -p dist/aur
sed -e "s/^pkgver=.*/pkgver=$VERSION/" -e "s/^sha256sums=.*/sha256sums=('$SUM')/" packaging/arch/PKGBUILD > dist/aur/PKGBUILD
RUNNER="$(command -v podman || command -v docker)"
# makepkg refuses to run as root: build as an unprivileged user, from the local tarball (same checksum as the release)
"$RUNNER" run --rm -v "$PWD:/src:Z" docker.io/library/archlinux bash -c "
  set -euo pipefail
  pacman -Sy --noconfirm --needed base-devel >/dev/null 2>&1
  useradd -m builder
  mkdir /build && cp /src/dist/aur/PKGBUILD /src/dist/$TARBALL /build/ && chown -R builder /build
  sed -i 's|^source=.*|source=(\"$TARBALL\")|' /build/PKGBUILD
  cd /build
  su builder -c 'makepkg --nodeps --noconfirm >/dev/null && makepkg --printsrcinfo' > /tmp/srcinfo
  cp /build/*.pkg.tar.zst /src/dist/
  # .SRCINFO must describe the published PKGBUILD (download URL), not the local test copy
  sed 's|source = $TARBALL|source = https://github.com/OverRevvv/vimvibe/releases/download/v$VERSION/$TARBALL|' /tmp/srcinfo > /src/dist/aur/.SRCINFO
"
ls -1 dist/*.pkg.tar.zst dist/aur/PKGBUILD dist/aur/.SRCINFO
