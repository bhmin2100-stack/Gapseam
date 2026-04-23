from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from gapsim.prediction import auto_anchor_spec, build_switch_state_from_prediction, recipe_with_switch_state
from gapsim.ui_qt.main_window import MainWindow
from gapsim.ui_qt.prediction_worker import ParameterPredictionWorker
from gapsim.ui_qt.switch_schema import default_switch_state


class MainWindowProjectResultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _wait_for_result_load(self, win: MainWindow, timeout_s: float = 3.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self._app.processEvents()
            if win._result_frames:
                return
            if (not win._result_loading) and win._result_loader_thread is None:
                break
            time.sleep(0.01)
        self.fail("Timed out waiting for results to load")

    def test_build_project_payload_prefers_last_run_dir_reference(self) -> None:
        win = MainWindow()
        try:
            with TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                project_dir = root / "project"
                run_dir = root / "runs" / "20260419_213854_caseA"
                project_dir.mkdir(parents=True, exist_ok=True)
                run_dir.mkdir(parents=True, exist_ok=True)

                win._current_path = project_dir / "SAVE.json"
                win._last_run_dir = run_dir
                win.right_stack.setCurrentWidget(win.panel_results)

                payload = win._build_project_payload()

                self.assertNotIn("saved_results", payload)
                self.assertEqual(payload["last_run_dir"], os.path.relpath(run_dir, project_dir))
                self.assertEqual(payload["view_state"]["panel"], "results")
        finally:
            win.close()

    def test_apply_loaded_restores_results_from_last_run_dir(self) -> None:
        win = MainWindow()
        try:
            with TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                project_dir = root / "project"
                project_dir.mkdir(parents=True, exist_ok=True)
                project_path = project_dir / "SAVE.json"
                run_dir = root / "runs" / "20260419_213854_caseA"
                run_dir.mkdir(parents=True, exist_ok=True)

                profiles = {
                    "version": 1,
                    "stage": {"index": 1, "continued_from": None},
                    "frame_steps": [0, 1],
                    "frame_profiles": [
                        [(-10.0, 0.0), (-5.0, -20.0), (5.0, -20.0), (10.0, 0.0)],
                        [(-9.0, 0.0), (-4.0, -18.0), (4.0, -18.0), (9.0, 0.0)],
                    ],
                    "frame_voids": [[], []],
                    "frame_voids_mode": "current",
                    "frame_stage_ids": [1, 1],
                    "x_window": [-12.0, 12.0],
                }
                recipe = {"run": {"case_name": "caseA", "cycles": 2}}
                meta = {"elapsed_total_s": 1.23}
                (run_dir / "profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
                (run_dir / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
                (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

                payload = {
                    "version": 1,
                    "units": {"length": "A", "y_down_is_negative": True},
                    "structure_points": [(-10.0, 0.0), (10.0, 0.0)],
                    "smoothing": {"base_points": [(-10.0, 0.0), (10.0, 0.0)], "segments": 50, "iterations": 5},
                    "geometry_final": [(-10.0, 0.0), (10.0, 0.0)],
                    "run": {"case_name": "caseA", "cycles": 2},
                    "model_base": {"base_rate": 1.0, "reparam_ds_a": 2.5},
                    "phase1_switches": {},
                    "last_run_dir": os.path.relpath(run_dir, project_dir),
                    "view_state": {"panel": "results"},
                }

                win._current_path = project_path
                win._apply_loaded(payload)
                self._wait_for_result_load(win)

                self.assertEqual(win._last_run_dir, run_dir.resolve())
                self.assertEqual(len(win._result_frames), 2)
                self.assertEqual(win._result_steps, [0, 1])
                self.assertEqual(win._result_stage_ids, [1, 1])
                self.assertEqual(win._result_x_window, (-12.0, 12.0))
                self.assertEqual(win.right_stack.currentWidget(), win.panel_results)
                self.assertTrue(win.btn_open_dir.isEnabled())
                self.assertTrue(win.btn_second_depo.isEnabled())
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

    def test_apply_prediction_result_updates_run_switch_ui(self) -> None:
        win = MainWindow()
        try:
            predicted = win._collect_switch_state()
            predicted["conformal"]["enabled"] = True
            predicted["conformal"]["params"]["base_rate"] = 3.25
            predicted["conformal"]["params"]["n_steps"] = 420
            predicted["attenuation"]["enabled"] = True
            predicted["attenuation"]["params"]["source_onset_width_a"] = 180.0
            predicted["attenuation"]["params"]["source_decay_pct"] = 62.0
            predicted["attenuation"]["params"]["source_distance_decay_pct"] = 18.0
            predicted["sputter"]["enabled"] = True
            predicted["sputter"]["params"]["strength_pct"] = 88.0
            predicted["redepo"]["enabled"] = True
            predicted["redepo"]["params"]["efficiency_pct"] = 37.0
            predicted["redepo"]["params"]["lobe_sigma_deg"] = 24.0
            predicted["inhibition"]["enabled"] = True
            predicted["inhibition"]["params"]["i_max"] = 0.45
            predicted["inhibition"]["params"]["lambda_a"] = 880.0

            win._apply_prediction_result(
                {
                    "loss": 0.1234,
                    "predicted_switch_state": predicted,
                },
                announce=True,
            )

            applied = win._collect_switch_state()

            self.assertAlmostEqual(applied["conformal"]["params"]["base_rate"], 3.25)
            self.assertEqual(applied["conformal"]["params"]["n_steps"], 420)
            self.assertTrue(applied["attenuation"]["enabled"])
            self.assertAlmostEqual(applied["attenuation"]["params"]["source_onset_width_a"], 180.0)
            self.assertTrue(applied["sputter"]["enabled"])
            self.assertAlmostEqual(applied["sputter"]["params"]["strength_pct"], 88.0)
            self.assertTrue(applied["redepo"]["enabled"])
            self.assertAlmostEqual(applied["redepo"]["params"]["efficiency_pct"], 37.0)
            self.assertAlmostEqual(applied["inhibition"]["params"]["lambda_a"], 880.0)
            self.assertEqual(win.lbl_status.text(), win._prediction_text("complete_loss", loss=0.1234))
        finally:
            win.close()

    def test_prediction_result_requires_confirmation_before_applying(self) -> None:
        win = MainWindow()
        try:
            before = win._collect_switch_state()
            predicted = win._collect_switch_state()
            predicted["conformal"]["params"]["base_rate"] = 6.75
            predicted["conformal"]["params"]["n_steps"] = 540
            predicted["attenuation"]["enabled"] = True
            predicted["attenuation"]["params"]["source_onset_width_a"] = 140.0

            with mock.patch.object(win, "_confirm_prediction_result", return_value=False):
                win._on_prediction_finished(
                    {
                        "loss": 0.321,
                        "evaluated_candidates": 7,
                        "predicted_switch_state": predicted,
                    }
                )

            after = win._collect_switch_state()

            self.assertAlmostEqual(
                after["conformal"]["params"]["base_rate"],
                before["conformal"]["params"]["base_rate"],
            )
            self.assertEqual(after["conformal"]["params"]["n_steps"], before["conformal"]["params"]["n_steps"])
            self.assertFalse(after["attenuation"]["enabled"])
            self.assertFalse(bool(win._prediction_result.get("applied", True)))
            self.assertEqual(win.lbl_status.text(), win._prediction_text("not_applied"))
        finally:
            win.close()

    def test_prediction_confirmation_dialog_opens(self) -> None:
        win = MainWindow()
        try:
            predicted = win._collect_switch_state()
            predicted["conformal"]["params"]["n_steps"] = 321
            predicted["sputter"]["enabled"] = True
            predicted["sputter"]["params"]["strength_pct"] = 45.0

            with mock.patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
                accepted = win._confirm_prediction_result(
                    {
                        "loss": 0.2,
                        "evaluated_candidates": 7,
                        "predicted_switch_state": predicted,
                    }
                )

            self.assertFalse(accepted)
        finally:
            win.close()

    def test_prediction_worker_keeps_base_rate_fixed_while_sampling_cycles(self) -> None:
        base_switch_state = default_switch_state()
        base_switch_state["conformal"]["params"]["base_rate"] = 2.5
        base_switch_state["conformal"]["params"]["n_steps"] = 240

        recipe = {
            "run": {"case_name": "caseA", "cycles": 240},
            "model_base": {"base_rate": 2.5, "reparam_ds_a": 2.5},
            "phase1_switches": base_switch_state,
        }
        pre_points = [(-120.0, 0.0), (-40.0, -220.0), (40.0, -220.0), (120.0, 0.0)]
        post_points = [(-120.0, 6.0), (-44.0, -176.0), (44.0, -176.0), (120.0, 6.0)]

        worker = ParameterPredictionWorker(
            pre_points=pre_points,
            post_points=post_points,
            anchor_spec=auto_anchor_spec(pre_points, post_points, division_count=5),
            base_recipe=recipe,
            base_switch_state=base_switch_state,
        )

        base_params = worker._base_params()
        bounds = worker._parameter_bounds(base_params)
        candidate = worker._sample_candidate(bounds, fixed_params={"base_rate": base_params["base_rate"]})
        preview_params, preview_dt = worker._preview_params(candidate)

        self.assertNotIn("base_rate", bounds)
        self.assertIn("sputter_strength_pct", bounds)
        self.assertIn("redepo_efficiency_pct", bounds)
        self.assertIn("redepo_lobe_sigma_deg", bounds)
        self.assertAlmostEqual(candidate["base_rate"], 2.5)
        self.assertAlmostEqual(preview_params["base_rate"], 2.5)
        self.assertGreaterEqual(preview_dt, 1.0)
        self.assertIn("n_steps", candidate)

    def test_prediction_switch_state_and_recipe_include_sputter_and_redepo(self) -> None:
        base_state = default_switch_state()
        base_state["conformal"]["params"]["base_rate"] = 2.5
        base_state["conformal"]["params"]["n_steps"] = 240
        base_state["sputter"]["params"]["peak_angle_deg"] = 55.0
        base_state["sputter"]["params"]["angle_sigma_deg"] = 15.0
        base_state["sputter"]["params"]["depth_decay_length_a"] = 1000.0
        base_state["sputter"]["params"]["vis_exponent"] = 1.0
        recipe = {
            "run": {"case_name": "caseA", "cycles": 240},
            "model_base": {
                "base_rate": 2.5,
                "reparam_ds_a": 2.5,
                "sputter_enabled": False,
                "sputter_only": False,
                "sputter_strength_pct": 0.0,
                "sputter_peak_angle_deg": 55.0,
                "sputter_angle_sigma_deg": 15.0,
                "sputter_depth_decay_length_a": 1000.0,
                "sputter_sky_vis_exponent": 1.0,
                "redepo_enabled": False,
                "redepo_efficiency_pct": 0.0,
                "redepo_lobe_sigma_deg": 20.0,
            },
            "phase1_switches": base_state,
        }
        params = {
            "base_rate": 2.5,
            "n_steps": 320.0,
            "source_onset_width_a": 80.0,
            "source_decay_pct": 45.0,
            "source_distance_decay_pct": 10.0,
            "sputter_strength_pct": 95.0,
            "redepo_efficiency_pct": 42.0,
            "redepo_lobe_sigma_deg": 27.0,
            "i_max": 0.2,
            "lambda_a": 640.0,
        }

        switch_state = build_switch_state_from_prediction(base_state, params)
        updated_recipe = recipe_with_switch_state(recipe, switch_state)
        model_base = updated_recipe["model_base"]

        self.assertTrue(switch_state["sputter"]["enabled"])
        self.assertAlmostEqual(switch_state["sputter"]["params"]["strength_pct"], 95.0)
        self.assertTrue(switch_state["redepo"]["enabled"])
        self.assertAlmostEqual(switch_state["redepo"]["params"]["efficiency_pct"], 42.0)
        self.assertAlmostEqual(switch_state["redepo"]["params"]["lobe_sigma_deg"], 27.0)
        self.assertTrue(model_base["sputter_enabled"])
        self.assertAlmostEqual(model_base["sputter_strength_pct"], 95.0)
        self.assertTrue(model_base["redepo_enabled"])
        self.assertAlmostEqual(model_base["redepo_efficiency_pct"], 42.0)
        self.assertAlmostEqual(model_base["redepo_lobe_sigma_deg"], 27.0)

    def test_prediction_initial_post_points_prefers_raw_structure_over_smoothed_pre(self) -> None:
        win = MainWindow()
        try:
            pre_raw = [(-120.0, 0.0), (-40.0, -220.0), (40.0, -220.0), (120.0, 0.0)]
            pre_smooth = [
                (-120.0, 0.0),
                (-80.0, -70.0),
                (-40.0, -180.0),
                (0.0, -220.0),
                (40.0, -180.0),
                (80.0, -70.0),
                (120.0, 0.0),
            ]

            win._set_structure_points(pre_raw, mark_origin=True, clear_undo=True)
            win.smoothing.set_base_points(pre_raw)
            win.smoothing.state.last_result = pre_smooth

            self.assertEqual(win._active_profile_points(), pre_smooth)
            self.assertEqual(win._prediction_initial_post_points(), pre_raw)
        finally:
            win.close()

    def test_parameter_prediction_payload_roundtrip_restores_post_state(self) -> None:
        win = MainWindow()
        win2 = MainWindow()
        try:
            pre_points = [(-120.0, 0.0), (-40.0, -220.0), (40.0, -220.0), (120.0, 0.0)]
            post_raw = [(-120.0, 8.0), (-44.0, -180.0), (44.0, -180.0), (120.0, 8.0)]
            post_smooth = [(-120.0, 10.0), (-48.0, -170.0), (48.0, -170.0), (120.0, 10.0)]

            win._set_structure_points(pre_points, mark_origin=True, clear_undo=True)
            win._prediction_post_points_raw = post_raw
            win._prediction_post_points_smooth = post_smooth
            win._prediction_anchor_spec = auto_anchor_spec(pre_points, post_smooth, division_count=5)

            predicted = win._collect_switch_state()
            predicted["conformal"]["params"]["base_rate"] = 4.5
            predicted["conformal"]["params"]["n_steps"] = 360
            predicted["attenuation"]["enabled"] = True
            predicted["attenuation"]["params"]["source_onset_width_a"] = 90.0
            predicted["attenuation"]["params"]["source_decay_pct"] = 55.0
            win._prediction_result = {
                "loss": 0.456,
                "predicted_switch_state": predicted,
            }

            payload = win._build_project_payload()

            self.assertIn("parameter_prediction", payload)
            self.assertEqual(payload["parameter_prediction"]["post_points_raw"], [[-120.0, 8.0], [-44.0, -180.0], [44.0, -180.0], [120.0, 8.0]])

            win2._apply_loaded(payload)
            restored = win2._collect_switch_state()

            self.assertEqual(win2.points_model.get_points(), pre_points)
            self.assertEqual(win2._prediction_post_points_raw, post_raw)
            self.assertEqual(win2._prediction_post_points_smooth, post_smooth)
            self.assertEqual(win2._prediction_anchor_spec["division_count"], 5)
            self.assertNotEqual(win2.points_model.get_points(), win2._prediction_post_points_raw)
            self.assertAlmostEqual(restored["conformal"]["params"]["base_rate"], 4.5)
            self.assertEqual(restored["conformal"]["params"]["n_steps"], 360)
            self.assertTrue(restored["attenuation"]["enabled"])
            self.assertAlmostEqual(restored["attenuation"]["params"]["source_onset_width_a"], 90.0)
        finally:
            win.close()
            win2.close()

    def test_parameter_prediction_payload_roundtrip_respects_unapplied_flag(self) -> None:
        win = MainWindow()
        win2 = MainWindow()
        try:
            pre_points = [(-120.0, 0.0), (-40.0, -220.0), (40.0, -220.0), (120.0, 0.0)]
            post_smooth = [(-120.0, 10.0), (-48.0, -170.0), (48.0, -170.0), (120.0, 10.0)]

            win._set_structure_points(pre_points, mark_origin=True, clear_undo=True)
            win._prediction_post_points_smooth = post_smooth
            win._prediction_anchor_spec = auto_anchor_spec(pre_points, post_smooth, division_count=5)

            predicted = win._collect_switch_state()
            predicted["conformal"]["params"]["base_rate"] = 4.5
            predicted["conformal"]["params"]["n_steps"] = 360
            win._prediction_result = {
                "loss": 0.456,
                "applied": False,
                "predicted_switch_state": predicted,
            }

            payload = win._build_project_payload()
            win2._apply_loaded(payload)
            restored = win2._collect_switch_state()

            self.assertFalse(bool(win2._prediction_result.get("applied", True)))
            self.assertAlmostEqual(restored["conformal"]["params"]["base_rate"], 1.0)
            self.assertEqual(restored["conformal"]["params"]["n_steps"], 200)
        finally:
            win.close()
            win2.close()


if __name__ == "__main__":
    unittest.main()
