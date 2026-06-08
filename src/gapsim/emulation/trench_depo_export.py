from __future__ import annotations

from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Sequence, Tuple

from gapsim.emulation.trench_depo import (
    DEFAULT_TRENCH_POINTS,
    SWEEP_PARAMETER_LABELS,
    TrenchDepoConfig,
    TrenchDepoResult,
    TrenchSweepResult,
)
from gapsim.engine.run_logger import write_json
from gapsim.ui_qt.views.result_vector_view import ResultVectorView

Point = Tuple[float, float]

def _default_runs_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "runs" / "trench_depo_emulation"
    return Path("runs") / "trench_depo_emulation"


def _default_results_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "results" / "trench_depo_emulation"
    return Path("results") / "trench_depo_emulation"


DEFAULT_RUNS_ROOT = _default_runs_root()
DEFAULT_RESULTS_ROOT = _default_results_root()
_DEFAULT_PHYSICAL_MEMO = "라운드 conformal offset 기반 트렌치 증착"
SPLIT_GROUP_MANIFEST_NAME = "스플릿묶음.json"
_SPLIT_NOTE_RE = re.compile(
    r"^(?P<base>.*?) \| Split Test (?P<index>\d+)/(?P<total>\d+) \| (?P<label>[^=]+)=(?P<value>[-+0-9.eE]+)$"
)


def _coerce_note(text: str) -> str:
    note = " ".join(str(text or "").strip().split())
    return note or _DEFAULT_PHYSICAL_MEMO


def _safe_korean_slug(text: str, *, max_len: int = 48) -> str:
    raw = _coerce_note(text)
    cleaned = re.sub(r"[^\w가-힣.-]+", "_", raw, flags=re.UNICODE).strip("._")
    if not cleaned:
        cleaned = "기본런"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("._")
    return cleaned or "기본런"


