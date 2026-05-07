#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

MINICONDA_DIR="$ROOT_DIR/.miniconda"
MINICONDA_PY="$MINICONDA_DIR/bin/python"
INSTALLER_PATH="$ROOT_DIR/.codex-cache/miniconda.sh"

mkdir -p "$ROOT_DIR/.codex-cache"

case "$(uname -m)" in
  arm64)
    MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh"
    ;;
  *)
    MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh"
    ;;
esac

if [ ! -x "$MINICONDA_PY" ]; then
  echo "[1/4] Installing local Miniconda..."
  curl -L "$MINICONDA_URL" -o "$INSTALLER_PATH"
  bash "$INSTALLER_PATH" -b -p "$MINICONDA_DIR"
else
  echo "[1/4] Reusing local Miniconda..."
fi

echo "[2/4] Installing build dependencies..."
"$MINICONDA_PY" -m pip install -e . pyinstaller openpyxl

echo "[3/4] Building GFS.app and GFS_Emulator.app..."
rm -rf build dist GFS.spec GFS_Emulator.spec

build_app() {
  app_name="$1"
  entrypoint="$2"
  "$MINICONDA_DIR/bin/pyinstaller" \
    --noconfirm \
    --clean \
    --windowed \
    --name "$app_name" \
    --paths src \
    --hidden-import pyclipper \
    --hidden-import openpyxl \
    --hidden-import PIL \
    --hidden-import PIL.Image \
    --hidden-import PIL.GifImagePlugin \
    "$entrypoint"
}

build_app GFS src/gapsim/ui_qt/main_window.py
build_app GFS_Emulator src/gapsim/emulation/trench_depo_ui.py

echo "[4/4] Done."
echo "App bundle: $ROOT_DIR/dist/GFS.app"
echo "Emulator app bundle: $ROOT_DIR/dist/GFS_Emulator.app"
