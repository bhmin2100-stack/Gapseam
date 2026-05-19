#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

# Legacy alias: GFE is now the emulator-first macOS app.
exec "$SCRIPT_DIR/build_gfe_macos.sh"
