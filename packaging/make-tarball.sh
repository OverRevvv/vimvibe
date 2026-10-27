#!/usr/bin/env bash
# Build the release tarball: dist/vimvibe-<version>-linux-x86_64.tar.gz
# It holds the compiled core, the Python overlay and the installer, so users need no Rust (only Python 3, PySide6
# and layer-shell-qt, which come from their distro because the overlay must run on the system's own Qt). It is also
# the source every distro package (.deb, .rpm, Arch) is made from (see packaging/stage.sh).
#
# The core is linked statically against musl, so one binary runs on every distro whatever its glibc (a core built on
# a new Fedora would not start on Debian stable). How it is built, first that works:
#   VIMVIBE_CORE_BIN=path   use this binary as it is
#   musl target installed   cargo build --target x86_64-unknown-linux-musl (CI: rustup target add + musl-tools)
#   podman or docker        build inside rust:1-alpine (musl by default)
#   otherwise               a normal (glibc) build, with a warning: it only runs on distros as new as this one
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' core/Cargo.toml | head -1)"
NAME="vimvibe-$VERSION-linux-$(uname -m)"
OUT="dist/$NAME"

core=""
if [ -n "${VIMVIBE_CORE_BIN:-}" ]; then
  core="$VIMVIBE_CORE_BIN"
elif rustup target list --installed 2>/dev/null | grep -q x86_64-unknown-linux-musl; then
  cargo build --release --manifest-path core/Cargo.toml --target x86_64-unknown-linux-musl
  core="${CARGO_TARGET_DIR:-core/target}/x86_64-unknown-linux-musl/release/vimvibe-core"
elif RUNNER="$(command -v podman || command -v docker)"; then
  mkdir -p dist/musl-target
  "$RUNNER" run --rm -v "$PWD:/src:Z" -v "$PWD/dist/musl-target:/target:Z" -e CARGO_TARGET_DIR=/target \
    docker.io/library/rust:1-alpine sh -c "apk add -q musl-dev >/dev/null && cargo build --release --manifest-path /src/core/Cargo.toml"
  core="dist/musl-target/release/vimvibe-core"
else
  echo "warning: no musl target and no podman/docker: building against this system's glibc (older distros can't run it)" >&2
  cargo build --release --manifest-path core/Cargo.toml
  core="${CARGO_TARGET_DIR:-core/target}/release/vimvibe-core"
fi

rm -rf "$OUT"; mkdir -p "$OUT/palette" "$OUT/packaging"
install -m755 "$core" "$OUT/vimvibe-core"
strip "$OUT/vimvibe-core" 2>/dev/null || true
install -m755 install.sh "$OUT/install.sh"
cp palette/vimvibe_*.py "$OUT/palette/"          # the tests stay behind: only the modules the overlay imports
cp -r packaging/vimvibe packaging/icons "$OUT/packaging/"
install -m755 packaging/stage.sh "$OUT/packaging/stage.sh"
cp README.md LICENSE "$OUT/"
tar -C dist -czf "dist/$NAME.tar.gz" "$NAME"
( cd dist && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )
echo "built dist/$NAME.tar.gz"
