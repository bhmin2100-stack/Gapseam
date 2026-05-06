#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

MINICONDA_DIR="$ROOT_DIR/.miniconda"
MINICONDA_PY="$MINICONDA_DIR/bin/python"
MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh"
INSTALLER_PATH="$ROOT_DIR/.codex-cache/miniconda.sh"

mkdir -p "$ROOT_DIR/.codex-cache"

if [ ! -x "$MINICONDA_PY" ]; then
  echo "[1/4] Installing local Miniconda..."
  curl -L "$MINICONDA_URL" -o "$INSTALLER_PATH"
  bash "$INSTALLER_PATH" -b -p "$MINICONDA_DIR"
else
  echo "[1/4] Reusing local Miniconda..."
fi

echo "[2/4] Installing build dependencies..."
"$MINICONDA_PY" -m pip install -e . pyinstaller

echo "[3/4] Building GFS.app..."
rm -rf build dist GFS.spec
"$MINICONDA_DIR/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name GFS \
  --paths src \
  --hidden-import pyclipper \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.GifImagePlugin \
  src/gapsim/ui_qt/main_window.py

echo "[4/4] Done."
echo "App bundle: $ROOT_DIR/dist/GFS.app"
