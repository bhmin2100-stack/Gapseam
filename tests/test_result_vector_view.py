from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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


if __name__ == "__main__":
    unittest.main()
