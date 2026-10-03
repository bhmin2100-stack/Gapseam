import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PIL import Image
from PySide6.QtWidgets import QApplication
from gapsim.emulation.app_icon import ICON_PATH, gfe_icon

def test_icon_has_native_windows_sizes_and_alpha():
    with Image.open(ICON_PATH) as icon:
        assert icon.format=='ICO'
        assert {(16,16),(32,32),(48,48),(256,256)}<=icon.ico.sizes()
        assert icon.convert('RGBA').getpixel((0,0))[3]==0

def test_qt_icon_loads_for_window_and_taskbar():
    app=QApplication.instance() or QApplication([])
    icon=gfe_icon()
    assert not icon.isNull()
    for size in (16,32,48,256):
        assert not icon.pixmap(size,size).isNull()
