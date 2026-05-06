#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Keep the src layout importable even before editable install.
if [ -n "${PYTHONPATH:-}" ]; then
  PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
else
  PYTHONPATH="$SCRIPT_DIR/src"
fi
export PYTHONPATH

run_python() {
  "$1" -m gapsim.ui_qt.main_window
}

if [ -x ".venv/bin/python" ]; then
  run_python ".venv/bin/python"
elif [ -x "gapsim/.venv/bin/python" ]; then
  run_python "gapsim/.venv/bin/python"
elif [ -x "venv/bin/python" ]; then
  run_python "venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  run_python "$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  run_python "$(command -v python)"
else
  echo "Python 3 executable not found."
  echo "Install Python 3.10+ and run: pip install -e ."
  exit 1
fi
