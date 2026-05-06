from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gapsim.engine.deposition_pipeline import equal_arc_resample
from gapsim.emulation.trench_depo import (
    BOWED_JAR_TRENCH_POINTS,
    DEFAULT_TRENCH_POINTS,
    ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
    TrenchDepoConfig,
    TrenchDepoResult,
    TrenchSweepResult,
    build_trench_depo_sweep_configs,
    compute_depth_deposition_factors,
    compute_depth_deposition_ratio,
    compute_effective_aspect_ratio,
    compute_inhibition_deposition_factors,
    compute_ion_transmission_factors,
    direct_sputter_angle_response,
    direct_sputter_incident_angles_deg,
    run_trench_depo,
    run_trench_depo_legacy_sputter,
    run_trench_depo_sweep,
    vertex_air_normals,
)
from gapsim.emulation.model4_redeposition import Model4RedepositionParams, compute_redeposition
from gapsim.emulation.trench_depo_export import export_trench_depo_run
from gapsim.emulation.trench_depo_export import export_trench_depo_sweep_runs
from gapsim.emulation.trench_depo_export import load_trench_depo_run
from gapsim.emulation.trench_depo_export import load_trench_depo_split_group

try:
    import pyclipper  # noqa: F401
except Exception:  # noqa: BLE001
    pyclipper = None  # type: ignore[assignment]


