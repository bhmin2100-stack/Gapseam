"""Shared packaged/source icon for GFE and its taskbar identity."""
from pathlib import Path
import sys
from PySide6.QtGui import QIcon

ICON_PATH=Path(__file__).resolve().parent/'assets/gfe.ico'

def gfe_icon():
    return QIcon(str(ICON_PATH))

def set_taskbar_identity():
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Gapseam.GFE')
