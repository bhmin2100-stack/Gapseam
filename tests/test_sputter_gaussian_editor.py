from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from gapsim.emulation.trench_depo import (
    BOWED_JAR_TRENCH_POINTS,
    ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
    TrenchDepoConfig,
    TrenchDepoResult,
    TrenchSweepResult,
)
from gapsim.emulation.trench_depo_ui import (
    DepthDepositionProfileEditor,
    IonTransmissionEditor,
    RedepositionLobeEditor,
    SputterGaussianEditor,
    TrenchDepoWindow,
)


class SputterGaussianEditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_peak_drag_updates_peak_angle_and_percent_without_changing_etch_cap(self) -> None:
        editor = SputterGaussianEditor()
        editor.resize(420, 140)
        editor.set_etch_cap_a(12.0)
        seen = []
        editor.parametersChanged.connect(lambda amount, peak, width: seen.append((amount, peak, width)))

        editor._apply_drag("peak", QPointF(editor._x_for_angle(70.0), editor._y_for_percent(25.0)))

        peak_pct, peak, width = editor.parameters()
        self.assertAlmostEqual(peak_pct, 25.0, places=6)
        self.assertAlmostEqual(peak, 70.0, places=6)
        self.assertAlmostEqual(width, 14.0, places=6)
        self.assertAlmostEqual(editor._etch_cap_a, 12.0, places=6)
        self.assertTrue(seen)

    def test_side_handle_drag_updates_width(self) -> None:
        editor = SputterGaussianEditor()
        editor.resize(420, 140)
        editor.set_parameters(8.0, 55.0, 14.0)

        editor._apply_drag("right_width", QPointF(editor._x_for_angle(75.0), editor._y_for_percent(0.0)))

        peak_pct, peak, width = editor.parameters()
        self.assertAlmostEqual(peak_pct, 8.0, places=6)
        self.assertAlmostEqual(peak, 55.0, places=6)
        self.assertAlmostEqual(width, 20.0, places=6)

    def test_editor_renders_curve(self) -> None:
        editor = SputterGaussianEditor()
        editor.resize(420, 140)
        editor.set_parameters(8.0, 55.0, 14.0)
        pixmap = QPixmap(editor.size())

        editor.render(pixmap)

        self.assertFalse(pixmap.isNull())

    def test_ion_transmission_editor_drags_start_and_drop(self) -> None:
        editor = IonTransmissionEditor()
        editor.resize(420, 170)
        seen = []
        editor.parametersChanged.connect(
            lambda start, end, drop, floor, curve: seen.append((start, end, drop, floor, curve))
        )

        editor._apply_drag("start", QPointF(editor._x_for_factor(1.0), editor._y_for_depth_pct(45.0)))
        start_depth, end_depth, drop, floor, curve = editor.parameters()
        self.assertAlmostEqual(start_depth, 45.0, places=6)
        self.assertAlmostEqual(end_depth, 100.0, places=6)
        self.assertAlmostEqual(drop, 100.0, places=6)
        self.assertAlmostEqual(floor, 0.0, places=6)
        self.assertAlmostEqual(curve, 1.0, places=6)

        editor._apply_drag("strength", QPointF(editor._x_for_factor(1.0), editor._y_for_depth_pct(82.0)))
        self.assertAlmostEqual(editor.parameters()[1], 82.0, places=6)
        self.assertAlmostEqual(editor.parameters()[2], 0.0, places=6)
        self.assertTrue(seen)

    def test_ion_transmission_editor_renders_minimap(self) -> None:
        editor = IonTransmissionEditor()
        editor.resize(420, 170)
        editor.set_parameters(20.0, 90.0, 65.0, 15.0, 1.4)
        pixmap = QPixmap(editor.size())

        editor.render(pixmap)

        self.assertFalse(pixmap.isNull())

    def test_redeposition_lobe_editor_drags_density_emit_and_distance(self) -> None:
        editor = RedepositionLobeEditor()
        editor.resize(420, 150)
        seen = []
        editor.parametersChanged.connect(lambda eff, emit, dist: seen.append((eff, emit, dist)))

        editor._apply_drag(
            "efficiency",
            QPointF(editor._amount_bar_rect().center().x(), editor._y_for_efficiency_pct(70.0)),
        )
        self.assertAlmostEqual(editor.parameters()[0], 70.0, places=6)

        source = editor._source_point()
        emit_point = editor._point_from_polar(editor._axis_angle_deg() + 30.0, editor._max_radius() * 0.85)
        editor._apply_drag("emit_right", emit_point)
        expected_emit = editor._half_angle_to_emit(30.0)
        self.assertAlmostEqual(editor.parameters()[1], expected_emit, places=6)

        axis_dx, axis_dy = editor._axis_vec()
        dist_t = 0.45
        dist_point = QPointF(
            source.x() + (axis_dx * editor._max_radius() * dist_t),
            source.y() + (axis_dy * editor._max_radius() * dist_t),
        )
        editor._apply_drag("distance", dist_point)
        self.assertAlmostEqual(editor.parameters()[2], editor._distance_from_t(dist_t), places=6)
        self.assertTrue(seen)

    def test_redeposition_lobe_editor_renders_cone(self) -> None:
        editor = RedepositionLobeEditor()
        editor.resize(420, 150)
        editor.set_parameters(45.0, 2.0, 1.5)
        pixmap = QPixmap(editor.size())

        editor.render(pixmap)

        self.assertFalse(pixmap.isNull())

    def test_depth_deposition_editor_drags_decay_floor_and_closure(self) -> None:
        editor = DepthDepositionProfileEditor()
        editor.resize(420, 170)
        seen = []
        editor.parametersChanged.connect(lambda k, power, floor, close: seen.append((k, power, floor, close)))

        editor._apply_drag("floor", QPointF(editor._x_for_ratio(0.12), editor._y_for_depth_ratio(1.0)))
        self.assertAlmostEqual(editor.parameters()[2], 12.0, places=6)

        editor._apply_drag(
            "attenuation",
            QPointF(editor._x_for_ratio(0.60), editor._y_for_depth_ratio(1.0)),
        )
        self.assertGreaterEqual(editor.parameters()[0], 0.0)
        self.assertLess(editor.parameters()[0], 0.8)

        editor._apply_drag("power", QPointF(editor._x_for_ratio(0.80), editor._y_for_depth_ratio(0.5)))
        self.assertGreaterEqual(editor.parameters()[1], 0.05)
        self.assertLessEqual(editor.parameters()[1], 8.0)

        editor._apply_drag(
            "closure",
            QPointF(editor._x_for_closure_threshold(24.0), editor._plot_rect().top() + 8.0),
        )
        self.assertAlmostEqual(editor.parameters()[3], 24.0, places=6)
        self.assertTrue(seen)

    def test_depth_deposition_editor_renders_profile_curve(self) -> None:
        editor = DepthDepositionProfileEditor()
        editor.resize(420, 170)
        editor.set_feature_geometry("line", 280.0, 4200.0, 2500.0)
        editor.set_parameters(0.55, 1.5, 7.0, 12.0)
        pixmap = QPixmap(editor.size())

        editor.render(pixmap)

        self.assertFalse(pixmap.isNull())

    def test_window_keeps_spinboxes_and_curve_editor_in_sync(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            window.set_active_emulator_number(1, run=False)
            window.spin_sputter_peak.setValue(62.0)
            self.assertAlmostEqual(window.sputter_curve_editor.parameters()[1], 62.0, places=6)

            window.spin_sputter_strength.setValue(9.5)
            self.assertAlmostEqual(window.sputter_curve_editor._etch_cap_a, 9.5, places=6)

            window.apply_sputter_curve_parameters(75.0, 48.0, 22.0)
            self.assertAlmostEqual(window.spin_sputter_strength.value(), 9.5, places=6)
            self.assertAlmostEqual(window.spin_sputter_peak_pct.value(), 75.0, places=6)
            self.assertAlmostEqual(window.spin_sputter_peak.value(), 48.0, places=6)
            self.assertAlmostEqual(window.spin_sputter_width.value(), 22.0, places=6)
            self.assertAlmostEqual(window.sputter_curve_editor.parameters()[0], 75.0, places=6)
            self.assertAlmostEqual(window.current_config().sputter_strength_a_per_cycle, 9.5, places=6)
            self.assertAlmostEqual(window.current_config().sputter_peak_pct, 75.0, places=6)
        finally:
            window.close()

    def test_emulator_two_shows_ion_transmission_minimap_controls(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            window.set_active_emulator_number(2, run=False)

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_ion_transmission())
            self.assertFalse(window._active_emulator_supports_reflected_ion())
            self.assertEqual(window.chk_sputter.text(), "Etch enabled")
            self.assertEqual(window.lbl_etch_section.text(), "Etch switch (1번 direct + 2번 modifier)")
            self.assertFalse(window.ion_map_group.isHidden())
            self.assertTrue(all(not widget.isHidden() for widget in window._ion_transmission_widgets))

            split_keys = {
                window.cmb_split_parameter.itemData(idx)
                for idx in range(window.cmb_split_parameter.count())
            }
            self.assertIn("ion_transmission_start_depth_pct", split_keys)
            self.assertIn("ion_transmission_end_depth_pct", split_keys)
            self.assertIn("ion_transmission_decay_strength_pct", split_keys)
            self.assertIn("ion_transmission_floor_pct", split_keys)
            self.assertIn("ion_transmission_curve_power", split_keys)
            self.assertIn("ion_transmission_aperture_shadow_pct", split_keys)
            self.assertIn("ion_transmission_lateral_shadow_pct", split_keys)
            self.assertIn("ion_transmission_edge_shadow_pct", split_keys)

            window.spin_ion_start_depth.setValue(32.5)
            self.assertAlmostEqual(window.ion_transmission_editor.parameters()[0], 32.5, places=6)
            window.spin_ion_end_depth.setValue(88.0)
            self.assertAlmostEqual(window.ion_transmission_editor.parameters()[1], 88.0, places=6)
            window.slider_ion_aperture_shadow.setValue(40)
            window.slider_ion_lateral_shadow.setValue(30)
            window.slider_ion_edge_shadow.setValue(20)
            self.assertEqual(window.lbl_ion_aperture_shadow_value.text(), "40%")

            window.apply_ion_transmission_editor_parameters(25.0, 80.0, 70.0, 12.5, 1.8)
            config = window.current_config()
            self.assertTrue(config.ion_transmission_enabled)
            self.assertAlmostEqual(config.ion_transmission_start_depth_pct, 25.0, places=6)
            self.assertAlmostEqual(config.ion_transmission_end_depth_pct, 80.0, places=6)
            self.assertAlmostEqual(config.ion_transmission_decay_strength_pct, 70.0, places=6)
            self.assertAlmostEqual(config.ion_transmission_floor_pct, 12.5, places=6)
            self.assertAlmostEqual(config.ion_transmission_curve_power, 1.8, places=6)
            self.assertAlmostEqual(config.ion_transmission_aperture_shadow_pct, 40.0, places=6)
            self.assertAlmostEqual(config.ion_transmission_lateral_shadow_pct, 30.0, places=6)
            self.assertAlmostEqual(config.ion_transmission_edge_shadow_pct, 20.0, places=6)

            window.chk_sputter.setChecked(False)
            config = window.current_config()
            self.assertFalse(config.sputter_enabled)
            self.assertFalse(config.ion_transmission_enabled)
            self.assertFalse(window.spin_ion_start_depth.isEnabled())
        finally:
            window.close()

    def test_emulator_three_inherits_sputter_controls_and_adds_reflected_controls(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            window.set_active_emulator_number(3, run=False)

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_reflected_ion())
            self.assertFalse(window._active_emulator_supports_ion_transmission())
            self.assertFalse(window.gaussian_group.isHidden())
            self.assertFalse(window.btn_compare_gapsim_angle.isHidden())
            self.assertEqual(window.btn_compare_gapsim_angle.text(), "Compare Emulator 01")
            self.assertEqual(window.lbl_etch_section.text(), "Etch switch (1번 direct + 3번 reflected)")
            self.assertEqual(window.lbl_sputter_section.text(), "기존 1번 Direct sputter kernel")
            self.assertEqual(window.lbl_reflected_section.text(), "3번 신규 Reflected ion")
            self.assertTrue(all(not widget.isHidden() for widget in window._sputter_widgets))
            self.assertTrue(all(not widget.isHidden() for widget in window._reflected_ion_widgets))
            self.assertTrue(all(widget.isHidden() for widget in window._ion_transmission_widgets))

            config = window.current_config()
            self.assertTrue(config.sputter_enabled)
            self.assertTrue(config.reflected_ion_enabled)
            self.assertAlmostEqual(config.sputter_strength_a_per_cycle, 4.0, places=6)
            self.assertAlmostEqual(config.sputter_peak_angle_deg, 55.0, places=6)
            self.assertAlmostEqual(config.sputter_width_deg, 14.0, places=6)
            self.assertAlmostEqual(config.reflected_ion_strength_pct, 35.0, places=6)

            split_keys = {
                window.cmb_split_parameter.itemData(idx)
                for idx in range(window.cmb_split_parameter.count())
            }
            self.assertIn("sputter_peak_angle_deg", split_keys)
            self.assertIn("sputter_width_deg", split_keys)
            self.assertIn("reflected_ion_strength_pct", split_keys)
            self.assertIn("reflected_ion_microtrench_weight", split_keys)
        finally:
            window.close()

    def test_emulator_four_is_redeposition_prep_and_compares_to_emulator_one(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            window.set_active_emulator_number(4, run=False)

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_redeposition())
            self.assertFalse(window._active_emulator_supports_ion_transmission())
            self.assertFalse(window._active_emulator_supports_reflected_ion())
            self.assertFalse(window.gaussian_group.isHidden())
            self.assertEqual(window.btn_compare_gapsim_angle.text(), "Compare Emulator 01")
            self.assertEqual(window.lbl_etch_section.text(), "Etch switch (2번 source + 4번 redepo)")
            self.assertEqual(window.lbl_sputter_section.text(), "기존 1번 Direct sputter kernel")
            self.assertTrue(all(not widget.isHidden() for widget in window._sputter_widgets))
            self.assertTrue(all(not widget.isHidden() for widget in window._redeposition_widgets))
            self.assertFalse(window.redepo_lobe_group.isHidden())
            self.assertTrue(all(widget.isHidden() for widget in window._ion_transmission_widgets))
            self.assertTrue(all(widget.isHidden() for widget in window._reflected_ion_widgets))

            config = window.current_config()
            self.assertTrue(config.sputter_enabled)
            self.assertTrue(config.redepo_enabled)
            self.assertEqual(window.cmb_redepo_source_model.count(), 1)
            self.assertEqual(config.redepo_source_model, "model2")
            self.assertAlmostEqual(config.redepo_efficiency_pct, 25.0, places=6)
            self.assertAlmostEqual(window.redepo_lobe_editor.parameters()[0], 25.0, places=6)
            window.spin_redepo_efficiency.setValue(40.0)
            self.assertAlmostEqual(window.redepo_lobe_editor.parameters()[0], 40.0, places=6)
            window.apply_redepo_lobe_parameters(55.0, 2.0, 3.0)
            self.assertAlmostEqual(window.spin_redepo_efficiency.value(), 55.0, places=6)
            self.assertAlmostEqual(window.spin_redepo_emit_power.value(), 2.0, places=6)
            self.assertAlmostEqual(window.spin_redepo_distance_power.value(), 3.0, places=6)
            self.assertFalse(config.ion_transmission_enabled)
            self.assertFalse(config.reflected_ion_enabled)
            self.assertAlmostEqual(config.sputter_strength_a_per_cycle, 4.0, places=6)

            split_keys = {
                window.cmb_split_parameter.itemData(idx)
                for idx in range(window.cmb_split_parameter.count())
            }
            self.assertIn("sputter_strength_a_per_cycle", split_keys)
            self.assertIn("sputter_peak_angle_deg", split_keys)
            self.assertIn("redepo_efficiency_pct", split_keys)
            self.assertIn("redepo_emit_power", split_keys)
            self.assertIn("redepo_distance_power", split_keys)
            self.assertNotIn("ion_transmission_decay_strength_pct", split_keys)
            self.assertNotIn("reflected_ion_strength_pct", split_keys)
        finally:
            window.close()

    def test_etch_dominant_run_uses_mixed_history_view(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0, 1],
            frame_profiles=[
                [(-10.0, 0.0), (10.0, 0.0)],
                [(-12.0, 0.0), (8.0, 0.0)],
            ],
            frame_voids=[[], []],
            final_profile=[(-12.0, 0.0), (8.0, 0.0)],
            meta={
                "cycles": 1,
                "sputter_active": True,
                "angstrom_per_cycle": 10.0,
                "sputter_strength_a_per_cycle": 12.0,
            },
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            try:
                window.set_active_emulator_number(4, run=False)
                window.run_emulation(save_artifacts=False)

                self.assertTrue(window.view._dynamic_substrate_fill)
                self.assertEqual(window.view._history_mode, "mixed_etch")
            finally:
                window.close()

    def test_emulator_five_is_depth_deposition_only_with_bowed_jar_geometry(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            window.set_active_emulator_number(5, run=False)

            self.assertFalse(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_depth_deposition())
            self.assertTrue(all(not widget.isHidden() for widget in window._depth_deposition_widgets))
            self.assertTrue(all(widget.isHidden() for widget in window._sputter_widgets))
            self.assertTrue(all(widget.isHidden() for widget in window._redeposition_widgets))
            self.assertFalse(window.depth_profile_group.isHidden())
            self.assertTrue(window.chk_depth_deposition.isChecked())
            self.assertIs(window.structure_points_group.parent(), window.structure_panel_content)
            self.assertIs(window.overlay_group.parent(), window.structure_panel_content)
            self.assertIs(window.smoothing_controls_group.parent(), window.smoothing_panel_content)
            self.assertIs(window.smoothed_points_group.parent(), window.smoothing_panel_content)
            self.assertIs(window.params_group.parent(), window.results_panel_content)
            self.assertIs(window.gaussian_group.parent(), window.results_panel_content)
            self.assertIs(window.ion_map_group.parent(), window.results_panel_content)
            self.assertIs(window.redepo_lobe_group.parent(), window.results_panel_content)
            self.assertIs(window.depth_profile_group.parent(), window.results_panel_content)
            self.assertEqual(
                [window.view_tabs.tabText(idx) for idx in range(window.view_tabs.count())],
                ["1 Structure", "2 Smoothing", "3 Result"],
            )
            self.assertEqual(
                [window.workflow_tabs.tabText(idx) for idx in range(window.workflow_tabs.count())],
                ["1 Structure", "2 Smoothing", "3 Result"],
            )

            config = window.current_config()
            self.assertEqual(tuple(config.points), BOWED_JAR_TRENCH_POINTS)
            self.assertTrue(config.deposition_depth_enabled)
            self.assertFalse(config.sputter_enabled)
            self.assertFalse(config.redepo_enabled)
            self.assertEqual(config.deposition_feature_type, "hole")
            self.assertIsNone(config.deposition_feature_length_a)
            self.assertFalse(window.spin_depth_feature_length.isEnabled())
            self.assertAlmostEqual(config.deposition_min_ratio, 0.03, places=6)
            self.assertAlmostEqual(config.deposition_post_closure_fill_pct_hole, 0.03, places=6)

            line_idx = window.cmb_depth_feature_type.findData("line")
            window.cmb_depth_feature_type.setCurrentIndex(line_idx)
            window.spin_depth_feature_length.setValue(2500.0)
            self.assertTrue(window.spin_depth_feature_length.isEnabled())
            config = window.current_config()
            self.assertEqual(config.deposition_feature_type, "line")
            self.assertAlmostEqual(config.deposition_feature_length_a, 2500.0, places=6)

            window.spin_depth_decay_k.setValue(1.1)
            self.assertAlmostEqual(window.depth_deposition_editor.parameters()[0], 1.1, places=6)
            window.apply_depth_deposition_editor_parameters(0.45, 1.7, 6.0, 16.0)
            self.assertAlmostEqual(window.spin_depth_decay_k.value(), 0.45, places=6)
            self.assertAlmostEqual(window.spin_depth_decay_power.value(), 1.7, places=6)
            self.assertAlmostEqual(window.spin_depth_min_ratio_pct.value(), 6.0, places=6)
            self.assertAlmostEqual(window.spin_depth_closure_threshold.value(), 16.0, places=6)
            config = window.current_config()
            self.assertAlmostEqual(config.deposition_depth_decay_k, 0.45, places=6)
            self.assertAlmostEqual(config.deposition_depth_decay_power, 1.7, places=6)
            self.assertAlmostEqual(config.deposition_min_ratio, 0.06, places=6)
            self.assertAlmostEqual(config.deposition_closure_threshold_a, 16.0, places=6)

            split_keys = {
                window.cmb_split_parameter.itemData(idx)
                for idx in range(window.cmb_split_parameter.count())
            }
            self.assertIn("deposition_depth_decay_k", split_keys)
            self.assertIn("deposition_post_closure_fill_pct_line", split_keys)
            self.assertNotIn("sputter_strength_a_per_cycle", split_keys)
            self.assertNotIn("redepo_efficiency_pct", split_keys)
        finally:
            window.close()

    def test_workflow_tabs_gate_structure_smoothing_and_result_controls(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            self.assertEqual(window.view_tabs.currentIndex(), 0)
            self.assertEqual(window.workflow_tabs.currentIndex(), 0)
            self.assertTrue(window.result_controls_widget.isHidden())
            self.assertIs(window.emulator_group.parent(), window.structure_panel_content)
            self.assertIs(window.smoothing_controls_group.parent(), window.smoothing_panel_content)
            self.assertIs(window.params_group.parent(), window.results_panel_content)
            self.assertIs(window.action_group.parent(), window.results_panel_content)
            self.assertIs(window.split_group.parent(), window.results_panel_content)

            window.btn_structure_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 1)
            self.assertEqual(window.workflow_tabs.currentIndex(), 1)
            self.assertTrue(window.result_controls_widget.isHidden())

            window.btn_smoothing_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 2)
            self.assertEqual(window.workflow_tabs.currentIndex(), 2)
            self.assertFalse(window.result_controls_widget.isHidden())

            window.workflow_tabs.setCurrentIndex(0)
            self.assertEqual(window.view_tabs.currentIndex(), 0)
            self.assertTrue(window.result_controls_widget.isHidden())

            window.run_emulation(save_artifacts=False)
            self.assertEqual(window.view_tabs.currentIndex(), 2)
            self.assertEqual(window.workflow_tabs.currentIndex(), 2)
            self.assertFalse(window.result_controls_widget.isHidden())
        finally:
            window.close()

    def test_structure_editor_geometry_feeds_current_config_and_mode_defaults(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            self.assertEqual(tuple(window.current_config().points), TrenchDepoConfig().points)

            window.set_active_emulator_number(2, run=False)
            self.assertEqual(tuple(window.current_config().points), ION_TRANSMISSION_STEPPED_TRENCH_POINTS)

            custom_points = [(-300.0, 0.0), (-100.0, -250.0), (100.0, -250.0), (300.0, 0.0)]
            window._set_structure_points(custom_points, fit=False)

            self.assertEqual(tuple(window.current_config().points), tuple(custom_points))
            self.assertIn("4 pts", window.lbl_geometry_source.text())
        finally:
            window.close()

    def test_structure_table_and_image_overlay_match_gapsim_flow(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            custom_points = [(-300.0, 0.0), (-100.0, -250.0), (100.0, -250.0), (300.0, 0.0)]
            window._on_structure_table_replace_points_requested(custom_points)

            self.assertEqual(tuple(window.current_config().points), tuple(custom_points))
            self.assertEqual(window.structure_points_model.rowCount(), len(custom_points))

            with tempfile.TemporaryDirectory() as tmpdir:
                image_path = Path(tmpdir) / "overlay.png"
                pixmap = QPixmap(24, 16)
                pixmap.fill()
                self.assertTrue(pixmap.save(str(image_path)))

                self.assertTrue(window._set_overlay_image(str(image_path), scale_a_per_px=5.0))
                self.assertIsNotNone(window.structure_view.get_overlay_state())
                self.assertIsNotNone(window.smoothing_view.get_overlay_state())
                self.assertTrue(window.btn_move_overlay.isEnabled())

                window.slider_overlay_opacity.setValue(60)
                self.assertAlmostEqual(window.structure_view.get_overlay_state()["opacity"], 0.6, places=6)
                self.assertAlmostEqual(window.smoothing_view.get_overlay_state()["opacity"], 0.6, places=6)
        finally:
            window.close()

    def test_structure_smoothing_can_be_used_or_bypassed_as_run_geometry(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            raw_points = [(-200.0, 0.0), (-120.0, -200.0), (0.0, -260.0), (120.0, -200.0), (200.0, 0.0)]
            window._set_structure_points(raw_points, fit=False)
            window.spin_smooth_segments.setValue(12)
            window.spin_smooth_iterations.setValue(1)

            window.apply_structure_smoothing()

            self.assertTrue(window._use_smoothed_geometry)
            self.assertGreater(len(window._smoothed_points), len(raw_points))
            self.assertEqual(tuple(window.current_config().points), tuple(window._smoothed_points))

            window.use_raw_geometry()
            self.assertEqual(tuple(window.current_config().points), tuple(raw_points))
        finally:
            window.close()

    def test_window_starts_on_emulator_zero_with_only_existing_toggles(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            self.assertEqual(window.active_emulator_number(), 0)
            self.assertEqual(window._emulator_numbers, [0, 1, 2, 3, 4, 5, 6])
            self.assertEqual(sorted(window._emulator_buttons), [0, 1, 2, 3, 4, 5, 6])
            self.assertTrue(window._emulator_buttons[0].isChecked())
            self.assertFalse(window._emulator_buttons[1].isChecked())
            self.assertFalse(window._emulator_buttons[2].isChecked())
            self.assertFalse(window._emulator_buttons[3].isChecked())
            self.assertFalse(window._emulator_buttons[4].isChecked())
            self.assertFalse(window._emulator_buttons[5].isChecked())
            self.assertFalse(window._emulator_buttons[6].isChecked())
        finally:
            window.close()

    def test_window_can_create_next_emulator_toggle(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.ensure_emulator_research_slot") as ensure_slot,
            mock.patch("gapsim.emulation.trench_depo_ui.save_created_emulator_numbers") as save_numbers,
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

            try:
                window.create_new_emulator()

                self.assertEqual(window.active_emulator_number(), 7)
                self.assertEqual(window._emulator_numbers, [0, 1, 2, 3, 4, 5, 6, 7])
                self.assertTrue(window._emulator_buttons[7].isChecked())
                ensure_slot.assert_called_once_with(7)
                save_numbers.assert_called_once_with([0, 1, 2, 3, 4, 5, 6, 7])
            finally:
                window.close()

    def test_emulator_toggle_does_not_run_preview_until_run_button(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result) as run_depo,
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

            try:
                self.assertEqual(run_depo.call_count, 0)

                window.set_active_emulator_number(1)

                self.assertEqual(window.active_emulator_number(), 1)
                self.assertEqual(run_depo.call_count, 0)
                self.assertFalse(window._emulator_run_timer.isActive())

                window.set_active_emulator_number(0)

                self.assertEqual(window.active_emulator_number(), 0)
                self.assertEqual(run_depo.call_count, 0)

                window.run_emulation(save_artifacts=False)

                self.assertEqual(run_depo.call_count, 1)
            finally:
                window._emulator_run_timer.stop()
                window.close()

    def test_window_elides_long_saved_run_name(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            run_dir = Path("/tmp/20260504_123456_트렌치증착_999사이클_123.456A_아주_긴_요청사항_이름_패널을_밀어내지_않도록_줄임")
            window._set_run_dir_label(run_dir)

            self.assertIn("...", window.lbl_run_dir.text())
            self.assertNotIn(str(run_dir), window.lbl_run_dir.text())
            self.assertEqual(window.lbl_run_dir.toolTip(), str(run_dir.resolve()))
        finally:
            window.close()

    def test_loading_replay_opens_saved_split_group(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        split_cases = [
            TrenchSweepResult("angstrom_per_cycle", "Depo A/CYC", 5.0, TrenchDepoConfig(cycles=0), result),
            TrenchSweepResult("angstrom_per_cycle", "Depo A/CYC", 10.0, TrenchDepoConfig(cycles=0), result),
        ]
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.load_trench_depo_run", return_value=(TrenchDepoConfig(cycles=0), result, "note")),
            mock.patch("gapsim.emulation.trench_depo_ui.load_trench_depo_split_group", return_value=split_cases),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            try:
                window.load_replay_json("/tmp/replay.json")

                self.assertEqual(len(window._split_windows), 1)
                self.assertEqual(len(window._split_windows[0]._cases), 2)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
