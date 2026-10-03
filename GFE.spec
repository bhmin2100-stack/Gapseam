# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

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
    datas=[(str(ROOT / 'src' / 'gapsim' / 'emulation' / 'help_trench_examples.json.gz'), 'gapsim/emulation'),
           (str(ROOT / 'src' / 'gapsim' / 'emulation' / 'assets' / 'gfe.ico'), 'gapsim/emulation/assets')],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt uses the Windows ICU API (unversioned ucnv_* exports). An unrelated
# Poppler/Conda ICU on PATH may also be named icuuc.dll, but exports ucnv_*_78.
# Never shadow the OS-provided ICU with that incompatible build dependency.
if sys.platform == 'win32':
    emulator.binaries = [
        entry for entry in emulator.binaries
        if Path(entry[0]).name.lower() != 'icuuc.dll'
    ]
emulator_pyz = PYZ(emulator.pure)

emulator_exe = EXE(
    emulator_pyz,
    emulator.scripts,
    [],
    exclude_binaries=True,
    name='GFE',
    icon=str(ROOT / 'src' / 'gapsim' / 'emulation' / 'assets' / 'gfe.ico'),
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
