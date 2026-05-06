from __future__ import annotations

import json
import math
import random
import traceback
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from gapsim.engine.runner import EngineRunner
from gapsim.prediction import (
    Point,
    build_feature_entries,
    build_switch_state_from_prediction,
    deep_copy_switch_state,
    estimate_fast_prediction_params,
    feature_loss,
    recipe_with_switch_state,
)


class PredictionCanceled(Exception):
    pass


class ParameterPredictionWorker(QObject):
    progress = Signal(int, int)
    message = Signal(str)
    finished = Signal(object)
    error = Signal(str)
    canceled = Signal()

    def __init__(
        self,
        *,
        pre_points: List[Point],
        post_points: List[Point],
        anchor_spec: Dict[str, Any],
        base_recipe: Dict[str, Any],
        base_switch_state: Dict[str, Dict[str, Any]],
        coarse_count: int = 5,
        local_seed_count: int = 1,
        local_count_per_seed: int = 2,
        preview_max_steps: int = 80,
        preview_reparam_ds_a: float = 8.0,
    ) -> None:
        super().__init__()
        self.pre_points = [(float(x), float(y)) for x, y in pre_points]
        self.post_points = [(float(x), float(y)) for x, y in post_points]
        self.anchor_spec = dict(anchor_spec or {})
        self.base_recipe = json.loads(json.dumps(base_recipe))
        self.base_switch_state = deep_copy_switch_state(base_switch_state)
        self.coarse_count = max(2, int(coarse_count))
        self.local_seed_count = max(1, int(local_seed_count))
        self.local_count_per_seed = max(1, int(local_count_per_seed))
        self.preview_max_steps = max(20, int(preview_max_steps))
        self.preview_reparam_ds_a = max(2.5, float(preview_reparam_ds_a))
        self._cancel = False
        self._rng = random.Random(1337)

    def request_cancel(self) -> None:
        self._cancel = True

    def _check_cancel(self) -> None:
        if self._cancel:
            raise PredictionCanceled()

    @staticmethod
    def _profile_bounds(points: List[Point]) -> Dict[str, float]:
        xs = [float(x) for x, _y in points] or [-1.0, 1.0]
        ys = [float(y) for _x, y in points] or [0.0, -1.0]
        return {
            "min_x": min(xs),
            "max_x": max(xs),
            "top_y": max(ys),
            "bottom_y": min(ys),
            "width": max(1.0, max(xs) - min(xs)),
            "depth": max(1.0, max(ys) - min(ys)),
        }

    def _base_params(self) -> Dict[str, float]:
        conformal = self.base_switch_state.get("conformal", {})
        attenuation = self.base_switch_state.get("attenuation", {})
        sputter = self.base_switch_state.get("sputter", {})
        redepo = self.base_switch_state.get("redepo", {})
        inhibition = self.base_switch_state.get("inhibition", {})
        conformal_params = conformal.get("params") if isinstance(conformal, dict) else {}
        attenuation_params = attenuation.get("params") if isinstance(attenuation, dict) else {}
        sputter_params = sputter.get("params") if isinstance(sputter, dict) else {}
        redepo_params = redepo.get("params") if isinstance(redepo, dict) else {}
        inhibition_params = inhibition.get("params") if isinstance(inhibition, dict) else {}
        sputter_enabled = bool(sputter.get("enabled", False)) if isinstance(sputter, dict) else False
        redepo_enabled = bool(redepo.get("enabled", False)) if isinstance(redepo, dict) else False
        return {
            "base_rate": max(0.01, float((conformal_params or {}).get("base_rate", 1.0) or 1.0)),
            "n_steps": max(1.0, float((conformal_params or {}).get("n_steps", 200) or 200)),
            "source_onset_width_a": max(0.0, float((attenuation_params or {}).get("source_onset_width_a", 0.0) or 0.0)),
            "source_decay_pct": max(0.0, min(100.0, float((attenuation_params or {}).get("source_decay_pct", 0.0) or 0.0))),
            "source_distance_decay_pct": max(
                0.0,
                min(100.0, float((attenuation_params or {}).get("source_distance_decay_pct", 0.0) or 0.0)),
            ),
            "sputter_strength_pct": max(
                0.0,
                min(
                    10000.0,
                    float((sputter_params or {}).get("strength_pct", 0.0) or 0.0) if sputter_enabled else 0.0,
                ),
            ),
            "redepo_efficiency_pct": max(
                0.0,
                min(
                    100.0,
                    float((redepo_params or {}).get("efficiency_pct", 0.0) or 0.0) if redepo_enabled else 0.0,
                ),
            ),
            "redepo_lobe_sigma_deg": max(
                1.0,
                min(60.0, float((redepo_params or {}).get("lobe_sigma_deg", 20.0) or 20.0)),
            ),
            "i_max": max(0.0, min(1.0, float((inhibition_params or {}).get("i_max", 0.0) or 0.0))),
            "lambda_a": max(1.0, float((inhibition_params or {}).get("lambda_a", 500.0) or 500.0)),
        }

    def _parameter_bounds(self, base_params: Dict[str, float]) -> Dict[str, Tuple[float, float]]:
        bounds = self._profile_bounds(self.pre_points + self.post_points)
        width = max(10.0, float(bounds["width"]))
        depth = max(10.0, float(bounds["depth"]))
        n_steps = max(20.0, float(base_params["n_steps"]))
        onset = max(0.0, float(base_params["source_onset_width_a"]))
        decay = max(0.0, float(base_params["source_decay_pct"]))
        dist_decay = max(0.0, float(base_params["source_distance_decay_pct"]))
        sputter_strength = max(0.0, float(base_params["sputter_strength_pct"]))
        redepo_eff = max(0.0, float(base_params["redepo_efficiency_pct"]))
        redepo_lobe = max(1.0, float(base_params["redepo_lobe_sigma_deg"]))
        i_max = max(0.0, float(base_params["i_max"]))
        lambda_a = max(10.0, float(base_params["lambda_a"]))
        return {
            "n_steps": (max(10.0, n_steps * 0.5), min(10_000.0, max(80.0, n_steps * 2.0))),
            "source_onset_width_a": (0.0, max(200.0, width * 1.75, onset * 2.0)),
            "source_decay_pct": (0.0, max(100.0, decay + 10.0)),
            "source_distance_decay_pct": (0.0, max(100.0, dist_decay + 10.0)),
            "sputter_strength_pct": (0.0, min(10000.0, max(200.0, sputter_strength * 2.5))),
            "redepo_efficiency_pct": (0.0, 100.0),
            "redepo_lobe_sigma_deg": (1.0, min(60.0, max(30.0, redepo_lobe * 1.5, redepo_eff * 0.5))),
            "i_max": (0.0, 1.0),
            "lambda_a": (10.0, max(1000.0, depth * 4.0, lambda_a * 2.0)),
        }

    @staticmethod
    def _log_sample(rng: random.Random, lo: float, hi: float) -> float:
        if lo <= 0.0 or hi <= lo:
            return lo
        return math.exp(rng.uniform(math.log(lo), math.log(hi)))

    def _sample_candidate(
        self,
        bounds: Dict[str, Tuple[float, float]],
        *,
        fixed_params: Optional[Dict[str, float]] = None,
        center: Optional[Dict[str, float]] = None,
        shrink: float = 1.0,
    ) -> Dict[str, float]:
        out: Dict[str, float] = {key: float(value) for key, value in (fixed_params or {}).items()}
        for name, (lo, hi) in bounds.items():
            if center is not None and name in center:
                mid = float(center[name])
                full_span = max(hi - lo, 1e-9)
                half_span = max(full_span * 0.5 * float(shrink), 1e-6)
                lo_i = max(lo, mid - half_span)
                hi_i = min(hi, mid + half_span)
            else:
                lo_i, hi_i = lo, hi

            if name == "lambda_a":
                value = self._log_sample(self._rng, max(lo_i, 1e-6), max(hi_i, max(lo_i, 1e-6)))
            elif name == "n_steps":
                value = round(self._rng.uniform(lo_i, hi_i))
            else:
                value = self._rng.uniform(lo_i, hi_i)

            if name == "source_decay_pct":
                value = max(0.0, min(100.0, value))
            elif name == "source_distance_decay_pct":
                value = max(0.0, min(100.0, value))
            elif name == "sputter_strength_pct":
                value = max(0.0, min(10000.0, value))
            elif name == "redepo_efficiency_pct":
                value = max(0.0, min(100.0, value))
            elif name == "redepo_lobe_sigma_deg":
                value = max(1.0, min(60.0, value))
            elif name == "i_max":
                value = max(0.0, min(1.0, value))
            out[name] = float(value)
        out["n_steps"] = max(1.0, round(out["n_steps"]))
        return out

    def _preview_params(self, params: Dict[str, float]) -> Tuple[Dict[str, float], float]:
        out = {key: float(value) for key, value in params.items()}
        steps = max(1, int(round(out.get("n_steps", 1.0))))
        preview_steps = max(20, min(steps, self.preview_max_steps))
        out["n_steps"] = float(preview_steps)
        preview_dt = (float(steps) / float(preview_steps)) if preview_steps > 0 else 1.0
        return out, max(1.0, preview_dt)

    def _evaluate_candidate(
        self,
        *,
        target_entries: List[Dict[str, Any]],
        params: Dict[str, float],
        candidate_index: int,
    ) -> Optional[Dict[str, Any]]:
        self._check_cancel()
        preview_params, preview_dt = self._preview_params(params)
        preview_switch_state = build_switch_state_from_prediction(self.base_switch_state, preview_params)
        applied_switch_state = build_switch_state_from_prediction(self.base_switch_state, params)
        recipe = recipe_with_switch_state(self.base_recipe, preview_switch_state)
        run_cfg = recipe.get("run")
        if not isinstance(run_cfg, dict):
            run_cfg = {}
            recipe["run"] = run_cfg
        run_cfg["dt"] = float(preview_dt)
        model_base = recipe.get("model_base")
        if not isinstance(model_base, dict):
            model_base = {}
            recipe["model_base"] = model_base
        model_base["reparam_ds_a"] = max(float(model_base.get("reparam_ds_a", 2.5)), self.preview_reparam_ds_a)

        runner = EngineRunner()
        sim_result = runner.simulate_recipe(recipe, cancel_check=lambda: self._cancel)
        sim_post_points = [(float(x), float(y)) for x, y in sim_result.get("final_profile", [])]
        if len(sim_post_points) < 2:
            raise RuntimeError("Prediction simulation produced no valid final profile.")
        candidate_entries = build_feature_entries(self.pre_points, sim_post_points, self.anchor_spec)
        loss = feature_loss(target_entries, candidate_entries)
        return {
            "loss": float(loss),
            "params": {key: float(value) for key, value in params.items()},
            "switch_state": deep_copy_switch_state(applied_switch_state),
            "sim_post_points": [(float(x), float(y)) for x, y in sim_post_points],
            "feature_count": len(candidate_entries),
            "preview_cycles": int(sim_result.get("cycles", 0)),
            "preview_completed_step": int(sim_result.get("completed_step", 0)),
        }

    @staticmethod
    def _trim_top_candidates(candidates: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
        ordered = sorted(candidates, key=lambda item: float(item["loss"]))
        return ordered[: max(1, int(limit))]

    def _result_payload(
        self,
        *,
        ranked: List[Dict[str, Any]],
        target_feature_count: int,
        evaluated_candidates: int,
        prediction_mode: str,
        fast_diagnostics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not ranked:
            raise RuntimeError("Parameter prediction did not produce any valid candidates.")
        best = ranked[0]
        payload: Dict[str, Any] = {
            "loss": float(best["loss"]),
            "predicted_switch_state": deep_copy_switch_state(best["switch_state"]),
            "best_params": dict(best["params"]),
            "top_candidates": [
                {
                    "loss": float(item["loss"]),
                    "params": dict(item["params"]),
                }
                for item in ranked
            ],
            "target_feature_count": int(target_feature_count),
            "evaluated_candidates": int(evaluated_candidates),
            "sim_post_points": [(float(x), float(y)) for x, y in best.get("sim_post_points", [])],
            "prediction_mode": str(prediction_mode),
        }
        if fast_diagnostics is not None:
            payload["fast_diagnostics"] = dict(fast_diagnostics)
        return payload

    def _fast_prediction_result(
        self,
        *,
        base_params: Dict[str, float],
        target_entries: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        estimate = estimate_fast_prediction_params(
            self.pre_points,
            self.post_points,
            self.anchor_spec,
            base_params,
        )
        if not estimate:
            return None

        params = estimate.get("params")
        if not isinstance(params, dict):
            return None
        fast_params = {key: float(value) for key, value in params.items()}
        self.progress.emit(1, 1)
        self.message.emit("Parameter prediction: fast feature estimate")
        candidate = self._evaluate_candidate(
            target_entries=target_entries,
            params=fast_params,
            candidate_index=1,
        )
        if candidate is None:
            return None
        self.message.emit(
            (
                f"Parameter prediction: fast feature estimate | loss={float(candidate['loss']):.4f} "
                f"| preview {int(candidate.get('preview_completed_step', 0))}/{int(candidate.get('preview_cycles', 0))}"
            )
        )
        return self._result_payload(
            ranked=[candidate],
            target_feature_count=len(target_entries),
            evaluated_candidates=1,
            prediction_mode="fast_feature",
            fast_diagnostics=estimate.get("diagnostics") if isinstance(estimate.get("diagnostics"), dict) else None,
        )

    def _sampling_prediction_result(
        self,
        *,
        base_params: Dict[str, float],
        target_entries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        bounds = self._parameter_bounds(base_params)
        fixed_params = {"base_rate": float(base_params["base_rate"])}

        total = 1 + (self.coarse_count - 1) + (self.local_seed_count * self.local_count_per_seed)
        step = 0
        candidates: List[Dict[str, Any]] = []

        def evaluate(params: Dict[str, float], label: str) -> None:
            nonlocal step, candidates
            self._check_cancel()
            step += 1
            self.progress.emit(step, total)
            self.message.emit(label)
            candidate = self._evaluate_candidate(
                target_entries=target_entries,
                params=params,
                candidate_index=step,
            )
            if candidate is not None:
                candidates.append(candidate)
                best = min(candidates, key=lambda item: float(item["loss"]))
                self.message.emit(
                    (
                        f"{label} | best loss={float(best['loss']):.4f} "
                        f"| preview {int(candidate.get('preview_completed_step', 0))}/{int(candidate.get('preview_cycles', 0))}"
                    )
                )

        evaluate(base_params, "Parameter prediction: baseline candidate")
        for idx in range(self.coarse_count - 1):
            evaluate(
                self._sample_candidate(bounds, fixed_params=fixed_params),
                f"Parameter prediction: coarse search {idx + 1}/{self.coarse_count - 1}",
            )

        top_seeds = self._trim_top_candidates(candidates, limit=self.local_seed_count)
        for seed_idx, seed in enumerate(top_seeds):
            center = seed.get("params") if isinstance(seed.get("params"), dict) else {}
            for local_idx in range(self.local_count_per_seed):
                evaluate(
                    self._sample_candidate(bounds, fixed_params=fixed_params, center=center, shrink=0.2),
                    (
                        "Parameter prediction: local refine "
                        f"{seed_idx + 1}/{len(top_seeds)}-{local_idx + 1}/{self.local_count_per_seed}"
                    ),
                )

        self._check_cancel()
        ranked = self._trim_top_candidates(candidates, limit=3)
        return self._result_payload(
            ranked=ranked,
            target_feature_count=len(target_entries),
            evaluated_candidates=len(candidates),
            prediction_mode="sampling",
        )

    @Slot()
    def run(self) -> None:
        try:
            self._check_cancel()
            base_params = self._base_params()
            target_entries = build_feature_entries(self.pre_points, self.post_points, self.anchor_spec)

            try:
                fast_result = self._fast_prediction_result(base_params=base_params, target_entries=target_entries)
            except PredictionCanceled:
                raise
            except Exception as exc:
                self.message.emit(f"Parameter prediction: fast estimate failed, falling back ({exc})")
                fast_result = None

            if fast_result is not None:
                self.finished.emit(fast_result)
                return

            self.message.emit("Parameter prediction: fast estimate unavailable, falling back to sampling")
            self.finished.emit(self._sampling_prediction_result(base_params=base_params, target_entries=target_entries))
        except PredictionCanceled:
            self.canceled.emit()
        except Exception as exc:
            self.error.emit(f"{exc}\n\n{traceback.format_exc()}")
