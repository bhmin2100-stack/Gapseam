from __future__ import annotations

import math
import unittest

from gapsim.engine.deposition_pipeline import (
    ConformalFluxModel,
    InhibitionFluxModel,
    SimulationState,
    SputterRedepositionFluxModel,
    Surface,
    TopologyCleanup,
    VertexNormalPropagator,
    ZeroFluxModel,
    _int_paths_area,
    deposit_step,
    equal_arc_resample,
    init_simulation_state,
)
from gapsim.engine.ion_los import OpeningLOS, PathLOS, _segment_intersects, build_opening_segment


def _legacy_visible_indices(pts, normals, i: int, j: int, eps_air: float = 1e-4) -> bool:
    if i == j:
        return False
    if i < 0 or j < 0 or i >= len(pts) or j >= len(pts):
        return False

    def _offset(index: int):
        x, y = pts[index]
        if 0 <= index < len(normals):
            nx, ny = normals[index]
            nl = math.hypot(nx, ny)
            if nl > 1e-12:
                return (x + (eps_air * nx / nl), y + (eps_air * ny / nl))
        return (x, y)

    p = _offset(i)
    q = _offset(j)
    min_x = min(p[0], q[0]) - eps_air
    max_x = max(p[0], q[0]) + eps_air
    min_y = min(p[1], q[1]) - eps_air
    max_y = max(p[1], q[1]) + eps_air
    ignore = {i - 1, i, j - 1, j}

    for seg_index in range(max(0, len(pts) - 1)):
        if seg_index in ignore:
            continue
        a = pts[seg_index]
        b = pts[seg_index + 1]
        if max(a[0], b[0]) < min_x or min(a[0], b[0]) > max_x or max(a[1], b[1]) < min_y or min(a[1], b[1]) > max_y:
            continue
        if _segment_intersects(p, q, a, b, eps=eps_air):
            return False
    return True


def _legacy_opening_visibility(pts, normals, point_index: int, source_height: float = 0.0, tol_y: float = 1e-6, eps_air: float = 1e-4) -> float:
    opening_los = OpeningLOS(pts, normals=normals, source_height=source_height, tol_y=tol_y, eps_air=eps_air)
    opening = opening_los.opening
    if opening is None or opening.length <= tol_y:
        return 0.0
    if point_index < 0 or point_index >= len(pts):
        return 0.0

    p_raw = pts[point_index]
    if abs(opening.y0 - p_raw[1]) <= tol_y:
        return 1.0

    p = opening_los._offset_point(point_index)  # type: ignore[attr-defined]
    if opening.y0 <= p[1] + tol_y:
        return 1.0

    def _project_x(q):
        dy = float(q[1] - p[1])
        if abs(dy) <= tol_y:
            if abs(float(q[0] - p[0])) <= tol_y:
                return None
            return opening.x_left if q[0] < p[0] else opening.x_right
        t = (opening.y0 - float(p[1])) / dy
        return float(p[0]) + (float(q[0] - p[0]) * t)

    intervals = []
    for seg_index in range(max(0, len(pts) - 1)):
        if seg_index in {point_index - 1, point_index}:
            continue
        a = pts[seg_index]
        b = pts[seg_index + 1]
        if max(a[1], b[1]) <= p[1] + tol_y:
            continue
        if min(a[1], b[1]) >= opening.y0 - tol_y and max(a[1], b[1]) >= opening.y0 - tol_y:
            continue
        xa = _project_x(a)
        xb = _project_x(b)
        if xa is None and xb is None:
            continue
        if xa is None:
            xa = opening.x_left if a[0] < p[0] else opening.x_right
        if xb is None:
            xb = opening.x_left if b[0] < p[0] else opening.x_right
        lo = max(opening.x_left, min(xa, xb))
        hi = min(opening.x_right, max(xa, xb))
        if hi <= lo + tol_y:
            continue
        x_mid = 0.5 * (lo + hi)
        if _segment_intersects(p, (float(x_mid), float(opening.y0)), a, b, eps=eps_air):
            intervals.append((lo, hi))

    intervals.sort()
    merged = []
    for lo, hi in intervals:
        if not merged or lo > merged[-1][1] + tol_y:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    blocked = sum(max(0.0, hi - lo) for lo, hi in merged)
    visible = max(0.0, opening.length - blocked)
    return max(0.0, min(1.0, visible / max(opening.length, tol_y)))


