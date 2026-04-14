from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gapsim.ui_qt.main_window import MainWindow


class MainWindowProjectResultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_build_project_payload_includes_saved_results(self) -> None:
        win = MainWindow()
        try:
            frames = [
                [(-10.0, 0.0), (-5.0, -20.0), (5.0, -20.0), (10.0, 0.0)],
                [(-9.0, 0.0), (-4.0, -18.0), (4.0, -18.0), (9.0, 0.0)],
            ]
            win._result_frames = [list(f) for f in frames]
            win._result_voids = [[], []]
            win._result_steps = [0, 1]
            win._result_stage_ids = [1, 1]
            win._result_stage_info = {"index": 1}
            win._result_recipe = {"run": {"case_name": "caseA", "cycles": 2}}
            win._result_meta = {"elapsed_total_s": 1.23}
            win._result_x_window = (-12.0, 12.0)
            win._result_void_mode = "legacy_cumulative"
            win._goto("results")

            payload = win._build_project_payload()
            self.assertIn("saved_results", payload)
            saved = payload["saved_results"]
            self.assertEqual(saved["frames"], frames)
            self.assertEqual(saved["steps"], [0, 1])
            self.assertEqual(saved["stage_ids"], [1, 1])
            self.assertEqual(saved["x_window"], [-12.0, 12.0])
            self.assertEqual(payload["view_state"]["panel"], "results")
        finally:
            win.close()

    def test_apply_loaded_restores_saved_results(self) -> None:
        win = MainWindow()
        try:
            payload = {
                "version": 1,
                "units": {"length": "A", "y_down_is_negative": True},
                "structure_points": [(-10.0, 0.0), (10.0, 0.0)],
                "smoothing": {"base_points": [(-10.0, 0.0), (10.0, 0.0)], "segments": 50, "iterations": 5},
                "geometry_final": [(-10.0, 0.0), (10.0, 0.0)],
                "run": {"case_name": "caseA", "cycles": 2},
                "model_base": {"base_rate": 1.0, "reparam_ds_a": 2.5},
                "phase1_switches": {},
                "saved_results": {
                    "frames": [
                        [(-10.0, 0.0), (-5.0, -20.0), (5.0, -20.0), (10.0, 0.0)],
                        [(-9.0, 0.0), (-4.0, -18.0), (4.0, -18.0), (9.0, 0.0)],
                    ],
                    "voids": [[], []],
                    "steps": [0, 1],
                    "stage_ids": [1, 1],
                    "stage_info": {"index": 1},
                    "void_mode": "legacy_cumulative",
                    "recipe": {"run": {"case_name": "caseA", "cycles": 2}},
                    "meta": {"elapsed_total_s": 1.23},
                    "x_window": [-12.0, 12.0],
                },
                "view_state": {"panel": "results"},
            }

            win._apply_loaded(payload)

            self.assertEqual(len(win._result_frames), 2)
            self.assertEqual(win._result_steps, [0, 1])
            self.assertEqual(win._result_stage_ids, [1, 1])
            self.assertEqual(win._result_x_window, (-12.0, 12.0))
            self.assertEqual(win.right_stack.currentWidget(), win.panel_results)
            self.assertTrue(win.btn_second_depo.isEnabled())
        finally:
            win.close()

    def test_second_depo_defaults_to_latest_stage_completion(self) -> None:
        win = MainWindow()
        try:
            win._result_frames = [
                [(-10.0, 0.0), (-5.0, -20.0), (5.0, -20.0), (10.0, 0.0)],
                [(-9.0, 0.0), (-4.0, -18.0), (4.0, -18.0), (9.0, 0.0)],
                [(-8.0, 0.0), (-3.0, -16.0), (3.0, -16.0), (8.0, 0.0)],
            ]
            win._result_voids = [[], [], []]
            win._result_steps = [0, 5, 10]
            win._result_stage_ids = [1, 1, 1]
            win._result_stage_info = {"index": 1}
            win._result_display_indices = [0, 2]
            win._frame_index = 0
            win._update_stage_visibility_controls()
            win.edit_case.setText("caseA")

            win._start_second_depo()

            self.assertEqual(win._continuation_seed_points, win._result_frames[2])
            self.assertEqual(len(win._continuation_base_frames or []), 3)
            self.assertEqual(win._continuation_base_steps, [0, 5, 10])
            self.assertEqual(win.edit_case.text(), "caseA_p2")
            self.assertEqual(win.right_stack.currentWidget(), win.panel_run)
        finally:
            win.close()

    def test_second_depo_can_start_from_selected_stage_completion(self) -> None:
        win = MainWindow()
        try:
            win._result_frames = [
                [(-10.0, 0.0), (-5.0, -20.0), (5.0, -20.0), (10.0, 0.0)],
                [(-9.0, 0.0), (-4.0, -18.0), (4.0, -18.0), (9.0, 0.0)],
                [(-8.0, 0.0), (-3.0, -16.0), (3.0, -16.0), (8.0, 0.0)],
                [(-7.0, 0.0), (-2.0, -14.0), (2.0, -14.0), (7.0, 0.0)],
            ]
            win._result_voids = [[], [], [], []]
            win._result_steps = [0, 5, 10, 15]
            win._result_stage_ids = [1, 1, 2, 2]
            win._result_stage_info = {"index": 2}
            win._update_stage_visibility_controls()
            idx = win.combo_next_depo_from.findData(1)
            self.assertGreaterEqual(idx, 0)
            win.combo_next_depo_from.setCurrentIndex(idx)
            win.edit_case.setText("caseA_p2")

            win._start_second_depo()

            self.assertEqual(win._continuation_seed_points, win._result_frames[1])
            self.assertEqual(len(win._continuation_base_frames or []), 2)
            self.assertEqual(win._continuation_base_stage_ids, [1, 1])
            self.assertEqual(win.edit_case.text(), "caseA_p3")
        finally:
            win.close()

    def test_sputter_only_turns_off_conformal_and_serializes_reference_mode(self) -> None:
        win = MainWindow()
        try:
            conformal = win._switch_widgets["conformal"]
            sputter = win._switch_widgets["sputter"]

            conformal["enabled"].setChecked(True)
            conformal["controls"]["base_rate"].setValue(2.5)
            sputter["enabled"].setChecked(True)
            sputter["controls"]["strength_pct"].setValue(75.0)
            sputter["controls"]["sputter_only"].setChecked(True)

            self.assertFalse(conformal["enabled"].isChecked())
            self.assertTrue(conformal["form_host"].isEnabled())

            recipe = win._build_recipe()

            self.assertFalse(recipe["model_base"]["conformal_enabled"])
            self.assertTrue(recipe["model_base"]["sputter_only"])
            self.assertEqual(recipe["model_base"]["base_rate"], 2.5)
            self.assertTrue(recipe["phase1_switches"]["sputter"]["params"]["sputter_only"])
        finally:
            win.close()

    def test_result_solid_fill_flags_apply_only_to_latest_etch_stage(self) -> None:
        win = MainWindow()
        try:
            win._result_recipe = {
                "run_stage": {"index": 2},
                "phase1_switches": {
                    "conformal": {"enabled": False, "params": {}},
                    "sputter": {"enabled": True, "params": {"sputter_only": True}},
                },
            }

            flags = win._result_solid_fill_flags([1, 1, 2, 2])

            self.assertEqual(flags, [False, False, True, True])
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
