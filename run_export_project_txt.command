#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

run_python() {
  "$1" export_project_txt.py
}

if [ -x ".venv/bin/python" ]; then
  run_python ".venv/bin/python"
elif [ -x "venv/bin/python" ]; then
  run_python "venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  run_python "$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  run_python "$(command -v python)"
else
  echo "Python 3 executable not found."
  exit 1
fi
