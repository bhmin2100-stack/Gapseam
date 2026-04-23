from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from gapsim.engine.deposition_pipeline import (
    ConformalFluxModel,
    FluxModel,
    InhibitionFluxModel,
    OffsetBoolean,
    SimulationCanceled,
    SputterRedepositionFluxModel,
    SealingFluxModel,
    SimulationState,
    TopologyCleanup,
    VertexNormalPropagator,
    ZeroFluxModel,
    deposit_step,
    init_simulation_state,
    normalize_surface_order,
)
from gapsim.engine.preprocess import compute_walls
from gapsim.engine.recipe import extract_case_name, extract_geometry_final, extract_geometry_raw, load_recipe
from gapsim.engine.run_logger import create_run_dir, make_meta, write_json

Point = Tuple[float, float]  # (x, y_user)


class EngineRunner:
    def __init__(self, runs_root: Path | str = "runs") -> None:
        self.runs_root = Path(runs_root)

    def simulate_recipe(
        self,
        recipe: Dict[str, Any],
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        message_cb: Optional[Callable[[str], None]] = None,
        detail_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        OffsetBoolean.require_backend()

        run_cfg = recipe.get("run")
        if not isinstance(run_cfg, dict):
            run_cfg = {}

        model_cfg = recipe.get("model_base")
        if not isinstance(model_cfg, dict):
            model_cfg = {}

        if (not run_cfg) or (not model_cfg):
            steps = recipe.get("steps") or []
            first_params: Dict[str, Any] = {}
            if isinstance(steps, list) and steps:
                first = steps[0]
                if isinstance(first, dict):
                    maybe_params = first.get("params") or {}
                    if isinstance(maybe_params, dict):
                        first_params = maybe_params

            if not run_cfg:
                run_cfg = {
                    "cycles": first_params.get("cycles", 1),
                    "dt": first_params.get("dt", 1.0),
                }

            if not model_cfg:
                model_cfg = {
                    "base_rate": first_params.get("base_rate", 1.0),
                    "epsilon": first_params.get("epsilon", 0.0),
                    "sealed_model": first_params.get("sealed_model", "b"),
                    "decay_k": first_params.get("decay_k", 0.0),
                }

        cycles = max(int(run_cfg.get("cycles", 1)), 1)
        dt = float(run_cfg.get("dt", 1.0))

        base_rate = max(0.0, float(model_cfg.get("base_rate", 1.0)))
        epsilon = max(0.0, float(model_cfg.get("epsilon", 0.0)))
        sealed_model = str(model_cfg.get("sealed_model", "b") or "b").lower()
        decay_k = max(0.0, float(model_cfg.get("decay_k", 0.0)))
        source_kind = str(model_cfg.get("source_kind", "none") or "none").lower()
        source_onset_width_a = max(0.0, float(model_cfg.get("source_onset_width_a", 0.0)))
        raw_decay_pct = model_cfg.get("source_decay_pct")
        if raw_decay_pct is None:
            raw_gamma = model_cfg.get("source_gamma")
            if raw_gamma is not None:
                raw_decay_pct = max(0.0, min(100.0, float(raw_gamma) * 70.0))
        source_decay_pct = None if raw_decay_pct is None else max(0.0, min(100.0, float(raw_decay_pct)))
        raw_dist_decay_pct = model_cfg.get("source_distance_decay_pct")
        if raw_dist_decay_pct is None:
            raw_dist_decay_len = model_cfg.get("source_distance_decay_len_a", model_cfg.get("source_distance_len_a", 0.0))
            try:
                raw_len = max(0.0, float(raw_dist_decay_len))
            except Exception:
                raw_len = 0.0
            if raw_len <= 0.0:
                raw_dist_decay_pct = 0.0
            else:
                raw_dist_decay_pct = (1.0 - math.exp(-100.0 / max(raw_len, 1e-9))) * 100.0
        source_distance_decay_pct = max(0.0, min(100.0, float(raw_dist_decay_pct)))
        sputter_enabled = bool(model_cfg.get("sputter_enabled", False))
        sputter_strength_pct = max(0.0, min(10000.0, float(model_cfg.get("sputter_strength_pct", 0.0))))
        sputter_peak_angle_deg = max(30.0, min(80.0, float(model_cfg.get("sputter_peak_angle_deg", 55.0))))
        sputter_angle_sigma_deg = max(
            1.0,
            min(40.0, float(model_cfg.get("sputter_angle_sigma_deg", model_cfg.get("sputter_peak_width_deg", 15.0)))),
        )
        raw_sputter_depth_decay_length_a = model_cfg.get("sputter_depth_decay_length_a")
        raw_sputter_ion_depth_decay_pct = model_cfg.get("sputter_ion_depth_decay_pct", 70.0)
        sputter_vis_exponent = max(
            0.0,
            min(8.0, float(model_cfg.get("sputter_sky_vis_exponent", model_cfg.get("sputter_vis_exponent", 1.0)))),
        )
        sputter_source_height_a = max(0.0, float(model_cfg.get("sputter_source_height_a", 10000.0) or 10000.0))
        inhibition_enabled = bool(model_cfg.get("inhibition_enabled", False))
        inhibition_i_max = max(0.0, min(1.0, float(model_cfg.get("inhibition_i_max", 0.0))))
        inhibition_lambda_a = max(0.0, float(model_cfg.get("inhibition_lambda_a", 0.0)))
        redepo_enabled = bool(model_cfg.get("redepo_enabled", False))
        redepo_efficiency_pct = max(0.0, min(100.0, float(model_cfg.get("redepo_efficiency_pct", 50.0))))
        raw_redepo_lobe_sigma_deg = model_cfg.get("redepo_lobe_sigma_deg")
        raw_redepo_specular_spread_pct = model_cfg.get("redepo_specular_spread_pct", 30.0)
        reparam_ds_a = max(0.5, min(200.0, float(model_cfg.get("reparam_ds_a", 2.5))))
        phase1_switches = recipe.get("phase1_switches")
        conformal_enabled = True
        sputter_only = bool(model_cfg.get("sputter_only", False))
        if isinstance(phase1_switches, dict):
            conformal_cfg = phase1_switches.get("conformal")
            if isinstance(conformal_cfg, dict):
                conformal_enabled = bool(conformal_cfg.get("enabled", True))
            sputter_cfg = phase1_switches.get("sputter")
            if isinstance(sputter_cfg, dict):
                sputter_params = sputter_cfg.get("params")
                if isinstance(sputter_params, dict):
                    sputter_only = bool(sputter_params.get("sputter_only", sputter_only))
        elif "conformal_enabled" in model_cfg:
            conformal_enabled = bool(model_cfg.get("conformal_enabled", True))
        if sputter_only:
            conformal_enabled = False

        def canceled() -> bool:
            return bool(cancel_check()) if cancel_check else False

        def say(s: str) -> None:
            if message_cb:
                message_cb(s)

        def detail(payload: Dict[str, Any]) -> None:
            if detail_cb:
                detail_cb(payload)

        raw_pts = extract_geometry_raw(recipe)
        pts = normalize_surface_order(extract_geometry_final(recipe))

        y_top_geom = max((float(p[1]) for p in pts), default=0.0)
        max_depth_geom = max((max(0.0, y_top_geom - float(p[1])) for p in pts), default=0.0)
        if raw_sputter_depth_decay_length_a is None:
            legacy_depth_pct = max(0.0, min(100.0, float(raw_sputter_ion_depth_decay_pct or 0.0)))
            if legacy_depth_pct <= 0.0 or max_depth_geom <= 1e-9:
                sputter_depth_decay_length_a = 0.0
            else:
                legacy_floor = max(1e-6, 1.0 - (legacy_depth_pct / 100.0))
                sputter_depth_decay_length_a = max_depth_geom / max(1e-9, -math.log(legacy_floor))
        else:
            sputter_depth_decay_length_a = max(0.0, float(raw_sputter_depth_decay_length_a))

        if raw_redepo_lobe_sigma_deg is None:
            legacy_spread_pct = max(0.0, min(100.0, float(raw_redepo_specular_spread_pct or 30.0)))
            redepo_lobe_sigma_deg = max(1.0, min(60.0, 5.0 + (0.35 * legacy_spread_pct)))
        else:
            redepo_lobe_sigma_deg = max(1.0, min(60.0, float(raw_redepo_lobe_sigma_deg)))

        sim_state: Optional[SimulationState] = None
        if len(pts) >= 2:
            units = "A"
            recipe_units = recipe.get("units")
            if isinstance(recipe_units, dict):
                units = str(recipe_units.get("length", "A"))
            sim_state = init_simulation_state(pts, units=units, reparam_ds_a=reparam_ds_a)

        if sealed_model.startswith("a") or sealed_model.startswith("b"):
            base_deposition_model: FluxModel = SealingFluxModel(
                epsilon=epsilon,
                sealed_model=sealed_model,
                decay_k=decay_k,
                source_kind=source_kind,
                source_onset_width_a=source_onset_width_a,
                source_decay_pct=source_decay_pct,
                source_distance_decay_pct=source_distance_decay_pct,
                source_block_width_a=model_cfg.get("source_block_width_a"),
                source_gamma=model_cfg.get("source_gamma"),
            )
        else:
            base_deposition_model = ConformalFluxModel()
        etch_reference_model: FluxModel = base_deposition_model
        flux_model: FluxModel
        if conformal_enabled:
            flux_model = base_deposition_model
        else:
            flux_model = ZeroFluxModel()
            etch_reference_model = ConformalFluxModel()
        if inhibition_enabled and inhibition_i_max > 0.0:
            flux_model = InhibitionFluxModel(
                flux_model,
                i_max=inhibition_i_max,
                lambda_a=inhibition_lambda_a,
            )
        if (sputter_enabled and sputter_strength_pct > 0.0) or (redepo_enabled and redepo_efficiency_pct > 0.0):
            flux_model = SputterRedepositionFluxModel(
                flux_model,
                etch_reference_model=etch_reference_model,
                sputter_only_mode=sputter_only,
                sputter_enabled=sputter_enabled,
                sputter_strength_pct=sputter_strength_pct,
                sputter_peak_angle_deg=sputter_peak_angle_deg,
                sputter_angle_sigma_deg=sputter_angle_sigma_deg,
                sputter_depth_decay_length_a=sputter_depth_decay_length_a,
                sputter_vis_exponent=sputter_vis_exponent,
                sputter_source_height_a=sputter_source_height_a,
                redepo_enabled=redepo_enabled,
                redepo_efficiency_pct=redepo_efficiency_pct,
                redepo_lobe_sigma_deg=redepo_lobe_sigma_deg,
            )
        propagator = VertexNormalPropagator()
        cleanup = TopologyCleanup()

        completed_step = 0
        for step in range(0, cycles + 1):
            if canceled():
                say("Canceled.")
                break

            pts_now = sim_state.surface.points if sim_state is not None else pts
            completed_step = int(step)

            if progress_cb:
                progress_cb(step, cycles)
            detail(
                {
                    "kind": "cycle",
                    "step": int(step),
                    "total": int(cycles),
                    "points": int(len(pts_now)),
                }
            )

            if step == cycles:
                break

            dr = base_rate * dt
            if dr <= 0.0 or sim_state is None or len(sim_state.surface.points) < 2:
                continue
            try:
                sim_state = deposit_step(
                    dr,
                    sim_state,
                    model=flux_model,
                    propagator=propagator,
                    cleanup=cleanup,
                    detail_cb=lambda payload, step=step, cycles=cycles: detail(
                        {
                            "step": int(step),
                            "total": int(cycles),
                            **payload,
                        }
                    ),
                    cancel_check=canceled,
                )
            except SimulationCanceled:
                say("Canceled.")
                break

        final_profile = list(sim_state.surface.points) if sim_state is not None else list(pts)
        return {
            "final_profile": [(float(x), float(y)) for x, y in final_profile],
            "completed_step": int(completed_step),
            "cycles": int(cycles),
            "points": int(len(final_profile)),
            "raw_profile": [(float(x), float(y)) for x, y in raw_pts],
        }

    def run(
        self,
        recipe_path: Path | str,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        message_cb: Optional[Callable[[str], None]] = None,
        detail_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Path:
        OffsetBoolean.require_backend()

        recipe_path = Path(recipe_path)
        recipe: Dict[str, Any] = load_recipe(recipe_path)

        run_cfg = recipe.get("run")
        if not isinstance(run_cfg, dict):
            run_cfg = {}

        model_cfg = recipe.get("model_base")
        if not isinstance(model_cfg, dict):
            model_cfg = {}

        if (not run_cfg) or (not model_cfg):
            steps = recipe.get("steps") or []
            first_params: Dict[str, Any] = {}
            if isinstance(steps, list) and steps:
                first = steps[0]
                if isinstance(first, dict):
                    maybe_params = first.get("params") or {}
                    if isinstance(maybe_params, dict):
                        first_params = maybe_params

            if not run_cfg:
                run_cfg = {
                    "cycles": first_params.get("cycles", 1),
                    "dt": first_params.get("dt", 1.0),
                }

            if not model_cfg:
                model_cfg = {
                    "base_rate": first_params.get("base_rate", 1.0),
                    "epsilon": first_params.get("epsilon", 0.0),
                    "sealed_model": first_params.get("sealed_model", "b"),
                    "decay_k": first_params.get("decay_k", 0.0),
                }

        cycles = max(int(run_cfg.get("cycles", 1)), 1)
        dt = float(run_cfg.get("dt", 1.0))

        base_rate = max(0.0, float(model_cfg.get("base_rate", 1.0)))
        epsilon = max(0.0, float(model_cfg.get("epsilon", 0.0)))
        sealed_model = str(model_cfg.get("sealed_model", "b") or "b").lower()
        decay_k = max(0.0, float(model_cfg.get("decay_k", 0.0)))
        source_kind = str(model_cfg.get("source_kind", "none") or "none").lower()
        source_onset_width_a = max(0.0, float(model_cfg.get("source_onset_width_a", 0.0)))
        raw_decay_pct = model_cfg.get("source_decay_pct")
        if raw_decay_pct is None:
            # Legacy fallback path.
            raw_gamma = model_cfg.get("source_gamma")
            if raw_gamma is not None:
                raw_decay_pct = max(0.0, min(100.0, float(raw_gamma) * 70.0))
        source_decay_pct = None if raw_decay_pct is None else max(0.0, min(100.0, float(raw_decay_pct)))
        raw_dist_decay_pct = model_cfg.get("source_distance_decay_pct")
        if raw_dist_decay_pct is None:
            raw_dist_decay_len = model_cfg.get("source_distance_decay_len_a", model_cfg.get("source_distance_len_a", 0.0))
            try:
                raw_len = max(0.0, float(raw_dist_decay_len))
            except Exception:
                raw_len = 0.0
            if raw_len <= 0.0:
                raw_dist_decay_pct = 0.0
            else:
                # Legacy fallback: map L(A) to an equivalent percent at 100A reference.
                raw_dist_decay_pct = (1.0 - math.exp(-100.0 / max(raw_len, 1e-9))) * 100.0
        source_distance_decay_pct = max(0.0, min(100.0, float(raw_dist_decay_pct)))
        sputter_enabled = bool(model_cfg.get("sputter_enabled", False))
        sputter_strength_pct = max(0.0, min(10000.0, float(model_cfg.get("sputter_strength_pct", 0.0))))
        sputter_peak_angle_deg = max(30.0, min(80.0, float(model_cfg.get("sputter_peak_angle_deg", 55.0))))
        sputter_angle_sigma_deg = max(
            1.0,
            min(40.0, float(model_cfg.get("sputter_angle_sigma_deg", model_cfg.get("sputter_peak_width_deg", 15.0)))),
        )
        raw_sputter_depth_decay_length_a = model_cfg.get("sputter_depth_decay_length_a")
        raw_sputter_ion_depth_decay_pct = model_cfg.get("sputter_ion_depth_decay_pct", 70.0)
        sputter_vis_exponent = max(
            0.0,
            min(8.0, float(model_cfg.get("sputter_sky_vis_exponent", model_cfg.get("sputter_vis_exponent", 1.0)))),
        )
        sputter_source_height_a = max(0.0, float(model_cfg.get("sputter_source_height_a", 10000.0) or 10000.0))
        inhibition_enabled = bool(model_cfg.get("inhibition_enabled", False))
        inhibition_i_max = max(0.0, min(1.0, float(model_cfg.get("inhibition_i_max", 0.0))))
        inhibition_lambda_a = max(0.0, float(model_cfg.get("inhibition_lambda_a", 0.0)))
        redepo_enabled = bool(model_cfg.get("redepo_enabled", False))
        redepo_efficiency_pct = max(0.0, min(100.0, float(model_cfg.get("redepo_efficiency_pct", 50.0))))
        raw_redepo_lobe_sigma_deg = model_cfg.get("redepo_lobe_sigma_deg")
        raw_redepo_specular_spread_pct = model_cfg.get("redepo_specular_spread_pct", 30.0)
        reparam_ds_a = max(0.5, min(200.0, float(model_cfg.get("reparam_ds_a", 2.5))))
        phase1_switches = recipe.get("phase1_switches")
        conformal_enabled = True
        sputter_only = bool(model_cfg.get("sputter_only", False))
        if isinstance(phase1_switches, dict):
            conformal_cfg = phase1_switches.get("conformal")
            if isinstance(conformal_cfg, dict):
                conformal_enabled = bool(conformal_cfg.get("enabled", True))
            sputter_cfg = phase1_switches.get("sputter")
            if isinstance(sputter_cfg, dict):
                sputter_params = sputter_cfg.get("params")
                if isinstance(sputter_params, dict):
                    sputter_only = bool(sputter_params.get("sputter_only", sputter_only))
        elif "conformal_enabled" in model_cfg:
            conformal_enabled = bool(model_cfg.get("conformal_enabled", True))
        if sputter_only:
            conformal_enabled = False
        run_stage_cfg = recipe.get("run_stage")
        if not isinstance(run_stage_cfg, dict):
            run_stage_cfg = {}
        stage_index = max(1, int(run_stage_cfg.get("index", 1)))
        continued_from = run_stage_cfg.get("continued_from")
        if continued_from is not None:
            continued_from = str(continued_from)

        case_name = extract_case_name(recipe)
        run_dir = create_run_dir(self.runs_root, case_name)

        def canceled() -> bool:
            return bool(cancel_check()) if cancel_check else False

        def say(s: str) -> None:
            if message_cb:
                message_cb(s)

        def detail(payload: Dict[str, Any]) -> None:
            if detail_cb:
                detail_cb(payload)

        # persist inputs
        (run_dir / "recipe.json").write_text(recipe_path.read_text(encoding="utf-8"), encoding="utf-8")
        write_json(run_dir / "meta.json", make_meta(recipe, engine_version="0.0.4-vertex-normal-pipeline"))

        raw_pts = extract_geometry_raw(recipe)
        pts = normalize_surface_order(extract_geometry_final(recipe))
        self._write_points_csv(run_dir / "geometry_raw.csv", raw_pts)
        self._write_points_csv(run_dir / "geometry_smooth.csv", pts)
        write_json(run_dir / "events.json", [])

        y_top_geom = max((float(p[1]) for p in pts), default=0.0)
        max_depth_geom = max((max(0.0, y_top_geom - float(p[1])) for p in pts), default=0.0)
        if raw_sputter_depth_decay_length_a is None:
            legacy_depth_pct = max(0.0, min(100.0, float(raw_sputter_ion_depth_decay_pct or 0.0)))
            if legacy_depth_pct <= 0.0 or max_depth_geom <= 1e-9:
                sputter_depth_decay_length_a = 0.0
            else:
                legacy_floor = max(1e-6, 1.0 - (legacy_depth_pct / 100.0))
                sputter_depth_decay_length_a = max_depth_geom / max(1e-9, -math.log(legacy_floor))
        else:
            sputter_depth_decay_length_a = max(0.0, float(raw_sputter_depth_decay_length_a))

        if raw_redepo_lobe_sigma_deg is None:
            legacy_spread_pct = max(0.0, min(100.0, float(raw_redepo_specular_spread_pct or 30.0)))
            redepo_lobe_sigma_deg = max(1.0, min(60.0, 5.0 + (0.35 * legacy_spread_pct)))
        else:
            redepo_lobe_sigma_deg = max(1.0, min(60.0, float(raw_redepo_lobe_sigma_deg)))

        x_window = None
        if len(pts) >= 2:
            wl, wr, _ = compute_walls(pts)
            x_window = (wl, wr)

        sim_state: Optional[SimulationState] = None
        if len(pts) >= 2:
            units = "A"
            recipe_units = recipe.get("units")
            if isinstance(recipe_units, dict):
                units = str(recipe_units.get("length", "A"))
            sim_state = init_simulation_state(pts, units=units, reparam_ds_a=reparam_ds_a)

        # module contract: model -> propagator -> cleanup, offset only as cleanup hint.
        if sealed_model.startswith("a") or sealed_model.startswith("b"):
            base_deposition_model: FluxModel = SealingFluxModel(
                epsilon=epsilon,
                sealed_model=sealed_model,
                decay_k=decay_k,
                source_kind=source_kind,
                source_onset_width_a=source_onset_width_a,
                source_decay_pct=source_decay_pct,
                source_distance_decay_pct=source_distance_decay_pct,
                source_block_width_a=model_cfg.get("source_block_width_a"),
                source_gamma=model_cfg.get("source_gamma"),
            )
        else:
            base_deposition_model = ConformalFluxModel()
        etch_reference_model: FluxModel = base_deposition_model
        flux_model: FluxModel
        if conformal_enabled:
            flux_model = base_deposition_model
        else:
            flux_model = ZeroFluxModel()
            etch_reference_model = ConformalFluxModel()
        if inhibition_enabled and inhibition_i_max > 0.0:
            flux_model = InhibitionFluxModel(
                flux_model,
                i_max=inhibition_i_max,
                lambda_a=inhibition_lambda_a,
            )
        if (sputter_enabled and sputter_strength_pct > 0.0) or (redepo_enabled and redepo_efficiency_pct > 0.0):
            flux_model = SputterRedepositionFluxModel(
                flux_model,
                etch_reference_model=etch_reference_model,
                sputter_only_mode=sputter_only,
                sputter_enabled=sputter_enabled,
                sputter_strength_pct=sputter_strength_pct,
                sputter_peak_angle_deg=sputter_peak_angle_deg,
                sputter_angle_sigma_deg=sputter_angle_sigma_deg,
                sputter_depth_decay_length_a=sputter_depth_decay_length_a,
                sputter_vis_exponent=sputter_vis_exponent,
                sputter_source_height_a=sputter_source_height_a,
                redepo_enabled=redepo_enabled,
                redepo_efficiency_pct=redepo_efficiency_pct,
                redepo_lobe_sigma_deg=redepo_lobe_sigma_deg,
            )
        propagator = VertexNormalPropagator()
        cleanup = TopologyCleanup()

        frame_steps: List[int] = []
        frame_profiles: List[List[Point]] = []
        frame_voids: List[List[List[Point]]] = []

        metrics_path = run_dir / "metrics.csv"
        with metrics_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["step", "time", "opening_width", "fill_ratio", "mode"])

            for step in range(0, cycles + 1):
                if canceled():
                    say("Canceled.")
                    break

                pts_now = sim_state.surface.points if sim_state is not None else pts
                t = step * dt
                xs = [p[0] for p in pts_now] if pts_now else [0.0]
                opening = float(max(xs) - min(xs)) if xs else 0.0
                mode = "open"
                if sim_state is not None:
                    mode = str(sim_state.meta.get("mode", "open"))
                w.writerow([step, f"{t:.6f}", f"{opening:.6f}", f"{0.0:.6f}", mode])

                void_polygons: List[List[Point]] = []
                if sim_state is not None:
                    # Keep per-step void extraction lightweight; cumulative persistence is handled in Results rendering.
                    void_polygons = OffsetBoolean.void_polygons_float(sim_state)

                # Keep per-cycle geometry for Results playback.
                frame_steps.append(step)
                frame_profiles.append(list(pts_now))
                frame_voids.append(void_polygons)

                if progress_cb:
                    progress_cb(step, cycles)
                detail(
                    {
                        "kind": "cycle",
                        "step": int(step),
                        "total": int(cycles),
                        "points": int(len(pts_now)),
                    }
                )

                if step == cycles:
                    break

                dr = base_rate * dt
                if dr <= 0.0 or sim_state is None or len(sim_state.surface.points) < 2:
                    continue
                try:
                    sim_state = deposit_step(
                        dr,
                        sim_state,
                        model=flux_model,
                        propagator=propagator,
                        cleanup=cleanup,
                        detail_cb=lambda payload, step=step, cycles=cycles: detail(
                            {
                                "step": int(step),
                                "total": int(cycles),
                                **payload,
                            }
                        ),
                        cancel_check=canceled,
                    )
                except SimulationCanceled:
                    say("Canceled.")
                    break

        write_json(
            run_dir / "profiles.json",
            {
                "version": 1,
                "stage": {
                    "index": stage_index,
                    "continued_from": continued_from,
                },
                "frame_steps": frame_steps,
                "frame_profiles": frame_profiles,
                "frame_voids": frame_voids,
                "frame_voids_mode": "current",
                "frame_stage_ids": [stage_index for _ in frame_profiles],
                "x_window": list(x_window) if x_window is not None else None,
            },
        )

        return run_dir

    @staticmethod
    def _write_points_csv(path: Path, pts: List[Point]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["x", "y"])
            for x, y in pts:
                w.writerow([f"{x:.6f}", f"{y:.6f}"])