class IonPhase1ModelTest(unittest.TestCase):
    def test_inhibition_applies_max_on_field_and_decays_inside_trench(self) -> None:
        pts = [
            (-200.0, 0.0),
            (-50.0, 0.0),
            (-50.0, -200.0),
            (50.0, -200.0),
            (50.0, 0.0),
            (200.0, 0.0),
        ]
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = InhibitionFluxModel(ConformalFluxModel(), i_max=0.8, lambda_a=100.0)
        flux = model.compute_flux(state)

        self.assertAlmostEqual(flux[0], 0.2, places=6)
        self.assertAlmostEqual(flux[1], 0.2, places=6)
        self.assertGreater(flux[2], flux[1])
        self.assertGreater(flux[3], flux[4])
        self.assertAlmostEqual(flux[2], 1.0 - (0.8 * math.exp(-2.0)), places=6)

    def test_inhibition_applies_max_on_all_field_points(self) -> None:
        pts = [
            (-300.0, 0.0),
            (-200.0, 0.0),
            (-50.0, 0.0),
            (-50.0, -200.0),
            (50.0, -200.0),
            (50.0, 0.0),
            (200.0, 0.0),
            (300.0, 0.0),
        ]
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = InhibitionFluxModel(ConformalFluxModel(), i_max=0.8, lambda_a=100.0)
        flux = model.compute_flux(state)

        self.assertAlmostEqual(flux[0], 0.2, places=6)
        self.assertAlmostEqual(flux[1], 0.2, places=6)
        self.assertAlmostEqual(flux[2], 0.2, places=6)
        self.assertAlmostEqual(flux[5], 0.2, places=6)

    def test_opening_los_uses_inner_lips_and_is_resolution_stable(self) -> None:
        pts = [
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
        normals = VertexNormalPropagator._vertex_air_normals(pts)
        opening = OpeningLOS(pts, normals=normals)
        self.assertIsNotNone(opening.opening)
        assert opening.opening is not None
        self.assertAlmostEqual(opening.opening.x_left, -40.0, places=6)
        self.assertAlmostEqual(opening.opening.x_right, 40.0, places=6)

        vis_coarse = opening.opening_visibility(3)
        self.assertGreaterEqual(vis_coarse, 0.0)
        self.assertLessEqual(vis_coarse, 1.0)
        self.assertLess(vis_coarse, 1.0)

        pts_fine = equal_arc_resample(pts, 5.0)
        normals_fine = VertexNormalPropagator._vertex_air_normals(pts_fine)
        opening_fine = OpeningLOS(pts_fine, normals=normals_fine)
        idx_fine = min(
            range(len(pts_fine)),
            key=lambda i: ((pts_fine[i][0] + 80.0) ** 2) + ((pts_fine[i][1] + 260.0) ** 2),
        )
        vis_fine = opening_fine.opening_visibility(idx_fine)
        self.assertAlmostEqual(vis_coarse, vis_fine, delta=0.05)

    def test_opening_los_matches_legacy_full_scan_visibility(self) -> None:
        base = [
            (-250.0, 0.0),
            (-70.0, 0.0),
            (-70.0, -120.0),
            (-120.0, -200.0),
            (-120.0, -340.0),
            (-30.0, -420.0),
            (30.0, -420.0),
            (120.0, -340.0),
            (120.0, -200.0),
            (70.0, -120.0),
            (70.0, 0.0),
            (250.0, 0.0),
        ]
        pts = equal_arc_resample(base, 10.0)
        normals = VertexNormalPropagator._vertex_air_normals(pts)
        opening = OpeningLOS(pts, normals=normals, source_height=10000.0)
        for i in range(len(pts)):
            self.assertAlmostEqual(
                opening.opening_visibility(i),
                _legacy_opening_visibility(pts, normals, i, source_height=10000.0),
                places=9,
            )

    def test_build_opening_segment_matches_opening_los_detection(self) -> None:
        pts = [
            (-240.0, 0.0),
            (-70.0, 0.0),
            (-40.0, -120.0),
            (-90.0, -260.0),
            (-90.0, -420.0),
            (90.0, -420.0),
            (90.0, -260.0),
            (40.0, -120.0),
            (70.0, 0.0),
            (240.0, 0.0),
        ]
        normals = VertexNormalPropagator._vertex_air_normals(pts)
        opening_los = OpeningLOS(pts, normals=normals, source_height=0.0, tol_y=1e-6)
        opening_fast = build_opening_segment(pts, source_height=0.0, tol_y=1e-6)

        self.assertIsNotNone(opening_los.opening)
        self.assertIsNotNone(opening_fast)
        assert opening_los.opening is not None
        assert opening_fast is not None
        self.assertEqual(opening_fast.left_index, opening_los.opening.left_index)
        self.assertEqual(opening_fast.right_index, opening_los.opening.right_index)
        self.assertAlmostEqual(opening_fast.x_left, opening_los.opening.x_left, places=6)
        self.assertAlmostEqual(opening_fast.x_right, opening_los.opening.x_right, places=6)

    def test_path_los_reports_clear_and_blocked(self) -> None:
        pts = [
            (-10.0, 0.0),
            (-2.0, 0.0),
            (-2.0, -2.0),
            (-4.0, -2.0),
            (-4.0, -4.0),
            (-4.0, -6.0),
            (4.0, -6.0),
            (4.0, -4.0),
            (4.0, -2.0),
            (2.0, -2.0),
            (2.0, 0.0),
            (10.0, 0.0),
        ]
        normals = VertexNormalPropagator._vertex_air_normals(pts)
        los = PathLOS(pts, normals=normals)
        self.assertTrue(los.visible_indices(4, 7))
        self.assertFalse(los.visible_indices(3, 8))

    def test_path_los_matches_legacy_full_scan_for_all_pairs(self) -> None:
        base = [
            (-200.0, 0.0),
            (-50.0, 0.0),
            (-50.0, -80.0),
            (-90.0, -120.0),
            (-90.0, -220.0),
            (-20.0, -320.0),
            (20.0, -320.0),
            (90.0, -220.0),
            (90.0, -120.0),
            (50.0, -80.0),
            (50.0, 0.0),
            (200.0, 0.0),
        ]
        pts = equal_arc_resample(base, 12.0)
        normals = VertexNormalPropagator._vertex_air_normals(pts)
        los = PathLOS(pts, normals=normals)

        for i in range(len(pts)):
            for j in range(len(pts)):
                self.assertEqual(
                    los.visible_indices(i, j),
                    _legacy_visible_indices(pts, normals, i, j),
                    msg=f"pair mismatch for ({i}, {j})",
                )

    def test_path_los_visible_set_matches_legacy_for_representative_geometry(self) -> None:
        base = [
            (-250.0, 0.0),
            (-70.0, 0.0),
            (-70.0, -120.0),
            (-120.0, -200.0),
            (-120.0, -340.0),
            (-30.0, -420.0),
            (30.0, -420.0),
            (120.0, -340.0),
            (120.0, -200.0),
            (70.0, -120.0),
            (70.0, 0.0),
            (250.0, 0.0),
        ]
        pts = equal_arc_resample(base, 10.0)
        normals = VertexNormalPropagator._vertex_air_normals(pts)
        los = PathLOS(pts, normals=normals)
        source_idx = min(
            range(len(pts)),
            key=lambda idx: ((pts[idx][0] + 120.0) ** 2) + ((pts[idx][1] + 200.0) ** 2),
        )
        expected = {j for j in range(len(pts)) if _legacy_visible_indices(pts, normals, source_idx, j)}
        actual = {j for j in range(len(pts)) if los.visible_indices(source_idx, j)}
        self.assertSetEqual(actual, expected)

    def test_path_los_pair_cache_is_symmetric(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (-40.0, -100.0),
                (-40.0, -240.0),
                (40.0, -240.0),
                (40.0, -100.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        normals = VertexNormalPropagator._vertex_air_normals(pts)
        los = PathLOS(pts, normals=normals)
        i = len(pts) // 3
        j = len(pts) - i - 1
        first = los.visible_indices(i, j)
        second = los.visible_indices(j, i)

        self.assertEqual(first, second)
        self.assertEqual(len(los._pair_cache), 1)

    def test_redeposition_preserves_mass_on_resampled_surface(self) -> None:
        pts = equal_arc_resample(
            [
                (-80.0, 0.0),
                (-20.0, -200.0),
                (20.0, -200.0),
                (80.0, 0.0),
            ],
            10.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = SputterRedepositionFluxModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=120.0,
            sputter_peak_angle_deg=55.0,
            sputter_angle_sigma_deg=15.0,
            sputter_depth_decay_length_a=0.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=True,
            redepo_efficiency_pct=50.0,
            redepo_lobe_sigma_deg=20.0,
        )
        flux = model.compute_flux(state)

        self.assertEqual(len(flux), len(pts))
        total_etch_mass = float(state.meta.get("redepo_total_etch_mass", 0.0))
        total_redepo_mass = float(state.meta.get("redepo_total_mass", 0.0))
        self.assertGreater(total_etch_mass, 0.0)
        self.assertGreater(total_redepo_mass, 0.0)
        self.assertAlmostEqual(total_redepo_mass, 0.5 * total_etch_mass, delta=1e-6)

    def test_sputter_strength_100_overrides_local_deposition_at_peak(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = SputterRedepositionFluxModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=100.0,
            sputter_peak_angle_deg=45.0,
            sputter_angle_sigma_deg=5.0,
            sputter_depth_decay_length_a=0.0,
            sputter_vis_exponent=0.0,
            redepo_enabled=False,
        )
        net_flux = model.compute_flux(state)
        facet_idx = len(pts) // 4
        etch_mean = float(state.meta.get("sputter_mean_etch_flux", 0.0))

        self.assertLess(net_flux[facet_idx], -1.5)
        self.assertGreater(etch_mean, 2.0)

    def test_sputter_can_run_as_etch_only_when_deposition_is_disabled(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = SputterRedepositionFluxModel(
            ZeroFluxModel(),
            etch_reference_model=ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=100.0,
            sputter_peak_angle_deg=45.0,
            sputter_angle_sigma_deg=5.0,
            sputter_depth_decay_length_a=0.0,
            sputter_vis_exponent=0.0,
            redepo_enabled=False,
        )
        net_flux = model.compute_flux(state)

        self.assertTrue(any(v < 0.0 for v in net_flux))
        self.assertAlmostEqual(max(net_flux), 0.0, delta=1e-9)

    def test_sputter_etch_only_step_removes_material_from_structure(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        state = init_simulation_state(pts, units="A", reparam_ds_a=2.5)
        model = SputterRedepositionFluxModel(
            ZeroFluxModel(),
            etch_reference_model=ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=100.0,
            sputter_peak_angle_deg=45.0,
            sputter_angle_sigma_deg=5.0,
            sputter_depth_decay_length_a=0.0,
            sputter_vis_exponent=0.0,
            redepo_enabled=False,
        )

        before_solid_area = float(_int_paths_area(state.solid_paths_i))
        out = deposit_step(
            1.0,
            state,
            model=model,
            propagator=VertexNormalPropagator(),
            cleanup=TopologyCleanup(),
        )
        after_solid_area = float(_int_paths_area(out.solid_paths_i))

        self.assertLess(after_solid_area, before_solid_area)
        self.assertEqual(out.meta.get("solid_merge_mode"), "candidate")

    def test_sputter_only_strength_maps_peak_etch_to_reference_fraction(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = SputterRedepositionFluxModel(
            ZeroFluxModel(),
            etch_reference_model=ConformalFluxModel(),
            sputter_only_mode=True,
            sputter_enabled=True,
            sputter_strength_pct=50.0,
            sputter_peak_angle_deg=45.0,
            sputter_angle_sigma_deg=5.0,
            sputter_depth_decay_length_a=0.0,
            sputter_vis_exponent=0.0,
            redepo_enabled=False,
        )

        net_flux = model.compute_flux(state)

        self.assertAlmostEqual(min(net_flux), -0.5, delta=1e-6)
        self.assertTrue(state.meta.get("sputter_only_mode"))

    def test_sputter_compute_flux_records_timing_meta(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = SputterRedepositionFluxModel(
            ZeroFluxModel(),
            etch_reference_model=ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=100.0,
            sputter_peak_angle_deg=45.0,
            sputter_angle_sigma_deg=5.0,
            sputter_depth_decay_length_a=0.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=False,
        )
        _ = model.compute_flux(state)
        self.assertIn("timing_compute_flux_s", state.meta)
        self.assertIn("timing_sky_visibility_s", state.meta)
        self.assertGreaterEqual(float(state.meta["timing_compute_flux_s"]), 0.0)
        self.assertGreaterEqual(float(state.meta["timing_sky_visibility_s"]), 0.0)

    def test_zero_deposition_and_no_sputter_keeps_flux_zero(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = SputterRedepositionFluxModel(
            ZeroFluxModel(),
            etch_reference_model=ConformalFluxModel(),
            sputter_enabled=False,
            redepo_enabled=False,
        )
        net_flux = model.compute_flux(state)

        self.assertTrue(all(abs(v) <= 1e-12 for v in net_flux))

    def test_large_ion_step_requests_substeps(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 20.0},
        )
        model = SputterRedepositionFluxModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=100.0,
            sputter_peak_angle_deg=55.0,
            sputter_angle_sigma_deg=30.0,
            sputter_depth_decay_length_a=1000.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=False,
        )
        self.assertGreater(model.recommended_substeps(state, 20.0), 1)

    def test_reparam_spacing_affects_substep_budget(self) -> None:
        pts = equal_arc_resample(
            [
                (-120.0, 0.0),
                (0.0, -120.0),
                (120.0, 0.0),
            ],
            10.0,
        )
        coarse = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 20.0, "reparam_ds": 10.0},
        )
        fine = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 20.0, "reparam_ds": 2.5},
        )
        model = SputterRedepositionFluxModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=100.0,
            sputter_peak_angle_deg=55.0,
            sputter_angle_sigma_deg=30.0,
            sputter_depth_decay_length_a=1000.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=False,
        )
        self.assertLess(model.recommended_substeps(coarse, 20.0), model.recommended_substeps(fine, 20.0))

    def test_redepo_outlier_hotspot_relaxes_legacy_budget(self) -> None:
        pts = [(float(i), 0.0) for i in range(200)]
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 10.0, "reparam_ds": 2.5, "step_idx": 0},
        )

        class StubModel(SputterRedepositionFluxModel):
            def compute_flux(self, state: SimulationState) -> List[float]:
                self._last_redepo_active_source_count = 190
                return [4.0] + ([1.0] * 199)

        model = StubModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=80.0,
            sputter_peak_angle_deg=55.0,
            sputter_angle_sigma_deg=15.0,
            sputter_depth_decay_length_a=1000.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=True,
            redepo_efficiency_pct=80.0,
            redepo_lobe_sigma_deg=20.0,
        )
        new_substeps = model.recommended_substeps(state, 10.0)
        self.assertEqual(state.meta.get("ion_substep_policy"), "redepo_outlier_p99")
        self.assertEqual(state.meta.get("ion_substeps_legacy"), 32)
        self.assertEqual(new_substeps, 26)

    def test_redepo_dense_smooth_case_relaxes_substeps_conservatively(self) -> None:
        pts = equal_arc_resample(
            [
                (-300.0, 0.0),
                (-120.0, 0.0),
                (-120.0, -300.0),
                (120.0, -300.0),
                (120.0, 0.0),
                (300.0, 0.0),
            ],
            2.5,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 30.0, "reparam_ds": 2.5, "step_idx": 1},
        )
        model = SputterRedepositionFluxModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=80.0,
            sputter_peak_angle_deg=55.0,
            sputter_angle_sigma_deg=15.0,
            sputter_depth_decay_length_a=1000.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=True,
            redepo_efficiency_pct=80.0,
            redepo_lobe_sigma_deg=20.0,
        )
        new_substeps = model.recommended_substeps(state, 30.0)
        flux = model.consume_cached_recommended_flux(state) or model.compute_flux(state)
        legacy_substeps = model._legacy_recommended_substeps(state, 30.0, flux)

        self.assertEqual(state.meta.get("ion_substep_policy"), "smooth_redepo_minus_one")
        self.assertEqual(new_substeps, legacy_substeps - 1)

    def test_redepo_first_cycle_keeps_legacy_substeps(self) -> None:
        pts = equal_arc_resample(
            [
                (-300.0, 0.0),
                (-120.0, 0.0),
                (-120.0, -300.0),
                (120.0, -300.0),
                (120.0, 0.0),
                (300.0, 0.0),
            ],
            2.5,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 30.0, "reparam_ds": 2.5, "step_idx": 0},
        )
        model = SputterRedepositionFluxModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=80.0,
            sputter_peak_angle_deg=55.0,
            sputter_angle_sigma_deg=15.0,
            sputter_depth_decay_length_a=1000.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=True,
            redepo_efficiency_pct=80.0,
            redepo_lobe_sigma_deg=20.0,
        )
        new_substeps = model.recommended_substeps(state, 30.0)
        flux = model.consume_cached_recommended_flux(state) or model.compute_flux(state)
        legacy_substeps = model._legacy_recommended_substeps(state, 30.0, flux)

        self.assertEqual(state.meta.get("ion_substep_policy"), "legacy")
        self.assertEqual(new_substeps, legacy_substeps)

    def test_redepo_sparse_case_keeps_legacy_substeps(self) -> None:
        pts = equal_arc_resample(
            [
                (-300.0, 0.0),
                (-30.0, 0.0),
                (-150.0, -400.0),
                (150.0, -400.0),
                (30.0, 0.0),
                (300.0, 0.0),
            ],
            2.5,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 30.0, "reparam_ds": 2.5},
        )
        model = SputterRedepositionFluxModel(
            ConformalFluxModel(),
            sputter_enabled=True,
            sputter_strength_pct=80.0,
            sputter_peak_angle_deg=55.0,
            sputter_angle_sigma_deg=15.0,
            sputter_depth_decay_length_a=1000.0,
            sputter_vis_exponent=1.0,
            redepo_enabled=True,
            redepo_efficiency_pct=80.0,
            redepo_lobe_sigma_deg=20.0,
        )
        new_substeps = model.recommended_substeps(state, 30.0)
        flux = model.consume_cached_recommended_flux(state) or model.compute_flux(state)
        legacy_substeps = model._legacy_recommended_substeps(state, 30.0, flux)

        self.assertEqual(state.meta.get("ion_substep_policy"), "legacy")
        self.assertEqual(new_substeps, legacy_substeps)

    def test_inhibition_flux_matches_reference_profile_using_same_opening(self) -> None:
        pts = equal_arc_resample(
            [
                (-250.0, 0.0),
                (-80.0, 0.0),
                (-60.0, -140.0),
                (-120.0, -260.0),
                (-120.0, -420.0),
                (120.0, -420.0),
                (120.0, -260.0),
                (60.0, -140.0),
                (80.0, 0.0),
                (250.0, 0.0),
            ],
            12.0,
        )
        state = SimulationState(
            surface=Surface(points=list(pts)),
            scale=1,
            x_left_i=0,
            x_right_i=0,
            y_top_i=0,
            y_bot_i=0,
            roi_path_i=[],
            solid_paths_i=[],
            meta={"dr": 1.0},
        )
        model = InhibitionFluxModel(ConformalFluxModel(), i_max=0.65, lambda_a=180.0)
        flux = model.compute_flux(state)

        ys = [float(p[1]) for p in pts]
        top_y = max(ys)
        y_span = max(1.0, top_y - min(ys))
        tol_y = max(1e-6, min(2.5, 0.02 * y_span))
        opening = OpeningLOS(pts, source_height=0.0, tol_y=tol_y).opening
        arc = model._arc_lengths(pts)
        li = int(opening.left_index) if opening is not None else -1
        ri = int(opening.right_index) if opening is not None else -1
        expected = []
        for i, (_x, y) in enumerate(pts):
            yv = float(y)
            is_top_field = abs(yv - top_y) <= tol_y and (i <= li or i >= ri)
            if is_top_field:
                inhib = 0.65
            elif li <= i <= ri:
                d_left = abs(arc[i] - arc[li])
                d_right = abs(arc[ri] - arc[i])
                d = min(d_left, d_right)
                inhib = 0.65 * math.exp(-d / 180.0)
            else:
                inhib = 0.0
            expected.append(max(0.0, 1.0 - inhib))

        for actual, ref in zip(flux, expected):
            self.assertAlmostEqual(actual, ref, places=9)


if __name__ == "__main__":
    unittest.main()
