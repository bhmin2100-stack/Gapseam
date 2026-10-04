"""Open the production window against isolated public-fixture data for UI QA."""
from pathlib import Path
import os
import tempfile

root = Path(tempfile.mkdtemp(prefix="gfe-final-ui-"))
for key, value in {"GAPSIM_DATA_ROOT":root,"GAPSIM_PARAMETER_LIBRARY":root/"presets.json",
                   "GAPSIM_STRUCTURE_LIBRARY":root/"structures.xlsx",
                   "GAPSIM_ADDON_ROOT":root/"addons","GAPSIM_ADDON_STATE":root/"addons.json"}.items():
    os.environ[key]=str(value)
os.environ.pop("QT_QPA_PLATFORM",None)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from gapsim.emulation.trench_depo_ui import TrenchDepoWindow
from gapsim.emulation.help_preferences import HelpPreferences
app=QApplication([])
app._gfe_help_preferences=HelpPreferences(QSettings(str(root/"help.ini"),QSettings.IniFormat),parent=app)
w=TrenchDepoWindow()
w.check_updates_on_startup=lambda:None
w.setWindowTitle("GFE · 최종 검증")
w._set_workflow_step("progress")
w.spin_angstrom_per_cycle.setValue(1)
w.spin_cycles.setValue(10)
w.show()
raise SystemExit(app.exec())
