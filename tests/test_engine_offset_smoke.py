from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gapsim.engine.deposition_pipeline import (
    ConformalFluxModel,
    OffsetBoolean,
    SimulationState,
    Surface,
    TopologyCleanup,
    VertexNormalPropagator,
    _clip_difference,
    _clip_intersection,
    _clip_to_roi_if_needed,
    _clip_union,
    _extract_surface_from_solid,
    _int_paths_area,
    _needs_reference_cleanup,
    _normalize_int_paths,
    _surface_chain_score,
    init_simulation_state,
)
from gapsim.engine.runner import EngineRunner

try:
    import pyclipper  # noqa: F401
except Exception:  # noqa: BLE001
    pyclipper = None  # type: ignore[assignment]


class EngineOffsetSmokeTest(unittest.TestCase):
    def _canonical_path(self, path):
        if not path:
            return tuple()
        pts = [tuple(p) for p in path]
        variants = []
        for seq in (pts, list(reversed(pts))):
            for i in range(len(seq)):
                rot = tuple(seq[i:] + seq[:i])
                variants.append(rot)
        return min(variants)

    def _canonical_paths(self, paths):
        return sorted(self._canonical_path(path) for path in paths if path)

    def _reference_cleanup(self, proposed, state, *, solid_ref_paths_i=None):
        fallback = list(proposed)
        candidate_from_surface = OffsetBoolean.surface_to_solid(
            fallback,
            scale=state.scale,
            y_bot_i=state.y_bot_i,
            roi_path_i=state.roi_path_i,
        )
        solid_candidate = _clip_union(state.solid_paths_i, candidate_from_surface)
        solid_candidate = _clip_intersection(solid_candidate, [state.roi_path_i])
        if not solid_candidate:
            solid_candidate = list(state.solid_paths_i)

        candidate_surface = _extract_surface_from_solid(state, solid_candidate, fallback)
        best_surface = candidate_surface
        best_solid = solid_candidate
        best_score = _surface_chain_score(candidate_surface, state)

        if solid_ref_paths_i and _needs_reference_cleanup(best_score, state):
            solid_ref = _clip_union(state.solid_paths_i, solid_ref_paths_i)
            solid_ref = _clip_intersection(solid_ref, [state.roi_path_i])
            if solid_ref:
                ref_surface = _extract_surface_from_solid(state, solid_ref, fallback)
                ref_score = _surface_chain_score(ref_surface, state)
                if ref_score > best_score:
                    best_surface = ref_surface
                    best_solid = solid_ref
                    best_score = ref_score

        if solid_ref_paths_i:
            ref_paths = _normalize_int_paths(solid_ref_paths_i)
            if ref_paths:
                ref_state = SimulationState(
                    surface=state.surface,
                    scale=state.scale,
                    x_left_i=state.x_left_i,
                    x_right_i=state.x_right_i,
                    y_top_i=state.y_top_i,
                    y_bot_i=state.y_bot_i,
                    roi_path_i=list(state.roi_path_i),
                    solid_paths_i=list(ref_paths),
                    meta=dict(state.meta),
                )
                ref_voids = OffsetBoolean.collect_void_air(ref_state)
                if ref_voids:
                    best_state = SimulationState(
                        surface=state.surface,
                        scale=state.scale,
                        x_left_i=state.x_left_i,
                        x_right_i=state.x_right_i,
                        y_top_i=state.y_top_i,
                        y_bot_i=state.y_bot_i,
                        roi_path_i=list(state.roi_path_i),
                        solid_paths_i=list(best_solid),
                        meta=dict(state.meta),
                    )
                    best_voids = OffsetBoolean.collect_void_air(best_state)
                    ref_void_area = _int_paths_area(ref_voids)
                    best_void_area = _int_paths_area(best_voids)
                    if ref_void_area > 0.0 and best_void_area + 1.0 < ref_void_area * 0.98:
                        carved = _clip_difference(best_solid, ref_voids)
                        carved = _clip_intersection(carved, [state.roi_path_i])
                        if carved:
                            best_solid = carved
                            best_surface = _extract_surface_from_solid(state, best_solid, fallback)
        return best_surface, best_solid

    def test_vertex_corner_uses_vertex_normal_without_miter(self) -> None:
        pts = [
            (-2.0, 0.0),
            (-1.0, 0.0),
            (0.0, 0.0),
            (0.0, -1.0),
            (0.0, -2.0),
        ]
        prop = VertexNormalPropagator()
        moved = prop.advance(pts, [1.0] * len(pts), 0.2)

        # Right-angle corner uses averaged vertex normal (45 deg).
        expected = 0.2 / (2.0 ** 0.5)
        self.assertAlmostEqual(moved[2][0], expected, places=6)
        self.assertAlmostEqual(moved[2][1], expected, places=6)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_source_transport_isotropic_growth_progresses(self) -> None:
        pts = [
            (-80.0, 0.0),
            (-30.0, 0.0),
            (-18.0, -200.0),
            (-10.0, -500.0),
            (10.0, -500.0),
            (18.0, -200.0),
            (30.0, 0.0),
            (80.0, 0.0),
        ]
        recipe = {
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "structure_points": pts,
            "smoothing": {"base_points": pts, "segments": 300, "iterations": 0},
            "geometry_final": pts,
            "run": {
                "case_name": "source_transport_iso_progress",
                "cycles": 30,
                "dt": 1.0,
            },
            "model_base": {
                "base_rate": 1.0,
                "epsilon": 10.0,
                "sealed_model": "b",
                "decay_k": 1.0,
                "source_kind": "dipas",
                "source_block_width_a": 10.0,
                "source_onset_width_a": 30.0,
                "source_gamma": 1.0,
            },
        }

        with tempfile.TemporaryDirectory(prefix="gapsim_source_transport_smoke_") as td:
            root = Path(td)
            recipe_path = root / "recipe.json"
            recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")

            run_dir = EngineRunner(root / "runs").run(recipe_path)
            data = json.loads((run_dir / "profiles.json").read_text(encoding="utf-8"))
            frames = data.get("frame_profiles") or []
            self.assertGreaterEqual(len(frames), 2)

            first = frames[0]
            last = frames[-1]
            self.assertGreaterEqual(len(first), 4)
            self.assertGreaterEqual(len(last), 4)
            n = min(len(first), len(last))
            moved = [
                ((float(last[i][0]) - float(first[i][0])) ** 2 + (float(last[i][1]) - float(first[i][1])) ** 2) ** 0.5
                for i in range(1, n - 1)
            ]
            self.assertGreater(max(moved, default=0.0), 0.5)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_offset_boolean_growth_smoke(self) -> None:
        recipe = {
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "structure_points": [
                (200.0, 0.0),
                (100.0, 0.0),
                (35.0, -350.0),
                (-35.0, -350.0),
                (-100.0, 0.0),
                (-200.0, 0.0),
            ],
            "smoothing": {
                "base_points": [
                    (200.0, 0.0),
                    (100.0, 0.0),
                    (35.0, -350.0),
                    (-35.0, -350.0),
                    (-100.0, 0.0),
                    (-200.0, 0.0),
                ],
                "segments": 200,
                "iterations": 0,
            },
            "geometry_final": [
                (200.0, 0.0),
                (100.0, 0.0),
                (35.0, -350.0),
                (-35.0, -350.0),
                (-100.0, 0.0),
                (-200.0, 0.0),
            ],
            "run": {
                "case_name": "offset_smoke",
                "cycles": 30,
                "dt": 1.0,
            },
            "model_base": {
                "base_rate": 1.2,
                "epsilon": 10.0,
            },
        }

        with tempfile.TemporaryDirectory(prefix="gapsim_offset_smoke_") as td:
            root = Path(td)
            recipe_path = root / "recipe.json"
            recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")

            run_dir = EngineRunner(root / "runs").run(recipe_path)
            self.assertTrue(run_dir.exists())

            profiles_path = run_dir / "profiles.json"
            self.assertTrue(profiles_path.exists())
            data = json.loads(profiles_path.read_text(encoding="utf-8"))

            frames = data.get("frame_profiles") or []
            frame_voids = data.get("frame_voids") or []
            self.assertGreaterEqual(len(frames), 6)
            self.assertEqual(len(frame_voids), len(frames))
            for frm in frames:
                self.assertIsInstance(frm, list)
                self.assertGreaterEqual(len(frm), 2)

            snapshots = sorted(run_dir.glob("snapshot_*.png"))
            self.assertEqual(len(snapshots), 0)

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_cleanup_roi_skip_matches_explicit_intersection(self) -> None:
        state = init_simulation_state(
            [
                (-200.0, 0.0),
                (-80.0, 0.0),
                (-40.0, -220.0),
                (40.0, -220.0),
                (80.0, 0.0),
                (200.0, 0.0),
            ],
            reparam_ds_a=8.0,
        )
        inside_a = list(state.solid_paths_i)
        inside_b = OffsetBoolean.surface_to_solid(
            [
                (-200.0, 0.0),
                (-100.0, 0.0),
                (-55.0, -180.0),
                (55.0, -180.0),
                (100.0, 0.0),
                (200.0, 0.0),
            ],
            scale=state.scale,
            y_bot_i=state.y_bot_i,
            roi_path_i=state.roi_path_i,
        )
        union_paths = _clip_union(inside_a, inside_b)
        self.assertEqual(
            self._canonical_paths(_clip_to_roi_if_needed(union_paths, state)),
            self._canonical_paths(_clip_intersection(union_paths, [state.roi_path_i])),
        )

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_cleanup_matches_reference_on_representative_deposition_step(self) -> None:
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
        state = init_simulation_state(pts, reparam_ds_a=8.0)
        propagator = VertexNormalPropagator()
        cleanup = TopologyCleanup()
        flux = ConformalFluxModel().compute_flux(state)
        proposed = propagator.advance(state.surface.points, flux, 3.0)
        solid_ref = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=3.0)

        actual_surface, actual_solid = cleanup.cleanup(proposed, state, solid_ref_paths_i=solid_ref)
        ref_surface, ref_solid = self._reference_cleanup(proposed, state, solid_ref_paths_i=solid_ref)

        self.assertEqual(len(actual_surface), len(ref_surface))
        for actual, ref in zip(actual_surface, ref_surface):
            self.assertAlmostEqual(actual[0], ref[0], places=9)
            self.assertAlmostEqual(actual[1], ref[1], places=9)
        self.assertEqual(self._canonical_paths(actual_solid), self._canonical_paths(ref_solid))

    @unittest.skipIf(pyclipper is None, "pyclipper is not installed")
    def test_trapped_void_stays_recorded_after_pinch_off(self) -> None:
        # Hourglass-like trench geometry: closes near top while leaving a trapped cavity.
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
        recipe = {
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "structure_points": pts,
            "smoothing": {"base_points": pts, "segments": 200, "iterations": 0},
            "geometry_final": pts,
            "run": {
                "case_name": "void_pinch_smoke",
                "cycles": 120,
                "dt": 1.0,
            },
            "model_base": {
                "base_rate": 3.0,
                "epsilon": 10.0,
            },
        }

        with tempfile.TemporaryDirectory(prefix="gapsim_void_smoke_") as td:
            root = Path(td)
            recipe_path = root / "recipe.json"
            recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")

            run_dir = EngineRunner(root / "runs").run(recipe_path)
            data = json.loads((run_dir / "profiles.json").read_text(encoding="utf-8"))

            frames = data.get("frame_profiles") or []
            frame_voids = data.get("frame_voids") or []
            self.assertEqual(len(frame_voids), len(frames))
            self.assertGreaterEqual(len(frames), 5)

            void_counts = [len(vf) for vf in frame_voids]
            self.assertGreaterEqual(max(void_counts), 1, "Expected at least one trapped void after pinch-off")

            first_nonzero = next((i for i, c in enumerate(void_counts) if c > 0), None)
            self.assertIsNotNone(first_nonzero)
            if first_nonzero is not None:
                self.assertTrue(
                    all(c > 0 for c in void_counts[first_nonzero:]),
                    "Once trapped void appears, it should remain isolated and persist in later frames",
                )

if __name__ == "__main__":
    unittest.main()
