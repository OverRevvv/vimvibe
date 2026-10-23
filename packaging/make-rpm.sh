#!/usr/bin/env bash
# Build the RPM inside a Fedora container (podman or docker), from the release tarball in dist/ (run
# packaging/make-tarball.sh first). Output: dist/vimvibe-<version>-1.*.x86_64.rpm
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' core/Cargo.toml | head -1)"
TARBALL="vimvibe-$VERSION-linux-x86_64.tar.gz"
[ -f "dist/$TARBALL" ] || { echo "missing dist/$TARBALL: run packaging/make-tarball.sh first"; exit 1; }
RUNNER="$(command -v podman || command -v docker)"
"$RUNNER" run --rm -v "$PWD:/src:Z" fedora:latest bash -c "
  set -euo pipefail
  dnf -q -y install rpm-build >/dev/null
  mkdir -p /root/rpmbuild/SOURCES && cp /src/dist/$TARBALL /root/rpmbuild/SOURCES/
  rpmbuild -bb --define 'vv_version $VERSION' /src/packaging/rpm/vimvibe.spec
  cp /root/rpmbuild/RPMS/x86_64/*.rpm /src/dist/
"
ls dist/*.rpm
