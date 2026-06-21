from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchDepoResult
from gapsim.emulation.trench_depo_ui import TrenchDepoWindow

ADDON_DIR = Path(__file__).resolve().parents[1] / "addons" / "dent-analysis"


def _load_addon_module(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, ADDON_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {filename}")
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    sys.path.insert(0, str(ADDON_DIR))
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


class DentAnalysisAddonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_dent_analysis_logic_measures_depth_and_slope(self) -> None:
        dent = _load_addon_module("dent_analysis_test_logic", "dent_analysis.py")
        region = dent.DentRegion(-2.0, -8.0, 2.0, 1.0)
        slope_line = dent.DentLine(-2.0, 0.0, 2.0, 0.0)

        samples = dent.analyze_dent_frames(
            [
                [(-2.0, 0.0), (0.0, -1.0), (2.0, 0.0)],
                [(-2.0, 0.0), (0.0, -6.0), (2.0, 0.0)],
            ],
            [0, 2],
            region,
            "vertical",
            slope_line=slope_line,
            angstrom_per_cycle=5.0,
        )

        self.assertEqual(len(samples), 2)
        self.assertAlmostEqual(samples[-1].dent_depth_a or 0.0, 6.0)
        self.assertAlmostEqual(samples[-1].thickness_a, 10.0)
        self.assertIsNotNone(samples[-1].slope_delta_deg)

    def test_dent_addon_loads_as_folder_and_updates_result_meta(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0, 1, 2],
            frame_profiles=[
                [(-2.0, 0.0), (0.0, -1.0), (2.0, 0.0)],
                [(-2.0, 0.0), (0.0, -3.0), (2.0, 0.0)],
                [(-2.0, 0.0), (0.0, -6.0), (2.0, 0.0)],
            ],
            frame_voids=[[], [], []],
            final_profile=[(-2.0, 0.0), (0.0, -6.0), (2.0, 0.0)],
            meta={"cycles": 2, "growth_model": "dent_test"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addons_root = root / "addons"
            shutil.copytree(ADDON_DIR, addons_root / "dent-analysis")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GAPSIM_ADDON_ROOT": str(addons_root),
                        "GAPSIM_ADDON_STATE": str(root / "addons_state.json"),
                    },
                ),
                mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
                mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
            ):
                window = TrenchDepoWindow()

            try:
                self.assertEqual(window._addon_manager.enabled_ids(), ["dent-analysis"])
                self.assertEqual(len(window._addon_runtime_handles), 1)
                controller = window._addon_runtime_handles[0]
                controller._on_region_selected(-2.0, -8.0, 2.0, 1.0)
                controller._on_slope_line_selected(-2.0, 0.0, 2.0, 0.0)

                config = TrenchDepoConfig(
                    points=result.frame_profiles[0],
                    cycles=2,
                    angstrom_per_cycle=10.0,
                )
                with mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"):
                    window._apply_emulation_result(config, result, None, use_preview_cache=True)

                self.assertIn("dent_analysis", result.meta)
                self.assertEqual(result.meta["dent_analysis"]["addon_id"], "dent-analysis")
                self.assertEqual(result.meta["dent_analysis"]["orientation"], "vertical")
                self.assertEqual(len(result.meta["dent_analysis"]["samples"]), 3)
                self.assertAlmostEqual(result.meta["dent_analysis"]["samples"][-1]["dent_depth_a"], 6.0)
                self.assertIn("Dent 깊이 6.000 A", controller.lbl_current.text())
                self.assertIn("Dent 깊이 6.000 A", window.lbl_result_summary.text())
                self.assertIn("[Dent Analysis]", window.edit_result_parameters.toPlainText())

                idx = controller.cmb_x_axis.findData("thickness")
                controller.cmb_x_axis.setCurrentIndex(idx)
                self.assertEqual(controller.graph._x_mode, "thickness")

                item = window.addon_list.item(0)
                self.assertEqual(item.data(Qt.ItemDataRole.UserRole), "dent-analysis")
                item.setCheckState(Qt.CheckState.Unchecked)
                QApplication.processEvents()

                self.assertNotIn("dent_analysis", result.meta)
                self.assertNotIn("Dent 깊이", window.lbl_result_summary.text())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
