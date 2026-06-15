from __future__ import annotations

import math
import unittest

from gapsim.emulation.dent_analysis import (
    DentLine,
    DentRegion,
    analyze_dent_frames,
    measure_dent_depth,
    measure_profile_slope,
)


class DentAnalysisTest(unittest.TestCase):
    def test_dent_depth_uses_selected_axis_inside_region(self) -> None:
        profile = [(-2.0, 0.0), (-1.0, -1.0), (0.0, -5.0), (1.0, -2.0), (2.0, 0.0)]

        self.assertAlmostEqual(measure_dent_depth(profile, DentRegion(-2.0, -6.0, 2.0, 1.0), "vertical") or 0.0, 5.0)
        self.assertAlmostEqual(measure_dent_depth(profile, DentRegion(-1.0, -6.0, 1.0, 1.0), "horizontal") or 0.0, 2.0)

    def test_slope_delta_compares_profile_segment_to_reference_line(self) -> None:
        profile = [(-2.0, 0.0), (0.0, 1.0), (2.0, 1.0)]
        region = DentRegion(-3.0, -1.0, 3.0, 2.0)
        reference = DentLine(-2.0, 0.0, 2.0, 0.0)

        slope_delta, film_angle, reference_angle = measure_profile_slope(profile, region, reference)

        self.assertAlmostEqual(reference_angle or 0.0, 0.0)
        self.assertAlmostEqual(film_angle or 0.0, math.degrees(math.atan2(1.0, 2.0)))
        self.assertAlmostEqual(slope_delta or 0.0, math.degrees(math.atan2(1.0, 2.0)))

    def test_analyze_dent_frames_tracks_cycle_and_thickness(self) -> None:
        frames = [
            [(-2.0, 0.0), (0.0, -1.0), (2.0, 0.0)],
            [(-2.0, 0.0), (0.0, -3.0), (2.0, 0.0)],
        ]

        samples = analyze_dent_frames(
            frames,
            [0, 4],
            DentRegion(-2.0, -4.0, 2.0, 1.0),
            "vertical",
            slope_line=DentLine(-2.0, 0.0, 2.0, 0.0),
            angstrom_per_cycle=12.5,
        )

        self.assertEqual([sample.cycle for sample in samples], [0, 4])
        self.assertEqual([sample.thickness_a for sample in samples], [0.0, 50.0])
        self.assertAlmostEqual(samples[-1].dent_depth_a or 0.0, 3.0)
        self.assertIsNotNone(samples[-1].slope_delta_deg)


if __name__ == "__main__":
    unittest.main()
