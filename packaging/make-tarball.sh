#!/usr/bin/env bash
# Build the release tarball: dist/vimvibe-<version>-linux-x86_64.tar.gz
# It holds the compiled core, the Python overlay and the installer, so users need no Rust (only Python 3, PySide6
# and layer-shell-qt, which come from their distro because the overlay must run on the system's own Qt).
set -euo pipefail
cd "$(dirname "$0")/.."
cargo build --release --manifest-path core/Cargo.toml
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' core/Cargo.toml | head -1)"
NAME="vimvibe-$VERSION-linux-$(uname -m)"
OUT="dist/$NAME"
rm -rf "$OUT"; mkdir -p "$OUT/palette" "$OUT/packaging"
install -m755 "${CARGO_TARGET_DIR:-core/target}/release/vimvibe-core" "$OUT/vimvibe-core"
strip "$OUT/vimvibe-core" 2>/dev/null || true
install -m755 install.sh "$OUT/install.sh"
cp palette/vimvibe_*.py "$OUT/palette/"          # the tests stay behind: only the modules the overlay imports
cp -r packaging/vimvibe packaging/icons "$OUT/packaging/"
cp README.md "$OUT/README.md"
tar -C dist -czf "dist/$NAME.tar.gz" "$NAME"
( cd dist && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )
echo "built dist/$NAME.tar.gz"
