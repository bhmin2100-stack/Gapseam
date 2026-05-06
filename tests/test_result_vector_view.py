from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QNativeGestureEvent, QPointingDevice
from PySide6.QtWidgets import QApplication

from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchDepoResult, TrenchSweepResult
from gapsim.emulation.trench_depo_ui import SplitTestWindow
from gapsim.ui_qt.views.result_vector_view import ResultVectorView


class ResultVectorViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_dynamic_substrate_fill_tracks_current_frame(self) -> None:
        frames = [
            [(-10.0, 0.0), (-6.0, -10.0), (6.0, -10.0), (10.0, 0.0)],
            [(-8.0, 0.0), (-4.0, -8.0), (4.0, -8.0), (8.0, 0.0)],
        ]
        view = ResultVectorView()
        view.set_frames(frames, dynamic_substrate_fill=True)
        view.show_frame(1, fit=False)

        substrate = view._substrate_item
        self.assertIsNotNone(substrate)
        bounds = substrate.path().boundingRect()
        self.assertAlmostEqual(bounds.left(), -8.0, places=3)
        self.assertAlmostEqual(bounds.right(), 8.0, places=3)

    def test_static_substrate_fill_stays_at_initial_frame(self) -> None:
        frames = [
            [(-10.0, 0.0), (-6.0, -10.0), (6.0, -10.0), (10.0, 0.0)],
            [(-8.0, 0.0), (-4.0, -8.0), (4.0, -8.0), (8.0, 0.0)],
        ]
        view = ResultVectorView()
        view.set_frames(frames, dynamic_substrate_fill=False)
        view.show_frame(1, fit=False)

        substrate = view._substrate_item
        self.assertIsNotNone(substrate)
        bounds = substrate.path().boundingRect()
        self.assertAlmostEqual(bounds.left(), -10.0, places=3)
        self.assertAlmostEqual(bounds.right(), 10.0, places=3)

    def test_solid_fill_frame_hides_deposition_layers_for_etch_playback(self) -> None:
        frames = [
            [(-10.0, 0.0), (-6.0, -10.0), (6.0, -10.0), (10.0, 0.0)],
            [(-12.0, 0.0), (-7.0, -12.0), (7.0, -12.0), (12.0, 0.0)],
            [(-9.0, 0.0), (-5.0, -9.0), (5.0, -9.0), (9.0, 0.0)],
        ]
        view = ResultVectorView()
        view.set_frames(frames, solid_fill_flags=[False, False, True])
        view.show_frame(1, fit=False)

        self.assertTrue(any(item is not None and item.isVisible() for item in view._layer_items))

        view.show_frame(2, fit=False)

        self.assertFalse(any(item is not None and item.isVisible() for item in view._layer_items))
        substrate = view._substrate_item
        self.assertIsNotNone(substrate)
        bounds = substrate.path().boundingRect()
        self.assertAlmostEqual(bounds.left(), -9.0, places=3)
        self.assertAlmostEqual(bounds.right(), 9.0, places=3)

    def test_ghost_history_mode_shows_faint_lines_without_filled_layers(self) -> None:
        frames = [
            [(-10.0, 0.0), (-6.0, -10.0), (6.0, -10.0), (10.0, 0.0)],
            [(-12.0, 0.0), (-7.0, -12.0), (7.0, -12.0), (12.0, 0.0)],
            [(-9.0, 0.0), (-5.0, -9.0), (5.0, -9.0), (9.0, 0.0)],
        ]
        view = ResultVectorView()
        view.set_frames(frames, dynamic_substrate_fill=True, history_mode="ghost_lines")
        view.show_frame(2, fit=False)

        self.assertEqual(view._history_mode, "ghost_lines")
        self.assertTrue(any(item is not None and item.isVisible() for item in view._history_line_items))
        self.assertFalse(any(item is not None and item.isVisible() for item in view._layer_items))
        substrate = view._substrate_item
        self.assertIsNotNone(substrate)
        bounds = substrate.path().boundingRect()
        self.assertAlmostEqual(bounds.left(), -9.0, places=3)
        self.assertAlmostEqual(bounds.right(), 9.0, places=3)

    def test_mixed_etch_mode_keeps_added_film_colored_and_removed_material_faint(self) -> None:
        frames = [
            [(-10.0, 0.0), (10.0, 0.0)],
            [(-12.0, 0.0), (8.0, 0.0)],
        ]
        view = ResultVectorView()
        view.set_frames(frames, dynamic_substrate_fill=True, history_mode="mixed_etch")
        view.show_frame(1, fit=False)

        self.assertEqual(view._history_mode, "mixed_etch")
        visible_layers = [item for item in view._layer_items if item is not None and item.isVisible()]
        visible_ghosts = [item for item in view._etch_ghost_items if item is not None and item.isVisible()]
        self.assertTrue(visible_layers)
        self.assertTrue(visible_ghosts)

        added_bounds = visible_layers[0].path().boundingRect()
        ghost_bounds = visible_ghosts[0].path().boundingRect()
        self.assertLessEqual(added_bounds.right(), -9.9)
        self.assertGreaterEqual(ghost_bounds.left(), 7.9)

    def test_mixed_etch_mode_hides_removed_ghost_after_redeposition(self) -> None:
        frames = [
            [(-10.0, 0.0), (10.0, 0.0)],
            [(-10.0, 0.0), (8.0, 0.0)],
            [(-12.0, 0.0), (10.0, 0.0)],
        ]
        view = ResultVectorView()
        view.set_frames(frames, dynamic_substrate_fill=True, history_mode="mixed_etch")
        view.show_frame(2, fit=False)

        self.assertTrue(any(item is not None and item.isVisible() for item in view._layer_items))
        self.assertFalse(any(item is not None and item.isVisible() for item in view._etch_ghost_items))

    def test_zoom_helper_can_zoom_in_and_out(self) -> None:
        view = ResultVectorView()
        view.resize(400, 300)
        view.set_frames([[(-10.0, 0.0), (10.0, 0.0)]])
        view.fit_content()

        initial = view.transform().m11()
        view._zoom_at_view_pos(2.0, QPointF(200.0, 150.0))
        zoomed_in = view.transform().m11()
        view._zoom_at_view_pos(0.5, QPointF(200.0, 150.0))
        zoomed_out = view.transform().m11()

        self.assertGreater(zoomed_in, initial)
        self.assertAlmostEqual(zoomed_out, initial, delta=max(1e-6, initial * 1e-6))

    def test_zoom_helper_keeps_anchor_scene_point_stable(self) -> None:
        view = ResultVectorView()
        view.resize(400, 300)
        view.set_frames([[(-20.0, 0.0), (20.0, 0.0)]])
        view.fit_content()

        anchor = QPointF(160.0, 120.0)
        before = view.mapToScene(anchor.toPoint())
        view._zoom_at_view_pos(2.0, anchor)
        after = view.mapToScene(anchor.toPoint())

        self.assertAlmostEqual(after.x(), before.x(), delta=1e-6)
        self.assertAlmostEqual(after.y(), before.y(), delta=1e-6)

    def test_native_zoom_ignores_implausible_local_anchor(self) -> None:
        class EventWithWindowRelativePosition:
            def position(self) -> QPointF:
                return QPointF(5000.0, 4000.0)

        view = ResultVectorView()
        view.resize(400, 300)

        pos = view._event_view_pos(EventWithWindowRelativePosition())
        center = QPointF(view.viewport().rect().center())

        self.assertAlmostEqual(pos.x(), center.x(), delta=1.0)
        self.assertAlmostEqual(pos.y(), center.y(), delta=1.0)

    def test_viewport_state_can_be_applied_to_another_view(self) -> None:
        frames = [[(-10.0, 0.0), (10.0, 0.0)]]
        wider_frames = [[(-100.0, 0.0), (100.0, 0.0)]]
        left = ResultVectorView()
        right = ResultVectorView()
        left.resize(400, 300)
        left.set_frames(frames)
        left.fit_content()
        right.resize(400, 300)
        right.set_frames(wider_frames)
        right.fit_content()

        left._zoom_at_view_pos(2.0, QPointF(200.0, 150.0))
        right.apply_viewport_state(left.viewport_state())

        self.assertAlmostEqual(right.transform().m11(), left.transform().m11(), places=9)
        left_center = left.mapToScene(left.viewport().rect().center())
        right_center = right.mapToScene(right.viewport().rect().center())
        self.assertAlmostEqual(right_center.x(), left_center.x(), delta=1.0)
        self.assertAlmostEqual(right_center.y(), left_center.y(), delta=1.0)

    def test_zoom_emits_viewport_changed(self) -> None:
        view = ResultVectorView()
        view.resize(400, 300)
        view.set_frames([[(-10.0, 0.0), (10.0, 0.0)]])
        view.fit_content()
        seen = []
        view.viewportChanged.connect(seen.append)

        view._zoom_at_view_pos(1.5, QPointF(200.0, 150.0))

        self.assertTrue(seen)
        self.assertIn("transform", seen[-1])

    def test_split_window_syncs_viewport_changes(self) -> None:
        frames = [[(-10.0, 0.0), (10.0, 0.0)]]
        cases = [
            TrenchSweepResult(
                parameter="angstrom_per_cycle",
                label="Depo A/CYC",
                value=float(value),
                config=TrenchDepoConfig(cycles=0, angstrom_per_cycle=float(value)),
                result=TrenchDepoResult(
                    frame_steps=[0],
                    frame_profiles=frames,
                    frame_voids=[[]],
                    final_profile=frames[-1],
                    meta={"cycles": 0},
                ),
            )
            for value in (5.0, 10.0)
        ]
        window = SplitTestWindow(cases)
        window.fit_all_views()

        source = window._views[0]
        target = window._views[1]
        source._zoom_at_view_pos(1.7, QPointF(200.0, 150.0))
        QApplication.processEvents()

        self.assertAlmostEqual(target.transform().m11(), source.transform().m11(), places=9)
        window.close()

    def test_split_window_keeps_film_history_when_deposition_is_dominant(self) -> None:
        frames = [
            [(-10.0, 0.0), (10.0, 0.0)],
            [(-12.0, 0.0), (12.0, 0.0)],
        ]
        case = TrenchSweepResult(
            parameter="sputter_strength_a_per_cycle",
            label="Etch A/CYC",
            value=4.0,
            config=TrenchDepoConfig(cycles=1, sputter_enabled=True, sputter_strength_a_per_cycle=4.0),
            result=TrenchDepoResult(
                frame_steps=[0, 1],
                frame_profiles=frames,
                frame_voids=[[], []],
                final_profile=frames[-1],
                meta={
                    "cycles": 1,
                    "angstrom_per_cycle": 10.0,
                    "sputter_active": True,
                    "sputter_strength_a_per_cycle": 4.0,
                },
            ),
        )

        window = SplitTestWindow([case])
        view = window._views[0]
        view.show_frame(1, fit=False)
        self.assertFalse(any(view._solid_fill_flags))
        self.assertEqual(view._history_mode, "film")
        self.assertFalse(any(item is not None and item.isVisible() for item in view._history_line_items))
        self.assertTrue(any(item is not None and item.isVisible() for item in view._layer_items))
        window.close()

    def test_split_window_uses_mixed_etch_history_when_etch_is_dominant(self) -> None:
        frames = [
            [(-10.0, 0.0), (10.0, 0.0)],
            [(-12.0, 0.0), (8.0, 0.0)],
        ]
        case = TrenchSweepResult(
            parameter="sputter_strength_a_per_cycle",
            label="Etch A/CYC",
            value=12.0,
            config=TrenchDepoConfig(cycles=1, sputter_enabled=True, sputter_strength_a_per_cycle=12.0),
            result=TrenchDepoResult(
                frame_steps=[0, 1],
                frame_profiles=frames,
                frame_voids=[[], []],
                final_profile=frames[-1],
                meta={
                    "cycles": 1,
                    "angstrom_per_cycle": 10.0,
                    "sputter_active": True,
                    "sputter_strength_a_per_cycle": 12.0,
                },
            ),
        )

        window = SplitTestWindow([case])
        view = window._views[0]
        view.show_frame(1, fit=False)
        self.assertTrue(all(view._solid_fill_flags))
        self.assertEqual(view._history_mode, "mixed_etch")
        self.assertFalse(any(item is not None and item.isVisible() for item in view._history_line_items))
        self.assertTrue(any(item is not None and item.isVisible() for item in view._layer_items))
        self.assertTrue(any(item is not None and item.isVisible() for item in view._etch_ghost_items))
        window.close()

    def test_zoom_amplification_preserves_direction(self) -> None:
        view = ResultVectorView()

        self.assertGreater(view._amplify_zoom_factor(1.02, 4.0), 1.02)
        self.assertLess(view._amplify_zoom_factor(0.98, 4.0), 0.98)

    def test_native_zoom_gesture_negative_value_zooms_out(self) -> None:
        view = ResultVectorView()
        view.resize(400, 300)
        view.set_frames([[(-10.0, 0.0), (10.0, 0.0)]])
        view.fit_content()

        initial = view.transform().m11()
        device = QPointingDevice.primaryPointingDevice()
        event = QNativeGestureEvent(
            Qt.NativeGestureType.ZoomNativeGesture,
            device,
            2,
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            -0.25,
            QPointF(0.0, 0.0),
        )

        self.assertTrue(view._handle_zoom_gesture_event(event))
        self.assertLess(view.transform().m11(), initial)

    def test_native_zoom_gesture_ignores_small_opposite_jitter(self) -> None:
        view = ResultVectorView()
        view.resize(400, 300)
        view.set_frames([[(-10.0, 0.0), (10.0, 0.0)]])
        view.fit_content()

        device = QPointingDevice.primaryPointingDevice()
        zoom_in = QNativeGestureEvent(
            Qt.NativeGestureType.ZoomNativeGesture,
            device,
            2,
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            0.04,
            QPointF(0.0, 0.0),
        )
        small_opposite_noise = QNativeGestureEvent(
            Qt.NativeGestureType.ZoomNativeGesture,
            device,
            2,
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            -0.003,
            QPointF(0.0, 0.0),
        )

        self.assertTrue(view._handle_zoom_gesture_event(zoom_in))
        after_zoom_in = view.transform().m11()
        self.assertTrue(view._handle_zoom_gesture_event(small_opposite_noise))

        self.assertAlmostEqual(view.transform().m11(), after_zoom_in, delta=after_zoom_in * 1e-9)

    def test_native_zoom_gesture_locks_direction_for_one_stroke(self) -> None:
        view = ResultVectorView()
        view.resize(400, 300)
        view.set_frames([[(-10.0, 0.0), (10.0, 0.0)]])
        view.fit_content()

        device = QPointingDevice.primaryPointingDevice()
        zoom_in = QNativeGestureEvent(
            Qt.NativeGestureType.ZoomNativeGesture,
            device,
            2,
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            0.06,
            QPointF(0.0, 0.0),
        )
        opposite_stroke_noise = QNativeGestureEvent(
            Qt.NativeGestureType.ZoomNativeGesture,
            device,
            2,
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            QPointF(200.0, 150.0),
            -0.08,
            QPointF(0.0, 0.0),
        )

        self.assertTrue(view._handle_zoom_gesture_event(zoom_in))
        after_zoom_in = view.transform().m11()
        self.assertTrue(view._handle_zoom_gesture_event(opposite_stroke_noise))

        self.assertAlmostEqual(view.transform().m11(), after_zoom_in, delta=after_zoom_in * 1e-9)


if __name__ == "__main__":
    unittest.main()
