from __future__ import annotations

import math
import unittest

from gapsim.engine.deposition_pipeline import REPARAM_DS_A, SIO2_L_MIN_A, equal_arc_resample


def _dist(a, b) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


class DepositionReparameterizationTest(unittest.TestCase):
    def test_physical_scale_constants(self) -> None:
        self.assertAlmostEqual(SIO2_L_MIN_A, 5.0, places=9)
        self.assertAlmostEqual(REPARAM_DS_A, 2.5, places=9)

    def test_equal_arc_resample_preserves_endpoints(self) -> None:
        pts = [(-200.0, 0.0), (-50.0, -300.0), (80.0, -300.0), (200.0, 0.0)]
        out = equal_arc_resample(pts, REPARAM_DS_A)
        self.assertGreaterEqual(len(out), 2)
        self.assertAlmostEqual(out[0][0], pts[0][0], places=9)
        self.assertAlmostEqual(out[0][1], pts[0][1], places=9)
        self.assertAlmostEqual(out[-1][0], pts[-1][0], places=9)
        self.assertAlmostEqual(out[-1][1], pts[-1][1], places=9)

    def test_equal_arc_resample_spacing_bounded(self) -> None:
        pts = [(-250.0, 0.0), (-120.0, -120.0), (-40.0, -320.0), (20.0, -320.0), (120.0, -120.0), (250.0, 0.0)]
        out = equal_arc_resample(pts, REPARAM_DS_A)
        self.assertGreater(len(out), len(pts))
        segs = [_dist(out[i], out[i + 1]) for i in range(len(out) - 1)]
        self.assertTrue(all(s <= (REPARAM_DS_A + 1e-7) for s in segs))
        self.assertTrue(all(s > 0.0 for s in segs))


if __name__ == "__main__":
    unittest.main()
