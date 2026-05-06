# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
COMMON_HIDDEN_IMPORTS = ['pyclipper', 'PIL', 'PIL.Image', 'PIL.GifImagePlugin']

app = Analysis(
    [str(ROOT / 'src' / 'gapsim' / 'ui_qt' / 'main_window.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[],
    hiddenimports=COMMON_HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
app_pyz = PYZ(app.pure)

app_exe = EXE(
    app_pyz,
    app.scripts,
    [],
    exclude_binaries=True,
    name='GFS',
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

emulator = Analysis(
    [str(ROOT / 'src' / 'gapsim' / 'emulation' / 'trench_depo_ui.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[],
    hiddenimports=COMMON_HIDDEN_IMPORTS,
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
    name='GFS_Emulator',
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
    app_exe,
    emulator_exe,
    app.binaries,
    app.datas,
    emulator.binaries,
    emulator.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GFS',
)
