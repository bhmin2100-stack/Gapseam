#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

# Legacy alias: GFE now starts the mini emulator by default.
exec "$SCRIPT_DIR/run_gfe.command"
