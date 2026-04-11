from __future__ import annotations

import unittest

from gapsim.ui_qt.models.points_table import PointsTableModel


class PointsTableModelTest(unittest.TestCase):
    def test_endpoints_are_forced_outside_inner_points(self) -> None:
        model = PointsTableModel()
        model.set_points(
            [
                (500.0, 0.0),
                (250.0, 0.0),
                (125.0, -4000.0),
                (-125.0, -4000.0),
                (-250.0, 0.0),
                (-500.0, 0.0),
            ]
        )

        self.assertTrue(model.set_point(1, (700.0, 0.0)))
        pts = model.get_points()
        self.assertGreater(pts[0][0], pts[1][0])

        self.assertTrue(model.set_point(4, (-700.0, 0.0)))
        pts = model.get_points()
        self.assertLess(pts[-1][0], pts[-2][0])

    def test_set_points_normalizes_endpoint_x_bounds(self) -> None:
        model = PointsTableModel()
        model.set_points(
            [
                (200.0, 0.0),
                (250.0, -10.0),
                (100.0, -50.0),
                (-250.0, -10.0),
                (-200.0, 0.0),
            ]
        )
        pts = model.get_points()
        self.assertGreater(pts[0][0], max(p[0] for p in pts[1:]))
        self.assertLess(pts[-1][0], min(p[0] for p in pts[:-1]))


if __name__ == "__main__":
    unittest.main()