def create_trench_run_dir(
    runs_root: Path | str,
    *,
    cycles: int,
    angstrom_per_cycle: float,
    request_note: str,
) -> Path:
    root = Path(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    note_slug = _safe_korean_slug(request_note)
    acyc = f"{float(angstrom_per_cycle):.3f}".rstrip("0").rstrip(".")
    base_name = f"{ts}_트렌치증착_{int(cycles)}사이클_{acyc}A_{note_slug}"
    for idx in range(1000):
        suffix = "" if idx == 0 else f"_{idx:03d}"
        run_dir = root / f"{base_name}{suffix}"
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_dir
        except FileExistsError:
            continue
    raise RuntimeError("고유한 트렌치 run 디렉터리를 만들지 못했습니다.")


def create_result_json_path(results_root: Path | str) -> Path:
    root = Path(results_root)
    now = datetime.now()
    result_dir = root / now.strftime("%Y%m%d")
    result_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"트렌치결과_{now.strftime('%Y%m%d_%H%M%S')}"
    for idx in range(1000):
        suffix = "" if idx == 0 else f"_{idx:03d}"
        path = result_dir / f"{base_name}{suffix}.json"
        if not path.exists():
            return path
    raise RuntimeError("고유한 결과 JSON 파일명을 만들지 못했습니다.")


def result_to_payload(
    config: TrenchDepoConfig,
    result: TrenchDepoResult,
    *,
    request_note: str,
) -> Dict[str, Any]:
    return {
        "version": 1,
        "created_at_local": datetime.now().isoformat(timespec="seconds"),
        "kind": "trench_depo_emulation",
        "request_note_ko": _coerce_note(request_note),
        "config": {
            "points": [[float(x), float(y)] for x, y in config.points],
            "cycles": int(config.cycles),
            "emulator_number": int(getattr(config, "emulator_number", 0) or 0),
            "angstrom_per_cycle": float(config.angstrom_per_cycle),
            "reparam_ds_a": float(config.reparam_ds_a),
            "sputter_enabled": bool(config.sputter_enabled),
            "sputter_strength_a_per_cycle": float(config.sputter_strength_a_per_cycle),
            "sputter_peak_pct": float(config.sputter_peak_pct),
            "sputter_peak_angle_deg": float(config.sputter_peak_angle_deg),
            "sputter_width_deg": float(config.sputter_width_deg),
            "sputter_smoothing_a": float(config.sputter_smoothing_a),
            "ion_transmission_enabled": bool(config.ion_transmission_enabled),
            "ion_transmission_override": (
                None
                if config.ion_transmission_override is None
                else float(config.ion_transmission_override)
            ),
            "ion_transmission_start_depth_pct": float(config.ion_transmission_start_depth_pct),
            "ion_transmission_end_depth_pct": float(config.ion_transmission_end_depth_pct),
            "ion_transmission_decay_strength_pct": float(config.ion_transmission_decay_strength_pct),
            "ion_transmission_floor_pct": float(config.ion_transmission_floor_pct),
            "ion_transmission_curve_power": float(config.ion_transmission_curve_power),
            "ion_transmission_aperture_shadow_pct": float(config.ion_transmission_aperture_shadow_pct),
            "ion_transmission_lateral_shadow_pct": float(config.ion_transmission_lateral_shadow_pct),
            "ion_transmission_edge_shadow_pct": float(config.ion_transmission_edge_shadow_pct),
            "reflected_ion_enabled": bool(config.reflected_ion_enabled),
            "reflected_ion_strength_pct": float(config.reflected_ion_strength_pct),
            "reflected_ion_bowing_weight": float(config.reflected_ion_bowing_weight),
            "reflected_ion_microtrench_weight": float(config.reflected_ion_microtrench_weight),
            "reflected_ion_range_a": float(config.reflected_ion_range_a),
            "redepo_enabled": bool(config.redepo_enabled),
            "redepo_source_model": str(config.redepo_source_model),
            "redepo_efficiency_pct": float(config.redepo_efficiency_pct),
            "redepo_emit_power": float(config.redepo_emit_power),
            "redepo_distance_power": float(config.redepo_distance_power),
            "redepo_neighbor_exclusion": int(config.redepo_neighbor_exclusion),
            "redepo_max_distance_a": float(config.redepo_max_distance_a),
            "redepo_soft_los_radius_points": int(config.redepo_soft_los_radius_points),
            "redepo_transport_model": str(config.redepo_transport_model),
            "redepo_ray_count": int(config.redepo_ray_count),
            "redepo_footprint_sigma_a": float(config.redepo_footprint_sigma_a),
            "redepo_footprint_radius_sigma": float(config.redepo_footprint_radius_sigma),
            "lf_overhang_enabled": bool(config.lf_overhang_enabled),
            "lf_overhang_dose": float(config.lf_overhang_dose),
            "lf_overhang_sputter_gain": float(config.lf_overhang_sputter_gain),
            "lf_overhang_redepo_fraction_pct": float(config.lf_overhang_redepo_fraction_pct),
            "lf_overhang_survival_penalty": float(config.lf_overhang_survival_penalty),
            "lf_overhang_width_a": float(config.lf_overhang_width_a),
            "deposition_depth_enabled": bool(config.deposition_depth_enabled),
            "deposition_feature_type": str(config.deposition_feature_type),
            "deposition_feature_width_a": float(config.deposition_feature_width_a),
            "deposition_feature_depth_a": float(config.deposition_feature_depth_a),
            "deposition_feature_length_a": (
                None
                if config.deposition_feature_length_a is None
                else float(config.deposition_feature_length_a)
            ),
            "deposition_attenuation_model": str(config.deposition_attenuation_model),
            "deposition_depth_decay_k": float(config.deposition_depth_decay_k),
            "deposition_depth_decay_power": float(config.deposition_depth_decay_power),
            "deposition_min_ratio": float(config.deposition_min_ratio),
            "deposition_use_equivalent_ar": bool(config.deposition_use_equivalent_ar),
            "deposition_closure_threshold_a": float(config.deposition_closure_threshold_a),
            "deposition_post_closure_fill_pct_hole": float(config.deposition_post_closure_fill_pct_hole),
            "deposition_post_closure_fill_pct_line": float(config.deposition_post_closure_fill_pct_line),
            "deposition_line_open_path_factor": float(config.deposition_line_open_path_factor),
            "deposition_residual_fill_decay_length_a": float(config.deposition_residual_fill_decay_length_a),
            "deposition_residual_fill_distribution": str(config.deposition_residual_fill_distribution),
            "deposition_max_depo_per_cell_a": (
                None
                if config.deposition_max_depo_per_cell_a is None
                else float(config.deposition_max_depo_per_cell_a)
            ),
            "deposition_conserve_volume": bool(config.deposition_conserve_volume),
            "inhibition_enabled": bool(config.inhibition_enabled),
            "inhibition_process_model": str(config.inhibition_process_model),
            "inhibition_strength_pct": float(config.inhibition_strength_pct),
            "inhibition_penetration_depth_a": float(config.inhibition_penetration_depth_a),
            "inhibition_decay_power": float(config.inhibition_decay_power),
            "inhibition_min_growth_ratio": float(config.inhibition_min_growth_ratio),
            "inhibition_bottom_boost_pct": float(config.inhibition_bottom_boost_pct),
            "inhibition_peald_recombination_pct": float(config.inhibition_peald_recombination_pct),
            "inhibition_smoothing_a": float(config.inhibition_smoothing_a),
        },
        "result": {
            "frame_steps": [int(v) for v in result.frame_steps],
            "frame_profiles": [
                [[float(x), float(y)] for x, y in frame]
                for frame in result.frame_profiles
            ],
            "frame_voids": [
                [
                    [[float(x), float(y)] for x, y in poly]
                    for poly in frame_voids
                ]
                for frame_voids in result.frame_voids
            ],
            "final_profile": [[float(x), float(y)] for x, y in result.final_profile],
            "meta": dict(result.meta),
        },
    }


def payload_to_trench_run(payload: Dict[str, Any]) -> Tuple[TrenchDepoConfig, TrenchDepoResult, str]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid replay payload: root must be an object.")
    if str(payload.get("kind", "")) != "trench_depo_emulation":
        raise ValueError("Invalid replay payload: unsupported kind.")

    config_raw = payload.get("config")
    result_raw = payload.get("result")
    if not isinstance(config_raw, dict) or not isinstance(result_raw, dict):
        raise ValueError("Invalid replay payload: missing config/result.")

    points_raw = config_raw.get("points", DEFAULT_TRENCH_POINTS)
    frame_profiles_raw = result_raw.get("frame_profiles", [])
    frame_voids_raw = result_raw.get("frame_voids", [])
    frame_steps_raw = result_raw.get("frame_steps", [])
    final_profile_raw = result_raw.get("final_profile", [])
    meta_raw = result_raw.get("meta", {})

    def _load_points(raw_points: Any, *, min_count: int) -> List[Point]:
        if not isinstance(raw_points, list):
            raise ValueError("Invalid replay payload: points must be a list.")
        pts: List[Point] = []
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("Invalid replay payload: point must be [x, y].")
            pts.append((float(point[0]), float(point[1])))
        if len(pts) < min_count:
            raise ValueError("Invalid replay payload: not enough points.")
        return pts

    points = _load_points(points_raw, min_count=2)
    frame_profiles = [_load_points(frame, min_count=2) for frame in frame_profiles_raw]
    frame_voids: List[List[List[Point]]] = []
    if not isinstance(frame_voids_raw, list):
        raise ValueError("Invalid replay payload: frame_voids must be a list.")
    for frame_void in frame_voids_raw:
        if not isinstance(frame_void, list):
            raise ValueError("Invalid replay payload: frame void entry must be a list.")
        polys: List[List[Point]] = []
        for poly in frame_void:
            polys.append(_load_points(poly, min_count=3))
        frame_voids.append(polys)

    if len(frame_voids) != len(frame_profiles):
        frame_voids = [[] for _ in frame_profiles]
    if not isinstance(frame_steps_raw, list):
        raise ValueError("Invalid replay payload: frame_steps must be a list.")
    frame_steps = [int(v) for v in frame_steps_raw]
    if len(frame_steps) != len(frame_profiles):
        frame_steps = list(range(len(frame_profiles)))

    final_profile = _load_points(final_profile_raw, min_count=2) if final_profile_raw else list(frame_profiles[-1])
    meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
    note = _coerce_note(str(payload.get("request_note_ko", "")))

    config = TrenchDepoConfig(
        points=points,
        cycles=int(config_raw.get("cycles", max(0, len(frame_profiles) - 1))),
        emulator_number=int(config_raw.get("emulator_number") or meta.get("emulator_number") or 0),
        angstrom_per_cycle=float(config_raw.get("angstrom_per_cycle", 10.0)),
        reparam_ds_a=float(config_raw.get("reparam_ds_a", 2.5)),
        sputter_enabled=bool(config_raw.get("sputter_enabled", False)),
        sputter_strength_a_per_cycle=float(config_raw.get("sputter_strength_a_per_cycle", 4.0)),
        sputter_peak_pct=float(config_raw.get("sputter_peak_pct", 100.0)),
        sputter_peak_angle_deg=float(config_raw.get("sputter_peak_angle_deg", 55.0)),
        sputter_width_deg=float(config_raw.get("sputter_width_deg", 14.0)),
        sputter_smoothing_a=float(config_raw.get("sputter_smoothing_a", 40.0)),
        ion_transmission_enabled=bool(config_raw.get("ion_transmission_enabled", False)),
        ion_transmission_override=(
            None
            if config_raw.get("ion_transmission_override", None) is None
            else float(config_raw.get("ion_transmission_override"))
        ),
        ion_transmission_start_depth_pct=float(
            config_raw.get("ion_transmission_start_depth_pct", 0.0)
        ),
        ion_transmission_end_depth_pct=float(
            config_raw.get("ion_transmission_end_depth_pct", 100.0)
        ),
        ion_transmission_decay_strength_pct=float(
            config_raw.get("ion_transmission_decay_strength_pct", 100.0)
        ),
        ion_transmission_floor_pct=float(config_raw.get("ion_transmission_floor_pct", 0.0)),
        ion_transmission_curve_power=float(config_raw.get("ion_transmission_curve_power", 1.0)),
        ion_transmission_aperture_shadow_pct=float(
            config_raw.get("ion_transmission_aperture_shadow_pct", 100.0)
        ),
        ion_transmission_lateral_shadow_pct=float(
            config_raw.get("ion_transmission_lateral_shadow_pct", 100.0)
        ),
        ion_transmission_edge_shadow_pct=float(
            config_raw.get("ion_transmission_edge_shadow_pct", 100.0)
        ),
        reflected_ion_enabled=bool(config_raw.get("reflected_ion_enabled", False)),
        reflected_ion_strength_pct=float(config_raw.get("reflected_ion_strength_pct", 0.0)),
        reflected_ion_bowing_weight=float(config_raw.get("reflected_ion_bowing_weight", 0.75)),
        reflected_ion_microtrench_weight=float(config_raw.get("reflected_ion_microtrench_weight", 1.0)),
        reflected_ion_range_a=float(config_raw.get("reflected_ion_range_a", 1600.0)),
        redepo_enabled=bool(config_raw.get("redepo_enabled", False)),
        redepo_source_model=str(config_raw.get("redepo_source_model", "model2")),
        redepo_efficiency_pct=float(config_raw.get("redepo_efficiency_pct", 25.0)),
        redepo_emit_power=float(config_raw.get("redepo_emit_power", 1.0)),
        redepo_distance_power=float(config_raw.get("redepo_distance_power", 1.0)),
        redepo_neighbor_exclusion=int(config_raw.get("redepo_neighbor_exclusion", 2)),
        redepo_max_distance_a=float(config_raw.get("redepo_max_distance_a", 1800.0)),
        redepo_soft_los_radius_points=int(config_raw.get("redepo_soft_los_radius_points", 0)),
        redepo_transport_model=str(config_raw.get("redepo_transport_model", "gapsim_binned_lobe_los")),
        redepo_ray_count=int(config_raw.get("redepo_ray_count", 7)),
        redepo_footprint_sigma_a=float(config_raw.get("redepo_footprint_sigma_a", 55.0)),
        redepo_footprint_radius_sigma=float(config_raw.get("redepo_footprint_radius_sigma", 3.0)),
        lf_overhang_enabled=bool(config_raw.get("lf_overhang_enabled", False)),
        lf_overhang_dose=float(config_raw.get("lf_overhang_dose", 1.0)),
        lf_overhang_sputter_gain=float(config_raw.get("lf_overhang_sputter_gain", 1.0)),
        lf_overhang_redepo_fraction_pct=float(config_raw.get("lf_overhang_redepo_fraction_pct", 30.0)),
        lf_overhang_survival_penalty=float(config_raw.get("lf_overhang_survival_penalty", 0.75)),
        lf_overhang_width_a=float(config_raw.get("lf_overhang_width_a", 180.0)),
        deposition_depth_enabled=bool(config_raw.get("deposition_depth_enabled", False)),
        deposition_feature_type=str(config_raw.get("deposition_feature_type", "hole")),
        deposition_feature_width_a=float(config_raw.get("deposition_feature_width_a", 240.0)),
        deposition_feature_depth_a=float(config_raw.get("deposition_feature_depth_a", 4700.0)),
        deposition_feature_length_a=(
            None
            if config_raw.get("deposition_feature_length_a", None) is None
            else float(config_raw.get("deposition_feature_length_a"))
        ),
        deposition_attenuation_model=str(config_raw.get("deposition_attenuation_model", "exponential")),
        deposition_depth_decay_k=float(config_raw.get("deposition_depth_decay_k", 0.8)),
        deposition_depth_decay_power=float(config_raw.get("deposition_depth_decay_power", 1.2)),
        deposition_min_ratio=float(config_raw.get("deposition_min_ratio", 0.03)),
        deposition_use_equivalent_ar=bool(config_raw.get("deposition_use_equivalent_ar", True)),
        deposition_closure_threshold_a=float(config_raw.get("deposition_closure_threshold_a", 8.0)),
        deposition_post_closure_fill_pct_hole=float(
            config_raw.get("deposition_post_closure_fill_pct_hole", 0.03)
        ),
        deposition_post_closure_fill_pct_line=float(
            config_raw.get("deposition_post_closure_fill_pct_line", 0.20)
        ),
        deposition_line_open_path_factor=float(config_raw.get("deposition_line_open_path_factor", 1.0)),
        deposition_residual_fill_decay_length_a=float(
            config_raw.get("deposition_residual_fill_decay_length_a", 1175.0)
        ),
        deposition_residual_fill_distribution=str(
            config_raw.get("deposition_residual_fill_distribution", "exponential_from_closure")
        ),
        deposition_max_depo_per_cell_a=(
            None
            if config_raw.get("deposition_max_depo_per_cell_a", None) is None
            else float(config_raw.get("deposition_max_depo_per_cell_a"))
        ),
        deposition_conserve_volume=bool(config_raw.get("deposition_conserve_volume", True)),
        inhibition_enabled=bool(config_raw.get("inhibition_enabled", False)),
        inhibition_process_model=str(config_raw.get("inhibition_process_model", "hybrid")),
        inhibition_strength_pct=float(config_raw.get("inhibition_strength_pct", 85.0)),
        inhibition_penetration_depth_a=float(config_raw.get("inhibition_penetration_depth_a", 1100.0)),
        inhibition_decay_power=float(config_raw.get("inhibition_decay_power", 1.2)),
        inhibition_min_growth_ratio=float(config_raw.get("inhibition_min_growth_ratio", 0.08)),
        inhibition_bottom_boost_pct=float(config_raw.get("inhibition_bottom_boost_pct", 20.0)),
        inhibition_peald_recombination_pct=float(config_raw.get("inhibition_peald_recombination_pct", 35.0)),
        inhibition_smoothing_a=float(config_raw.get("inhibition_smoothing_a", 45.0)),
    )
    result = TrenchDepoResult(
        frame_steps=frame_steps,
        frame_profiles=frame_profiles,
        frame_voids=frame_voids,
        final_profile=final_profile,
        meta=meta,
    )
    return config, result, note


def load_trench_depo_run(path: Path | str) -> Tuple[TrenchDepoConfig, TrenchDepoResult, str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload_to_trench_run(payload)


def save_trench_depo_result_json(
    config: TrenchDepoConfig,
    result: TrenchDepoResult,
    *,
    request_note: str = "",
    results_root: Path | str = DEFAULT_RESULTS_ROOT,
) -> Path:
    payload = result_to_payload(config, result, request_note=_coerce_note(request_note))
    payload["save_type"] = "result_panel_json"
    path = create_result_json_path(results_root)
    payload["result_json_path"] = str(path)
    write_json(path, payload)
    return path


def _gif_panel_lines(
    result: TrenchDepoResult,
    config: TrenchDepoConfig,
    *,
    request_note: str,
    frame_index: int,
) -> List[str]:
    total_cycles = int(result.meta.get("cycles", max(0, len(result.frame_profiles) - 1)))
    cycle = int(result.frame_steps[frame_index]) if frame_index < len(result.frame_steps) else frame_index
    point_count = len(result.frame_profiles[frame_index]) if frame_index < len(result.frame_profiles) else 0
    note = _coerce_note(request_note)
    return [
        "트렌치 증착 런 정보",
        "",
        f"현재 cycle: {cycle} / {total_cycles}",
        f"현재 점 수: {point_count}",
        "",
        "[진행 파라미터]",
        f"증착 모델: {result.meta.get('growth_model', 'unknown')}",
        f"전파 방식: {result.meta.get('propagation', 'unknown')}",
        f"사이클 수: {int(config.cycles)}",
        f"사이클당 증착량: {float(config.angstrom_per_cycle):g} A",
        f"재샘플 간격: {float(config.reparam_ds_a):g} A",
        f"스퍼터: {'ON' if config.sputter_enabled else 'OFF'}",
        f"스퍼터 세기: {float(config.sputter_strength_a_per_cycle):g} A/CYC",
        f"스퍼터 peak 비율: {float(config.sputter_peak_pct):g} %",
        f"스퍼터 peak angle: {float(config.sputter_peak_angle_deg):g} deg",
        f"스퍼터 width: {float(config.sputter_width_deg):g} deg",
        f"스퍼터 smoothing: {float(config.sputter_smoothing_a):g} A",
        f"ion transmission: {'ON' if config.ion_transmission_enabled else 'OFF'}",
        f"ion start depth: {float(config.ion_transmission_start_depth_pct):g} %",
        f"ion end depth: {float(config.ion_transmission_end_depth_pct):g} %",
        f"ion drop strength: {float(config.ion_transmission_decay_strength_pct):g} %",
        f"ion floor: {float(config.ion_transmission_floor_pct):g} %",
        f"ion curve: {float(config.ion_transmission_curve_power):g}",
        f"ion aperture: {float(config.ion_transmission_aperture_shadow_pct):g} %",
        f"ion hidden: {float(config.ion_transmission_lateral_shadow_pct):g} %",
        f"ion edge: {float(config.ion_transmission_edge_shadow_pct):g} %",
        f"reflected ion: {'ON' if config.reflected_ion_enabled else 'OFF'}",
        f"reflected strength: {float(config.reflected_ion_strength_pct):g} %",
        f"bowing weight: {float(config.reflected_ion_bowing_weight):g}",
        f"microtrench weight: {float(config.reflected_ion_microtrench_weight):g}",
        f"reflection range: {float(config.reflected_ion_range_a):g} A",
        f"redeposition: {'ON' if config.redepo_enabled else 'OFF'}",
        f"redepo source: {config.redepo_source_model}",
        f"redepo efficiency: {float(config.redepo_efficiency_pct):g} %",
        f"redepo emit power: {float(config.redepo_emit_power):g}",
        f"redepo distance power: {float(config.redepo_distance_power):g}",
        f"redepo soft LOS: {int(config.redepo_soft_los_radius_points)} pt",
        f"redepo transport: {config.redepo_transport_model}",
        f"redepo rays: {int(config.redepo_ray_count)}",
        f"redepo footprint sigma: {float(config.redepo_footprint_sigma_a):g} A",
        f"LF overhang proxy: {'ON' if config.lf_overhang_enabled else 'OFF'}",
        f"LF dose/gain: {float(config.lf_overhang_dose):g} / {float(config.lf_overhang_sputter_gain):g}",
        f"LF redepo/survival/width: {float(config.lf_overhang_redepo_fraction_pct):g} % / {float(config.lf_overhang_survival_penalty):g} / {float(config.lf_overhang_width_a):g} A",
        f"depth depo: {'ON' if config.deposition_depth_enabled else 'OFF'}",
        f"feature type: {config.deposition_feature_type}",
        f"depth decay K: {float(config.deposition_depth_decay_k):g}",
        f"min depo ratio: {float(config.deposition_min_ratio) * 100.0:g} %",
        f"hole post-fill: {float(config.deposition_post_closure_fill_pct_hole) * 100.0:g} %",
        f"line post-fill: {float(config.deposition_post_closure_fill_pct_line) * 100.0:g} %",
        f"inhibition: {'ON' if config.inhibition_enabled else 'OFF'}",
        f"inhibit model: {config.inhibition_process_model}",
        f"inhibit strength/depth: {float(config.inhibition_strength_pct):g} % / {float(config.inhibition_penetration_depth_a):g} A",
        f"inhibit floor/boost: {float(config.inhibition_min_growth_ratio) * 100.0:g} % / {float(config.inhibition_bottom_boost_pct):g} %",
        "",
        "[요청사항]",
        note,
    ]


def _render_gif_frames(
    result: TrenchDepoResult,
    config: TrenchDepoConfig,
    *,
    request_note: str,
) -> List[Any]:
    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Pillow가 없어 GIF를 만들 수 없습니다.") from exc

    try:
        from PySide6.QtCore import QBuffer, QByteArray, QPoint, Qt
        from PySide6.QtGui import QFont, QImage, QPainter
        from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("PySide6가 없어 GIF를 만들 수 없습니다.") from exc

    frames = result.frame_profiles
    if not frames:
        raise RuntimeError("GIF로 저장할 frame이 없습니다.")

    app = QApplication.instance()
    temp_app = None
    if app is None:
        temp_app = QApplication([])
        app = temp_app

    def _pick_font_family() -> str:
        for candidate in (
            "Apple SD Gothic Neo",
            "Noto Sans CJK KR",
            "Noto Sans KR",
            "Malgun Gothic",
            "Arial Unicode MS",
            "Helvetica",
        ):
            if candidate:
                return candidate
        return app.font().family()

    font_family = _pick_font_family()
    width = 1820
    height = 1040
    panel_width = 420
    rendered: List[Any] = []
    container = QWidget()
    container.resize(width, height)
    root = QVBoxLayout(container)
    root.setContentsMargins(18, 18, 18, 18)
    root.setSpacing(10)

    title = QLabel("트렌치 증착 미니 에뮬레이터")
    title_font = QFont(font_family, 16)
    title_font.setBold(True)
    title.setFont(title_font)
    title.setStyleSheet("color: #1f2937;")
    root.addWidget(title, 0)

    subtitle = QLabel("")
    subtitle.setFont(QFont(font_family, 11))
    subtitle.setStyleSheet("color: #4b5563; padding-bottom: 8px;")
    root.addWidget(subtitle, 0)

    host = QWidget()
    host_layout = QVBoxLayout(host)
    host_layout.setContentsMargins(0, 0, 0, 0)
    host_layout.setSpacing(0)
    view = ResultVectorView()
    view.resize(width - panel_width - 54, height - 36)
    view.set_frames(
        result.frame_profiles,
        voids=result.frame_voids,
        redepo_overlays=result.meta.get("frame_redepo_overlays"),
        etch_overlays=result.meta.get("frame_etch_overlays"),
        void_mode="current",
        dynamic_substrate_fill=bool(result.meta.get("sputter_active")),
        history_mode="mixed_etch" if bool(result.meta.get("sputter_active")) else "film",
    )
    view.setFont(QFont(font_family, 13))
    host_layout.addWidget(view, 1)

    panel = QFrame()
    panel.setFixedWidth(panel_width)
    panel.setStyleSheet(
        "QFrame { background: #f7fafc; border: 1px solid #d8e3ee; border-radius: 10px; }"
        "QLabel { color: #1f2937; }"
    )
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(18, 18, 18, 18)
    panel_layout.setSpacing(8)

    panel_title = QLabel("진행 파라미터")
    panel_title_font = QFont(font_family, 14)
    panel_title_font.setBold(True)
    panel_title.setFont(panel_title_font)
    panel_layout.addWidget(panel_title)

    panel_text = QLabel("")
    panel_text.setWordWrap(True)
    panel_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    panel_text.setFont(QFont(font_family, 11))
    panel_text.setStyleSheet("line-height: 1.35;")
    panel_layout.addWidget(panel_text, 1)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(14)
    row.addWidget(host, 1)
    row.addWidget(panel, 0)
    root.addLayout(row, 1)

    container.setFont(QFont(font_family, 11))
    container.setStyleSheet("background: white;")
    container.show()
    view.fit_content()
    app.processEvents()

    try:
        for idx in range(len(frames)):
            view.show_frame(idx, fit=False)
            current_cycle = int(result.frame_steps[idx]) if idx < len(result.frame_steps) else idx
            total_cycles = int(result.meta.get("cycles", len(frames) - 1))
            subtitle.setText(
                f"Cycle {current_cycle}/{total_cycles}  |  {float(config.angstrom_per_cycle):g} A/CYC"
            )
            panel_text.setText("\n".join(_gif_panel_lines(result, config, request_note=request_note, frame_index=idx)))
            app.processEvents()

            qimage = QImage(width, height, QImage.Format.Format_ARGB32)
            qimage.fill(Qt.GlobalColor.white)
            painter = QPainter(qimage)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            try:
                container.render(painter, QPoint(0, 0))
            finally:
                painter.end()

            png_bytes = QByteArray()
            buffer = QBuffer(png_bytes)
            if not buffer.open(QBuffer.OpenModeFlag.WriteOnly):
                raise RuntimeError("GIF export용 메모리 버퍼를 열지 못했습니다.")
            try:
                ok = qimage.save(buffer, "PNG")
            finally:
                buffer.close()
            if not ok:
                raise RuntimeError("GIF export frame을 렌더하지 못했습니다.")

            frame = Image.open(BytesIO(bytes(png_bytes)))
            frame.load()
            rendered.append(frame.convert("RGB"))
            frame.close()
    finally:
        container.close()
        container.deleteLater()
        view.close()
        view.deleteLater()
        if temp_app is not None:
            temp_app.quit()
    return rendered


def export_trench_depo_run(
    config: TrenchDepoConfig,
    result: TrenchDepoResult,
    *,
    request_note: str = "",
    runs_root: Path | str = DEFAULT_RUNS_ROOT,
) -> Path:
    note = _coerce_note(request_note)
    run_dir = create_trench_run_dir(
        runs_root,
        cycles=int(config.cycles),
        angstrom_per_cycle=float(config.angstrom_per_cycle),
        request_note=note,
    )
    base_name = run_dir.name
    payload = result_to_payload(config, result, request_note=note)

    replay_path = run_dir / f"에뮬레이터재생_{base_name}.json"
    meta_path = run_dir / f"런정보_{base_name}.json"
    summary_path = run_dir / f"요청사항요약_{base_name}.txt"
    gif_path = run_dir / f"트렌치증착_{base_name}.gif"

    write_json(replay_path, payload)
    write_json(
        meta_path,
        {
            "version": 1,
            "created_at_local": payload["created_at_local"],
            "request_note_ko": note,
            "run_dir": str(run_dir),
            "config": payload["config"],
            "result_meta": payload["result"]["meta"],
        },
    )

    summary_lines = [
        "트렌치 증착 미니 에뮬레이터 런 요약",
        "",
        f"생성 시각: {payload['created_at_local']}",
        f"런 폴더: {run_dir}",
        "",
        "[런 정보]",
        f"사이클 수: {int(config.cycles)}",
        f"사이클당 증착량: {float(config.angstrom_per_cycle):g} A",
        f"재샘플 간격: {float(config.reparam_ds_a):g} A",
        f"스퍼터: {'ON' if config.sputter_enabled else 'OFF'}",
        f"스퍼터 세기: {float(config.sputter_strength_a_per_cycle):g} A/CYC",
        f"스퍼터 peak 비율: {float(config.sputter_peak_pct):g} %",
        f"스퍼터 peak angle: {float(config.sputter_peak_angle_deg):g} deg",
        f"스퍼터 width: {float(config.sputter_width_deg):g} deg",
        f"스퍼터 smoothing: {float(config.sputter_smoothing_a):g} A",
        f"ion transmission: {'ON' if config.ion_transmission_enabled else 'OFF'}",
        f"ion start depth: {float(config.ion_transmission_start_depth_pct):g} %",
        f"ion end depth: {float(config.ion_transmission_end_depth_pct):g} %",
        f"ion drop strength: {float(config.ion_transmission_decay_strength_pct):g} %",
        f"ion floor: {float(config.ion_transmission_floor_pct):g} %",
        f"ion curve: {float(config.ion_transmission_curve_power):g}",
        f"ion aperture: {float(config.ion_transmission_aperture_shadow_pct):g} %",
        f"ion hidden: {float(config.ion_transmission_lateral_shadow_pct):g} %",
        f"ion edge: {float(config.ion_transmission_edge_shadow_pct):g} %",
        f"reflected ion: {'ON' if config.reflected_ion_enabled else 'OFF'}",
        f"reflected strength: {float(config.reflected_ion_strength_pct):g} %",
        f"bowing weight: {float(config.reflected_ion_bowing_weight):g}",
        f"microtrench weight: {float(config.reflected_ion_microtrench_weight):g}",
        f"reflection range: {float(config.reflected_ion_range_a):g} A",
        f"depth depo: {'ON' if config.deposition_depth_enabled else 'OFF'}",
        f"feature type: {config.deposition_feature_type}",
        f"feature width/depth: {float(config.deposition_feature_width_a):g} / {float(config.deposition_feature_depth_a):g} A",
        f"depth decay K/power: {float(config.deposition_depth_decay_k):g} / {float(config.deposition_depth_decay_power):g}",
        f"min depo ratio: {float(config.deposition_min_ratio) * 100.0:g} %",
        f"closure threshold: {float(config.deposition_closure_threshold_a):g} A",
        f"hole/line post-fill: {float(config.deposition_post_closure_fill_pct_hole) * 100.0:g} / {float(config.deposition_post_closure_fill_pct_line) * 100.0:g} %",
        f"line open path: {float(config.deposition_line_open_path_factor):g}",
        f"inhibition: {'ON' if config.inhibition_enabled else 'OFF'}",
        f"inhibit model: {config.inhibition_process_model}",
        f"inhibit strength/depth: {float(config.inhibition_strength_pct):g} % / {float(config.inhibition_penetration_depth_a):g} A",
        f"inhibit floor/boost/recomb: {float(config.inhibition_min_growth_ratio) * 100.0:g} % / {float(config.inhibition_bottom_boost_pct):g} % / {float(config.inhibition_peald_recombination_pct):g} %",
        f"inhibit smoothing: {float(config.inhibition_smoothing_a):g} A",
        f"초기 점 수: {int(result.meta.get('initial_points', 0))}",
        f"최종 점 수: {int(result.meta.get('final_points', 0))}",
        "",
        "[에뮬레이션 내용]",
        f"growth_model: {result.meta.get('growth_model', 'unknown')}",
        f"propagation: {result.meta.get('propagation', 'unknown')}",
        f"sputter_model: {result.meta.get('sputter_model', 'unknown')}",
        f"frame 수: {len(result.frame_profiles)}",
        "",
        "[이번 버전 제외 항목]",
        ", ".join(str(v) for v in result.meta.get("sputter_excluded_effects", [])),
        "",
        "[요청사항 / 물리 메모]",
        note,
        "",
        "[생성 파일]",
        replay_path.name,
        meta_path.name,
        summary_path.name,
        gif_path.name,
    ]
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    images = _render_gif_frames(result, config, request_note=note)
    try:
        images[0].save(
            str(gif_path),
            save_all=True,
            append_images=images[1:],
            duration=180,
            loop=0,
            optimize=False,
            disposal=2,
        )
    finally:
        for image in images:
            image.close()

    return run_dir


def split_case_request_note(
    base_note: str,
    case: TrenchSweepResult,
    *,
    index: int,
    total: int,
) -> str:
    note = _coerce_note(base_note)
    value = f"{float(case.value):g}"
    return f"{note} | Split Test {int(index)}/{int(total)} | {case.label}={value}"


def _first_replay_json(run_dir: Path) -> Path | None:
    files = sorted(Path(run_dir).glob("에뮬레이터재생_*.json"))
    return files[0] if files else None


def _write_split_group_manifests(
    cases: Sequence[TrenchSweepResult],
    saved_dirs: Sequence[Path],
    *,
    request_note: str,
) -> None:
    if not cases or len(cases) != len(saved_dirs):
        return

    entries: List[Dict[str, Any]] = []
    for idx, (case, run_dir_raw) in enumerate(zip(cases, saved_dirs), start=1):
        run_dir = Path(run_dir_raw)
        replay = _first_replay_json(run_dir)
        if replay is None:
            return
        entries.append(
            {
                "index": int(idx),
                "parameter": str(case.parameter),
                "label": str(case.label),
                "value": float(case.value),
                "run_dir": run_dir.name,
                "replay_json": replay.name,
            }
        )

    manifest = {
        "version": 1,
        "kind": "trench_depo_split_group",
        "request_note_ko": _coerce_note(request_note),
        "parameter": str(cases[0].parameter),
        "label": str(cases[0].label),
        "total": int(len(entries)),
        "cases": entries,
    }
    for run_dir_raw in saved_dirs:
        run_dir = Path(run_dir_raw)
        if run_dir.exists():
            write_json(run_dir / SPLIT_GROUP_MANIFEST_NAME, manifest)


def _parameter_from_label(label: str) -> str:
    label_s = str(label)
    for parameter, known_label in SWEEP_PARAMETER_LABELS.items():
        if known_label == label_s:
            return parameter
    return "loaded_split"


def _case_from_replay(
    replay_path: Path,
    *,
    parameter: str,
    label: str,
    value: float,
) -> TrenchSweepResult:
    config, result, _note = load_trench_depo_run(replay_path)
    return TrenchSweepResult(
        parameter=str(parameter),
        label=str(label),
        value=float(value),
        config=config,
        result=result,
    )


def _load_split_group_from_manifest(replay_path: Path) -> List[TrenchSweepResult]:
    manifest_path = replay_path.parent / SPLIT_GROUP_MANIFEST_NAME
    if not manifest_path.exists():
        return []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or str(payload.get("kind", "")) != "trench_depo_split_group":
        return []
    entries = payload.get("cases")
    if not isinstance(entries, list):
        return []

    root = replay_path.parent.parent
    cases: List[Tuple[int, TrenchSweepResult]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index", len(cases) + 1))
            label = str(entry.get("label", payload.get("label", "Split")))
            parameter = str(entry.get("parameter", payload.get("parameter", _parameter_from_label(label))))
            value = float(entry.get("value", 0.0))
            replay_name = str(entry.get("replay_json", ""))
            run_dir_name = str(entry.get("run_dir", ""))
        except (TypeError, ValueError):
            continue
        if not replay_name or not run_dir_name:
            continue
        case_replay = root / run_dir_name / replay_name
        if case_replay.exists():
            cases.append((index, _case_from_replay(case_replay, parameter=parameter, label=label, value=value)))

    cases.sort(key=lambda item: item[0])
    return [case for _idx, case in cases]


def _split_note_parts(note: str) -> Tuple[str, int, int, str, float] | None:
    m = _SPLIT_NOTE_RE.match(str(note))
    if not m:
        return None
    try:
        return (
            str(m.group("base")),
            int(m.group("index")),
            int(m.group("total")),
            str(m.group("label")),
            float(m.group("value")),
        )
    except (TypeError, ValueError):
        return None


def _load_split_group_from_notes(replay_path: Path) -> List[TrenchSweepResult]:
    selected_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    selected_note = str(selected_payload.get("request_note_ko", ""))
    selected_parts = _split_note_parts(selected_note)
    if selected_parts is None:
        return []
    base_note, _selected_index, total, label, _value = selected_parts
    parameter = _parameter_from_label(label)
    root = replay_path.parent.parent

    grouped: List[Tuple[int, TrenchSweepResult]] = []
    for candidate in sorted(root.glob("*/에뮬레이터재생_*.json")):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        parts = _split_note_parts(str(payload.get("request_note_ko", "")))
        if parts is None:
            continue
        cand_base, cand_index, cand_total, cand_label, cand_value = parts
        if cand_base != base_note or cand_total != total or cand_label != label:
            continue
        grouped.append(
            (
                cand_index,
                _case_from_replay(candidate, parameter=parameter, label=cand_label, value=cand_value),
            )
        )

    grouped.sort(key=lambda item: item[0])
    if len(grouped) != total:
        return []
    return [case for _idx, case in grouped]


def load_trench_depo_split_group(path: Path | str) -> List[TrenchSweepResult]:
    replay_path = Path(path).resolve()
    if replay_path.is_dir():
        replay = _first_replay_json(replay_path)
        if replay is None:
            return []
        replay_path = replay.resolve()
    if not replay_path.exists():
        return []
    cases = _load_split_group_from_manifest(replay_path)
    if len(cases) > 1:
        return cases
    return _load_split_group_from_notes(replay_path)


def export_trench_depo_sweep_runs(
    cases: Sequence[TrenchSweepResult],
    *,
    request_note: str = "",
    runs_root: Path | str = DEFAULT_RUNS_ROOT,
) -> List[Path]:
    saved_dirs: List[Path] = []
    total = len(cases)
    for idx, case in enumerate(cases, start=1):
        saved_dirs.append(
            export_trench_depo_run(
                case.config,
                case.result,
                request_note=split_case_request_note(request_note, case, index=idx, total=total),
                runs_root=runs_root,
            )
        )
    _write_split_group_manifests(cases, saved_dirs, request_note=request_note)
    return saved_dirs
