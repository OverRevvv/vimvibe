#!/usr/bin/env bash
# Run the vimvibe in this source tree as a separate "dev" profile, next to the installed one (see README "Developing").
#   ./dev.sh start|stop|restart|status|settings|doctor|logs|open|version   same commands as `vimvibe`, for the dev copy
#   ./dev.sh build                                                         just build
# `start` and `restart` rebuild first (cargo only recompiles what changed); NO_BUILD=1 skips that.
# The dev copy has its own D-Bus name (org.vimvibe.DaemonDev), KDE shortcuts (Meta+Alt+Space / Meta+Alt+Q / Ctrl+Alt+,),
# settings (~/.config/vimvibe-dev, starting from your installed settings) and logs, so installing or updating the
# installed vimvibe never touches it and vice versa. It shares the pointer/keyboard permission.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
export VIMVIBE_PROFILE=dev
export VIMVIBE_CORE="${CARGO_TARGET_DIR:-$here/core/target}/release/vimvibe-core"
export VIMVIBE_PALETTE_DIR="$here/palette"
build() { cargo build --release --manifest-path "$here/core/Cargo.toml"; }
case "${1:-start}" in
  build) build; exit ;;
  start|restart) [ -n "${NO_BUILD:-}" ] || build ;;
esac
exec "$here/packaging/vimvibe" "${@:-start}"