class TrenchDepoEmulationTest(unittest.TestCase):
    def assertProfilesAlmostEqual(self, left, right, *, places: int = 9) -> None:
        self.assertEqual(len(left), len(right))
        for frame_l, frame_r in zip(left, right):
            self.assertEqual(len(frame_l), len(frame_r))
            for point_l, point_r in zip(frame_l, frame_r):
                self.assertAlmostEqual(point_l[0], point_r[0], places=places)
                self.assertAlmostEqual(point_l[1], point_r[1], places=places)

    def sidewall_roughness(self, profile) -> float:
        pts = [p for p in profile if -220.0 < float(p[0]) < -90.0 and 20.0 < float(p[1]) < 260.0]
        vals = []
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            ax, ay = a
            bx, by = b
            cx, cy = c
            dx = cx - ax
            dy = cy - ay
            den = math.hypot(dx, dy)
            if den > 1e-9:
                vals.append(abs((dy * bx - dx * by + cx * ay - cy * ax) / den))
        return max(vals) if vals else 0.0

    def y_near(self, profile, target_x: float) -> float:
        return min(profile, key=lambda p: abs(float(p[0]) - target_x))[1]

    def polygon_area(self, polygon) -> float:
        if len(polygon) < 3:
            return 0.0
        area2 = 0.0
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
            area2 += float(x1) * float(y2) - float(x2) * float(y1)
        return abs(area2) * 0.5

    def test_default_config_uses_10a_per_cycle_and_sample_trench(self) -> None:
        config = TrenchDepoConfig()

        self.assertEqual(tuple(config.points), DEFAULT_TRENCH_POINTS)
        self.assertEqual(DEFAULT_TRENCH_POINTS[0], (1500.0, 0.0))
        self.assertEqual(DEFAULT_TRENCH_POINTS[-1], (-1500.0, 0.0))
        self.assertEqual(config.cycles, 20)
        self.assertAlmostEqual(config.angstrom_per_cycle, 10.0, places=9)
        self.assertAlmostEqual(config.sputter_peak_pct, 100.0, places=9)
        self.assertAlmostEqual(config.sputter_smoothing_a, 40.0, places=9)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_cycles_create_n_plus_one_frames(self) -> None:
        result = run_trench_depo(TrenchDepoConfig(cycles=2))

        self.assertEqual(result.frame_steps, [0, 1, 2])
        self.assertEqual(len(result.frame_profiles), 3)
        self.assertEqual(len(result.frame_voids), 3)
        self.assertEqual(result.meta["cycles"], 2)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_three_cycles_grow_top_field_by_about_30a(self) -> None:
        result = run_trench_depo(TrenchDepoConfig(cycles=3, angstrom_per_cycle=10.0))

        self.assertAlmostEqual(result.final_profile[0][1], 30.0, delta=0.1)
        self.assertAlmostEqual(result.final_profile[-1][1], 30.0, delta=0.1)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_one_cycle_keeps_flat_field_uniform_before_lip_rounding(self) -> None:
        result = run_trench_depo(TrenchDepoConfig(cycles=1, angstrom_per_cycle=10.0))

        left_field = [
            y
            for x, y in result.final_profile
            if -1500.0 <= float(x) <= -255.0
        ]
        right_field = [
            y
            for x, y in result.final_profile
            if 255.0 <= float(x) <= 1500.0
        ]

        self.assertGreater(len(left_field), 10)
        self.assertGreater(len(right_field), 10)
        self.assertLess(max(left_field) - min(left_field), 0.01)
        self.assertLess(max(right_field) - min(right_field), 0.01)
        self.assertAlmostEqual(sum(left_field) / len(left_field), 10.0, delta=0.01)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_custom_angstrom_per_cycle_controls_growth(self) -> None:
        result = run_trench_depo(TrenchDepoConfig(cycles=2, angstrom_per_cycle=5.0))

        self.assertAlmostEqual(result.final_profile[0][1], 10.0, delta=0.1)
        self.assertAlmostEqual(result.meta["angstrom_per_cycle"], 5.0, places=9)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_sputter_off_matches_conformal_only(self) -> None:
        baseline = run_trench_depo(TrenchDepoConfig(cycles=2, angstrom_per_cycle=10.0))
        with_sputter_off = run_trench_depo(
            TrenchDepoConfig(
                cycles=2,
                angstrom_per_cycle=10.0,
                sputter_enabled=False,
                sputter_strength_a_per_cycle=12.0,
            )
        )

        self.assertProfilesAlmostEqual(baseline.frame_profiles, with_sputter_off.frame_profiles)
        self.assertFalse(with_sputter_off.meta["sputter_active"])

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_zero_sputter_strength_matches_conformal_only(self) -> None:
        baseline = run_trench_depo(TrenchDepoConfig(cycles=2, angstrom_per_cycle=10.0))
        zero_strength = run_trench_depo(
            TrenchDepoConfig(
                cycles=2,
                angstrom_per_cycle=10.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=0.0,
            )
        )

        self.assertProfilesAlmostEqual(baseline.frame_profiles, zero_strength.frame_profiles)
        self.assertFalse(zero_strength.meta["sputter_active"])

    def test_direct_sputter_angle_response_varies_by_surface_angle(self) -> None:
        flat_angle = direct_sputter_incident_angles_deg([(0.0, 0.0), (100.0, 0.0)])[0]
        vertical_angle = direct_sputter_incident_angles_deg([(0.0, 0.0), (0.0, -100.0)])[0]
        slope_angle = direct_sputter_incident_angles_deg(
            [(0.0, 0.0), (math.cos(math.radians(55.0)), -math.sin(math.radians(55.0)))]
        )[0]

        self.assertAlmostEqual(flat_angle, 0.0, places=6)
        self.assertAlmostEqual(vertical_angle, 90.0, places=6)
        self.assertAlmostEqual(slope_angle, 55.0, places=6)
        slope_response = direct_sputter_angle_response(slope_angle, peak_angle_deg=55.0, width_deg=10.0)
        half_slope_response = direct_sputter_angle_response(
            slope_angle,
            peak_angle_deg=55.0,
            width_deg=10.0,
            peak_pct=50.0,
        )
        flat_response = direct_sputter_angle_response(flat_angle, peak_angle_deg=55.0, width_deg=10.0)
        vertical_response = direct_sputter_angle_response(vertical_angle, peak_angle_deg=55.0, width_deg=10.0)
        self.assertAlmostEqual(half_slope_response, slope_response * 0.5, places=6)
        self.assertGreater(slope_response, flat_response)
        self.assertGreater(slope_response, vertical_response)

    def test_direct_sputter_peak_angle_is_configurable(self) -> None:
        response_35_at_35 = direct_sputter_angle_response(35.0, peak_angle_deg=35.0, width_deg=8.0)
        response_65_at_35 = direct_sputter_angle_response(65.0, peak_angle_deg=35.0, width_deg=8.0)
        response_35_at_65 = direct_sputter_angle_response(35.0, peak_angle_deg=65.0, width_deg=8.0)
        response_65_at_65 = direct_sputter_angle_response(65.0, peak_angle_deg=65.0, width_deg=8.0)

        self.assertGreater(response_35_at_35, response_65_at_35)
        self.assertGreater(response_65_at_65, response_35_at_65)

    def test_sweep_configs_generate_expected_values(self) -> None:
        cases = build_trench_depo_sweep_configs(
            TrenchDepoConfig(cycles=2, angstrom_per_cycle=10.0),
            "sputter_strength_a_per_cycle",
            0.0,
            8.0,
            4.0,
        )

        self.assertEqual([case.value for case in cases], [0.0, 4.0, 8.0])
        self.assertTrue(all(case.config.sputter_enabled for case in cases))
        self.assertEqual([case.config.sputter_strength_a_per_cycle for case in cases], [0.0, 4.0, 8.0])

    def test_sweep_configs_allow_zero_deposition(self) -> None:
        cases = build_trench_depo_sweep_configs(
            TrenchDepoConfig(cycles=1),
            "angstrom_per_cycle",
            0.0,
            10.0,
            5.0,
        )

        self.assertEqual([case.config.angstrom_per_cycle for case in cases], [0.0, 5.0, 10.0])

    def test_sweep_configs_preserve_other_parameters(self) -> None:
        base = TrenchDepoConfig(
            cycles=7,
            angstrom_per_cycle=12.5,
            sputter_enabled=False,
            sputter_strength_a_per_cycle=3.0,
            sputter_peak_angle_deg=55.0,
            sputter_width_deg=14.0,
        )

        cases = build_trench_depo_sweep_configs(base, "sputter_peak_angle_deg", 35.0, 55.0, 20.0)

        self.assertEqual([case.value for case in cases], [35.0, 55.0])
        for case in cases:
            self.assertEqual(case.config.cycles, 7)
            self.assertAlmostEqual(case.config.angstrom_per_cycle, 12.5, places=9)
            self.assertAlmostEqual(case.config.sputter_strength_a_per_cycle, 3.0, places=9)
            self.assertAlmostEqual(case.config.sputter_width_deg, 14.0, places=9)
            self.assertTrue(case.config.sputter_enabled)

    def test_sweep_configs_can_descend(self) -> None:
        cases = build_trench_depo_sweep_configs(TrenchDepoConfig(), "cycles", 10.0, 0.0, 5.0)

        self.assertEqual([case.config.cycles for case in cases], [10, 5, 0])

    def test_invalid_sweep_inputs_fail_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "sweep step"):
            build_trench_depo_sweep_configs(TrenchDepoConfig(), "angstrom_per_cycle", 1.0, 3.0, 0.0)

        with self.assertRaisesRegex(ValueError, "unsupported sweep parameter"):
            build_trench_depo_sweep_configs(TrenchDepoConfig(), "old_ion_los", 1.0, 3.0, 1.0)

        with self.assertRaisesRegex(ValueError, "sputter_peak_angle_deg"):
            build_trench_depo_sweep_configs(TrenchDepoConfig(), "sputter_peak_angle_deg", 100.0, 110.0, 5.0)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_run_sweep_returns_one_result_per_value(self) -> None:
        cases = run_trench_depo_sweep(
            TrenchDepoConfig(cycles=1, angstrom_per_cycle=10.0),
            "angstrom_per_cycle",
            5.0,
            10.0,
            5.0,
        )

        self.assertEqual([case.value for case in cases], [5.0, 10.0])
        self.assertEqual([len(case.result.frame_profiles) for case in cases], [2, 2])
        self.assertLess(cases[0].result.final_profile[0][1], cases[1].result.final_profile[0][1])

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_direct_sputter_changes_sloped_corner_profile(self) -> None:
        baseline = run_trench_depo(TrenchDepoConfig(cycles=4, angstrom_per_cycle=10.0))
        sputtered = run_trench_depo(
            TrenchDepoConfig(
                cycles=4,
                angstrom_per_cycle=10.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=16.0,
                sputter_peak_angle_deg=55.0,
                sputter_width_deg=10.0,
            )
        )

        def y_near(profile, target_x: float) -> float:
            return min(profile, key=lambda p: abs(float(p[0]) - target_x))[1]

        self.assertTrue(sputtered.meta["sputter_active"])
        self.assertLess(y_near(sputtered.final_profile, -220.0), y_near(baseline.final_profile, -220.0))
        self.assertLess(y_near(sputtered.final_profile, 220.0), y_near(baseline.final_profile, 220.0))

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_direct_sputter_substeps_suppress_large_etch_sidewall_teeth(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                cycles=10,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                sputter_smoothing_a=0.0,
            )
        )

        self.assertGreater(result.meta["direct_sputter_internal_substeps"], 1)
        self.assertLess(self.sidewall_roughness(result.final_profile), 0.1)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_direct_sputter_supports_etch_only_without_deposition(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                cycles=10,
                angstrom_per_cycle=0.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                sputter_smoothing_a=40.0,
            )
        )

        self.assertEqual(len(result.frame_profiles), 11)
        self.assertTrue(result.meta["sputter_active"])
        self.assertGreater(result.meta["direct_sputter_internal_substeps"], 1)
        self.assertLess(self.sidewall_roughness(result.final_profile), 0.1)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_direct_sputter_smoothing_does_not_bleed_into_flat_bottom(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                cycles=6,
                angstrom_per_cycle=0.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                sputter_peak_angle_deg=55.0,
                sputter_width_deg=14.0,
                sputter_smoothing_a=80.0,
            )
        )

        self.assertAlmostEqual(self.y_near(result.final_profile, 0.0), -4000.0, delta=0.5)

    def test_model4_redeposition_reflection_lobe_can_target_bottom(self) -> None:
        points = equal_arc_resample(DEFAULT_TRENCH_POINTS, 25.0)
        normals = vertex_air_normals(points)
        surface_y = max(y for _x, y in points)
        bottom_y = min(y for _x, y in points)
        depth_span = surface_y - bottom_y
        source_candidates = [
            idx
            for idx, (x, y) in enumerate(points)
            if x < 0.0 and 0.55 <= ((surface_y - y) / depth_span) <= 0.70
        ]
        source_idx = max(source_candidates, key=lambda idx: abs(normals[idx][0]))
        etch = [0.0 for _ in points]
        etch[source_idx] = 10.0

        redepo = compute_redeposition(
            points,
            normals,
            etch,
            Model4RedepositionParams(
                redepo_efficiency=1.0,
                distance_power=0.0,
                max_redepo_distance=0.0,
                lateral_spread_a=0.0,
                max_redepo_to_etch_ratio=0.0,
            ),
        )

        bottom_redepo = sum(
            redepo.dh_redepo[idx]
            for idx, (_x, y) in enumerate(points)
            if abs(y - bottom_y) < 1e-6
        )

        self.assertEqual(redepo.debug_summary["transport_model"], "gapsim_binned_lobe_los")
        self.assertGreater(bottom_redepo, 0.0)
        self.assertGreater(redepo.debug_summary["active_source_count"], 0)

    def test_model4_redeposition_preserves_symmetric_source_field(self) -> None:
        points = equal_arc_resample(DEFAULT_TRENCH_POINTS, 40.0)
        normals = vertex_air_normals(points)
        etch = [
            5.0 if abs(nx) > 0.2 and y < -500.0 else 0.0
            for (x, y), (nx, _ny) in zip(points, normals)
        ]

        redepo = compute_redeposition(
            points,
            normals,
            etch,
            Model4RedepositionParams(redepo_efficiency=0.5),
        )

        mirrored_pairs = []
        for idx, (x, y) in enumerate(points):
            if x >= -1e-6:
                continue
            mirror_idx = min(
                range(len(points)),
                key=lambda j: abs(points[j][0] + x) + abs(points[j][1] - y),
            )
            if abs(points[mirror_idx][0] + x) < 1e-6 and abs(points[mirror_idx][1] - y) < 1e-6:
                mirrored_pairs.append((idx, mirror_idx))

        self.assertTrue(mirrored_pairs)
        self.assertTrue(redepo.debug_summary["symmetry_preserved"])
        self.assertLessEqual(
            max(abs(redepo.dh_redepo[i] - redepo.dh_redepo[j]) for i, j in mirrored_pairs),
            1e-9,
        )

    def test_model4_redeposition_lateral_spread_smooths_sidewall_dh(self) -> None:
        points = equal_arc_resample(DEFAULT_TRENCH_POINTS, 40.0)
        normals = vertex_air_normals(points)
        etch = [
            5.0 if abs(nx) > 0.2 and y < -500.0 else 0.0
            for (x, y), (nx, _ny) in zip(points, normals)
        ]

        def sidewall_dh_roughness(values) -> float:
            deltas = []
            for idx in range(len(values) - 1):
                x0, _y0 = points[idx]
                x1, _y1 = points[idx + 1]
                nx0, _ny0 = normals[idx]
                nx1, _ny1 = normals[idx + 1]
                if abs(nx0) >= 0.18 and abs(nx1) >= 0.18 and x0 * x1 > 0.0:
                    deltas.append(abs(values[idx + 1] - values[idx]))
            return sum(deltas) / max(1, len(deltas))

        unsmoothed = compute_redeposition(
            points,
            normals,
            etch,
            Model4RedepositionParams(redepo_efficiency=0.5, lateral_spread_a=0.0),
        )
        smoothed = compute_redeposition(
            points,
            normals,
            etch,
            Model4RedepositionParams(redepo_efficiency=0.5, lateral_spread_a=55.0),
        )

        self.assertEqual(unsmoothed.debug_summary["redepo_spread_radius_points"], 0)
        self.assertGreater(smoothed.debug_summary["redepo_spread_radius_points"], 0)
        self.assertLess(
            sidewall_dh_roughness(smoothed.dh_redepo),
            sidewall_dh_roughness(unsmoothed.dh_redepo),
        )
        self.assertAlmostEqual(
            smoothed.debug_summary["total_redepo_mass"],
            unsmoothed.debug_summary["total_redepo_mass"],
            places=9,
        )

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_model4_redeposition_regularizes_profile_delta(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                cycles=2,
                angstrom_per_cycle=10.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=12.0,
                sputter_smoothing_a=40.0,
                redepo_enabled=True,
                redepo_efficiency_pct=25.0,
            )
        )
        fields = result.meta["redepo_debug_fields_last"]
        raw_delta = [
            float(redepo) - float(etch)
            for redepo, etch in zip(fields["redepo_field"], fields["sputter_effective_field"])
        ]
        regularized_delta = [float(v) for v in fields["profile_delta_field"]]

        def adjacent_roughness(values) -> float:
            return sum(
                abs(float(values[idx + 1]) - float(values[idx]))
                for idx in range(len(values) - 1)
            ) / max(1, len(values) - 1)

        self.assertGreater(
            result.meta["redepo_debug_summary_last"]["redepo"]["profile_smooth_radius_points"],
            0,
        )
        self.assertLess(adjacent_roughness(regularized_delta), adjacent_roughness(raw_delta))

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_reflected_ion_off_and_zero_strength_match_emulator_one(self) -> None:
        base = TrenchDepoConfig(
            cycles=3,
            angstrom_per_cycle=0.0,
            sputter_enabled=True,
            sputter_strength_a_per_cycle=8.0,
            sputter_peak_angle_deg=55.0,
            sputter_width_deg=14.0,
        )
        emulator_one = run_trench_depo(base)
        reflected_off = run_trench_depo(
            TrenchDepoConfig(
                **{
                    **base.__dict__,
                    "reflected_ion_enabled": False,
                    "reflected_ion_strength_pct": 45.0,
                }
            )
        )
        reflected_zero = run_trench_depo(
            TrenchDepoConfig(
                **{
                    **base.__dict__,
                    "reflected_ion_enabled": True,
                    "reflected_ion_strength_pct": 0.0,
                }
            )
        )

        self.assertProfilesAlmostEqual(emulator_one.frame_profiles, reflected_off.frame_profiles)
        self.assertProfilesAlmostEqual(emulator_one.frame_profiles, reflected_zero.frame_profiles)
        self.assertFalse(reflected_off.meta["reflected_ion_active"])
        self.assertFalse(reflected_zero.meta["reflected_ion_active"])

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_reflected_ion_debug_field_is_separate_and_zone_weighted(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                cycles=2,
                angstrom_per_cycle=0.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                reflected_ion_enabled=True,
                reflected_ion_strength_pct=50.0,
                reflected_ion_bowing_weight=1.0,
                reflected_ion_microtrench_weight=1.2,
            )
        )

        fields = result.meta["reflected_ion_debug_fields_last"]
        summary = result.meta["reflected_ion_debug_summary_last"]["reflected_ion"]

        self.assertTrue(result.meta["reflected_ion_active"])
        self.assertIn("direct_sputter_field", fields)
        self.assertIn("reflection_source_field", fields)
        self.assertIn("reflected_ion_field", fields)
        self.assertGreater(max(fields["reflection_source_field"]), 0.0)
        self.assertGreater(max(fields["reflected_ion_field"]), 0.0)
        self.assertLess(summary["top"], summary["mid_sidewall"])
        self.assertGreater(summary["bottom_corner"], summary["bottom_center"])
        self.assertGreater(result.meta["reflected_direct_ratio_last"], 0.0)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_reflected_ion_requires_direct_sputter_source(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                cycles=2,
                angstrom_per_cycle=10.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=0.0,
                reflected_ion_enabled=True,
                reflected_ion_strength_pct=50.0,
            )
        )

        self.assertFalse(result.meta["sputter_active"])
        self.assertFalse(result.meta["reflected_ion_active"])
        self.assertEqual(result.meta["reflected_ion_total_last"], 0.0)

    def test_model4_redeposition_uses_only_positive_gross_etch_sources(self) -> None:
        points = [
            (-200.0, 0.0),
            (-80.0, 0.0),
            (-80.0, -60.0),
            (-80.0, -120.0),
            (80.0, -120.0),
            (80.0, -60.0),
            (80.0, 0.0),
            (200.0, 0.0),
        ]
        normals = vertex_air_normals(points)
        result = compute_redeposition(
            points,
            normals,
            [0.0, 5.0, 5.0, 0.0, 0.0, 5.0, 5.0, 0.0],
            Model4RedepositionParams(redepo_efficiency=0.5, neighbor_exclusion=0),
        )

        summary = result.debug_summary
        self.assertGreater(summary["total_removed_mass"], 0.0)
        self.assertGreater(summary["total_redepo_mass"], 0.0)
        self.assertLessEqual(summary["total_redepo_mass"], 0.5 * summary["total_removed_mass"] + 1e-9)
        self.assertAlmostEqual(summary["bottom_source_mass"], 0.0, places=9)
        self.assertAlmostEqual(result.dh_redepo[2], result.dh_redepo[5], places=9)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_model4_zero_efficiency_matches_direct_sputter(self) -> None:
        base = TrenchDepoConfig(
            cycles=2,
            angstrom_per_cycle=0.0,
            sputter_enabled=True,
            sputter_strength_a_per_cycle=8.0,
            sputter_peak_angle_deg=55.0,
            sputter_width_deg=14.0,
        )
        model_one = run_trench_depo(base)
        model_four_zero = run_trench_depo(
            TrenchDepoConfig(
                **{
                    **base.__dict__,
                    "redepo_enabled": True,
                    "redepo_source_model": "model2",
                    "redepo_efficiency_pct": 0.0,
                }
            )
        )

        self.assertProfilesAlmostEqual(model_one.frame_profiles, model_four_zero.frame_profiles)
        self.assertFalse(model_four_zero.meta["redepo_active"])
        self.assertEqual(model_four_zero.meta["redepo_source_model"], "model2")
        self.assertEqual(model_four_zero.meta["redepo_total_mass_last"], 0.0)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_model4_redeposition_mass_is_bounded_by_efficiency(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                cycles=1,
                angstrom_per_cycle=0.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                sputter_smoothing_a=40.0,
                redepo_enabled=True,
                redepo_source_model="model2",
                redepo_efficiency_pct=25.0,
            )
        )

        removed = float(result.meta["redepo_total_removed_mass_last"])
        redepo = float(result.meta["redepo_total_mass_last"])
        summary = result.meta["redepo_debug_summary_last"]["redepo"]

        self.assertTrue(result.meta["redepo_active"])
        self.assertEqual(result.meta["redepo_model"], "gapsim_binned_lobe_los")
        self.assertGreater(removed, 0.0)
        self.assertGreater(redepo, 0.0)
        self.assertLessEqual(redepo, 0.25 * removed + 1e-6)
        self.assertGreater(summary["active_source_count"], 0)
        self.assertGreater(summary["active_target_count"], 0)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_model4_legacy_model_one_source_is_coerced_to_model_two(self) -> None:
        base = dict(
            cycles=1,
            angstrom_per_cycle=0.0,
            sputter_enabled=True,
            sputter_strength_a_per_cycle=8.0,
            sputter_smoothing_a=40.0,
            redepo_enabled=True,
            redepo_efficiency_pct=25.0,
        )
        legacy = run_trench_depo(TrenchDepoConfig(**base, redepo_source_model="model1"))
        current = run_trench_depo(TrenchDepoConfig(**base, redepo_source_model="model2"))

        self.assertEqual(legacy.meta["redepo_source_model"], "model2")
        self.assertProfilesAlmostEqual(legacy.frame_profiles, current.frame_profiles)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_model4_redeposition_does_not_refill_sealed_void_after_pinch_off(self) -> None:
        points = [
            (-200.0, 0.0),
            (-40.0, 0.0),
            (-25.0, -120.0),
            (-80.0, -260.0),
            (-80.0, -420.0),
            (80.0, -420.0),
            (80.0, -260.0),
            (25.0, -120.0),
            (40.0, 0.0),
            (200.0, 0.0),
        ]

        result = run_trench_depo(
            TrenchDepoConfig(
                points=points,
                cycles=60,
                angstrom_per_cycle=3.0,
                reparam_ds_a=8.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=1.0,
                redepo_enabled=True,
                redepo_efficiency_pct=25.0,
            )
        )

        void_areas = [
            sum(self.polygon_area(poly) for poly in frame_voids)
            for frame_voids in result.frame_voids
        ]
        first_void = next((idx for idx, area in enumerate(void_areas) if area > 0.0), None)

        self.assertIsNotNone(first_void)
        if first_void is not None:
            initial_area = void_areas[first_void]
            self.assertGreater(initial_area, 0.0)
            self.assertTrue(all(area > 0.0 for area in void_areas[first_void:]))
            self.assertGreaterEqual(min(void_areas[first_void:]), initial_area * 0.99)

    def test_depth_deposition_factor_decreases_with_effective_ar(self) -> None:
        top = compute_depth_deposition_ratio(
            compute_effective_aspect_ratio(0.0, "hole", 200.0),
            depth_decay_k=0.8,
            depth_decay_power=1.2,
            min_depo_ratio=0.03,
        )
        middle = compute_depth_deposition_ratio(
            compute_effective_aspect_ratio(1000.0, "hole", 200.0),
            depth_decay_k=0.8,
            depth_decay_power=1.2,
            min_depo_ratio=0.03,
        )
        bottom = compute_depth_deposition_ratio(
            compute_effective_aspect_ratio(3000.0, "hole", 200.0),
            depth_decay_k=0.8,
            depth_decay_power=1.2,
            min_depo_ratio=0.03,
        )

        self.assertAlmostEqual(top, 1.0, places=9)
        self.assertGreater(top, middle)
        self.assertGreater(middle, bottom)
        self.assertGreaterEqual(bottom, 0.03)

    def test_depth_deposition_line_has_lower_ear_than_hole(self) -> None:
        hole_ear = compute_effective_aspect_ratio(2000.0, "hole", 250.0)
        line_ear = compute_effective_aspect_ratio(2000.0, "line", 250.0)
        hole_factor = compute_depth_deposition_factors(
            [(0.0, 0.0), (0.0, -2000.0)],
            feature_type="hole",
            feature_width_a=250.0,
        )[-1]
        line_factor = compute_depth_deposition_factors(
            [(0.0, 0.0), (0.0, -2000.0)],
            feature_type="line",
            feature_width_a=250.0,
        )[-1]

        self.assertLess(line_ear, hole_ear)
        self.assertGreaterEqual(line_factor, hole_factor)

    def test_inhibition_deposition_suppresses_top_more_than_bottom(self) -> None:
        factors = compute_inhibition_deposition_factors(
            BOWED_JAR_TRENCH_POINTS,
            process_model="hybrid",
            inhibition_strength_pct=85.0,
            inhibition_penetration_depth_a=1100.0,
            inhibition_min_growth_ratio=0.08,
            inhibition_smoothing_a=0.0,
        )
        paired = list(zip(BOWED_JAR_TRENCH_POINTS, factors))
        top = [factor for (_x, y), factor in paired if y == 0.0]
        bottom = [factor for (_x, y), factor in paired if y <= -4600.0]

        self.assertTrue(top)
        self.assertTrue(bottom)
        self.assertLess(sum(top) / len(top), sum(bottom) / len(bottom))
        self.assertGreaterEqual(min(factors), 0.08)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_inhibition_deposition_uses_smooth_depo_only_path(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                points=BOWED_JAR_TRENCH_POINTS,
                cycles=2,
                angstrom_per_cycle=10.0,
                reparam_ds_a=8.0,
                deposition_depth_enabled=True,
                inhibition_enabled=True,
                inhibition_strength_pct=85.0,
                inhibition_penetration_depth_a=1100.0,
                inhibition_min_growth_ratio=0.08,
                inhibition_smoothing_a=45.0,
            )
        )
        fields = result.meta["inhibition_debug_fields_last"]
        summary = result.meta["inhibition_debug_summary_last"]["growth_ratio"]

        self.assertTrue(result.meta["inhibition_active"])
        self.assertFalse(result.meta["sputter_active"])
        self.assertEqual(result.meta["growth_model"], "inhibition_weighted_deposition")
        self.assertEqual(result.meta["propagation"], "vertex_normal_inhibition_depo_post_closure_fill")
        self.assertTrue(fields["growth_ratio_field"])
        self.assertLess(summary["top"], summary["bottom"])

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_depth_deposition_closure_fill_budget_separates_hole_and_line(self) -> None:
        base = dict(
            points=BOWED_JAR_TRENCH_POINTS,
            cycles=80,
            angstrom_per_cycle=10.0,
            reparam_ds_a=8.0,
            deposition_depth_enabled=True,
            deposition_feature_width_a=240.0,
            deposition_feature_depth_a=4700.0,
        )

        hole_sealed = run_trench_depo(
            TrenchDepoConfig(
                **base,
                deposition_feature_type="hole",
                deposition_post_closure_fill_pct_hole=0.0,
            )
        )
        hole_fill = run_trench_depo(
            TrenchDepoConfig(
                **base,
                deposition_feature_type="hole",
                deposition_post_closure_fill_pct_hole=0.03,
            )
        )
        line_fill = run_trench_depo(
            TrenchDepoConfig(
                **base,
                deposition_feature_type="line",
                deposition_post_closure_fill_pct_line=0.20,
                deposition_line_open_path_factor=1.0,
            )
        )
        line_closed = run_trench_depo(
            TrenchDepoConfig(
                **base,
                deposition_feature_type="line",
                deposition_post_closure_fill_pct_line=0.20,
                deposition_line_open_path_factor=0.0,
            )
        )

        hole_sealed_area = sum(self.polygon_area(poly) for poly in hole_sealed.frame_voids[-1])
        hole_fill_area = sum(self.polygon_area(poly) for poly in hole_fill.frame_voids[-1])
        line_fill_area = sum(self.polygon_area(poly) for poly in line_fill.frame_voids[-1])
        line_closed_area = sum(self.polygon_area(poly) for poly in line_closed.frame_voids[-1])

        self.assertTrue(hole_sealed.meta["deposition_depth_active"])
        self.assertFalse(hole_sealed.meta["sputter_active"])
        self.assertFalse(hole_sealed.meta["redepo_active"])
        self.assertTrue(hole_sealed.meta["deposition_closure_detected"])
        self.assertEqual(hole_sealed.meta["deposition_post_closure_allowed_fill_area_a2"], 0.0)
        self.assertLess(hole_fill_area, hole_sealed_area)
        self.assertLess(line_fill_area, line_closed_area)
        self.assertLess(line_fill_area, hole_fill_area)
        self.assertLessEqual(
            line_fill.meta["deposition_post_closure_budget_used_area_a2"],
            line_fill.meta["deposition_post_closure_allowed_fill_area_a2"] + 1e-6,
        )

    def test_ion_transmission_factor_decreases_in_stepped_trench_depth(self) -> None:
        factors = compute_ion_transmission_factors(ION_TRANSMISSION_STEPPED_TRENCH_POINTS)
        paired = list(zip(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, factors))
        top = [factor for (_x, y), factor in paired if y == 0.0]
        bottom = [factor for (_x, y), factor in paired if y <= -3800.0]
        mid_neck = [factor for (_x, y), factor in paired if y == -1650.0]

        self.assertTrue(top)
        self.assertTrue(bottom)
        self.assertTrue(mid_neck)
        self.assertGreater(sum(top) / len(top), sum(mid_neck) / len(mid_neck))
        self.assertGreater(sum(top) / len(top), sum(bottom) / len(bottom))
        self.assertTrue(all(0.0 <= factor <= 1.0 for factor in factors))

    def test_ion_transmission_curve_controls_shape_depth_drop(self) -> None:
        no_drop = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            decay_strength_pct=0.0,
        )
        delayed = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            start_depth_pct=50.0,
        )
        floored = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            floor_pct=45.0,
        )
        fast_curve = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            curve_power=0.5,
        )
        linear_curve = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            curve_power=1.0,
        )
        slow_curve = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            curve_power=2.0,
        )
        delayed_paired = list(zip(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, delayed))
        mid_neck = [factor for (_x, y), factor in delayed_paired if y == -1650.0]
        bottom = [factor for (_x, y), factor in delayed_paired if y <= -3800.0]
        fast_mid = [
            factor
            for (_x, y), factor in zip(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, fast_curve)
            if y == -1650.0
        ]
        linear_mid = [
            factor
            for (_x, y), factor in zip(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, linear_curve)
            if y == -1650.0
        ]
        slow_mid = [
            factor
            for (_x, y), factor in zip(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, slow_curve)
            if y == -1650.0
        ]

        self.assertTrue(all(abs(factor - 1.0) < 1e-9 for factor in no_drop))
        self.assertTrue(mid_neck)
        self.assertTrue(all(abs(factor - 1.0) < 1e-9 for factor in mid_neck))
        self.assertTrue(bottom)
        self.assertLess(sum(bottom) / len(bottom), 1.0)
        self.assertGreaterEqual(min(floored), 0.45)
        self.assertLess(sum(fast_mid) / len(fast_mid), sum(linear_mid) / len(linear_mid))
        self.assertLess(sum(linear_mid) / len(linear_mid), sum(slow_mid) / len(slow_mid))

    def test_ion_transmission_can_show_depth_only_without_geometry_shadowing(self) -> None:
        factors = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            curve_power=1.0,
            aperture_shadow_pct=0.0,
            lateral_shadow_pct=0.0,
            edge_shadow_pct=0.0,
        )
        max_depth = abs(min(y for _x, y in ION_TRANSMISSION_STEPPED_TRENCH_POINTS))
        paired = list(zip(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, factors))
        top = [factor for (_x, y), factor in paired if y == 0.0]
        mid_neck = [factor for (_x, y), factor in paired if y == -1650.0]
        bottom = [factor for (_x, y), factor in paired if y <= -3800.0]

        self.assertTrue(all(abs(factor - 1.0) < 1e-9 for factor in top))
        self.assertTrue(mid_neck)
        self.assertTrue(bottom)
        self.assertAlmostEqual(sum(mid_neck) / len(mid_neck), 1.0 - (1650.0 / max_depth), places=9)
        self.assertAlmostEqual(sum(bottom) / len(bottom), 0.0, places=9)

    def test_ion_transmission_end_depth_caps_depth_curve_early(self) -> None:
        factors = compute_ion_transmission_factors(
            ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            end_depth_pct=50.0,
            curve_power=1.0,
            aperture_shadow_pct=0.0,
            lateral_shadow_pct=0.0,
            edge_shadow_pct=0.0,
        )
        max_depth = abs(min(y for _x, y in ION_TRANSMISSION_STEPPED_TRENCH_POINTS))
        paired = list(zip(ION_TRANSMISSION_STEPPED_TRENCH_POINTS, factors))
        mid_neck = [factor for (_x, y), factor in paired if y == -1650.0]
        bottom = [factor for (_x, y), factor in paired if y <= -3800.0]

        self.assertTrue(mid_neck)
        self.assertAlmostEqual(
            sum(mid_neck) / len(mid_neck),
            1.0 - ((1650.0 / max_depth) / 0.5),
            places=9,
        )
        self.assertAlmostEqual(sum(bottom) / len(bottom), 0.0, places=9)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_ion_transmission_off_matches_emulator_one_direct_sputter(self) -> None:
        cfg = TrenchDepoConfig(
            points=ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            cycles=2,
            angstrom_per_cycle=10.0,
            sputter_enabled=True,
            sputter_strength_a_per_cycle=8.0,
            ion_transmission_enabled=False,
        )
        one = run_trench_depo(cfg)
        two_off = run_trench_depo(
            TrenchDepoConfig(
                points=ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
                cycles=2,
                angstrom_per_cycle=10.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                ion_transmission_enabled=False,
            )
        )

        self.assertProfilesAlmostEqual(one.frame_profiles, two_off.frame_profiles)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_ion_transmission_override_one_matches_direct_sputter(self) -> None:
        base = TrenchDepoConfig(
            points=ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
            cycles=2,
            angstrom_per_cycle=10.0,
            sputter_enabled=True,
            sputter_strength_a_per_cycle=8.0,
            ion_transmission_enabled=False,
        )
        model_one = run_trench_depo(base)
        forced_one = run_trench_depo(
            TrenchDepoConfig(
                points=ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
                cycles=2,
                angstrom_per_cycle=10.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                ion_transmission_enabled=True,
                ion_transmission_override=1.0,
            )
        )

        self.assertProfilesAlmostEqual(model_one.frame_profiles, forced_one.frame_profiles)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_ion_transmission_debug_keeps_deposition_field_unmodified(self) -> None:
        result = run_trench_depo(
            TrenchDepoConfig(
                points=ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
                cycles=2,
                angstrom_per_cycle=10.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                ion_transmission_enabled=True,
            )
        )

        fields = result.meta["ion_debug_fields_last"]
        summary = result.meta["ion_debug_summary_last"]
        deposition_substep_a = (
            result.meta["angstrom_per_cycle"] / result.meta["direct_sputter_internal_substeps"]
        )
        self.assertTrue(fields["ion_factor_field"])
        self.assertTrue(all(abs(v - deposition_substep_a) < 1e-6 for v in fields["depo_field"]))
        self.assertGreater(summary["ion_factor"]["top"], summary["ion_factor"]["bottom"])
        self.assertGreater(summary["sputter_raw"]["bottom"], 0.0)
        self.assertLess(summary["sputter_effective"]["bottom"], summary["sputter_raw"]["bottom"])
        self.assertEqual(result.meta["ion_transmission_model"], "depth_curve_opening_width_sky_visibility")
        self.assertFalse(result.meta.get("reflected_ion_active", False))
        self.assertAlmostEqual(float(result.meta.get("reflected_ion_total_last", 0.0)), 0.0, places=9)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_zero_sputter_with_ion_transmission_matches_conformal_only(self) -> None:
        baseline = run_trench_depo(
            TrenchDepoConfig(points=ION_TRANSMISSION_STEPPED_TRENCH_POINTS, cycles=2)
        )
        zero_sputter = run_trench_depo(
            TrenchDepoConfig(
                points=ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
                cycles=2,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=0.0,
                ion_transmission_enabled=True,
            )
        )

        self.assertProfilesAlmostEqual(baseline.frame_profiles, zero_sputter.frame_profiles)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_gapsim_angle_only_compare_disables_non_angle_effects(self) -> None:
        result = run_trench_depo_legacy_sputter(
            TrenchDepoConfig(
                cycles=2,
                angstrom_per_cycle=0.0,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=8.0,
                sputter_peak_angle_deg=55.0,
                sputter_width_deg=14.0,
            )
        )

        self.assertEqual(len(result.frame_profiles), 3)
        self.assertTrue(result.meta["sputter_active"])
        self.assertEqual(result.meta["sputter_model"], "gapsim_angle_only_sputter")
        self.assertEqual(result.meta["sputter_depth_decay_length_a"], 0.0)
        self.assertEqual(result.meta["sputter_vis_exponent"], 0.0)
        self.assertFalse(result.meta["redepo_enabled"])
        self.assertEqual(result.meta["legacy_step_scale_a"], 8.0)
        self.assertEqual(result.meta["legacy_deposition_flux_scale"], 0.0)
        self.assertGreaterEqual(result.meta["legacy_ion_substeps_last"], 1)

    def test_invalid_cycles_fail_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "cycles"):
            run_trench_depo(TrenchDepoConfig(cycles=-1))

        with self.assertRaisesRegex(ValueError, "cycles"):
            run_trench_depo(TrenchDepoConfig(cycles=1.5))  # type: ignore[arg-type]

    def test_invalid_points_fail_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "points"):
            run_trench_depo(TrenchDepoConfig(points=[(0.0, 0.0)], cycles=1))

        with self.assertRaisesRegex(ValueError, "points"):
            run_trench_depo(TrenchDepoConfig(points=[(0.0, 0.0), (0.0, 1.0)], cycles=1))

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_export_run_bundle_creates_korean_named_artifacts(self) -> None:
        config = TrenchDepoConfig(cycles=2, angstrom_per_cycle=10.0)
        result = run_trench_depo(config)
        with tempfile.TemporaryDirectory(prefix="gapsim_trench_export_") as td:
            run_dir = export_trench_depo_run(
                config,
                result,
                request_note="입구 둥글어짐 확인",
                runs_root=td,
            )

            self.assertTrue(run_dir.exists())
            self.assertIn("트렌치증착", run_dir.name)
            self.assertIn("입구_둥글어짐_확인", run_dir.name)

            replay_files = list(run_dir.glob("에뮬레이터재생_*.json"))
            meta_files = list(run_dir.glob("런정보_*.json"))
            summary_files = list(run_dir.glob("요청사항요약_*.txt"))
            gif_files = list(run_dir.glob("트렌치증착_*.gif"))
            self.assertEqual(len(replay_files), 1)
            self.assertEqual(len(meta_files), 1)
            self.assertEqual(len(summary_files), 1)
            self.assertEqual(len(gif_files), 1)

            payload = json.loads(replay_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["request_note_ko"], "입구 둥글어짐 확인")
            self.assertEqual(payload["config"]["cycles"], 2)
            self.assertFalse(payload["config"]["sputter_enabled"])
            self.assertAlmostEqual(payload["config"]["sputter_peak_pct"], 100.0, places=9)
            self.assertAlmostEqual(payload["config"]["sputter_smoothing_a"], 40.0, places=9)
            self.assertEqual(len(payload["result"]["frame_profiles"]), 3)

            summary_text = summary_files[0].read_text(encoding="utf-8")
            self.assertIn("요청사항 / 물리 메모", summary_text)
            self.assertIn("입구 둥글어짐 확인", summary_text)

            loaded_config, loaded_result, loaded_note = load_trench_depo_run(replay_files[0])
            self.assertEqual(int(loaded_config.cycles), 2)
            self.assertAlmostEqual(float(loaded_config.angstrom_per_cycle), 10.0, places=9)
            self.assertEqual(loaded_note, "입구 둥글어짐 확인")
            self.assertEqual(len(loaded_result.frame_profiles), 3)

    def test_export_sweep_runs_saves_each_case_with_split_note(self) -> None:
        config = TrenchDepoConfig(cycles=1, angstrom_per_cycle=10.0)
        result = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 1},
        )
        cases = [
            TrenchSweepResult("angstrom_per_cycle", "Depo A/CYC", 5.0, config, result),
            TrenchSweepResult("angstrom_per_cycle", "Depo A/CYC", 10.0, config, result),
        ]

        with mock.patch(
            "gapsim.emulation.trench_depo_export.export_trench_depo_run",
            side_effect=[Path("/tmp/split_1"), Path("/tmp/split_2")],
        ) as exporter:
            saved_dirs = export_trench_depo_sweep_runs(cases, request_note="스플릿 저장", runs_root="runs/root")

        self.assertEqual(saved_dirs, [Path("/tmp/split_1"), Path("/tmp/split_2")])
        self.assertEqual(exporter.call_count, 2)
        self.assertEqual(exporter.call_args_list[0].kwargs["request_note"], "스플릿 저장 | Split Test 1/2 | Depo A/CYC=5")
        self.assertEqual(exporter.call_args_list[1].kwargs["request_note"], "스플릿 저장 | Split Test 2/2 | Depo A/CYC=10")
        self.assertEqual(exporter.call_args_list[0].kwargs["runs_root"], "runs/root")

    def test_export_sweep_runs_can_reload_split_group_from_one_replay(self) -> None:
        config_a = TrenchDepoConfig(cycles=0, angstrom_per_cycle=5.0)
        config_b = TrenchDepoConfig(cycles=0, angstrom_per_cycle=10.0)
        result_a = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (1.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (1.0, 0.0)],
            meta={"cycles": 0},
        )
        result_b = TrenchDepoResult(
            frame_steps=[0],
            frame_profiles=[[(0.0, 0.0), (2.0, 0.0)]],
            frame_voids=[[]],
            final_profile=[(0.0, 0.0), (2.0, 0.0)],
            meta={"cycles": 0},
        )
        cases = [
            TrenchSweepResult("angstrom_per_cycle", "Depo A/CYC", 5.0, config_a, result_a),
            TrenchSweepResult("angstrom_per_cycle", "Depo A/CYC", 10.0, config_b, result_b),
        ]

        with tempfile.TemporaryDirectory(prefix="gapsim_trench_split_") as td:
            saved_dirs = export_trench_depo_sweep_runs(cases, request_note="스플릿 저장", runs_root=td)
            replay = next(saved_dirs[0].glob("에뮬레이터재생_*.json"))

            loaded = load_trench_depo_split_group(replay)

            self.assertEqual([case.value for case in loaded], [5.0, 10.0])
            self.assertEqual([case.label for case in loaded], ["Depo A/CYC", "Depo A/CYC"])
            self.assertTrue(all((run_dir / "스플릿묶음.json").exists() for run_dir in saved_dirs))


if __name__ == "__main__":
    unittest.main()
