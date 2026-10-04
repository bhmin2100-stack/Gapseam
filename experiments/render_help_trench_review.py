"""Render implementation screenshots for local visual QA, not user simulation."""
import os
import argparse
import gzip
import json
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from gapsim.emulation.parameter_help_trench import load_movie
from gapsim.emulation.parameter_help_visuals import TrenchAnimation

app=QApplication.instance() or QApplication([])
parser=argparse.ArgumentParser()
parser.add_argument('--asset', type=Path)
parser.add_argument('--output', type=Path)
parser.add_argument('--keys', nargs='+', default=['cvd_overhang_pct','cvd_bottom_ratio_pct',
    'spin_redepo_emit_power','spin_incident_sigma','spin_depth_post_fill_hole_pct'])
args=parser.parse_args()
data=json.loads(gzip.decompress(args.asset.read_bytes())) if args.asset else None
# The offscreen platform has no system font database on Windows. Load a local
# Korean font for these test renders only; the native app uses normal Qt fonts.
fontfile=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/malgun.ttf'
if fontfile.exists():
    fontid=QFontDatabase.addApplicationFont(str(fontfile))
    families=QFontDatabase.applicationFontFamilies(fontid)
    if families:
        app.setFont(QFont(families[0],9))
output=args.output or Path(__file__).resolve().parent/'help-trench-review'
output.mkdir(parents=True,exist_ok=True)
widget=TrenchAnimation()
widget.resize(624,408)
for key in args.keys:
    movie=({**data['cases'][key], 'runs':[data['runs'][rid] for rid in data['cases'][key]['runs']]}
           if data else load_movie(*key.split('@')))
    if movie is None:
        raise ValueError(f'No calculated help movie for {key}')
    widget.configure(movie,key.split('@')[0],'growth')
    for view in ('shape','zoom','meaning'):
        widget.set_view(view)
        widget.phase=.9
        filename=output/f'{key}-{view}.png'
        widget.grab().save(str(filename))
        print(filename)
