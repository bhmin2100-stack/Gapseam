#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

run_python() {
  "$1" -m gapsim.emulation.trench_depo_ui
}

find_python() {
  if [ -x ".venv/bin/python" ]; then
    printf '%s\n' ".venv/bin/python"
  elif [ -x "venv/bin/python" ]; then
    printf '%s\n' "venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m venv ".venv"
    printf '%s\n' ".venv/bin/python"
  elif command -v python >/dev/null 2>&1; then
    python -m venv ".venv"
    printf '%s\n' ".venv/bin/python"
  else
    echo "Python 3 executable not found." >&2
    echo "Install Python 3.10+ and retry." >&2
    exit 1
  fi
}

PYTHON_EXE="$(find_python)"

if [ -n "${PYTHONPATH:-}" ]; then
  PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
else
  PYTHONPATH="$SCRIPT_DIR/src"
fi
export PYTHONPATH

if ! "$PYTHON_EXE" -c "import PySide6, pyclipper, PIL, openpyxl" >/dev/null 2>&1; then
  "$PYTHON_EXE" -m pip install --upgrade pip
  "$PYTHON_EXE" -m pip install -e . openpyxl
fi

run_python "$PYTHON_EXE"
