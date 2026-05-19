# -*- mode: python ; coding: utf-8 -*-

# Legacy name kept for history/compatibility.
# GFE.spec is the canonical PyInstaller spec for current packaging.

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
HIDDEN_IMPORTS = [
    'pyclipper',
    'openpyxl',
    'PIL',
    'PIL.Image',
    'PIL.GifImagePlugin',
    'gapsim.ui_qt.calibrate_dialog',
    'gapsim.ui_qt.controllers.smoothing_ctrl',
    'gapsim.ui_qt.models.points_table',
    'gapsim.ui_qt.models.points_table_view',
    'gapsim.ui_qt.views.structure_view',
    'gapsim.ui_qt.views.result_vector_view',
]

emulator = Analysis(
    [str(ROOT / 'src' / 'gapsim' / 'emulation' / 'trench_depo_ui.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
emulator_pyz = PYZ(emulator.pure)

emulator_exe = EXE(
    emulator_pyz,
    emulator.scripts,
    [],
    exclude_binaries=True,
    name='GFE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    emulator_exe,
    emulator.binaries,
    emulator.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GFE',
)
