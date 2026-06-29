from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_STRUCTURE_LIBRARY_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault(
    "GAPSIM_STRUCTURE_LIBRARY",
    str(Path(_STRUCTURE_LIBRARY_TMP.name) / "structures.xlsx"),
)
_ADDON_LIBRARY_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("GAPSIM_ADDON_ROOT", str(Path(_ADDON_LIBRARY_TMP.name) / "addons"))
os.environ.setdefault("GAPSIM_ADDON_STATE", str(Path(_ADDON_LIBRARY_TMP.name) / "addons_state.json"))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from gapsim.emulation.research_registry import DEFAULT_CREATED_EMULATOR_NUMBERS
from gapsim.emulation.trench_depo import (
    BOWED_JAR_TRENCH_POINTS,
    ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
    TrenchDepoConfig,
    TrenchDepoResult,
    TrenchSweepResult,
)
from gapsim.emulation.trench_depo_ui import (
    DepthDepositionProfileEditor,
    InhibitionProfileEditor,
    IonTransmissionEditor,
    RedepositionLobeEditor,
    SplitTestWindow,
    SputterGaussianEditor,
    TrenchDepoWindow,
    _depth_deposition_formula_text,
    _map_structure_points_to_rect,
)
from gapsim.ui_qt.views.structure_view import StructureView


