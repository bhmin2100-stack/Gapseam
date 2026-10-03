"""Render implementation screenshots for local visual QA, not user simulation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from gapsim.emulation.parameter_help_trench import load_movie
from gapsim.emulation.parameter_help_visuals import TrenchAnimation

app=QApplication.instance() or QApplication([])
# The offscreen platform has no system font database on Windows. Load a local
# Korean font for these test renders only; the native app uses normal Qt fonts.
fontfile=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/malgun.ttf'
if fontfile.exists():
    fontid=QFontDatabase.addApplicationFont(str(fontfile))
    families=QFontDatabase.applicationFontFamilies(fontid)
    if families:
        app.setFont(QFont(families[0],9))
output=Path(__file__).resolve().parent/'help-trench-review'
output.mkdir(exist_ok=True)
widget=TrenchAnimation()
widget.resize(624,408)
for key in ('cvd_overhang_pct','spin_redepo_emit_power','spin_incident_sigma','spin_depth_post_fill_hole_pct'):
    widget.configure(load_movie(key),key,'growth')
    for view in ('shape','zoom','meaning'):
        widget.set_view(view)
        widget.phase=.9
        filename=output/f'{key}-{view}.png'
        widget.grab().save(str(filename))
        print(filename)
