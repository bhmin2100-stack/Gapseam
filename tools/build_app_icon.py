"""Render the editable GFE vector to native Windows icon sizes."""
from pathlib import Path
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'src/gapsim/emulation/assets'

def build():
    app=QApplication.instance() or QApplication([])
    renderer=QSvgRenderer(str(ASSETS/'gfe.svg'))
    assert renderer.isValid()
    image=QImage(1024,1024,QImage.Format_RGBA8888)
    image.fill(0)
    painter=QPainter(image)
    renderer.render(painter)
    painter.end()
    assert image.save(str(ASSETS/'gfe.png'))
    with Image.open(ASSETS/'gfe.png') as png:
        png.save(ASSETS/'gfe.ico',sizes=[(s,s) for s in (16,24,32,48,64,128,256)])
    print('GFE icon rendered: SVG, PNG, ICO (16–256px)')

if __name__=='__main__':build()