EXPECTED_EMULATOR_NUMBERS = list(DEFAULT_CREATED_EMULATOR_NUMBERS)


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

    def test_structure_background_mapping_fills_plot_rect(self) -> None:
        rect = QRectF(44.0, 30.0, 320.0, 150.0)
        mapped = _map_structure_points_to_rect(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, rect)

        self.assertGreaterEqual(len(mapped), 2)
        self.assertAlmostEqual(min(point.x() for point in mapped), rect.left(), places=6)
        self.assertAlmostEqual(max(point.x() for point in mapped), rect.right(), places=6)
        self.assertAlmostEqual(min(point.y() for point in mapped), rect.top(), places=6)
        self.assertAlmostEqual(max(point.y() for point in mapped), rect.bottom(), places=6)

    def test_ion_transmission_editor_renders_full_structure_background(self) -> None:
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

    def test_redeposition_lobe_editor_reflection_mode_controls_spread_and_bias(self) -> None:
        editor = RedepositionLobeEditor()
        editor.resize(440, 180)
        seen = []
        editor.parametersChanged.connect(lambda eff, spread, bias: seen.append((eff, spread, bias)))
        editor.set_mode("reflection")
        editor.set_parameters(35.0, 22.0, -40.0)

        self.assertEqual(editor.parameters(), (35.0, 22.0, -40.0))

        source = editor._source_point()
        spread_point = editor._point_from_polar(editor._axis_angle_deg() + 42.0, editor._max_radius() * 0.85)
        editor._apply_drag("emit_right", spread_point)
        self.assertAlmostEqual(editor.parameters()[1], 42.0, places=6)

        bias_point = editor._point_from_polar(editor._specular_axis_angle_deg(), editor._max_radius() * 0.58)
        editor._apply_drag("distance", bias_point)
        self.assertAlmostEqual(editor.parameters()[2], 100.0, places=6)
        self.assertTrue(seen)

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

    def test_depth_deposition_editor_toggles_depo_rate_and_attenuation_display(self) -> None:
        editor = DepthDepositionProfileEditor()
        editor.resize(420, 170)

        self.assertEqual(editor.display_mode(), "depo_rate")
        self.assertAlmostEqual(editor._deposition_ratio_for_x(editor._x_for_ratio(0.25)), 0.25, places=6)

        editor.set_display_mode("attenuation")

        self.assertEqual(editor.display_mode(), "attenuation")
        self.assertAlmostEqual(editor._deposition_ratio_for_x(editor._x_for_ratio(0.25)), 0.75, places=6)
        self.assertAlmostEqual(editor._display_value_for_ratio(0.75), 0.25, places=6)

    def test_depth_deposition_editor_renders_profile_curve_with_structure_background(self) -> None:
        editor = DepthDepositionProfileEditor()
        editor.resize(420, 170)
        editor.set_feature_geometry("line", 280.0, 4200.0, 2500.0)
        editor.set_parameters(0.55, 1.5, 7.0, 12.0)
        editor.set_display_mode("attenuation")
        pixmap = QPixmap(editor.size())

        editor.render(pixmap)

        self.assertFalse(pixmap.isNull())

    def test_depth_deposition_formula_text_switches_between_rate_and_attenuation(self) -> None:
        rate_formula = _depth_deposition_formula_text(
            display_mode="depo_rate",
            base_rate_a_per_cycle=12.5,
            attenuation_model="exponential",
            depth_decay_k=0.55,
            depth_decay_power=1.4,
            min_ratio_pct=5.0,
            feature_type="hole",
            feature_width_a=240.0,
            feature_length_a=None,
        )
        attenuation_formula = _depth_deposition_formula_text(
            display_mode="attenuation",
            base_rate_a_per_cycle=12.5,
            attenuation_model="exponential",
            depth_decay_k=0.55,
            depth_decay_power=1.4,
            min_ratio_pct=5.0,
            feature_type="line",
            feature_width_a=240.0,
            feature_length_a=2500.0,
        )

        self.assertIn("Dep rate식", rate_formula)
        self.assertIn("dep_rate(z)=D0*R(z)", rate_formula)
        self.assertIn("g(z)=z/W", rate_formula)
        self.assertIn("D0=12.500 A/CYC", rate_formula)
        self.assertIn("감쇄식", attenuation_formula)
        self.assertIn("depletion(z)=1-R(z)", attenuation_formula)
        self.assertIn("g(z)=z*(W+L)/(2*W*L)", attenuation_formula)

    def test_inhibition_profile_editor_drags_growth_curve_handles(self) -> None:
        editor = InhibitionProfileEditor()
        editor.resize(460, 210)
        editor.set_feature_depth(4000.0)
        editor.set_parameters(80.0, 1000.0, 1.1, 5.0, 20.0, 30.0)
        seen = []
        editor.parametersChanged.connect(
            lambda strength, penetration, power, floor, boost, recomb: seen.append(
                (strength, penetration, power, floor, boost, recomb)
            )
        )

        editor._apply_drag("strength", QPointF(editor._x_for_ratio(0.35), editor._y_for_depth_ratio(0.0)))
        self.assertAlmostEqual(editor.parameters()[0], 65.0, places=6)

        editor._apply_drag("penetration", QPointF(editor._x_for_ratio(0.70), editor._y_for_depth_ratio(0.50)))
        self.assertAlmostEqual(editor.parameters()[1], 2000.0, places=6)

        editor._apply_drag("floor", QPointF(editor._x_for_ratio(0.15), editor._y_for_depth_ratio(1.0)))
        self.assertAlmostEqual(editor.parameters()[3], 15.0, places=6)

        editor._apply_drag("boost", QPointF(editor._x_for_ratio(1.20), editor._y_for_depth_ratio(1.0)))
        self.assertGreater(editor.parameters()[4], 0.0)

        editor._apply_drag("recombination", QPointF(editor._x_for_ratio(0.72), editor._y_for_depth_ratio(0.72)))
        self.assertGreaterEqual(editor.parameters()[5], 0.0)
        self.assertLessEqual(editor.parameters()[5], 100.0)
        self.assertTrue(seen)

    def test_inhibition_profile_editor_renders_growth_ratio_curve(self) -> None:
        editor = InhibitionProfileEditor()
        editor.resize(460, 210)
        editor.set_structure_points(BOWED_JAR_TRENCH_POINTS)
        editor.set_feature_depth(4700.0)
        editor.set_parameters(85.0, 1100.0, 1.2, 8.0, 20.0, 35.0)
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
            window.set_active_emulator_number(2, run=False)
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

    def test_window_keeps_inhibition_spinboxes_and_visual_editor_in_sync(self) -> None:
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
            window.set_active_emulator_number(0, run=False)
            window.chk_depth_deposition.setChecked(True)
            window.chk_inhibition_deposition.setChecked(True)
            window.sync_etch_control_availability()
            self.assertFalse(window.inhibition_profile_group.isHidden())
            self.assertFalse(window.depth_profile_group.isHidden())
            self.assertTrue(window.chk_depth_deposition.isChecked())
            self.assertTrue(window.chk_inhibition_deposition.isChecked())

            window.spin_inhibition_strength.setValue(64.0)
            self.assertAlmostEqual(window.inhibition_profile_editor.parameters()[0], 64.0, places=6)

            window.apply_inhibition_profile_parameters(42.0, 1800.0, 1.8, 11.0, 33.0, 27.0)
            self.assertAlmostEqual(window.spin_inhibition_strength.value(), 42.0, places=6)
            self.assertAlmostEqual(window.spin_inhibition_penetration.value(), 1800.0, places=6)
            self.assertAlmostEqual(window.spin_inhibition_decay_power.value(), 1.8, places=6)
            self.assertAlmostEqual(window.spin_inhibition_min_growth.value(), 11.0, places=6)
            self.assertAlmostEqual(window.spin_inhibition_bottom_boost.value(), 33.0, places=6)
            self.assertAlmostEqual(window.spin_inhibition_recombination.value(), 27.0, places=6)

            config = window.current_config()
            self.assertTrue(config.inhibition_enabled)
            self.assertTrue(config.deposition_depth_enabled)
            self.assertAlmostEqual(config.inhibition_strength_pct, 42.0, places=6)
            self.assertAlmostEqual(config.inhibition_penetration_depth_a, 1800.0, places=6)
            self.assertAlmostEqual(config.inhibition_min_growth_ratio, 0.11, places=6)

            window.chk_inhibition_deposition.setChecked(False)
            window.sync_etch_control_availability()
            self.assertTrue(window.inhibition_profile_group.isHidden())
            self.assertTrue(window.chk_depth_deposition.isChecked())
            self.assertFalse(window.depth_profile_group.isHidden())
            window.chk_inhibition_deposition.setChecked(True)
            window.sync_etch_control_availability()
            self.assertFalse(window.inhibition_profile_group.isHidden())
            self.assertAlmostEqual(window.spin_inhibition_strength.value(), 42.0, places=6)
        finally:
            window.close()

    def test_emulator_switch_preserves_shared_numeric_parameters(self) -> None:
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
            window.set_active_emulator_number(0, run=False)
            window.spin_cycles.setValue(37)
            window.spin_angstrom_per_cycle.setValue(12.25)
            window.spin_sputter_strength.setValue(8.75)
            window.spin_sputter_peak_pct.setValue(72.0)
            window.spin_sputter_peak.setValue(61.0)
            window.spin_sputter_width.setValue(19.0)
            window.spin_sputter_smoothing.setValue(52.5)

            window.set_active_emulator_number(0, run=False)

            self.assertEqual(window.spin_cycles.value(), 37)
            self.assertAlmostEqual(window.spin_angstrom_per_cycle.value(), 12.25, places=6)
            self.assertAlmostEqual(window.spin_sputter_strength.value(), 8.75, places=6)
            self.assertAlmostEqual(window.spin_sputter_peak_pct.value(), 72.0, places=6)
            self.assertAlmostEqual(window.spin_sputter_peak.value(), 61.0, places=6)
            self.assertAlmostEqual(window.spin_sputter_width.value(), 19.0, places=6)
            self.assertAlmostEqual(window.spin_sputter_smoothing.value(), 52.5, places=6)

            window.spin_ion_start_depth.setValue(31.5)
            window.spin_ion_curve_power.setValue(1.75)
            window.spin_redepo_efficiency.setValue(43.0)
            window.spin_depth_decay_k.setValue(0.72)
            window.spin_depth_min_ratio_pct.setValue(11.0)

            window.set_active_emulator_number(0, run=False)

            self.assertEqual(window.spin_cycles.value(), 37)
            self.assertAlmostEqual(window.spin_angstrom_per_cycle.value(), 12.25, places=6)
            self.assertAlmostEqual(window.spin_sputter_strength.value(), 8.75, places=6)
            self.assertAlmostEqual(window.spin_ion_start_depth.value(), 31.5, places=6)
            self.assertAlmostEqual(window.spin_ion_curve_power.value(), 1.75, places=6)
            self.assertAlmostEqual(window.spin_redepo_efficiency.value(), 43.0, places=6)
            self.assertAlmostEqual(window.spin_depth_decay_k.value(), 0.72, places=6)
            self.assertAlmostEqual(window.spin_depth_min_ratio_pct.value(), 11.0, places=6)
            self.assertFalse(window.chk_sputter.isChecked())
            self.assertFalse(window.chk_ion_transmission.isChecked())
            self.assertFalse(window.chk_redepo.isChecked())
            self.assertFalse(window.chk_depth_deposition.isChecked())
            self.assertFalse(window.chk_reflected_ion.isChecked())
        finally:
            window.close()

    def test_quality_mode_controls_reparam_ds(self) -> None:
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
            self.assertIn("보통", window.cmb_quality_mode.currentText())
            self.assertAlmostEqual(window.current_config().reparam_ds_a, 10.0, places=6)

            fast_idx = window.cmb_quality_mode.findText("빠름 (20 A)")
            window.cmb_quality_mode.setCurrentIndex(fast_idx)
            self.assertAlmostEqual(window.spin_reparam_ds.value(), 20.0, places=6)
            self.assertAlmostEqual(window.current_config().reparam_ds_a, 20.0, places=6)

            window.spin_reparam_ds.setValue(7.5)
            self.assertEqual(window.cmb_quality_mode.currentText(), "사용자")
            self.assertAlmostEqual(window.current_config().reparam_ds_a, 7.5, places=6)

            window._apply_parameter_config_values({"reparam_ds_a": 5.0})
            self.assertIn("정밀", window.cmb_quality_mode.currentText())
            self.assertAlmostEqual(window.current_config().reparam_ds_a, 5.0, places=6)
        finally:
            window.close()

    def test_value_control_wheel_is_ignored_until_control_has_focus(self) -> None:
        class FakeWheelEvent:
            def __init__(self) -> None:
                self.ignored = False

            def type(self):
                return QEvent.Type.Wheel

            def ignore(self) -> None:
                self.ignored = True

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
            window.clearFocus()
            QApplication.processEvents()
            wheel_event = FakeWheelEvent()

            filtered = window.eventFilter(window.spin_angstrom_per_cycle, wheel_event)

            self.assertTrue(filtered)
            self.assertTrue(wheel_event.ignored)

            slider_wheel_event = FakeWheelEvent()
            filtered = window.eventFilter(window.slider_ion_aperture_shadow, slider_wheel_event)

            self.assertTrue(filtered)
            self.assertTrue(slider_wheel_event.ignored)
        finally:
            window.close()

    def test_split_window_slider_wheel_is_ignored_until_slider_has_focus(self) -> None:
        class FakeWheelEvent:
            def __init__(self) -> None:
                self.ignored = False

            def type(self):
                return QEvent.Type.Wheel

            def ignore(self) -> None:
                self.ignored = True

        result = TrenchDepoResult(
            frame_steps=[0, 1],
            frame_profiles=[
                [(0.0, 0.0), (1.0, 0.0)],
                [(0.0, -1.0), (1.0, -1.0)],
            ],
            frame_voids=[[], []],
            final_profile=[(0.0, -1.0), (1.0, -1.0)],
            meta={"cycles": 1},
        )
        case = TrenchSweepResult(
            parameter="split",
            label="Case",
            value=0.0,
            config=TrenchDepoConfig(cycles=1),
            result=result,
        )
        with mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"):
            window = SplitTestWindow([case])

        try:
            window.clearFocus()
            QApplication.processEvents()
            slider_wheel_event = FakeWheelEvent()

            filtered = window.eventFilter(window.slider_frame, slider_wheel_event)

            self.assertTrue(filtered)
            self.assertTrue(slider_wheel_event.ignored)
        finally:
            window.close()

    def test_unified_model_shows_ion_transmission_map_controls_when_enabled(self) -> None:
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
            window.set_active_emulator_number(0, run=False)
            window.chk_sputter.setChecked(True)
            window.chk_ion_transmission.setChecked(True)
            window.sync_etch_control_availability()

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_ion_transmission())
            self.assertFalse(window._active_emulator_supports_reflected_ion())
            self.assertEqual(window.chk_sputter.text(), "Etch enabled")
            self.assertEqual(window.lbl_etch_section.text(), "Direct angle sputter etch (통합 source)")
            self.assertFalse(window.ion_map_group.isHidden())
            self.assertTrue(all(not widget.isHidden() for widget in window._ion_transmission_widgets))
            self.assertEqual(tuple(window.ion_transmission_editor._points), tuple(window._current_geometry_points()))
            self.assertEqual(window.cmb_emulator_default_preset.count(), 1)
            self.assertEqual(window.cmb_emulator_default_preset.itemText(0), "기본")

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

    @unittest.skip("Reflected ion emulator was removed from the rebuilt 0-5 active menu.")
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
            self.assertFalse(window.btn_compare_options.isHidden())
            self.assertEqual(window.cmb_compare_target.currentData(), 1)
            self.assertIn("Emulator 01", window.cmb_compare_target.currentText())
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

    @unittest.skip("Emulator 04 is now depth depletion, not GapSim redeposition.")
    def test_emulator_four_is_gapsim_redeposition_and_compares_to_model_one(self) -> None:
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
            self.assertEqual(window.current_config().emulator_number, 4)
            self.assertEqual(window.current_config().redepo_transport_model, "gapsim_original_per_vertex_los")
            self.assertEqual(window.cmb_compare_target.currentData(), 1)
            self.assertIn("Emulator 01", window.cmb_compare_target.currentText())
            self.assertGreaterEqual(window.cmb_compare_target.findData(1), 0)
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

    @unittest.skip("Redeposition/reflected compare path was removed from the active menu.")
    def test_compare_options_run_selected_emulator_target(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result) as run_mock,
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            try:
                window.set_active_emulator_number(4, run=False)
                target_idx = window.cmb_compare_target.findData(3)
                self.assertGreaterEqual(target_idx, 0)
                window.cmb_compare_target.setCurrentIndex(target_idx)

                window.run_compare_for_active_emulator()

                self.assertEqual(run_mock.call_count, 2)
                current_cfg = run_mock.call_args_list[0].args[0]
                target_cfg = run_mock.call_args_list[1].args[0]
                self.assertTrue(current_cfg.redepo_enabled)
                self.assertFalse(current_cfg.reflected_ion_enabled)
                self.assertTrue(target_cfg.reflected_ion_enabled)
                self.assertFalse(target_cfg.redepo_enabled)
                self.assertEqual(len(window._split_windows), 1)
            finally:
                for split_window in list(window._split_windows):
                    split_window.close()
                window.close()

    @unittest.skip("GapSim redeposition compare target was removed from the active menu.")
    def test_compare_options_run_gapsim_redepo_target(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        legacy_result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (2.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (2.0, 0.0)],
            meta={"cycles": 0, "redepo_model": "gapsim_original_per_vertex_los"},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result) as run_mock,
            mock.patch(
                "gapsim.emulation.trench_depo_ui.run_trench_depo_legacy_redeposition",
                return_value=legacy_result,
            ) as legacy_mock,
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            try:
                window.set_active_emulator_number(4, run=False)
                self.assertEqual(window.cmb_compare_target.currentData(), 1)

                window.run_compare_for_active_emulator()

                self.assertEqual(run_mock.call_count, 2)
                self.assertEqual(legacy_mock.call_count, 0)
                first_cfg = run_mock.call_args_list[0].args[0]
                target_cfg = run_mock.call_args_list[1].args[0]
                self.assertEqual(first_cfg.emulator_number, 4)
                self.assertEqual(target_cfg.emulator_number, 1)
                self.assertTrue(first_cfg.redepo_enabled)
                self.assertFalse(target_cfg.redepo_enabled)
                self.assertEqual(len(window._split_windows), 1)
            finally:
                for split_window in list(window._split_windows):
                    split_window.close()
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

    def test_run_progress_bar_tracks_cycle_callback(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0, 1, 2, 3],
            frame_profiles=[
                [(0.0, 0.0), (1.0, 0.0)],
                [(0.0, -1.0), (1.0, -1.0)],
                [(0.0, -2.0), (1.0, -2.0)],
                [(0.0, -3.0), (1.0, -3.0)],
            ],
            frame_voids=[[], [], [], []],
            final_profile=[(0.0, -3.0), (1.0, -3.0)],
            meta={"cycles": 3},
        )

        window_holder = {}

        def fake_run(config, *, progress_cb=None, **_kwargs):
            self.assertIsNotNone(progress_cb)
            window = window_holder["window"]
            self.assertFalse(window.progress_run.isHidden())
            progress_cb(0, 3)
            progress_cb(2, 3)
            progress_cb(3, 3)
            self.assertEqual(window.progress_run.maximum(), 3)
            self.assertEqual(window.progress_run.value(), 3)
            return result

        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", side_effect=fake_run),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            window_holder["window"] = window
            try:
                window.run_emulation(save_artifacts=False)

                self.assertTrue(window.progress_run.isHidden())
                self.assertEqual(window.lbl_status.text(), "Cycle 3/3 | 점 2")
            finally:
                window.close()

    def test_next_depo_stage_starts_from_previous_final_profile_and_colors_stage(self) -> None:
        a = [(0.0, 0.0), (1.0, 0.0)]
        b = [(0.0, -1.0), (1.0, -1.0)]
        c = [(0.0, -2.0), (1.0, -2.0)]
        first = TrenchDepoResult(
            frame_steps=[0, 1],
            frame_profiles=[a, b],
            frame_voids=[[], []],
            final_profile=b,
            meta={"cycles": 1, "stage_index": 1},
        )
        second = TrenchDepoResult(
            frame_steps=[0, 1],
            frame_profiles=[b, c],
            frame_voids=[[], []],
            final_profile=c,
            meta={"cycles": 1},
        )
        captured_configs = []

        def fake_run(config, **_kwargs):
            captured_configs.append(config)
            return first if len(captured_configs) == 1 else second

        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", side_effect=fake_run),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            try:
                window.set_active_emulator_number(0, run=False)

                window.run_emulation(save_artifacts=False)
                window.start_next_depo_stage()
                window.run_emulation(save_artifacts=False)

                self.assertEqual(len(captured_configs), 2)
                self.assertEqual(list(captured_configs[1].points), b)
                self.assertEqual(window._result.frame_profiles, [a, b, c])
                self.assertEqual(window._result.meta["frame_stage_ids"], [1, 1, 2])
                self.assertEqual(window.view._frame_stage_ids, [1, 1, 2])
            finally:
                window.close()

    def test_window_routes_data_files_under_configured_data_root(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch.dict(
                os.environ,
                {
                    "QT_QPA_PLATFORM": "offscreen",
                    "GAPSIM_DATA_ROOT": str(Path(tmpdir) / "shared_data"),
                },
                clear=True,
            ),
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            try:
                data_root = Path(tmpdir) / "shared_data"

                self.assertEqual(window._runs_root, data_root.resolve() / "runs" / "trench_depo_emulation")
                self.assertEqual(window._results_root, data_root.resolve() / "results" / "trench_depo_emulation")
                self.assertEqual(
                    window._structure_library_path,
                    data_root.resolve() / "emulator_research" / "structures.xlsx",
                )
                self.assertEqual(
                    window._parameter_library_path,
                    data_root.resolve() / "emulator_research" / "parameter_presets.json",
                )
                self.assertEqual(window._addon_manager.addons_dir, data_root.resolve() / "addons")
                self.assertEqual(
                    window._addon_manager.state_path,
                    data_root.resolve() / "addons" / "addons_state.json",
                )
            finally:
                window.close()

    def test_window_starts_with_corrupt_structure_workbook_by_using_fallback(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            corrupt_workbook = Path(tmpdir) / "structures.xlsx"
            corrupt_workbook.write_text("not a zip workbook", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GAPSIM_STRUCTURE_LIBRARY": str(corrupt_workbook)}):
                window = TrenchDepoWindow()
            try:
                self.assertGreaterEqual(len(window._structure_points), 2)
                self.assertEqual(window._active_structure_sheet_name, "")
            finally:
                window.close()

    def test_result_panel_shows_parameters_and_repeat_playback(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0, 1, 2],
            frame_profiles=[
                [(0.0, 0.0), (1.0, 0.0)],
                [(0.0, -1.0), (1.0, -1.0)],
                [(0.0, -2.0), (1.0, -2.0)],
            ],
            frame_voids=[[], [], []],
            final_profile=[(0.0, -2.0), (1.0, -2.0)],
            meta={"cycles": 2, "growth_model": "test_model"},
        )
        captured = {}

        def fake_run(config, **_kwargs):
            captured["config"] = config
            return result

        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", side_effect=fake_run),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
            tempfile.TemporaryDirectory() as tmp_results,
            mock.patch("gapsim.emulation.trench_depo_ui.DEFAULT_RESULTS_ROOT", tmp_results),
        ):
            window = TrenchDepoWindow()
            try:
                window.set_active_emulator_number(0, run=False)
                window.spin_cycles.setValue(2)
                window.spin_angstrom_per_cycle.setValue(12.5)
                window.spin_sputter_strength.setValue(6.25)
                window.chk_sputter.setChecked(True)

                window.run_emulation(save_artifacts=False)

                self.assertIs(captured["config"], window._result_config)
                params_text = window.edit_result_parameters.toPlainText()
                self.assertIn("모델: 기본 통합 모델", params_text)
                self.assertIn("현재 stage cycles: 2", params_text)
                self.assertIn("표시 누적 cycles: 2", params_text)
                self.assertIn("Depo: 12.500 A/CYC", params_text)
                self.assertIn("Direct sputter: ON", params_text)
                self.assertIn("Etch: 6.250 A/CYC", params_text)
                self.assertIn("Growth model: test_model", params_text)

                self.assertTrue(window.btn_result_play.isEnabled())
                self.assertEqual(window.slider_frame.value(), 2)
                window.btn_result_play.click()
                self.assertTrue(window._result_playback_timer.isActive())
                self.assertEqual(window.btn_result_play.text(), "정지")
                self.assertEqual(window.slider_frame.value(), 0)

                window._advance_result_playback()
                self.assertEqual(window.slider_frame.value(), 1)
                window._advance_result_playback()
                self.assertEqual(window.slider_frame.value(), 2)
                window._advance_result_playback()
                self.assertEqual(window.slider_frame.value(), 0)

                self.assertTrue(window.btn_save_result_json.isEnabled())
                window.btn_save_result_json.click()
                saved_files = list(Path(tmp_results).glob("*/트렌치결과_*.json"))
                self.assertEqual(len(saved_files), 1)
                payload = json.loads(saved_files[0].read_text(encoding="utf-8"))
                self.assertEqual(payload["config"]["cycles"], 2)
                self.assertEqual(payload["result"]["meta"]["growth_model"], "test_model")
                self.assertEqual(len(payload["result"]["frame_profiles"]), 3)
                self.assertEqual(window._last_run_dir, saved_files[0].parent.resolve())
                self.assertIn("결과 저장", window.lbl_run_dir.text())
                self.assertEqual(window.lbl_run_dir.toolTip(), str(saved_files[0].resolve()))

                window.btn_result_play.click()
                self.assertFalse(window._result_playback_timer.isActive())
                self.assertEqual(window.btn_result_play.text(), "반복재생")
            finally:
                window.close()

    @unittest.skip("Model7 LF overhang proxy was removed from the rebuilt 0-5 active menu.")
    def test_emulator_seven_exposes_lf_overhang_proxy_and_collapses_sections(self) -> None:
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
            window.set_active_emulator_number(7, run=False)

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_ion_transmission())
            self.assertTrue(window._active_emulator_supports_lf_overhang())
            self.assertFalse(window._active_emulator_supports_redeposition())
            self.assertFalse(window._active_emulator_supports_reflected_ion())
            self.assertFalse(window._active_emulator_supports_depth_deposition())
            self.assertEqual(window.cmb_compare_target.currentData(), 1)
            self.assertIn("7번 LF", window.lbl_lf_overhang_section.text())
            self.assertFalse(window.chk_lf_overhang.isHidden())
            self.assertFalse(window.spin_lf_overhang_dose.isHidden())

            split_keys = {
                window.cmb_split_parameter.itemData(idx)
                for idx in range(window.cmb_split_parameter.count())
            }
            self.assertIn("lf_overhang_dose", split_keys)
            self.assertIn("lf_overhang_width_a", split_keys)

            config = window.current_config()
            self.assertTrue(config.sputter_enabled)
            self.assertTrue(config.ion_transmission_enabled)
            self.assertTrue(config.lf_overhang_enabled)
            self.assertAlmostEqual(config.lf_overhang_redepo_fraction_pct, 30.0, places=6)

            window.spin_lf_overhang_dose.setValue(1.75)
            window.chk_lf_overhang.setChecked(False)
            QApplication.processEvents()
            self.assertFalse(window.chk_lf_overhang.isHidden())
            self.assertTrue(window.spin_lf_overhang_dose.isHidden())
            self.assertAlmostEqual(window.spin_lf_overhang_dose.value(), 1.75, places=6)
            self.assertFalse(window.current_config().lf_overhang_enabled)

            window.chk_lf_overhang.setChecked(True)
            QApplication.processEvents()
            self.assertFalse(window.spin_lf_overhang_dose.isHidden())
            self.assertAlmostEqual(window.current_config().lf_overhang_dose, 1.75, places=6)
        finally:
            window.close()

    def test_unified_model_depth_deposition_uses_current_geometry_when_enabled(self) -> None:
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
            window.set_active_emulator_number(0, run=False)
            window.chk_depth_deposition.setChecked(True)
            window.sync_etch_control_availability()

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_depth_deposition())
            self.assertFalse(window._active_emulator_supports_lf_overhang())
            self.assertFalse(window.chk_depth_deposition.isHidden())
            self.assertFalse(window.spin_depth_decay_k.isHidden())
            self.assertFalse(window.depth_profile_group.isHidden())
            self.assertTrue(all(widget.isHidden() for widget in window._depth_advanced_widgets()))
            window.btn_depth_advanced.setChecked(True)
            self.assertTrue(all(not widget.isHidden() for widget in [
                window.lbl_depth_closure_section,
                window.lbl_depth_closure_threshold,
                window.spin_depth_closure_threshold,
                window.lbl_depth_post_fill_hole,
                window.spin_depth_post_fill_hole_pct,
            ]))
            self.assertTrue(all(widget.isHidden() for widget in [
                window.lbl_depth_post_fill_line,
                window.spin_depth_post_fill_line_pct,
                window.lbl_depth_line_open_path,
                window.spin_depth_line_open_path,
                window.lbl_depth_residual_decay,
                window.spin_depth_residual_decay,
            ]))
            self.assertFalse(window.chk_sputter.isHidden())
            self.assertFalse(window.chk_redepo.isHidden())
            self.assertFalse(window.chk_sputter.isChecked())
            self.assertFalse(window.chk_redepo.isChecked())
            self.assertTrue(all(widget.isHidden() for widget in window._lf_overhang_widgets))
            self.assertFalse(window.depth_profile_group.isHidden())
            self.assertTrue(window.chk_depth_deposition.isChecked())
            self.assertGreaterEqual(window.cmb_emulator_default_preset.findText("기본"), 0)
            self.assertEqual(tuple(window.depth_deposition_editor._structure_points), tuple(window._current_geometry_points()))
            self.assertIs(window.structure_points_group.parent(), window.structure_panel_content)
            self.assertIs(window.overlay_group.parent(), window.structure_panel_content)
            self.assertIs(window.smoothing_controls_group.parent(), window.smoothing_panel_content)
            self.assertIs(window.smoothed_points_group.parent(), window.smoothing_panel_content)
            self.assertFalse(hasattr(window, "emulator_group"))
            self.assertFalse(hasattr(window, "parameter_preset_group"))
            self.assertIs(window.params_group.parent(), window.progress_panel_content)
            self.assertIs(window.gaussian_group.parent(), window.progress_panel_content)
            self.assertIs(window.ion_map_group.parent(), window.progress_panel_content)
            self.assertIs(window.redepo_lobe_group.parent(), window.progress_panel_content)
            self.assertIs(window.depth_profile_group.parent(), window.progress_panel_content)
            self.assertIs(window.result_summary_group.parent(), window.result_panel_content)
            self.assertFalse(hasattr(window, "btn_new_emulator"))
            self.assertEqual(
                [window.view_tabs.tabText(idx) for idx in range(window.view_tabs.count())],
                ["1 구조", "2 스무딩", "3 진행", "4 결과"],
            )
            self.assertEqual(
                [window.workflow_tabs.tabText(idx) for idx in range(window.workflow_tabs.count())],
                ["1 구조", "2 스무딩", "3 진행", "4 결과", "5 옵션"],
            )
            self.assertGreaterEqual(window.right_panel.minimumWidth(), 440)
            self.assertGreaterEqual(window.right_panel.maximumWidth(), 560)

            config = window.current_config()
            self.assertEqual(tuple(config.points), tuple(window._current_geometry_points()))
            self.assertTrue(config.deposition_depth_enabled)
            self.assertFalse(config.sputter_enabled)
            self.assertFalse(config.redepo_enabled)
            self.assertEqual(config.deposition_feature_type, "hole")
            self.assertIsNone(config.deposition_feature_length_a)
            self.assertFalse(window.spin_depth_feature_length.isEnabled())
            self.assertAlmostEqual(config.deposition_min_ratio, 0.03, places=6)
            self.assertAlmostEqual(config.deposition_post_closure_fill_pct_hole, 0.03, places=6)
            self.assertEqual(window.spin_depth_decay_k.decimals(), 5)
            self.assertAlmostEqual(window.spin_depth_decay_k.singleStep(), 0.00001, places=8)
            window.spin_depth_decay_k.setValue(0.12345)
            self.assertAlmostEqual(window.spin_depth_decay_k.value(), 0.12345, places=6)
            self.assertAlmostEqual(window.current_config().deposition_depth_decay_k, 0.12345, places=6)
            self.assertIn("K=0.12345", window.lbl_depth_formula.text())

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
            window.spin_angstrom_per_cycle.setValue(12.5)
            self.assertIn("Dep rate식", window.lbl_depth_formula.text())
            self.assertIn("D0=12.500 A/CYC", window.lbl_depth_formula.text())
            self.assertIn("K=0.45000", window.lbl_depth_formula.text())
            self.assertIn("g(z)=z*(W+L)/(2*W*L)", window.lbl_depth_formula.text())
            attenuation_idx = window.cmb_depth_display_mode.findData("attenuation")
            window.cmb_depth_display_mode.setCurrentIndex(attenuation_idx)
            self.assertEqual(window.depth_deposition_editor.display_mode(), "attenuation")
            self.assertIn("감쇄식", window.lbl_depth_formula.text())
            self.assertIn("depletion(z)=1-R(z)", window.lbl_depth_formula.text())
            self.assertIn("K=0.45000", window.lbl_depth_formula.text())
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
            self.assertIn("sputter_strength_a_per_cycle", split_keys)
            self.assertIn("redepo_efficiency_pct", split_keys)
            depth_k_idx = window.cmb_split_parameter.findData("deposition_depth_decay_k")
            self.assertGreaterEqual(depth_k_idx, 0)
            window.cmb_split_parameter.setCurrentIndex(depth_k_idx)
            self.assertEqual(window.spin_split_start.decimals(), 5)
            self.assertEqual(window.spin_split_end.decimals(), 5)
            self.assertEqual(window.spin_split_step.decimals(), 5)
            self.assertAlmostEqual(window.spin_split_step.minimum(), 0.00001, places=8)
            window.spin_split_start.setValue(0.12345)
            self.assertAlmostEqual(window.spin_split_start.value(), 0.12345, places=6)
            window.spin_split_step.setValue(0.00001)
            self.assertAlmostEqual(window.spin_split_step.value(), 0.00001, places=8)

            window.resize(1280, 720)
            window.show()
            QApplication.processEvents()
            self.assertEqual(window.progress_scroll_area.horizontalScrollBar().maximum(), 0)
            self.assertGreater(window.progress_scroll_area.verticalScrollBar().maximum(), 0)
        finally:
            window.close()

    def test_emulator_zero_integrates_active_models_with_model_six_redepo(self) -> None:
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
            window.set_active_emulator_number(0, run=False)

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_ion_transmission())
            self.assertTrue(window._active_emulator_supports_depth_deposition())
            self.assertTrue(window._active_emulator_supports_redeposition())
            self.assertFalse(window._active_emulator_supports_lf_overhang())
            self.assertFalse(window._active_emulator_supports_reflected_ion())
            self.assertFalse(window.chk_sputter.isHidden())
            self.assertFalse(window.chk_ion_transmission.isHidden())
            self.assertTrue(any(widget.isHidden() for widget in window._ion_transmission_widgets))
            self.assertFalse(window.chk_redepo.isHidden())
            self.assertTrue(window.lbl_redepo_efficiency.isHidden())
            self.assertTrue(window.cmb_redepo_source_model.isHidden())
            self.assertTrue(window.redepo_lobe_group.isHidden())
            self.assertTrue(all(widget.isHidden() for widget in window._lf_overhang_widgets))
            self.assertFalse(window.chk_depth_deposition.isHidden())
            self.assertTrue(window.spin_depth_decay_k.isHidden())
            self.assertTrue(window.depth_profile_group.isHidden())
            self.assertTrue(all(widget.isHidden() for widget in window._reflected_ion_widgets))
            self.assertIn("통합", window.lbl_etch_section.text())
            self.assertEqual(window.chk_depth_deposition.text(), "Depth depletion")
            self.assertEqual(window.chk_inhibition_deposition.text(), "Inhibition deposition")
            self.assertFalse(window.chk_inhibition_deposition.isHidden())
            self.assertEqual(window.cmb_compare_target.currentData(), "legacy_gapsim_angle")
            self.assertFalse(window.chk_sputter.isChecked())
            self.assertFalse(window.chk_ion_transmission.isChecked())
            self.assertFalse(window.chk_redepo.isChecked())
            self.assertFalse(window.chk_depth_deposition.isChecked())
            self.assertFalse(window.chk_inhibition_deposition.isChecked())

            split_parameters = {
                str(window.cmb_split_parameter.itemData(idx))
                for idx in range(window.cmb_split_parameter.count())
            }
            self.assertIn("sputter_strength_a_per_cycle", split_parameters)
            self.assertIn("ion_transmission_start_depth_pct", split_parameters)
            self.assertIn("redepo_efficiency_pct", split_parameters)
            self.assertIn("redepo_emit_power", split_parameters)
            self.assertIn("redepo_distance_power", split_parameters)
            self.assertNotIn("lf_overhang_dose", split_parameters)
            self.assertIn("deposition_depth_decay_k", split_parameters)
            self.assertIn("inhibition_strength_pct", split_parameters)
            self.assertNotIn("reflected_ion_strength_pct", split_parameters)

            config = window.current_config()
            self.assertEqual(tuple(config.points), tuple(window._current_geometry_points()))
            self.assertFalse(config.sputter_enabled)
            self.assertFalse(config.ion_transmission_enabled)
            self.assertFalse(config.redepo_enabled)
            self.assertFalse(config.deposition_depth_enabled)
            self.assertFalse(config.inhibition_enabled)

            window.chk_sputter.setChecked(True)
            window.chk_ion_transmission.setChecked(True)
            window.chk_redepo.setChecked(True)
            window.chk_depth_deposition.setChecked(True)
            window.sync_etch_control_availability()
            self.assertTrue(all(not widget.isHidden() for widget in window._ion_transmission_widgets))
            self.assertFalse(window.lbl_redepo_efficiency.isHidden())
            self.assertFalse(window.redepo_lobe_group.isHidden())
            self.assertFalse(window.spin_depth_decay_k.isHidden())
            self.assertFalse(window.depth_profile_group.isHidden())
            config = window.current_config()
            self.assertTrue(config.sputter_enabled)
            self.assertTrue(config.ion_transmission_enabled)
            self.assertTrue(config.redepo_enabled)
            self.assertAlmostEqual(config.redepo_emit_power, 22.0, places=6)
            self.assertAlmostEqual(config.redepo_distance_power, 25.0, places=6)
            self.assertFalse(config.lf_overhang_enabled)
            self.assertTrue(config.deposition_depth_enabled)
            self.assertFalse(config.inhibition_enabled)
            self.assertFalse(config.reflected_ion_enabled)

            window.chk_inhibition_deposition.setChecked(True)
            window.sync_etch_control_availability()
            self.assertTrue(window.chk_depth_deposition.isChecked())
            self.assertTrue(window.chk_inhibition_deposition.isChecked())
            combined_config = window.current_config()
            self.assertTrue(combined_config.deposition_depth_enabled)
            self.assertTrue(combined_config.inhibition_enabled)
        finally:
            window.close()

    def test_model_parameter_sections_can_reorder_by_title(self) -> None:
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

        def grid_row(widget):
            index = window.params_grid.indexOf(widget)
            self.assertGreaterEqual(index, 0)
            row, _column, _row_span, _column_span = window.params_grid.getItemPosition(index)
            return row

        try:
            top_titles = [
                window.lbl_etch_section.text(),
                window.lbl_ion_depth_section.text(),
                window.lbl_redepo_section.text(),
                window.lbl_depth_depo_section.text(),
                window.lbl_inhibition_section.text(),
            ]
            self.assertTrue(all("번" not in title for title in top_titles))
            self.assertLess(grid_row(window.lbl_etch_section), grid_row(window.lbl_depth_depo_section))

            window._move_model_parameter_section("depth", "direct")

            self.assertEqual(window._model_parameter_section_order[0], "depth")
            self.assertLess(grid_row(window.lbl_depth_depo_section), grid_row(window.lbl_etch_section))
            self.assertLess(grid_row(window.lbl_etch_section), grid_row(window.lbl_ion_depth_section))
        finally:
            window.close()

    def test_unified_model_exposes_reflection_gaussian_redepo_controls_when_enabled(self) -> None:
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
            window.set_active_emulator_number(0, run=False)
            window.chk_sputter.setChecked(True)
            window.chk_redepo.setChecked(True)
            window.sync_etch_control_availability()

            self.assertTrue(window._active_emulator_supports_sputter())
            self.assertTrue(window._active_emulator_supports_redeposition())
            self.assertTrue(window._active_emulator_supports_ion_transmission())
            self.assertTrue(window._active_emulator_supports_depth_deposition())
            self.assertEqual(window.cmb_compare_target.currentData(), "legacy_gapsim_angle")
            self.assertIn("통합", window.lbl_etch_section.text())
            self.assertIn("reflection", window.lbl_redepo_section.text())
            self.assertEqual(window.lbl_redepo_emit_power.text(), "Angular spread deg")
            self.assertEqual(window.lbl_redepo_distance_power.text(), "Specular bias %")
            self.assertGreaterEqual(window.spin_redepo_emit_power.maximum(), 80.0)
            self.assertLessEqual(window.spin_redepo_distance_power.minimum(), -100.0)
            self.assertGreaterEqual(window.spin_redepo_distance_power.maximum(), 100.0)
            self.assertFalse(window.lbl_redepo_efficiency.isHidden())
            self.assertTrue(window.cmb_redepo_source_model.isHidden())
            self.assertFalse(window.redepo_lobe_group.isHidden())
            self.assertTrue(window.redepo_lobe_group.isEnabled())
            self.assertEqual(window.redepo_lobe_editor.parameters(), (25.0, 22.0, 25.0))
            self.assertFalse(window.chk_show_redepo_overlay.isHidden())
            self.assertFalse(window.chk_show_redepo_overlay.isEnabled())

            split_parameters = {
                str(window.cmb_split_parameter.itemData(idx))
                for idx in range(window.cmb_split_parameter.count())
            }
            self.assertIn("redepo_efficiency_pct", split_parameters)
            self.assertIn("redepo_emit_power", split_parameters)
            self.assertIn("redepo_distance_power", split_parameters)
            self.assertIn("ion_transmission_start_depth_pct", split_parameters)

            config = window.current_config()
            self.assertEqual(config.emulator_number, 0)
            self.assertTrue(config.sputter_enabled)
            self.assertTrue(config.redepo_enabled)
            self.assertAlmostEqual(config.redepo_emit_power, 22.0, places=6)
            self.assertAlmostEqual(config.redepo_distance_power, 25.0, places=6)
            window.spin_redepo_distance_power.setValue(-35.0)
            self.assertAlmostEqual(window.current_config().redepo_distance_power, -35.0, places=6)

            overlay_result = TrenchDepoResult(
                frame_steps=[0, 1],
                frame_profiles=[
                    [(-10.0, 0.0), (10.0, 0.0)],
                    [(-12.0, 0.0), (12.0, 0.0)],
                ],
                frame_voids=[[], []],
                final_profile=[(-12.0, 0.0), (12.0, 0.0)],
                meta={
                    "cycles": 1,
                    "frame_redepo_overlays": [[], [(0.0, -2.0, 1.0)]],
                    "frame_etch_overlays": [[], [(-2.0, -1.0, 1.0)]],
                },
            )
            window._apply_emulation_result(config, overlay_result, None, use_preview_cache=True)
            self.assertFalse(window.chk_show_redepo_overlay.isHidden())
            self.assertTrue(window.chk_show_redepo_overlay.isEnabled())
            window.chk_show_redepo_overlay.setChecked(True)
            window.show_frame(1)
            self.assertTrue(window.view._redepo_overlay_items)
            window.chk_show_redepo_overlay.setChecked(False)
            self.assertFalse(window.view._redepo_overlay_items)
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
            self.assertFalse(hasattr(window, "emulator_group"))
            self.assertFalse(hasattr(window, "parameter_preset_group"))
            self.assertFalse(hasattr(window, "btn_new_emulator"))
            self.assertIs(window.structure_library_group.parent(), window.structure_panel_content)
            self.assertIs(window.smoothing_controls_group.parent(), window.smoothing_panel_content)
            self.assertIs(window.params_group.parent(), window.progress_panel_content)
            self.assertIs(window.action_group.parent(), window.progress_panel_content)
            self.assertIs(window.split_group.parent(), window.action_group)
            self.assertIs(window.compare_group.parent(), window.action_group)
            self.assertIs(window.addon_group.parent(), window.options_panel_content)
            self.assertIs(window.addon_extension_group.parent(), window.progress_panel_content)
            self.assertEqual(window.btn_split_options.text(), "Split")
            self.assertEqual(window.btn_compare_options.text(), "Compare")
            self.assertEqual(window.split_group.title(), "Split Test 파라미터")
            self.assertEqual(window.compare_group.title(), "Compare Test 파라미터")
            self.assertTrue(window.split_group.isHidden())
            self.assertTrue(window.compare_group.isHidden())

            window.btn_split_options.click()
            self.assertFalse(window.split_group.isHidden())
            self.assertTrue(window.compare_group.isHidden())

            window.btn_compare_options.click()
            self.assertTrue(window.split_group.isHidden())
            self.assertFalse(window.compare_group.isHidden())

            self.assertFalse(hasattr(window, "btn_structure_next"))
            window.btn_structure_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 1)
            self.assertEqual(window.workflow_tabs.currentIndex(), 1)
            self.assertTrue(window.result_controls_widget.isHidden())

            self.assertFalse(hasattr(window, "btn_smoothing_next"))
            self.assertFalse(hasattr(window, "btn_smoothing_back"))
            window.btn_smoothing_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 2)
            self.assertEqual(window.workflow_tabs.currentIndex(), 2)
            self.assertTrue(window.result_controls_widget.isHidden())

            window.btn_progress_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 3)
            self.assertEqual(window.workflow_tabs.currentIndex(), 3)
            self.assertFalse(window.result_controls_widget.isHidden())

            window.btn_results_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 3)
            self.assertEqual(window.workflow_tabs.currentIndex(), 4)
            self.assertFalse(window.result_controls_widget.isHidden())

            window.btn_options_panel_back.click()
            self.assertEqual(window.view_tabs.currentIndex(), 3)
            self.assertEqual(window.workflow_tabs.currentIndex(), 3)

            window.workflow_tabs.setCurrentIndex(0)
            self.assertEqual(window.view_tabs.currentIndex(), 0)
            self.assertTrue(window.result_controls_widget.isHidden())

            window.run_emulation(save_artifacts=False)
            self.assertEqual(window.view_tabs.currentIndex(), 3)
            self.assertEqual(window.workflow_tabs.currentIndex(), 3)
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
            self.assertAlmostEqual(
                window.spin_depth_feature_depth.value(),
                TrenchDepoWindow._geometry_depth_a(window._current_geometry_points()),
                places=6,
            )

            window.set_active_emulator_number(2, run=False)
            self.assertEqual(window.active_emulator_number(), 0)
            self.assertEqual(tuple(window.current_config().points), TrenchDepoConfig().points)
            self.assertAlmostEqual(
                window.spin_depth_feature_depth.value(),
                TrenchDepoWindow._geometry_depth_a(TrenchDepoConfig().points),
                places=6,
            )

            custom_points = [(-300.0, 0.0), (-100.0, -250.0), (100.0, -250.0), (300.0, 0.0)]
            window._set_structure_points(custom_points, fit=False)

            self.assertEqual(tuple(window.current_config().points), tuple(custom_points))
            self.assertIn("4점", window.lbl_geometry_source.text())
            self.assertAlmostEqual(window.spin_depth_feature_depth.value(), 250.0, places=6)
            self.assertAlmostEqual(window.current_config().deposition_feature_depth_a, 250.0, places=6)
        finally:
            window.close()

    def test_structure_library_exports_loads_and_saves_excel_sheets(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()
            try:
                window._structure_library_path = Path(tmp) / "structures.xlsx"
                window.refresh_structure_library(show_status=False)

                window.export_default_structures_to_library()
                self.assertEqual(window.cmb_structure_library.count(), 1)
                self.assertEqual(
                    [
                        window.cmb_structure_library.itemText(idx)
                        for idx in range(window.cmb_structure_library.count())
                    ],
                    ["기본 트렌치"],
                )
                default_idx = window.cmb_structure_library.findData("em00_integrated_depo_etch_depth")
                self.assertGreaterEqual(default_idx, 0)
                window.cmb_structure_library.setCurrentIndex(default_idx)
                window.load_selected_structure_from_library()
                self.assertEqual(tuple(window.current_config().points), tuple(BOWED_JAR_TRENCH_POINTS))
                self.assertEqual(window.edit_structure_name.text(), "기본 트렌치")
                self.assertFalse(hasattr(window, "btn_load_structure"))
                self.assertFalse(hasattr(window, "btn_load_structure_view"))
                self.assertFalse(hasattr(window, "btn_save_structure_view"))

                custom_points = [(-50.0, 0.0), (0.0, -80.0), (50.0, 0.0)]
                window._set_structure_points(custom_points, fit=False)
                window.edit_structure_name.setText("custom_test_structure")
                window.save_current_structure_to_library()
                self.assertGreaterEqual(window.cmb_structure_library.findData("custom_test_structure"), 0)
                self.assertEqual(window.edit_structure_name.text(), "custom test structure")
                self.assertEqual(tuple(window.current_config().points), tuple(custom_points))
            finally:
                window.close()

    def test_addon_panel_lists_and_toggles_loaded_addons(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "addon_src"
            source.mkdir()
            (source / "addon.json").write_text(
                json.dumps(
                    {
                        "id": "rate-guard",
                        "name": "Rate Guard",
                        "version": "0.1.0",
                        "description": "Checks deposition rate settings.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GAPSIM_ADDON_ROOT": str(root / "addons"),
                        "GAPSIM_ADDON_STATE": str(root / "addons_state.json"),
                    },
                ),
                mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
                mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
            ):
                window = TrenchDepoWindow()

            try:
                window._install_addon_from_path(source)

                self.assertEqual(window.addon_list.count(), 1)
                item = window.addon_list.item(0)
                self.assertEqual(item.data(Qt.ItemDataRole.UserRole), "rate-guard")
                self.assertEqual(item.checkState(), Qt.CheckState.Checked)
                self.assertIn("활성 1개", window.lbl_addon_status.text())
                self.assertEqual(window._addon_manager.enabled_ids(), ["rate-guard"])

                item.setCheckState(Qt.CheckState.Unchecked)
                QApplication.processEvents()

                self.assertEqual(window._addon_manager.enabled_ids(), [])
                self.assertIn("활성 0개", window.lbl_addon_status.text())
            finally:
                window.close()

    def test_drop_in_addon_folder_loads_progress_widget_on_startup(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon_dir = root / "addons" / "startup_widget"
            addon_dir.mkdir(parents=True)
            (addon_dir / "addon.json").write_text(
                json.dumps(
                    {
                        "id": "startup-widget",
                        "name": "Startup Widget",
                        "version": "0.1.0",
                        "entrypoint": "addon.py",
                        "extension_points": ["progress.panel"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (addon_dir / "addon.py").write_text(
                "from PySide6.QtWidgets import QLabel\n"
                "\n"
                "def register(context):\n"
                "    context.add_progress_widget(QLabel('startup addon loaded'), title='Startup Widget')\n",
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GAPSIM_ADDON_ROOT": str(root / "addons"),
                        "GAPSIM_ADDON_STATE": str(root / "addons" / "addons_state.json"),
                    },
                ),
                mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
                mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
            ):
                window = TrenchDepoWindow()

            try:
                self.assertEqual(window._addon_manager.enabled_ids(), ["startup-widget"])
                self.assertIs(window.addon_group.parent(), window.options_panel_content)
                self.assertIs(window.addon_extension_group.parent(), window.progress_panel_content)
                self.assertFalse(window.addon_extension_group.isHidden())
                self.assertIn("기능 로드: 1개", window.lbl_addon_status.text())
                labels = [label.text() for label in window.addon_extension_group.findChildren(QLabel)]
                self.assertIn("startup addon loaded", labels)
            finally:
                window.close()

    def test_addon_runtime_receives_result_and_frame_events(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0, 3],
            frame_profiles=[
                [(0.0, 0.0), (1.0, 0.0)],
                [(0.0, 0.0), (1.0, -2.0)],
            ],
            frame_voids=[[], []],
            final_profile=[(0.0, 0.0), (1.0, -2.0)],
            meta={"cycles": 3},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon_dir = root / "addons" / "event_probe"
            addon_dir.mkdir(parents=True)
            (addon_dir / "addon.json").write_text(
                json.dumps(
                    {
                        "id": "event-probe",
                        "name": "Event Probe",
                        "version": "0.1.0",
                        "entrypoint": "addon.py",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (addon_dir / "addon.py").write_text(
                "class Probe:\n"
                "    def __init__(self, context):\n"
                "        self.events = []\n"
                "        self._frame_signal = context.frame_shown\n"
                "        self._result_signal = context.result_applied\n"
                "        self._frame_slot = lambda idx: self.events.append(('frame', int(idx)))\n"
                "        self._result_slot = lambda _config, result: self.events.append(\n"
                "            ('result', len(result.frame_profiles))\n"
                "        )\n"
                "        if self._frame_signal is not None:\n"
                "            self._frame_signal.connect(self._frame_slot)\n"
                "        if self._result_signal is not None:\n"
                "            self._result_signal.connect(self._result_slot)\n"
                "\n"
                "    def teardown(self):\n"
                "        if self._frame_signal is not None:\n"
                "            self._frame_signal.disconnect(self._frame_slot)\n"
                "        if self._result_signal is not None:\n"
                "            self._result_signal.disconnect(self._result_slot)\n"
                "\n"
                "def register(context):\n"
                "    return Probe(context)\n",
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GAPSIM_ADDON_ROOT": str(root / "addons"),
                        "GAPSIM_ADDON_STATE": str(root / "addons" / "addons_state.json"),
                    },
                ),
                mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
                mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
            ):
                window = TrenchDepoWindow()

            try:
                self.assertEqual(len(window._addon_runtime_handles), 1)
                handle = window._addon_runtime_handles[0]
                self.assertEqual(handle.events, [])

                config = TrenchDepoConfig(points=result.frame_profiles[0], cycles=3)
                with mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"):
                    window._apply_emulation_result(config, result, None, use_preview_cache=True)

                self.assertIn(("frame", 1), handle.events)
                self.assertIn(("result", 2), handle.events)
                event_count = len(handle.events)
                item = window.addon_list.item(0)
                item.setCheckState(Qt.CheckState.Unchecked)
                QApplication.processEvents()

                with mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"):
                    window._apply_emulation_result(config, result, None, use_preview_cache=True)

                self.assertEqual(len(handle.events), event_count)
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

            window.btn_smoothing_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 2)
            window.btn_progress_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 3)
            self.assertEqual(tuple(window.view._frame_profiles_raw[0]), tuple(window._smoothed_points))
            self.assertIn("입력 미리보기: smooth", window.lbl_status.text())
            self.assertFalse(window.slider_frame.isEnabled())

            window.use_raw_geometry()
            self.assertEqual(tuple(window.current_config().points), tuple(raw_points))
            self.assertEqual(tuple(window.view._frame_profiles_raw[0]), tuple(raw_points))
            self.assertIn("입력 미리보기: raw", window.lbl_status.text())
        finally:
            window.close()

    def test_structure_edits_refresh_smoothing_base_preview(self) -> None:
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
            raw_points = [(-200.0, 0.0), (-120.0, -200.0), (120.0, -200.0), (200.0, 0.0)]
            moved_points = [(-200.0, 0.0), (-90.0, -240.0), (120.0, -200.0), (200.0, 0.0)]
            window._set_structure_points(raw_points, fit=False)

            window._on_structure_point_moved(1, -90.0, -240.0)

            self.assertEqual(tuple(window._structure_points), tuple(moved_points))
            self.assertFalse(window._use_smoothed_geometry)
            self.assertEqual(window._smoothed_points, [])
            self.assertEqual(
                tuple(window.smoothing_view._pts),
                tuple((float(x), -float(y)) for x, y in moved_points),
            )

            window.spin_smooth_segments.setValue(12)
            window.spin_smooth_iterations.setValue(1)
            window.apply_structure_smoothing()
            self.assertTrue(window._use_smoothed_geometry)
            self.assertGreater(len(window._smoothed_points), len(moved_points))

            edited_again = [(-200.0, 0.0), (-90.0, -240.0), (90.0, -260.0), (200.0, 0.0)]
            window._on_structure_point_moved(2, 90.0, -260.0)

            self.assertEqual(tuple(window._structure_points), tuple(edited_again))
            self.assertFalse(window._use_smoothed_geometry)
            self.assertEqual(window._smoothed_points, [])
            self.assertEqual(
                tuple(window.smoothing_view._pts),
                tuple((float(x), -float(y)) for x, y in edited_again),
            )
        finally:
            window.close()

    def test_structure_symmetric_edit_moves_mirror_point(self) -> None:
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
            raw_points = [(-200.0, 0.0), (-120.0, -200.0), (120.0, -200.0), (200.0, 0.0)]
            window._set_structure_points(raw_points, fit=False)
            self.assertFalse(window.chk_symmetric_structure_edit.isHidden())
            window.chk_symmetric_structure_edit.setChecked(True)

            window._on_structure_point_moved(1, -90.0, -240.0)

            moved_points = [(-200.0, 0.0), (-90.0, -240.0), (90.0, -240.0), (200.0, 0.0)]
            self.assertEqual(tuple(window._structure_points), tuple(moved_points))
            self.assertEqual(
                tuple(window.structure_view._pts),
                tuple((float(x), -float(y)) for x, y in moved_points),
            )
            self.assertEqual(tuple(window.structure_points_model.get_points()), tuple(moved_points))

            window._on_structure_table_point_edit_requested(2, 80.0, -260.0)

            table_moved_points = [(-200.0, 0.0), (-80.0, -260.0), (80.0, -260.0), (200.0, 0.0)]
            self.assertEqual(tuple(window._structure_points), tuple(table_moved_points))
            self.assertEqual(tuple(window.structure_points_model.get_points()), tuple(table_moved_points))
        finally:
            window.close()

    def test_structure_ctrl_z_undoes_point_move(self) -> None:
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
            raw_points = [(-200.0, 0.0), (-120.0, -200.0), (120.0, -200.0), (200.0, 0.0)]
            moved_points = [(-200.0, 0.0), (-90.0, -240.0), (120.0, -200.0), (200.0, 0.0)]
            window._set_workflow_step("structure")
            window._set_structure_points(raw_points, fit=False)
            window._clear_structure_undo_stack()
            window.show()
            window.activateWindow()
            window.setFocus()
            QApplication.processEvents()

            window._on_structure_point_moved(1, -90.0, -240.0)
            self.assertEqual(tuple(window._structure_points), tuple(moved_points))

            QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            QApplication.processEvents()

            self.assertEqual(tuple(window._structure_points), tuple(raw_points))
            self.assertEqual(tuple(window.structure_points_model.get_points()), tuple(raw_points))
            self.assertEqual(
                tuple(window.structure_view._pts),
                tuple((float(x), -float(y)) for x, y in raw_points),
            )
        finally:
            window.close()

    def test_structure_shift_box_selects_and_moves_multiple_points(self) -> None:
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
            raw_points = [
                (-200.0, 0.0),
                (-120.0, -200.0),
                (0.0, -260.0),
                (120.0, -200.0),
                (200.0, 0.0),
            ]
            moved_points = [
                (-200.0, 0.0),
                (-100.0, -220.0),
                (20.0, -280.0),
                (140.0, -220.0),
                (200.0, 0.0),
            ]
            window._set_workflow_step("structure")
            window._set_structure_points(raw_points, fit=False)
            window._clear_structure_undo_stack()
            window.resize(1280, 820)
            window.show()
            window.structure_view.fit_points()
            QApplication.processEvents()

            view = window.structure_view
            start = QPoint(view.mapFromScene(QPointF(-150.0, 150.0)))
            end = QPoint(view.mapFromScene(QPointF(150.0, 300.0)))
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, start)
            QTest.mouseMove(view.viewport(), end)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, end)
            QApplication.processEvents()

            self.assertEqual(view.selected_point_indices(), [1, 2, 3])

            with mock.patch(
                "gapsim.ui_qt.views.structure_view.QApplication.keyboardModifiers",
                return_value=Qt.KeyboardModifier.NoModifier,
            ):
                view._on_item_drag_start_raw(1, -120.0, 200.0)
                view._point_items[1].setPos(QPointF(-100.0, 220.0))
                view._on_item_drag_finish_raw(1, -100.0, 220.0)
            QApplication.processEvents()

            self.assertEqual(tuple(window._structure_points), tuple(moved_points))
            self.assertEqual(tuple(window.structure_points_model.get_points()), tuple(moved_points))

            QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            QApplication.processEvents()

            self.assertEqual(tuple(window._structure_points), tuple(raw_points))
        finally:
            window.close()

    def test_structure_plain_box_selects_multiple_points_from_empty_area(self) -> None:
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
            raw_points = [
                (-200.0, 0.0),
                (-120.0, -200.0),
                (0.0, -260.0),
                (120.0, -200.0),
                (200.0, 0.0),
            ]
            moved_points = [
                (-200.0, 0.0),
                (-100.0, -220.0),
                (20.0, -280.0),
                (140.0, -220.0),
                (200.0, 0.0),
            ]
            window._set_workflow_step("structure")
            window._set_structure_points(raw_points, fit=False)
            window._clear_structure_undo_stack()
            window.resize(1280, 820)
            window.show()
            window.structure_view.fit_points()
            QApplication.processEvents()

            view = window.structure_view
            start = QPoint(view.mapFromScene(QPointF(-150.0, 150.0)))
            end = QPoint(view.mapFromScene(QPointF(150.0, 300.0)))
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
            QTest.mouseMove(view.viewport(), end)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
            QApplication.processEvents()

            self.assertEqual(view.selected_point_indices(), [1, 2, 3])

            view._on_item_drag_start_raw(1, -120.0, 200.0)
            view._point_items[1].setPos(QPointF(-100.0, 220.0))
            view._on_item_drag_finish_raw(1, -100.0, 220.0)
            QApplication.processEvents()

            self.assertEqual(tuple(window._structure_points), tuple(moved_points))
            self.assertEqual(tuple(window.structure_points_model.get_points()), tuple(moved_points))
        finally:
            window.close()

    def test_structure_multi_point_drag_uses_raw_delta_without_grid_snap(self) -> None:
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
            raw_points = [
                (-200.0, 0.0),
                (-120.0, -200.0),
                (0.0, -260.0),
                (120.0, -200.0),
                (200.0, 0.0),
            ]
            expected = [
                (-200.0, 0.0),
                (-99.3, -222.7),
                (20.7, -282.7),
                (140.7, -222.7),
                (200.0, 0.0),
            ]
            window._set_workflow_step("structure")
            window._set_structure_points(raw_points, fit=False)
            window._clear_structure_undo_stack()
            view = window.structure_view
            view._selected_indices = {1, 2, 3}
            view._sync_selected_point_items()

            with mock.patch.object(view, "_snap", side_effect=AssertionError("multi drag should not snap")):
                view._on_item_drag_start_raw(1, -120.0, 200.0)
                view._point_items[1].setPos(QPointF(-99.3, 222.7))
                view._on_item_drag_finish_raw(1, -99.3, 222.7)
            QApplication.processEvents()

            for actual, wanted in zip(window._structure_points, expected):
                self.assertAlmostEqual(actual[0], wanted[0], places=6)
                self.assertAlmostEqual(actual[1], wanted[1], places=6)
        finally:
            window.close()

    def test_structure_shift_multi_point_drag_locks_to_dominant_axis(self) -> None:
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
            raw_points = [
                (-200.0, 0.0),
                (-120.0, -200.0),
                (0.0, -260.0),
                (120.0, -200.0),
                (200.0, 0.0),
            ]
            expected_horizontal = [
                (-200.0, 0.0),
                (-70.0, -200.0),
                (50.0, -260.0),
                (170.0, -200.0),
                (200.0, 0.0),
            ]
            window._set_workflow_step("structure")
            window._set_structure_points(raw_points, fit=False)
            window._clear_structure_undo_stack()
            view = window.structure_view
            view._selected_indices = {1, 2, 3}
            view._sync_selected_point_items()

            with mock.patch(
                "gapsim.ui_qt.views.structure_view.QApplication.keyboardModifiers",
                return_value=Qt.KeyboardModifier.ShiftModifier,
            ):
                view._on_item_drag_start_raw(1, -120.0, 200.0)
                view._point_items[1].setPos(QPointF(-70.0, 230.0))
                view._on_item_drag_finish_raw(1, -70.0, 200.0)
            QApplication.processEvents()

            self.assertEqual(tuple(window._structure_points), tuple(expected_horizontal))

            expected_vertical = [
                (-200.0, 0.0),
                (-120.0, -280.0),
                (0.0, -340.0),
                (120.0, -280.0),
                (200.0, 0.0),
            ]
            window._set_structure_points(raw_points, fit=False)
            window._clear_structure_undo_stack()
            view._selected_indices = {1, 2, 3}
            view._sync_selected_point_items()
            with mock.patch(
                "gapsim.ui_qt.views.structure_view.QApplication.keyboardModifiers",
                return_value=Qt.KeyboardModifier.ShiftModifier,
            ):
                view._on_item_drag_start_raw(1, -120.0, 200.0)
                view._point_items[1].setPos(QPointF(-100.0, 280.0))
                view._on_item_drag_finish_raw(1, -120.0, 280.0)
            QApplication.processEvents()

            self.assertEqual(tuple(window._structure_points), tuple(expected_vertical))
        finally:
            window.close()

    def test_structure_view_measurement_region_and_line_emit_user_coordinates(self) -> None:
        view = StructureView()
        view.resize(520, 360)
        view.set_points_xy([(-3.0, 0.0), (-1.0, -5.0), (0.0, -7.0), (1.0, -5.0), (3.0, 0.0)])
        view.show()
        view.fit_points()
        QApplication.processEvents()

        try:
            regions = []
            lines = []
            view.measurementRegionSelected.connect(lambda *args: regions.append(tuple(float(v) for v in args)))
            view.measurementLineSelected.connect(lambda *args: lines.append(tuple(float(v) for v in args)))

            view.begin_measurement_region_selection()
            region_start = QPoint(view.mapFromScene(QPointF(-2.0, -1.0)))
            region_end = QPoint(view.mapFromScene(QPointF(2.0, 8.0)))
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, region_start)
            QTest.mouseMove(view.viewport(), region_end)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, region_end)
            QApplication.processEvents()

            self.assertEqual(len(regions), 1)
            self.assertAlmostEqual(regions[0][0], -2.0, delta=0.2)
            self.assertAlmostEqual(regions[0][1], 1.0, delta=0.2)
            self.assertAlmostEqual(regions[0][2], 2.0, delta=0.2)
            self.assertAlmostEqual(regions[0][3], -8.0, delta=0.2)

            view.begin_measurement_line_selection()
            line_start = QPoint(view.mapFromScene(QPointF(-2.0, 0.0)))
            line_end = QPoint(view.mapFromScene(QPointF(2.0, 0.0)))
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, line_start)
            QTest.mouseMove(view.viewport(), line_end)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, line_end)
            QApplication.processEvents()

            self.assertEqual(len(lines), 1)
            self.assertAlmostEqual(lines[0][0], -2.0, delta=0.2)
            self.assertAlmostEqual(lines[0][1], 0.0, delta=0.2)
            self.assertAlmostEqual(lines[0][2], 2.0, delta=0.2)
            self.assertAlmostEqual(lines[0][3], 0.0, delta=0.2)
        finally:
            view.close()

    def test_geometry_changes_invalidate_result_and_show_latest_preview(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(10.0, 10.0), (20.0, 10.0)]],
            frame_voids=[[]],
            final_profile=[(10.0, 10.0), (20.0, 10.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

        try:
            raw_points = [(-200.0, 0.0), (-120.0, -200.0), (120.0, -200.0), (200.0, 0.0)]
            moved_points = [(-200.0, 0.0), (-90.0, -240.0), (120.0, -200.0), (200.0, 0.0)]
            window._set_structure_points(raw_points, fit=False)
            with mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result):
                window.run_emulation(save_artifacts=False)

            self.assertIs(window._result, result)
            self.assertEqual(tuple(window.view._frame_profiles_raw[0]), tuple(result.frame_profiles[0]))

            window.btn_results_panel_back.click()
            window.btn_progress_panel_back.click()
            window.btn_smoothing_panel_back.click()
            self.assertEqual(window.view_tabs.currentIndex(), 0)
            window._on_structure_point_moved(1, -90.0, -240.0)
            window.btn_structure_panel_next.click()
            window.btn_smoothing_panel_next.click()
            window.btn_progress_panel_next.click()

            self.assertIsNone(window._result)
            self.assertEqual(tuple(window.current_config().points), tuple(moved_points))
            self.assertEqual(tuple(window.view._frame_profiles_raw[0]), tuple(moved_points))
            self.assertIn("입력 미리보기: raw", window.lbl_status.text())
        finally:
            window.close()

    def test_raw_structure_edits_survive_emulator_switch(self) -> None:
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
            custom_points = [(-220.0, 0.0), (-80.0, -260.0), (90.0, -230.0), (220.0, 0.0)]
            window._on_structure_table_replace_points_requested(custom_points)
            self.assertEqual(tuple(window.current_config().points), tuple(custom_points))
            self.assertFalse(window._use_smoothed_geometry)

            window.set_active_emulator_number(2, run=False)

            self.assertEqual(window.active_emulator_number(), 0)
            self.assertEqual(tuple(window._structure_points), tuple(custom_points))
            self.assertEqual(tuple(window.current_config().points), tuple(custom_points))
            self.assertFalse(window._use_smoothed_geometry)
            self.assertEqual(tuple(window.ion_transmission_editor._points), tuple(custom_points))
        finally:
            window.close()

    def test_emulator_switch_preserves_completed_smoothing_geometry(self) -> None:
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
            raw_points = [(-180.0, 0.0), (-90.0, -220.0), (0.0, -280.0), (90.0, -220.0), (180.0, 0.0)]
            window._set_structure_points(raw_points, fit=False)
            window.spin_smooth_segments.setValue(16)
            window.spin_smooth_iterations.setValue(1)
            window.apply_structure_smoothing()
            smoothed_points = tuple(window._smoothed_points)

            window.btn_smoothing_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 2)
            window.btn_progress_panel_next.click()
            self.assertEqual(window.view_tabs.currentIndex(), 3)
            window.set_active_emulator_number(5, run=False)

            self.assertEqual(window.active_emulator_number(), 0)
            self.assertEqual(window.view_tabs.currentIndex(), 3)
            self.assertTrue(window._use_smoothed_geometry)
            self.assertEqual(tuple(window._smoothed_points), smoothed_points)
            self.assertEqual(tuple(window.current_config().points), smoothed_points)
            self.assertEqual(tuple(window.depth_deposition_editor._structure_points), smoothed_points)
            self.assertEqual(tuple(window.inhibition_profile_editor._structure_points), smoothed_points)
            self.assertIn("입력 미리보기: smooth", window.lbl_status.text())
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
            self.assertEqual(window._emulator_numbers, EXPECTED_EMULATOR_NUMBERS)
            self.assertFalse(hasattr(window, "_emulator_buttons"))
            self.assertFalse(hasattr(window, "emulator_group"))
            self.assertEqual(window.cmb_emulator_default_preset.count(), 1)
            self.assertEqual(window.cmb_emulator_default_preset.itemText(0), "기본")
            self.assertFalse(window.chk_sputter.isChecked())
            self.assertFalse(window.chk_ion_transmission.isChecked())
            self.assertFalse(window.chk_redepo.isChecked())
            self.assertFalse(window.chk_depth_deposition.isChecked())
            self.assertFalse(window.chk_inhibition_deposition.isChecked())
        finally:
            window.close()

    def test_window_reports_full_emulator_slots_after_last_default_exists(self) -> None:
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        with (
            mock.patch("gapsim.emulation.trench_depo_ui.run_trench_depo", return_value=result),
            mock.patch("gapsim.emulation.trench_depo_ui.QMessageBox.information") as info_box,
            mock.patch("gapsim.emulation.trench_depo_ui.QTimer.singleShot"),
        ):
            window = TrenchDepoWindow()

            try:
                window.create_new_emulator()

                self.assertEqual(window.active_emulator_number(), 0)
                self.assertEqual(window._emulator_numbers, EXPECTED_EMULATOR_NUMBERS)
                info_box.assert_called_once()
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

                self.assertEqual(window.active_emulator_number(), 0)
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
