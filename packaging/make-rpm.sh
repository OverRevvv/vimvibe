#!/usr/bin/env bash
# Build the RPM inside a container of the target distro (podman or docker), from the release tarball in dist/ (run
# packaging/make-tarball.sh first). The spec picks the right dependency names for each.
#   packaging/make-rpm.sh            Fedora   -> dist/vimvibe-<version>-1.fcNN.x86_64.rpm
#   packaging/make-rpm.sh opensuse   openSUSE -> dist/vimvibe-<version>-1.opensuse.x86_64.rpm
set -euo pipefail
cd "$(dirname "$0")/.."
DISTRO="${1:-fedora}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' core/Cargo.toml | head -1)"
TARBALL="vimvibe-$VERSION-linux-x86_64.tar.gz"
[ -f "dist/$TARBALL" ] || { echo "missing dist/$TARBALL: run packaging/make-tarball.sh first"; exit 1; }
RUNNER="$(command -v podman || command -v docker)"
case "$DISTRO" in
  fedora)   IMAGE=docker.io/library/fedora:latest; PREP="dnf -q -y install rpm-build >/dev/null"; DIST="" ;;
  opensuse) IMAGE=docker.io/opensuse/tumbleweed;   PREP="zypper -q --non-interactive install rpm-build >/dev/null"; DIST="--define 'dist .opensuse'" ;;
  *) echo "unknown distro $DISTRO (fedora, opensuse)"; exit 2 ;;
esac
"$RUNNER" run --rm -v "$PWD:/src:Z" "$IMAGE" bash -c "
  set -euo pipefail
  $PREP
  mkdir -p /root/rpmbuild/SOURCES && cp /src/dist/$TARBALL /root/rpmbuild/SOURCES/
  rpmbuild -bb --define '_topdir /root/rpmbuild' --define 'vv_version $VERSION' $DIST /src/packaging/rpm/vimvibe.spec >/dev/null  # one build folder on every distro (openSUSE defaults to /usr/src/packages)
  cp /root/rpmbuild/RPMS/x86_64/*.rpm /src/dist/
"
ls -1 dist/*.rpm
