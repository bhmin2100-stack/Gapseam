from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from gapsim.engine.deposition_pipeline import (
    FluxModel,
    OffsetBoolean,
    REPARAM_DS_A,
    SimulationCanceled,
    SimulationState,
    SputterRedepositionFluxModel,
    Surface,
    TopologyCleanup,
    VertexNormalPropagator,
    _clip_difference,
    _clip_offset,
    _clip_union,
    deposit_step,
    _extract_surface_from_solid,
    _int_paths_area,
    equal_arc_resample,
    init_simulation_state,
    normalize_surface_order,
)
from gapsim.emulation.model4_redeposition import (
    Model4RedepositionParams,
    compute_arc_weights,
    compute_redeposition,
)

Point = Tuple[float, float]

DEFAULT_TRENCH_POINTS: Tuple[Point, ...] = (
    (1500.0, 0.0),
    (250.0, 0.0),
    (125.0, -4000.0),
    (-125.0, -4000.0),
    (-250.0, 0.0),
    (-1500.0, 0.0),
)

ION_TRANSMISSION_STEPPED_TRENCH_POINTS: Tuple[Point, ...] = (
    (2200.0, 0.0),
    (640.0, 0.0),
    (640.0, -850.0),
    (430.0, -850.0),
    (430.0, -1650.0),
    (260.0, -1650.0),
    (260.0, -3850.0),
    (-260.0, -3850.0),
    (-260.0, -1650.0),
    (-430.0, -1650.0),
    (-430.0, -850.0),
    (-640.0, -850.0),
    (-640.0, 0.0),
    (-2200.0, 0.0),
)

BOWED_JAR_TRENCH_POINTS: Tuple[Point, ...] = (
    (1800.0, 0.0),
    (120.0, 0.0),
    (90.0, -260.0),
    (150.0, -820.0),
    (250.0, -1900.0),
    (235.0, -3250.0),
    (135.0, -4700.0),
    (-135.0, -4700.0),
    (-235.0, -3250.0),
    (-250.0, -1900.0),
    (-150.0, -820.0),
    (-90.0, -260.0),
    (-120.0, 0.0),
    (-1800.0, 0.0),
)


@dataclass(frozen=True)
class TrenchDepoConfig:
    points: Sequence[Point] = DEFAULT_TRENCH_POINTS
    cycles: int = 20
    emulator_number: int = 0
    angstrom_per_cycle: float = 10.0
    reparam_ds_a: float = REPARAM_DS_A
    sputter_enabled: bool = False
    sputter_strength_a_per_cycle: float = 4.0
    sputter_peak_pct: float = 100.0
    sputter_peak_angle_deg: float = 55.0
    sputter_width_deg: float = 14.0
    sputter_smoothing_a: float = 40.0
    ion_transmission_enabled: bool = False
    ion_transmission_override: Optional[float] = None
    ion_transmission_start_depth_pct: float = 0.0
    ion_transmission_end_depth_pct: float = 100.0
    ion_transmission_decay_strength_pct: float = 100.0
    ion_transmission_floor_pct: float = 0.0
    ion_transmission_curve_power: float = 1.0
    ion_transmission_aperture_shadow_pct: float = 100.0
    ion_transmission_lateral_shadow_pct: float = 100.0
    ion_transmission_edge_shadow_pct: float = 100.0
    reflected_ion_enabled: bool = False
    reflected_ion_strength_pct: float = 0.0
    reflected_ion_bowing_weight: float = 0.75
    reflected_ion_microtrench_weight: float = 1.0
    reflected_ion_range_a: float = 1600.0
    redepo_enabled: bool = False
    redepo_source_model: str = "model2"
    redepo_efficiency_pct: float = 25.0
    redepo_emit_power: float = 1.0
    redepo_distance_power: float = 1.0
    redepo_neighbor_exclusion: int = 2
    redepo_max_distance_a: float = 1800.0
    redepo_soft_los_radius_points: int = 0
    redepo_transport_model: str = "gapsim_binned_lobe_los"
    redepo_ray_count: int = 7
    redepo_footprint_sigma_a: float = 55.0
    redepo_footprint_radius_sigma: float = 3.0
    lf_overhang_enabled: bool = False
    lf_overhang_dose: float = 1.0
    lf_overhang_sputter_gain: float = 1.0
    lf_overhang_redepo_fraction_pct: float = 30.0
    lf_overhang_survival_penalty: float = 0.75
    lf_overhang_width_a: float = 180.0
    closure_redepo_enabled: bool = False
    closure_redepo_efficiency_pct: float = 35.0
    closure_redepo_shadow_gain: float = 2.0
    closure_redepo_width_a: float = 160.0
    closure_redepo_survival_penalty: float = 0.85
    closure_redepo_smoothing_a: float = 160.0
    deposition_depth_enabled: bool = False
    deposition_feature_type: str = "hole"
    deposition_feature_width_a: float = 240.0
    deposition_feature_depth_a: float = 4700.0
    deposition_feature_length_a: Optional[float] = None
    deposition_attenuation_model: str = "exponential"
    deposition_depth_decay_k: float = 0.8
    deposition_depth_decay_power: float = 1.2
    deposition_min_ratio: float = 0.03
    deposition_use_equivalent_ar: bool = True
    deposition_closure_threshold_a: float = 8.0
    deposition_post_closure_fill_pct_hole: float = 0.03
    deposition_post_closure_fill_pct_line: float = 0.20
    deposition_line_open_path_factor: float = 1.0
    deposition_residual_fill_decay_length_a: float = 1175.0
    deposition_residual_fill_distribution: str = "exponential_from_closure"
    deposition_max_depo_per_cell_a: Optional[float] = None
    deposition_conserve_volume: bool = True
    inhibition_enabled: bool = False
    inhibition_process_model: str = "hybrid"
    inhibition_strength_pct: float = 85.0
    inhibition_penetration_depth_a: float = 1100.0
    inhibition_decay_power: float = 1.2
    inhibition_min_growth_ratio: float = 0.08
    inhibition_bottom_boost_pct: float = 20.0
    inhibition_peald_recombination_pct: float = 35.0
    inhibition_smoothing_a: float = 45.0


@dataclass(frozen=True)
class TrenchDepoResult:
    frame_steps: List[int]
    frame_profiles: List[List[Point]]
    frame_voids: List[List[List[Point]]]
    final_profile: List[Point]
    meta: Dict[str, Any]


@dataclass(frozen=True)
class TrenchSweepConfig:
    parameter: str
    label: str
    value: float
    config: TrenchDepoConfig


@dataclass(frozen=True)
class TrenchSweepResult:
    parameter: str
    label: str
    value: float
    config: TrenchDepoConfig
    result: TrenchDepoResult


FieldOverlaySample = Tuple[float, float, float]
RedepoOverlaySample = FieldOverlaySample
TransportLineSample = Tuple[float, float, float, float, float]


class _ConstantFluxModel(FluxModel):
    def __init__(self, value: float) -> None:
        self.value = float(value)

    def compute_flux(self, state) -> List[float]:  # noqa: ANN001
        return [self.value for _ in state.surface.points]


SWEEP_PARAMETER_LABELS: Dict[str, str] = {
    "cycles": "Cycles",
    "angstrom_per_cycle": "Depo A/CYC",
    "sputter_strength_a_per_cycle": "Etch A/CYC",
    "sputter_peak_pct": "Peak %",
    "sputter_peak_angle_deg": "Peak angle",
    "sputter_width_deg": "Width",
    "ion_transmission_start_depth_pct": "Ion start %",
    "ion_transmission_end_depth_pct": "Ion end %",
    "ion_transmission_decay_strength_pct": "Ion drop %",
    "ion_transmission_floor_pct": "Ion floor %",
    "ion_transmission_curve_power": "Ion curve",
    "ion_transmission_aperture_shadow_pct": "Ion aperture %",
    "ion_transmission_lateral_shadow_pct": "Ion hidden %",
    "ion_transmission_edge_shadow_pct": "Ion edge %",
    "reflected_ion_strength_pct": "Reflect %",
    "reflected_ion_bowing_weight": "Bowing",
    "reflected_ion_microtrench_weight": "Microtrench",
    "reflected_ion_range_a": "Reflect range",
    "redepo_efficiency_pct": "Redepo %",
    "redepo_emit_power": "Emit power",
    "redepo_distance_power": "Distance power",
    "redepo_neighbor_exclusion": "Neighbor skip",
    "redepo_max_distance_a": "Redepo range",
    "redepo_soft_los_radius_points": "Soft LOS",
    "redepo_ray_count": "Redepo rays",
    "redepo_footprint_sigma_a": "Footprint sigma",
    "lf_overhang_dose": "LF dose",
    "lf_overhang_sputter_gain": "LF sputter gain",
    "lf_overhang_redepo_fraction_pct": "LF redepo %",
    "lf_overhang_survival_penalty": "LF survival loss",
    "lf_overhang_width_a": "LF width",
    "closure_redepo_efficiency_pct": "Closure redepo %",
    "closure_redepo_shadow_gain": "Closure capture",
    "closure_redepo_width_a": "Closure width",
    "closure_redepo_survival_penalty": "Closure survival loss",
    "closure_redepo_smoothing_a": "Closure smooth",
    "deposition_depth_decay_k": "Depth decay",
    "deposition_depth_decay_power": "Depth power",
    "deposition_min_ratio": "Min depo ratio",
    "deposition_closure_threshold_a": "Closure threshold",
    "deposition_post_closure_fill_pct_hole": "Hole post-fill",
    "deposition_post_closure_fill_pct_line": "Line post-fill",
    "deposition_line_open_path_factor": "Line open path",
    "deposition_residual_fill_decay_length_a": "Residual decay",
    "inhibition_strength_pct": "Inhibit %",
    "inhibition_penetration_depth_a": "Inhibit depth",
    "inhibition_min_growth_ratio": "Inhibit floor",
    "inhibition_bottom_boost_pct": "Bottom boost",
    "inhibition_peald_recombination_pct": "PEALD recomb",
    "inhibition_smoothing_a": "Inhibit smooth",
}

_SPUTTER_SWEEP_PARAMETERS = frozenset(
    {
        "sputter_strength_a_per_cycle",
        "sputter_peak_pct",
        "sputter_peak_angle_deg",
        "sputter_width_deg",
    }
)

_ION_TRANSMISSION_SWEEP_PARAMETERS = frozenset(
    {
        "ion_transmission_start_depth_pct",
        "ion_transmission_end_depth_pct",
        "ion_transmission_decay_strength_pct",
        "ion_transmission_floor_pct",
        "ion_transmission_curve_power",
        "ion_transmission_aperture_shadow_pct",
        "ion_transmission_lateral_shadow_pct",
        "ion_transmission_edge_shadow_pct",
    }
)

_REFLECTED_ION_SWEEP_PARAMETERS = frozenset(
    {
        "reflected_ion_strength_pct",
        "reflected_ion_bowing_weight",
        "reflected_ion_microtrench_weight",
        "reflected_ion_range_a",
    }
)

_REDEPO_SWEEP_PARAMETERS = frozenset(
    {
        "redepo_efficiency_pct",
        "redepo_emit_power",
        "redepo_distance_power",
        "redepo_neighbor_exclusion",
        "redepo_max_distance_a",
        "redepo_soft_los_radius_points",
        "redepo_ray_count",
        "redepo_footprint_sigma_a",
    }
)

_LF_OVERHANG_SWEEP_PARAMETERS = frozenset(
    {
        "lf_overhang_dose",
        "lf_overhang_sputter_gain",
        "lf_overhang_redepo_fraction_pct",
        "lf_overhang_survival_penalty",
        "lf_overhang_width_a",
    }
)

_CLOSURE_REDEPO_SWEEP_PARAMETERS = frozenset(
    {
        "closure_redepo_efficiency_pct",
        "closure_redepo_shadow_gain",
        "closure_redepo_width_a",
        "closure_redepo_survival_penalty",
        "closure_redepo_smoothing_a",
    }
)

_DEPTH_DEPOSITION_SWEEP_PARAMETERS = frozenset(
    {
        "deposition_depth_decay_k",
        "deposition_depth_decay_power",
        "deposition_min_ratio",
        "deposition_closure_threshold_a",
        "deposition_post_closure_fill_pct_hole",
        "deposition_post_closure_fill_pct_line",
        "deposition_line_open_path_factor",
        "deposition_residual_fill_decay_length_a",
    }
)

_INHIBITION_SWEEP_PARAMETERS = frozenset(
    {
        "inhibition_strength_pct",
        "inhibition_penetration_depth_a",
        "inhibition_min_growth_ratio",
        "inhibition_bottom_boost_pct",
        "inhibition_peald_recombination_pct",
        "inhibition_smoothing_a",
    }
)


def _coerce_cycles(value: int) -> int:
    if isinstance(value, bool):
        raise ValueError("cycles must be a non-negative integer")
    try:
        fv = float(value)
    except Exception as exc:
        raise ValueError("cycles must be a non-negative integer") from exc
    if not math.isfinite(fv) or int(fv) != fv or int(fv) < 0:
        raise ValueError("cycles must be a non-negative integer")
    return int(fv)


def _coerce_positive_float(value: float, *, name: str) -> float:
    try:
        fv = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be positive") from exc
    if not math.isfinite(fv) or fv <= 0.0:
        raise ValueError(f"{name} must be positive")
    return fv


def _coerce_non_negative_float(value: float, *, name: str) -> float:
    try:
        fv = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be non-negative") from exc
    if not math.isfinite(fv) or fv < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return fv


def _coerce_finite_float(value: float, *, name: str) -> float:
    try:
        fv = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(fv):
        raise ValueError(f"{name} must be finite")
    return fv


def _coerce_points(points: Sequence[Point]) -> List[Point]:
    if points is None:
        raise ValueError("points must contain at least 2 points")

    out: List[Point] = []
    try:
        iterator = iter(points)
    except TypeError as exc:
        raise ValueError("points must contain at least 2 points") from exc

    for p in iterator:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("points must be a sequence of (x, y) pairs")
        x, y = p
        xf = float(x)
        yf = float(y)
        if not math.isfinite(xf) or not math.isfinite(yf):
            raise ValueError("points must contain finite coordinates")
        out.append((xf, yf))

    if len(out) < 2:
        raise ValueError("points must contain at least 2 points")

    normalized = normalize_surface_order(out)
    if len(normalized) < 2:
        raise ValueError("points must contain at least 2 distinct points")
    if normalized[-1][0] - normalized[0][0] <= 1e-12:
        raise ValueError("points endpoints must define a positive x-span")
    return normalized


def _segment_air_normal(a: Point, b: Point) -> Point:
    dx = float(b[0] - a[0])
    dy = float(b[1] - a[1])
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        return (0.0, 1.0)
    return (-dy / length, dx / length)


def vertex_air_normals(points: Sequence[Point]) -> List[Point]:
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n <= 0:
        return []
    if n == 1:
        return [(0.0, 1.0)]

    seg_normals = [_segment_air_normal(pts[i], pts[i + 1]) for i in range(n - 1)]
    out: List[Point] = []
    for idx in range(n):
        nx = 0.0
        ny = 0.0
        count = 0
        if idx > 0:
            sx, sy = seg_normals[idx - 1]
            nx += sx
            ny += sy
            count += 1
        if idx < n - 1:
            sx, sy = seg_normals[idx]
            nx += sx
            ny += sy
            count += 1
        length = math.hypot(nx, ny)
        if count <= 0 or length <= 1e-12:
            out.append(seg_normals[max(0, min(idx, n - 2))])
        else:
            out.append((nx / length, ny / length))
    return out


def _smooth_scalar_values(values: Sequence[float], radius_points: int) -> List[float]:
    vals = [float(v) for v in values]
    if radius_points <= 0 or len(vals) <= 2:
        return vals
    radius = min(int(radius_points), max(1, len(vals) // 2))
    out: List[float] = []
    for idx in range(len(vals)):
        left = max(0, idx - radius)
        right = min(len(vals) - 1, idx + radius)
        total = 0.0
        weight_sum = 0.0
        for j in range(left, right + 1):
            weight = float(radius + 1 - abs(j - idx))
            total += vals[j] * weight
            weight_sum += weight
        out.append(total / weight_sum if weight_sum > 0.0 else vals[idx])
    return out


def _smooth_active_scalar_values(
    values: Sequence[float],
    radius_points: int,
    active: Sequence[bool],
) -> List[float]:
    vals = [float(v) for v in values]
    mask = [bool(v) for v in active]
    if len(mask) != len(vals):
        mask = [True for _ in vals]
    if radius_points <= 0 or len(vals) <= 2:
        return [vals[i] if mask[i] else 0.0 for i in range(len(vals))]

    radius = min(int(radius_points), max(1, len(vals) // 2))
    out: List[float] = []
    for idx in range(len(vals)):
        if not mask[idx]:
            out.append(0.0)
            continue
        left = idx
        while left > 0 and mask[left - 1] and (idx - left) < radius:
            left -= 1
        right = idx
        while right < (len(vals) - 1) and mask[right + 1] and (right - idx) < radius:
            right += 1
        total = 0.0
        weight_sum = 0.0
        for j in range(left, right + 1):
            weight = float(radius + 1 - abs(j - idx))
            total += vals[j] * weight
            weight_sum += weight
        out.append(total / weight_sum if weight_sum > 0.0 else vals[idx])
    return out


def _smooth_unit_vectors(vectors: Sequence[Point], radius_points: int) -> List[Point]:
    if radius_points <= 0 or len(vectors) <= 2:
        return [(float(x), float(y)) for x, y in vectors]
    xs = _smooth_scalar_values([x for x, _y in vectors], radius_points)
    ys = _smooth_scalar_values([y for _x, y in vectors], radius_points)
    out: List[Point] = []
    for idx, (x, y) in enumerate(zip(xs, ys)):
        length = math.hypot(float(x), float(y))
        if length <= 1e-12:
            out.append((float(vectors[idx][0]), float(vectors[idx][1])))
        else:
            out.append((float(x) / length, float(y) / length))
    return out


def _incident_angles_from_normals_deg(normals: Sequence[Point]) -> List[float]:
    out: List[float] = []
    for nx, ny in normals:
        _ = nx
        # Ions arrive from the top plasma; incidence is measured from the local
        # air-side normal toward the upward source direction.
        dot = max(0.0, min(1.0, float(ny)))
        out.append(math.degrees(math.acos(dot)))
    return out


def direct_sputter_incident_angles_deg(points: Sequence[Point]) -> List[float]:
    return _incident_angles_from_normals_deg(vertex_air_normals(points))


def direct_sputter_angle_response(
    angle_deg: float,
    *,
    peak_angle_deg: float,
    width_deg: float,
    peak_pct: float = 100.0,
) -> float:
    width = _coerce_positive_float(width_deg, name="sputter_width_deg")
    peak = max(0.0, min(89.9, float(peak_angle_deg)))
    amplitude = max(0.0, min(100.0, float(peak_pct))) / 100.0
    angle = max(0.0, min(90.0, float(angle_deg)))
    z = (angle - peak) / width
    return float(amplitude * math.exp(-0.5 * z * z))


def _line_intersections_at_y(points: Sequence[Point], y_value: float) -> List[float]:
    y0 = float(y_value)
    xs: List[float] = []
    for a, b in zip(points, points[1:]):
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        if math.isclose(ay, by, rel_tol=0.0, abs_tol=1e-9):
            continue
        low = min(ay, by)
        high = max(ay, by)
        if y0 < low - 1e-9 or y0 > high + 1e-9:
            continue
        t = (y0 - ay) / (by - ay)
        if -1e-9 <= t <= 1.0 + 1e-9:
            xs.append(ax + t * (bx - ax))

    xs.sort()
    unique: List[float] = []
    for x in xs:
        if not unique or abs(x - unique[-1]) > 1e-6:
            unique.append(float(x))
    return unique


def _gap_for_point_at_y(points: Sequence[Point], x_value: float, y_value: float) -> Tuple[float, float, float, float]:
    xs = _line_intersections_at_y(points, y_value)
    if len(xs) >= 2:
        x = float(x_value)
        for left, right in zip(xs, xs[1:]):
            if left - 1e-6 <= x <= right + 1e-6 and right > left:
                return float(right - left), float((left + right) * 0.5), float(left), float(right)
        nearest_left, nearest_right = min(
            zip(xs, xs[1:]),
            key=lambda pair: min(abs(x - pair[0]), abs(x - pair[1]), abs(x - ((pair[0] + pair[1]) * 0.5))),
        )
        if nearest_right > nearest_left:
            return (
                float(nearest_right - nearest_left),
                float((nearest_left + nearest_right) * 0.5),
                float(nearest_left),
                float(nearest_right),
            )

    x_min = min(float(x) for x, _y in points)
    x_max = max(float(x) for x, _y in points)
    return float(max(x_max - x_min, 1e-9)), float((x_min + x_max) * 0.5), float(x_min), float(x_max)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _positive_or_default(value: Optional[float], default: float) -> float:
    try:
        fv = float(default if value is None else value)
    except Exception:
        return max(1e-9, float(default))
    if not math.isfinite(fv) or fv <= 0.0:
        return max(1e-9, float(default))
    return fv


def _feature_type_key(value: str) -> str:
    raw = str(value or "hole").strip().lower()
    if raw in {"line", "trench"}:
        return "line"
    return "hole"


def compute_effective_aspect_ratio(
    depth_a: float,
    feature_type: str,
    feature_width_a: float,
    feature_length_a: Optional[float] = None,
    *,
    use_equivalent_aspect_ratio: bool = True,
) -> float:
    depth = max(0.0, float(depth_a))
    width = _positive_or_default(feature_width_a, 1.0)
    if not bool(use_equivalent_aspect_ratio):
        return float(depth / width)

    if _feature_type_key(feature_type) == "line":
        length = None if feature_length_a is None else float(feature_length_a)
        if length is None or not math.isfinite(length) or length <= 0.0 or length >= width * 1000.0:
            return float(depth / max(2.0 * width, 1e-9))
        return float(depth * (width + length) / max(2.0 * width * length, 1e-9))
    return float(depth / width)


def compute_depth_deposition_ratio(
    effective_aspect_ratio: float,
    *,
    attenuation_model: str = "exponential",
    depth_decay_k: float = 0.8,
    depth_decay_power: float = 1.2,
    min_depo_ratio: float = 0.03,
) -> float:
    ear = max(0.0, float(effective_aspect_ratio))
    min_ratio = _clamp01(float(min_depo_ratio))
    k = max(0.0, float(depth_decay_k))
    power = max(0.05, float(depth_decay_power))
    if k <= 1e-12 or ear <= 1e-12:
        raw = 1.0
    else:
        model = str(attenuation_model or "exponential").strip().lower()
        if model == "power":
            raw = 1.0 / (1.0 + k * (ear ** power))
        elif model == "logistic":
            ar50 = max(1e-6, 1.0 / max(k, 1e-6))
            raw = 1.0 / (1.0 + ((ear / ar50) ** power))
        else:
            raw = math.exp(-k * (ear ** power))
    return _clamp01(min_ratio + ((1.0 - min_ratio) * _clamp01(raw)))


def compute_depth_deposition_factors(
    points: Sequence[Point],
    *,
    feature_type: str = "hole",
    feature_width_a: float = 240.0,
    feature_length_a: Optional[float] = None,
    attenuation_model: str = "exponential",
    depth_decay_k: float = 0.8,
    depth_decay_power: float = 1.2,
    min_depo_ratio: float = 0.03,
    use_equivalent_aspect_ratio: bool = True,
) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return []
    surface_y = max(y for _x, y in pts)
    out: List[float] = []
    for _x, y in pts:
        depth = max(0.0, surface_y - float(y))
        ear = compute_effective_aspect_ratio(
            depth,
            feature_type,
            feature_width_a,
            feature_length_a,
            use_equivalent_aspect_ratio=use_equivalent_aspect_ratio,
        )
        out.append(
            compute_depth_deposition_ratio(
                ear,
                attenuation_model=attenuation_model,
                depth_decay_k=depth_decay_k,
                depth_decay_power=depth_decay_power,
                min_depo_ratio=min_depo_ratio,
            )
        )
    return out


def _inhibition_process_key(value: str) -> str:
    raw = str(value or "hybrid").strip().lower().replace("-", "_")
    if raw in {"pecvd", "pe_cvd", "cvd"}:
        return "pecvd"
    if raw in {"peald", "pe_ald", "ald"}:
        return "peald"
    return "hybrid"


def compute_inhibition_deposition_factors(
    points: Sequence[Point],
    *,
    process_model: str = "hybrid",
    feature_type: str = "hole",
    feature_width_a: float = 240.0,
    feature_length_a: Optional[float] = None,
    attenuation_model: str = "exponential",
    depth_decay_k: float = 0.8,
    depth_decay_power: float = 1.2,
    min_depo_ratio: float = 0.03,
    use_equivalent_aspect_ratio: bool = True,
    inhibition_strength_pct: float = 85.0,
    inhibition_penetration_depth_a: float = 1100.0,
    inhibition_decay_power: float = 1.2,
    inhibition_min_growth_ratio: float = 0.08,
    inhibition_bottom_boost_pct: float = 20.0,
    inhibition_peald_recombination_pct: float = 35.0,
    inhibition_smoothing_a: float = 45.0,
    reparam_ds_a: float = REPARAM_DS_A,
) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return []

    process = _inhibition_process_key(process_model)
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(1e-9, surface_y - bottom_y)
    penetration = _positive_or_default(inhibition_penetration_depth_a, depth_span * 0.25)
    coverage_power = max(0.05, float(inhibition_decay_power))
    strength = _clamp01(float(inhibition_strength_pct) / 100.0)
    growth_floor = _clamp01(float(inhibition_min_growth_ratio))
    bottom_boost = max(0.0, float(inhibition_bottom_boost_pct) / 100.0)
    recomb_weight = _clamp01(float(inhibition_peald_recombination_pct) / 100.0)

    radical_factors = compute_depth_deposition_factors(
        pts,
        feature_type=feature_type,
        feature_width_a=feature_width_a,
        feature_length_a=feature_length_a,
        attenuation_model=attenuation_model,
        depth_decay_k=depth_decay_k,
        depth_decay_power=depth_decay_power,
        min_depo_ratio=min_depo_ratio,
        use_equivalent_aspect_ratio=use_equivalent_aspect_ratio,
    )

    ratios: List[float] = []
    for (_x, y), radical_factor in zip(pts, radical_factors):
        depth = max(0.0, surface_y - float(y))
        depth_norm = _clamp01(depth / depth_span)
        inhibitor_coverage = math.exp(-((depth / penetration) ** coverage_power))
        inhibited = max(growth_floor, 1.0 - (strength * inhibitor_coverage))

        recombination_loss = 0.0
        if process == "peald":
            recombination_loss = recomb_weight * (1.0 - _clamp01(radical_factor))
        elif process == "hybrid":
            recombination_loss = 0.5 * recomb_weight * (1.0 - _clamp01(radical_factor))
        transport = max(growth_floor, 1.0 - recombination_loss)

        boost = 1.0 + bottom_boost * (1.0 - inhibitor_coverage) * (depth_norm ** 0.7)
        ratios.append(max(growth_floor, min(2.0, inhibited * transport * boost)))

    radius_points = int(round(max(0.0, float(inhibition_smoothing_a)) / max(float(reparam_ds_a), 1e-9)))
    if radius_points > 0:
        ratios = _smooth_scalar_values(ratios, radius_points)
    return [min(2.0, max(0.0, value)) for value in ratios]


def detect_depth_deposition_closure(
    points: Sequence[Point],
    *,
    closure_threshold_a: float,
    reparam_ds_a: float = REPARAM_DS_A,
) -> Dict[str, Any]:
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < 2:
        return {"closed": False, "closureDepth": None, "minOpeningWidth": 0.0}
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    max_depth = max(0.0, surface_y - bottom_y)
    if max_depth <= 1e-9:
        return {"closed": False, "closureDepth": None, "minOpeningWidth": 0.0}

    threshold = max(0.0, float(closure_threshold_a))
    bin_a = max(float(reparam_ds_a) * 4.0, max_depth / 160.0, 1.0)
    min_width = float("inf")
    min_depth = 0.0
    depth = min(max_depth, bin_a)
    while depth <= max_depth + 1e-9:
        y_probe = surface_y - min(depth, max_depth)
        xs = _line_intersections_at_y(pts, y_probe)
        if len(xs) >= 2:
            widths = [max(0.0, float(r - l)) for l, r in zip(xs, xs[1:])]
            width = min(widths) if widths else 0.0
        else:
            width = 0.0
        if width < min_width:
            min_width = width
            min_depth = min(depth, max_depth)
        depth += bin_a

    if not math.isfinite(min_width):
        min_width = 0.0
    return {
        "closed": bool(min_width <= threshold),
        "closureDepth": float(min_depth) if min_width <= threshold else None,
        "minOpeningWidth": float(min_width),
    }


class _DepthDependentDepositionFluxModel(FluxModel):
    def __init__(
        self,
        *,
        feature_type: str,
        feature_width_a: float,
        feature_length_a: Optional[float],
        attenuation_model: str,
        depth_decay_k: float,
        depth_decay_power: float,
        min_depo_ratio: float,
        use_equivalent_aspect_ratio: bool,
        max_depo_per_cell_a: Optional[float],
    ) -> None:
        self.feature_type = _feature_type_key(feature_type)
        self.feature_width_a = _positive_or_default(feature_width_a, 240.0)
        self.feature_length_a = feature_length_a
        self.attenuation_model = str(attenuation_model or "exponential")
        self.depth_decay_k = max(0.0, float(depth_decay_k))
        self.depth_decay_power = max(0.05, float(depth_decay_power))
        self.min_depo_ratio = _clamp01(float(min_depo_ratio))
        self.use_equivalent_aspect_ratio = bool(use_equivalent_aspect_ratio)
        self.max_depo_per_cell_a = None if max_depo_per_cell_a is None else max(0.0, float(max_depo_per_cell_a))

    def compute_flux(self, state: SimulationState) -> List[float]:
        pts = [(float(x), float(y)) for x, y in state.surface.points]
        if not pts:
            return []
        surface_y = max(y for _x, y in pts)
        dr = max(0.0, float(state.meta.get("dr", 0.0) or 0.0))
        flux_cap = None
        if self.max_depo_per_cell_a is not None and dr > 1e-12:
            flux_cap = self.max_depo_per_cell_a / dr

        ratios: List[float] = []
        ears: List[float] = []
        depths: List[float] = []
        for _x, y in pts:
            depth = max(0.0, surface_y - float(y))
            ear = compute_effective_aspect_ratio(
                depth,
                self.feature_type,
                self.feature_width_a,
                self.feature_length_a,
                use_equivalent_aspect_ratio=self.use_equivalent_aspect_ratio,
            )
            ratio = compute_depth_deposition_ratio(
                ear,
                attenuation_model=self.attenuation_model,
                depth_decay_k=self.depth_decay_k,
                depth_decay_power=self.depth_decay_power,
                min_depo_ratio=self.min_depo_ratio,
            )
            if flux_cap is not None:
                ratio = min(ratio, max(0.0, float(flux_cap)))
            depths.append(depth)
            ears.append(ear)
            ratios.append(ratio)

        state.meta["depth_deposition_debug_fields_last"] = {
            "x": [round(float(x), 6) for x, _y in pts],
            "y": [round(float(y), 6) for _x, y in pts],
            "depth_field": [round(float(v), 6) for v in depths],
            "effective_ar_field": [round(float(v), 6) for v in ears],
            "depth_ratio_field": [round(float(v), 6) for v in ratios],
            "depo_field": [round(float(dr) * float(v), 6) for v in ratios],
        }
        state.meta["depth_deposition_debug_summary_last"] = {
            "depth_ratio": _field_summary_by_depth(pts, ratios),
            "depo": _field_summary_by_depth(pts, [float(dr) * float(v) for v in ratios]),
        }
        return ratios


class _InhibitionDepositionFluxModel(FluxModel):
    def __init__(
        self,
        *,
        process_model: str,
        feature_type: str,
        feature_width_a: float,
        feature_length_a: Optional[float],
        attenuation_model: str,
        depth_decay_k: float,
        depth_decay_power: float,
        min_depo_ratio: float,
        use_equivalent_aspect_ratio: bool,
        inhibition_strength_pct: float,
        inhibition_penetration_depth_a: float,
        inhibition_decay_power: float,
        inhibition_min_growth_ratio: float,
        inhibition_bottom_boost_pct: float,
        inhibition_peald_recombination_pct: float,
        inhibition_smoothing_a: float,
        reparam_ds_a: float,
    ) -> None:
        self.process_model = _inhibition_process_key(process_model)
        self.feature_type = _feature_type_key(feature_type)
        self.feature_width_a = _positive_or_default(feature_width_a, 240.0)
        self.feature_length_a = feature_length_a
        self.attenuation_model = str(attenuation_model or "exponential")
        self.depth_decay_k = max(0.0, float(depth_decay_k))
        self.depth_decay_power = max(0.05, float(depth_decay_power))
        self.min_depo_ratio = _clamp01(float(min_depo_ratio))
        self.use_equivalent_aspect_ratio = bool(use_equivalent_aspect_ratio)
        self.inhibition_strength_pct = max(0.0, min(100.0, float(inhibition_strength_pct)))
        self.inhibition_penetration_depth_a = _positive_or_default(inhibition_penetration_depth_a, 1100.0)
        self.inhibition_decay_power = max(0.05, float(inhibition_decay_power))
        self.inhibition_min_growth_ratio = _clamp01(float(inhibition_min_growth_ratio))
        self.inhibition_bottom_boost_pct = max(0.0, min(200.0, float(inhibition_bottom_boost_pct)))
        self.inhibition_peald_recombination_pct = max(0.0, min(100.0, float(inhibition_peald_recombination_pct)))
        self.inhibition_smoothing_a = max(0.0, float(inhibition_smoothing_a))
        self.reparam_ds_a = max(0.5, float(reparam_ds_a))

    def compute_flux(self, state: SimulationState) -> List[float]:
        pts = [(float(x), float(y)) for x, y in state.surface.points]
        if not pts:
            return []
        surface_y = max(y for _x, y in pts)
        dr = max(0.0, float(state.meta.get("dr", 0.0) or 0.0))
        ratios = compute_inhibition_deposition_factors(
            pts,
            process_model=self.process_model,
            feature_type=self.feature_type,
            feature_width_a=self.feature_width_a,
            feature_length_a=self.feature_length_a,
            attenuation_model=self.attenuation_model,
            depth_decay_k=self.depth_decay_k,
            depth_decay_power=self.depth_decay_power,
            min_depo_ratio=self.min_depo_ratio,
            use_equivalent_aspect_ratio=self.use_equivalent_aspect_ratio,
            inhibition_strength_pct=self.inhibition_strength_pct,
            inhibition_penetration_depth_a=self.inhibition_penetration_depth_a,
            inhibition_decay_power=self.inhibition_decay_power,
            inhibition_min_growth_ratio=self.inhibition_min_growth_ratio,
            inhibition_bottom_boost_pct=self.inhibition_bottom_boost_pct,
            inhibition_peald_recombination_pct=self.inhibition_peald_recombination_pct,
            inhibition_smoothing_a=self.inhibition_smoothing_a,
            reparam_ds_a=self.reparam_ds_a,
        )
        depths = [max(0.0, surface_y - float(y)) for _x, y in pts]
        state.meta["inhibition_debug_fields_last"] = {
            "x": [round(float(x), 6) for x, _y in pts],
            "y": [round(float(y), 6) for _x, y in pts],
            "depth_field": [round(float(v), 6) for v in depths],
            "growth_ratio_field": [round(float(v), 6) for v in ratios],
            "depo_field": [round(float(dr) * float(v), 6) for v in ratios],
        }
        state.meta["inhibition_debug_summary_last"] = {
            "growth_ratio": _field_summary_by_depth(pts, ratios),
            "depo": _field_summary_by_depth(pts, [float(dr) * float(v) for v in ratios]),
        }
        return ratios


def _depth_depo_internal_substeps(deposition_a: float, reparam_ds_a: float) -> int:
    target_a = max(5.0, float(reparam_ds_a) * 3.0)
    move_a = max(0.0, float(deposition_a))
    if move_a <= target_a:
        return 1
    return max(1, min(24, int(math.ceil(move_a / target_a))))


def _void_area_a2(voids_i: Sequence[Sequence[Tuple[int, int]]], scale: int) -> float:
    if not voids_i:
        return 0.0
    return float(_int_paths_area(voids_i)) / max(float(scale) * float(scale), 1.0)


def _path_perimeter_a(path_i: Sequence[Tuple[int, int]], scale: int) -> float:
    if len(path_i) < 2:
        return 0.0
    inv = 1.0 / max(float(scale), 1.0)
    perimeter = 0.0
    for a, b in zip(path_i, list(path_i[1:]) + [path_i[0]]):
        perimeter += math.hypot(float(b[0] - a[0]) * inv, float(b[1] - a[1]) * inv)
    return perimeter


def _post_closure_allowed_fill_fraction(
    *,
    feature_type: str,
    post_closure_fill_pct_hole: float,
    post_closure_fill_pct_line: float,
    line_open_path_factor: float,
) -> float:
    if _feature_type_key(feature_type) == "line":
        return _clamp01(float(post_closure_fill_pct_line)) * _clamp01(float(line_open_path_factor))
    return _clamp01(float(post_closure_fill_pct_hole))


def _estimate_post_closure_candidate_fill_area_a2(
    voids_i: Sequence[Sequence[Tuple[int, int]]],
    state: SimulationState,
    *,
    nominal_depo_a: float,
    feature_type: str,
    feature_width_a: float,
    feature_length_a: Optional[float],
    attenuation_model: str,
    depth_decay_k: float,
    depth_decay_power: float,
    min_depo_ratio: float,
    use_equivalent_aspect_ratio: bool,
    closure_depth_a: float,
    residual_fill_decay_length_a: float,
    residual_fill_distribution: str,
) -> float:
    if not voids_i or nominal_depo_a <= 0.0:
        return 0.0
    surface_y = max((float(y) for _x, y in state.surface.points), default=0.0)
    decay_len = _positive_or_default(residual_fill_decay_length_a, 1.0)
    distribution = str(residual_fill_distribution or "exponential_from_closure").strip().lower()
    total = 0.0
    scale = max(float(state.scale), 1.0)
    for path in voids_i:
        if len(path) < 2:
            continue
        for a, b in zip(path, list(path[1:]) + [path[0]]):
            ax, ay = float(a[0]) / scale, float(a[1]) / scale
            bx, by = float(b[0]) / scale, float(b[1]) / scale
            seg_len = math.hypot(bx - ax, by - ay)
            if seg_len <= 1e-12:
                continue
            mid_y = (ay + by) * 0.5
            z = max(0.0, surface_y - mid_y)
            ear = compute_effective_aspect_ratio(
                z,
                feature_type,
                feature_width_a,
                feature_length_a,
                use_equivalent_aspect_ratio=use_equivalent_aspect_ratio,
            )
            ratio = compute_depth_deposition_ratio(
                ear,
                attenuation_model=attenuation_model,
                depth_decay_k=depth_decay_k,
                depth_decay_power=depth_decay_power,
                min_depo_ratio=min_depo_ratio,
            )
            if distribution == "uniform_below_closure":
                residual_factor = 1.0
            else:
                dz = max(0.0, z - max(0.0, float(closure_depth_a)))
                residual_factor = math.exp(-dz / decay_len)
            total += seg_len * float(nominal_depo_a) * ratio * residual_factor
    return max(0.0, float(total))


def _fill_voids_by_area_budget(
    state: SimulationState,
    voids_i: Sequence[Sequence[Tuple[int, int]]],
    *,
    target_fill_area_a2: float,
) -> float:
    if not voids_i or target_fill_area_a2 <= 0.0:
        return 0.0
    scale = max(int(state.scale), 1)
    target_i2 = max(1.0, float(target_fill_area_a2) * float(scale) * float(scale))
    void_area_i2 = float(_int_paths_area(voids_i))
    if void_area_i2 <= 1.0:
        return 0.0

    def area_loss_for_delta(delta_i: int) -> Tuple[float, List[List[Tuple[int, int]]]]:
        if delta_i <= 0:
            return 0.0, [list(path) for path in voids_i]
        shrink = _clip_offset(voids_i, -int(delta_i), arc_tolerance=max(scale * 0.25, 1.0))
        remaining_i2 = float(_int_paths_area(shrink)) if shrink else 0.0
        return max(0.0, void_area_i2 - remaining_i2), shrink

    hi = max(1, int(round(math.sqrt(min(void_area_i2, target_i2)) * 2.0)))
    hi = max(hi, scale)
    loss_hi, shrink_hi = area_loss_for_delta(hi)
    while loss_hi < target_i2 and shrink_hi and hi < scale * 100000:
        hi *= 2
        loss_hi, shrink_hi = area_loss_for_delta(hi)

    lo = 0
    best_delta = 0
    best_loss = 0.0
    best_shrink: List[List[Tuple[int, int]]] = [list(path) for path in voids_i]
    for _ in range(28):
        mid = (lo + hi) // 2
        if mid <= lo:
            break
        loss_mid, shrink_mid = area_loss_for_delta(mid)
        if loss_mid <= target_i2:
            best_delta = mid
            best_loss = loss_mid
            best_shrink = shrink_mid
            lo = mid
        else:
            hi = mid

    if best_delta <= 0 or best_loss <= 0.0:
        return 0.0
    fill_paths = _clip_difference(voids_i, best_shrink) if best_shrink else [list(path) for path in voids_i]
    if not fill_paths:
        return 0.0
    merged = _clip_union(state.solid_paths_i, fill_paths)
    if not merged:
        return 0.0
    state.solid_paths_i = merged
    state.surface.points = equal_arc_resample(
        _extract_surface_from_solid(state, merged, state.surface.points),
        _state_reparam_ds_from_meta(state),
    )
    return float(best_loss) / (float(scale) * float(scale))


def _state_reparam_ds_from_meta(state: SimulationState) -> float:
    return max(0.5, min(200.0, float(state.meta.get("reparam_ds", REPARAM_DS_A) or REPARAM_DS_A)))


def _apply_depth_post_closure_fill(
    state: SimulationState,
    cfg: TrenchDepoConfig,
    *,
    nominal_depo_a: float,
    cycle_index: int,
) -> None:
    if not bool(cfg.deposition_depth_enabled or cfg.inhibition_enabled) or nominal_depo_a <= 0.0:
        return
    voids_i = OffsetBoolean.collect_void_air(state)
    if not voids_i:
        return

    scale = max(int(state.scale), 1)
    current_void_area = _void_area_a2(voids_i, scale)
    if current_void_area <= 1e-9:
        return

    closure_set = bool(state.meta.get("depth_closure_detected", False))
    if not closure_set:
        surface_y = max((float(y) for _x, y in state.surface.points), default=0.0)
        top_void_y = max(float(y_i) / float(scale) for path in voids_i for _x_i, y_i in path)
        closure_depth = max(0.0, surface_y - top_void_y)
        fill_fraction = _post_closure_allowed_fill_fraction(
            feature_type=cfg.deposition_feature_type,
            post_closure_fill_pct_hole=cfg.deposition_post_closure_fill_pct_hole,
            post_closure_fill_pct_line=cfg.deposition_post_closure_fill_pct_line,
            line_open_path_factor=cfg.deposition_line_open_path_factor,
        )
        allowed = current_void_area * fill_fraction
        state.meta["depth_closure_detected"] = True
        state.meta["depth_closure_step"] = int(cycle_index)
        state.meta["depth_closure_depth_a"] = float(closure_depth)
        state.meta["depth_closure_void_area_a2"] = float(current_void_area)
        state.meta["depth_post_closure_allowed_fill_area_a2"] = float(max(0.0, allowed))
        state.meta["depth_post_closure_budget_used_area_a2"] = 0.0

    allowed_area = max(0.0, float(state.meta.get("depth_post_closure_allowed_fill_area_a2", 0.0) or 0.0))
    used_area = max(0.0, float(state.meta.get("depth_post_closure_budget_used_area_a2", 0.0) or 0.0))
    remaining_budget = max(0.0, allowed_area - used_area)
    if remaining_budget <= 1e-9:
        return

    feature_depth = _positive_or_default(cfg.deposition_feature_depth_a, 4700.0)
    residual_decay = _positive_or_default(cfg.deposition_residual_fill_decay_length_a, feature_depth * 0.25)
    closure_depth = max(0.0, float(state.meta.get("depth_closure_depth_a", 0.0) or 0.0))
    candidate_area = _estimate_post_closure_candidate_fill_area_a2(
        voids_i,
        state,
        nominal_depo_a=nominal_depo_a,
        feature_type=cfg.deposition_feature_type,
        feature_width_a=cfg.deposition_feature_width_a,
        feature_length_a=cfg.deposition_feature_length_a,
        attenuation_model=cfg.deposition_attenuation_model,
        depth_decay_k=cfg.deposition_depth_decay_k,
        depth_decay_power=cfg.deposition_depth_decay_power,
        min_depo_ratio=cfg.deposition_min_ratio,
        use_equivalent_aspect_ratio=cfg.deposition_use_equivalent_ar,
        closure_depth_a=closure_depth,
        residual_fill_decay_length_a=residual_decay,
        residual_fill_distribution=cfg.deposition_residual_fill_distribution,
    )
    target_area = min(max(0.0, candidate_area), remaining_budget)
    if bool(cfg.deposition_conserve_volume):
        target_area = min(target_area, current_void_area)
    filled_area = _fill_voids_by_area_budget(state, voids_i, target_fill_area_a2=target_area)
    if filled_area <= 0.0:
        return
    state.meta["depth_post_closure_budget_used_area_a2"] = min(allowed_area, used_area + filled_area)
    state.meta["depth_post_closure_last_fill_area_a2"] = float(filled_area)


def _apply_depth_deposition_step(
    state: SimulationState,
    cfg: TrenchDepoConfig,
    *,
    deposition_a: float,
    reparam_ds_a: float,
    cycle_index: int,
) -> None:
    state.meta["dr"] = float(deposition_a)
    state.meta["reparam_ds"] = float(reparam_ds_a)
    model = _DepthDependentDepositionFluxModel(
        feature_type=cfg.deposition_feature_type,
        feature_width_a=cfg.deposition_feature_width_a,
        feature_length_a=cfg.deposition_feature_length_a,
        attenuation_model=cfg.deposition_attenuation_model,
        depth_decay_k=cfg.deposition_depth_decay_k,
        depth_decay_power=cfg.deposition_depth_decay_power,
        min_depo_ratio=cfg.deposition_min_ratio,
        use_equivalent_aspect_ratio=cfg.deposition_use_equivalent_ar,
        max_depo_per_cell_a=cfg.deposition_max_depo_per_cell_a,
    )
    pts = normalize_surface_order(state.surface.points)
    if len(pts) < 2 or deposition_a <= 0.0:
        state.surface.points = pts
        return
    flux = model.compute_flux(state)
    if len(flux) != len(pts):
        flux = [1.0 for _ in pts]
    proposed = VertexNormalPropagator().advance(pts, flux, deposition_a)
    positive = [max(0.0, float(v)) for v in flux]
    mean_flux = sum(positive) / float(len(positive)) if positive else 1.0
    solid_ref = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=deposition_a * mean_flux)
    clean_surface, clean_solid = TopologyCleanup().cleanup(
        proposed,
        state,
        solid_ref_paths_i=solid_ref,
        solid_merge_mode="union",
    )
    state.surface.points = equal_arc_resample(clean_surface, reparam_ds_a)
    if clean_solid:
        state.solid_paths_i = clean_solid

    closure_probe = detect_depth_deposition_closure(
        state.surface.points,
        closure_threshold_a=cfg.deposition_closure_threshold_a,
        reparam_ds_a=reparam_ds_a,
    )
    state.meta["depth_closure_probe_last"] = closure_probe
    _apply_depth_post_closure_fill(state, cfg, nominal_depo_a=deposition_a, cycle_index=cycle_index)


def _apply_inhibition_deposition_step(
    state: SimulationState,
    cfg: TrenchDepoConfig,
    *,
    deposition_a: float,
    reparam_ds_a: float,
    cycle_index: int,
) -> None:
    state.meta["dr"] = float(deposition_a)
    state.meta["reparam_ds"] = float(reparam_ds_a)
    model = _InhibitionDepositionFluxModel(
        process_model=cfg.inhibition_process_model,
        feature_type=cfg.deposition_feature_type,
        feature_width_a=cfg.deposition_feature_width_a,
        feature_length_a=cfg.deposition_feature_length_a,
        attenuation_model=cfg.deposition_attenuation_model,
        depth_decay_k=cfg.deposition_depth_decay_k,
        depth_decay_power=cfg.deposition_depth_decay_power,
        min_depo_ratio=cfg.deposition_min_ratio,
        use_equivalent_aspect_ratio=cfg.deposition_use_equivalent_ar,
        inhibition_strength_pct=cfg.inhibition_strength_pct,
        inhibition_penetration_depth_a=cfg.inhibition_penetration_depth_a,
        inhibition_decay_power=cfg.inhibition_decay_power,
        inhibition_min_growth_ratio=cfg.inhibition_min_growth_ratio,
        inhibition_bottom_boost_pct=cfg.inhibition_bottom_boost_pct,
        inhibition_peald_recombination_pct=cfg.inhibition_peald_recombination_pct,
        inhibition_smoothing_a=cfg.inhibition_smoothing_a,
        reparam_ds_a=reparam_ds_a,
    )
    pts = normalize_surface_order(state.surface.points)
    if len(pts) < 2 or deposition_a <= 0.0:
        state.surface.points = pts
        return
    flux = model.compute_flux(state)
    if len(flux) != len(pts):
        flux = [1.0 for _ in pts]
    proposed = VertexNormalPropagator().advance(pts, flux, deposition_a)
    positive = [max(0.0, float(v)) for v in flux]
    mean_flux = sum(positive) / float(len(positive)) if positive else 1.0
    solid_ref = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=deposition_a * mean_flux)
    clean_surface, clean_solid = TopologyCleanup().cleanup(
        proposed,
        state,
        solid_ref_paths_i=solid_ref,
        solid_merge_mode="union",
    )
    state.surface.points = equal_arc_resample(clean_surface, reparam_ds_a)
    if clean_solid:
        state.solid_paths_i = clean_solid

    closure_probe = detect_depth_deposition_closure(
        state.surface.points,
        closure_threshold_a=cfg.deposition_closure_threshold_a,
        reparam_ds_a=reparam_ds_a,
    )
    state.meta["depth_closure_probe_last"] = closure_probe
    _apply_depth_post_closure_fill(state, cfg, nominal_depo_a=deposition_a, cycle_index=cycle_index)


def compute_ion_transmission_factors(
    points: Sequence[Point],
    *,
    enabled: bool = True,
    override: Optional[float] = None,
    start_depth_pct: float = 0.0,
    end_depth_pct: float = 100.0,
    decay_strength_pct: float = 100.0,
    floor_pct: float = 0.0,
    curve_power: float = 1.0,
    aperture_shadow_pct: float = 100.0,
    lateral_shadow_pct: float = 100.0,
    edge_shadow_pct: float = 100.0,
    reparam_ds_a: float = REPARAM_DS_A,
) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return []
    if override is not None:
        return [_clamp01(float(override)) for _ in pts]
    if not enabled:
        return [1.0 for _ in pts]

    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    max_depth = max(0.0, surface_y - bottom_y)
    if max_depth <= 1e-9:
        return [1.0 for _ in pts]

    start_depth = max_depth * _clamp01(float(start_depth_pct) / 100.0)
    end_depth = max_depth * _clamp01(float(end_depth_pct) / 100.0)
    end_depth = max(start_depth + 1e-9, end_depth)
    decay_strength = _clamp01(float(decay_strength_pct) / 100.0)
    floor_factor = _clamp01(float(floor_pct) / 100.0)
    curve_power_f = max(0.2, min(6.0, float(curve_power)))
    aperture_shadow_strength = _clamp01(float(aperture_shadow_pct) / 100.0)
    lateral_shadow_strength = _clamp01(float(lateral_shadow_pct) / 100.0)
    edge_shadow_strength = _clamp01(float(edge_shadow_pct) / 100.0)
    if decay_strength <= 1e-12:
        return [1.0 for _ in pts]

    bin_a = max(40.0, float(reparam_ds_a) * 12.0)
    opening_probe_depth = max(bin_a, max_depth * 0.015)
    opening_y = surface_y - min(max_depth, opening_probe_depth)
    opening_width, _opening_center, opening_left, opening_right = _gap_for_point_at_y(pts, 0.0, opening_y)
    opening_width = max(opening_width, float(reparam_ds_a), 1e-9)

    gap_cache: Dict[int, Tuple[float, float, float, float]] = {}

    def gap_at_depth_key(key: int) -> Tuple[float, float, float, float]:
        key_i = max(0, int(key))
        cached = gap_cache.get(key_i)
        if cached is None:
            depth = float(key_i) * bin_a
            y_probe = surface_y - min(max_depth, max(0.0, depth))
            cached = _gap_for_point_at_y(pts, 0.0, y_probe)
            gap_cache[key_i] = cached
        return cached

    # Width shadowing is caused by apertures above the point. Precomputing the
    # best bottleneck per depth bin avoids re-scanning all upper bins for every
    # surface point while keeping the same single-opening approximation.
    max_bin = max(1, int(math.ceil(max_depth / bin_a)))
    bottleneck_cache: Dict[int, Tuple[float, float, float, float]] = {
        0: (opening_width, _opening_center, opening_left, opening_right)
    }
    best_width = opening_width
    best_center = _opening_center
    best_left = opening_left
    best_right = opening_right
    for key in range(1, max_bin + 1):
        width, center, left, right = gap_at_depth_key(key)
        if width < best_width:
            best_width = width
            best_center = center
            best_left = left
            best_right = right
        bottleneck_cache[key] = (best_width, best_center, best_left, best_right)

    def bottleneck_above(depth: float) -> Tuple[float, float, float, float]:
        limit_depth = max(0.0, float(depth) - bin_a)
        if limit_depth <= 1e-9:
            return opening_width, _opening_center, opening_left, opening_right
        key = max(0, min(max_bin, int(math.ceil(limit_depth / bin_a))))
        return bottleneck_cache.get(key, bottleneck_cache[max_bin])

    out: List[float] = []
    for x, y in pts:
        depth = max(0.0, surface_y - y)
        if depth <= max(float(reparam_ds_a) * 2.0, 1.0) or depth <= start_depth:
            out.append(1.0)
            continue
        aperture_width, aperture_center, aperture_left, aperture_right = bottleneck_above(depth)
        aperture_width = max(aperture_width, float(reparam_ds_a), 1e-9)

        raw_width_factor = 0.35 + 0.65 * _clamp01(aperture_width / opening_width)
        width_factor = 1.0 - (aperture_shadow_strength * (1.0 - raw_width_factor))

        lateral_shadow = max(aperture_left - x, x - aperture_right, 0.0)
        raw_sky_factor = 1.0 / (
            1.0 + lateral_shadow / max(aperture_width * 0.22, float(reparam_ds_a), 1e-9)
        )
        sky_factor = 1.0 - (lateral_shadow_strength * (1.0 - raw_sky_factor))

        half_width = aperture_width * 0.5
        center_offset = abs(x - aperture_center) / max(half_width, 1e-9)
        raw_edge_factor = 0.65 + 0.35 * (1.0 - _clamp01(center_offset) ** 1.5)
        edge_factor = 1.0 - (edge_shadow_strength * (1.0 - raw_edge_factor))

        depth_span = max(end_depth - start_depth, 1e-9)
        depth_t = _clamp01((depth - start_depth) / depth_span)
        depth_curve_factor = 1.0 - (decay_strength * (depth_t ** curve_power_f))
        geometry_visibility = _clamp01(width_factor * sky_factor * edge_factor)
        out.append(_clamp01(max(floor_factor, depth_curve_factor * geometry_visibility)))
    return out


def _weighted_centroid(points: Sequence[Point], weights: Sequence[float], indices: Sequence[int]) -> Tuple[float, float, float]:
    total = 0.0
    sx = 0.0
    sy = 0.0
    for idx in indices:
        if idx < 0 or idx >= len(points) or idx >= len(weights):
            continue
        weight = max(0.0, float(weights[idx]))
        if weight <= 0.0:
            continue
        x, y = points[idx]
        sx += float(x) * weight
        sy += float(y) * weight
        total += weight
    if total <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (sx / total, sy / total, total)


def compute_reflected_ion_fields(
    points: Sequence[Point],
    normals: Sequence[Point],
    direct_sputter_field: Sequence[float],
    *,
    strength_pct: float,
    bowing_weight: float,
    microtrench_weight: float,
    reflection_range_a: float,
    reparam_ds_a: float = REPARAM_DS_A,
    smoothing_radius_points: int = 0,
) -> Tuple[List[float], List[float]]:
    pts = [(float(x), float(y)) for x, y in points]
    direct = [max(0.0, float(v)) for v in direct_sputter_field]
    n = len(pts)
    if n == 0:
        return [], []
    if len(direct) != n or len(normals) != n:
        return [0.0 for _ in pts], [0.0 for _ in pts]

    strength = max(0.0, float(strength_pct)) / 100.0
    if strength <= 0.0 or max(direct, default=0.0) <= 0.0:
        return [0.0 for _ in pts], [0.0 for _ in pts]

    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    max_depth = max(surface_y - bottom_y, 1e-9)
    bottom_width, bottom_center, bottom_left, bottom_right = _gap_for_point_at_y(
        pts,
        0.0,
        bottom_y + min(max_depth * 0.01, max(float(reparam_ds_a), 1.0)),
    )
    bottom_width = max(bottom_width, float(reparam_ds_a), 1e-9)
    half_bottom = max(bottom_width * 0.5, float(reparam_ds_a), 1e-9)
    range_a = max(float(reflection_range_a), float(reparam_ds_a) * 8.0, 1e-9)

    source_field: List[float] = []
    source_gates: List[float] = []
    target_raw: List[float] = []
    source_left: List[int] = []
    source_right: List[int] = []
    source_all: List[int] = []

    for idx, ((x, y), (nx, ny), direct_a) in enumerate(zip(pts, normals, direct)):
        depth_frac = _clamp01((surface_y - float(y)) / max_depth)
        lateral = _clamp01(abs(float(nx)))
        top_suppression = _clamp01((depth_frac - 0.035) / 0.12)
        upper_bias = 0.35 + 0.65 * (1.0 - _clamp01(depth_frac * 0.9))
        source_gate = (lateral ** 0.85) * top_suppression * upper_bias
        source_value = max(0.0, float(direct_a) * source_gate)
        source_gates.append(source_gate)
        source_field.append(source_value)
        if source_value > 0.0:
            source_all.append(idx)
            if float(x) < bottom_center:
                source_left.append(idx)
            else:
                source_right.append(idx)

        sidewall_mid = (lateral ** 1.15) * math.exp(-0.5 * ((depth_frac - 0.48) / 0.19) ** 2)
        bottom_depth = math.exp(-0.5 * ((depth_frac - 0.93) / 0.12) ** 2)
        corner_dist = min(abs(float(x) - bottom_left), abs(float(x) - bottom_right))
        corner_scale = max(float(reparam_ds_a) * 10.0, half_bottom * 0.32)
        corner_proximity = math.exp(-0.5 * (corner_dist / corner_scale) ** 2)
        center_dist = abs(float(x) - bottom_center)
        center_proximity = math.exp(-0.5 * (center_dist / max(half_bottom * 0.35, 1e-9)) ** 2)
        bottom_corner = bottom_depth * corner_proximity * (0.45 + 0.55 * lateral)
        bottom_center_target = bottom_depth * center_proximity * 0.10
        target_value = (
            max(0.0, float(bowing_weight)) * sidewall_mid
            + max(0.0, float(microtrench_weight)) * (bottom_corner + bottom_center_target)
        )
        if depth_frac < 0.055 or (depth_frac < 0.12 and float(ny) > 0.65):
            target_value = 0.0
        target_raw.append(max(0.0, target_value))

    if sum(source_field) <= 1e-12 or max(target_raw, default=0.0) <= 1e-12:
        return source_field, [0.0 for _ in pts]

    all_cx, all_cy, all_total = _weighted_centroid(pts, source_field, source_all)
    left_cx, left_cy, left_total = _weighted_centroid(pts, source_field, source_left)
    right_cx, right_cy, right_total = _weighted_centroid(pts, source_field, source_right)
    source_gate_sum = max(sum(source_gates), 1e-12)
    global_source_scale = sum(source_field) / source_gate_sum
    max_direct = max(direct, default=0.0)
    max_reflected = max_direct * min(0.95, 0.10 + strength * 1.35)

    reflected: List[float] = []
    for (x, y), target_value in zip(pts, target_raw):
        if target_value <= 0.0:
            reflected.append(0.0)
            continue
        if float(x) < bottom_center and left_total > 0.0:
            cx, cy, side_total = left_cx, left_cy, left_total
        elif float(x) >= bottom_center and right_total > 0.0:
            cx, cy, side_total = right_cx, right_cy, right_total
        else:
            cx, cy, side_total = all_cx, all_cy, all_total
        side_scale = global_source_scale
        if side_total > 0.0 and all_total > 0.0:
            side_scale *= 0.65 + 0.35 * _clamp01(side_total / all_total * 2.0)
        distance = math.hypot(float(x) - cx, float(y) - cy)
        energy_decay = 1.0 / (1.0 + distance / range_a)
        value = strength * side_scale * target_value * energy_decay
        reflected.append(min(max_reflected, max(0.0, value)))

    smooth_radius = max(0, min(6, int(smoothing_radius_points)))
    if smooth_radius > 0:
        active = [value > 1e-6 for value in target_raw]
        reflected = _smooth_active_scalar_values(reflected, smooth_radius, active)
        reflected = [min(max_reflected, max(0.0, value)) for value in reflected]
    return source_field, reflected


def _field_summary_by_depth(points: Sequence[Point], values: Sequence[float]) -> Dict[str, float]:
    pts = [(float(x), float(y)) for x, y in points]
    vals = [float(v) for v in values]
    if not pts or len(pts) != len(vals):
        return {"top": 0.0, "mid": 0.0, "bottom": 0.0}
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    max_depth = max(surface_y - bottom_y, 1e-9)
    buckets: Dict[str, List[float]] = {"top": [], "mid": [], "bottom": []}
    for (_x, y), value in zip(pts, vals):
        depth_frac = max(0.0, min(1.0, (surface_y - y) / max_depth))
        if depth_frac < 1.0 / 3.0:
            buckets["top"].append(value)
        elif depth_frac < 2.0 / 3.0:
            buckets["mid"].append(value)
        else:
            buckets["bottom"].append(value)
    return {
        key: float(sum(bucket) / len(bucket)) if bucket else 0.0
        for key, bucket in buckets.items()
    }


def _field_summary_for_reflection_zones(
    points: Sequence[Point],
    normals: Sequence[Point],
    values: Sequence[float],
    *,
    reparam_ds_a: float,
) -> Dict[str, float]:
    pts = [(float(x), float(y)) for x, y in points]
    vals = [float(v) for v in values]
    if not pts or len(pts) != len(vals) or len(normals) != len(vals):
        return {
            "top": 0.0,
            "mid_sidewall": 0.0,
            "bottom_center": 0.0,
            "bottom_corner": 0.0,
        }

    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    max_depth = max(surface_y - bottom_y, 1e-9)
    bottom_width, bottom_center_x, bottom_left, bottom_right = _gap_for_point_at_y(
        pts,
        0.0,
        bottom_y + min(max_depth * 0.01, max(float(reparam_ds_a), 1.0)),
    )
    half_bottom = max(float(bottom_width) * 0.5, float(reparam_ds_a), 1e-9)
    corner_limit = max(float(reparam_ds_a) * 12.0, half_bottom * 0.38)

    buckets: Dict[str, List[float]] = {
        "top": [],
        "mid_sidewall": [],
        "bottom_center": [],
        "bottom_corner": [],
    }
    for (x, y), (nx, ny), value in zip(pts, normals, vals):
        depth_frac = _clamp01((surface_y - float(y)) / max_depth)
        lateral = abs(float(nx))
        corner_dist = min(abs(float(x) - bottom_left), abs(float(x) - bottom_right))
        center_dist = abs(float(x) - bottom_center_x)
        if depth_frac < 0.12 and float(ny) > 0.55:
            buckets["top"].append(value)
        if 0.25 <= depth_frac <= 0.70 and lateral > 0.45:
            buckets["mid_sidewall"].append(value)
        if depth_frac >= 0.76 and corner_dist <= corner_limit:
            buckets["bottom_corner"].append(value)
        if depth_frac >= 0.76 and center_dist <= max(float(reparam_ds_a) * 12.0, half_bottom * 0.28):
            buckets["bottom_center"].append(value)

    return {
        key: float(sum(bucket) / len(bucket)) if bucket else 0.0
        for key, bucket in buckets.items()
    }


def _debug_field_payload(
    points: Sequence[Point],
    *,
    deposition_a: float,
    sputter_raw: Sequence[float],
    ion_factors: Sequence[float],
    sputter_effective: Sequence[float],
    reflection_source: Optional[Sequence[float]] = None,
    reflected_ion: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    reflection_source_values = (
        [float(v) for v in reflection_source]
        if reflection_source is not None and len(reflection_source) == len(points)
        else [0.0 for _ in points]
    )
    reflected_values = (
        [max(0.0, float(v)) for v in reflected_ion]
        if reflected_ion is not None and len(reflected_ion) == len(points)
        else [0.0 for _ in points]
    )
    total_etch = [float(direct) + float(reflected) for direct, reflected in zip(sputter_effective, reflected_values)]
    net_growth = [float(deposition_a) - float(v) for v in total_etch]
    return {
        "x": [round(float(x), 6) for x, _y in points],
        "y": [round(float(y), 6) for _x, y in points],
        "depo_field": [round(float(deposition_a), 6) for _ in points],
        "sputter_raw_field": [round(float(v), 6) for v in sputter_raw],
        "ion_factor_field": [round(_clamp01(v), 6) for v in ion_factors],
        "sputter_effective_field": [round(float(v), 6) for v in sputter_effective],
        "direct_sputter_field": [round(float(v), 6) for v in sputter_effective],
        "reflection_source_field": [round(float(v), 6) for v in reflection_source_values],
        "reflected_ion_field": [round(float(v), 6) for v in reflected_values],
        "total_etch_field": [round(float(v), 6) for v in total_etch],
        "net_growth_field": [round(float(v), 6) for v in net_growth],
    }


def _apply_direct_sputter_step(
    state,
    *,
    deposition_a: float,
    sputter_strength_a: float,
    sputter_peak_pct: float,
    sputter_peak_angle_deg: float,
    sputter_width_deg: float,
    sputter_smoothing_a: float,
    reparam_ds_a: float,
    ion_transmission_enabled: bool = False,
    ion_transmission_override: Optional[float] = None,
    ion_transmission_start_depth_pct: float = 0.0,
    ion_transmission_end_depth_pct: float = 100.0,
    ion_transmission_decay_strength_pct: float = 100.0,
    ion_transmission_floor_pct: float = 0.0,
    ion_transmission_curve_power: float = 1.0,
    ion_transmission_aperture_shadow_pct: float = 100.0,
    ion_transmission_lateral_shadow_pct: float = 100.0,
    ion_transmission_edge_shadow_pct: float = 100.0,
    reflected_ion_enabled: bool = False,
    reflected_ion_strength_pct: float = 0.0,
    reflected_ion_bowing_weight: float = 0.75,
    reflected_ion_microtrench_weight: float = 1.0,
    reflected_ion_range_a: float = 1600.0,
) -> Tuple[List[float], List[float], float]:
    grown_solid = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=deposition_a)
    grown_surface = _extract_surface_from_solid(state, grown_solid, state.surface.points)
    grown_surface = equal_arc_resample(grown_surface, reparam_ds_a)
    smooth_radius = max(0, int(round(float(sputter_smoothing_a) / max(float(reparam_ds_a), 1e-9))))
    raw_normals = vertex_air_normals(grown_surface)
    normals = _smooth_unit_vectors(raw_normals, smooth_radius)
    angles = _incident_angles_from_normals_deg(raw_normals)
    responses = [
        direct_sputter_angle_response(
            angle,
            peak_angle_deg=sputter_peak_angle_deg,
            width_deg=sputter_width_deg,
            peak_pct=sputter_peak_pct,
        )
        for angle in angles
    ]
    response_active_floor = max(1e-4, max(responses, default=0.0) * 0.02)
    active = [response >= response_active_floor for response in responses]
    etch_values = _smooth_active_scalar_values(
        [float(sputter_strength_a) * float(response) for response in responses],
        smooth_radius,
        active,
    )
    ion_factors = compute_ion_transmission_factors(
        grown_surface,
        enabled=ion_transmission_enabled,
        override=ion_transmission_override,
        start_depth_pct=ion_transmission_start_depth_pct,
        end_depth_pct=ion_transmission_end_depth_pct,
        decay_strength_pct=ion_transmission_decay_strength_pct,
        floor_pct=ion_transmission_floor_pct,
        curve_power=ion_transmission_curve_power,
        aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
        lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
        edge_shadow_pct=ion_transmission_edge_shadow_pct,
        reparam_ds_a=reparam_ds_a,
    )
    if len(ion_factors) != len(etch_values):
        ion_factors = [1.0 for _ in etch_values]
    effective_etch_values = [
        float(etch_a) * _clamp01(float(factor))
        for etch_a, factor in zip(etch_values, ion_factors)
    ]
    reflected_active = bool(reflected_ion_enabled) and float(reflected_ion_strength_pct) > 0.0
    if reflected_active:
        reflection_source_values, reflected_ion_values = compute_reflected_ion_fields(
            grown_surface,
            normals,
            effective_etch_values,
            strength_pct=reflected_ion_strength_pct,
            bowing_weight=reflected_ion_bowing_weight,
            microtrench_weight=reflected_ion_microtrench_weight,
            reflection_range_a=reflected_ion_range_a,
            reparam_ds_a=reparam_ds_a,
            smoothing_radius_points=max(0, smooth_radius // 2),
        )
    else:
        reflection_source_values = [0.0 for _ in effective_etch_values]
        reflected_ion_values = [0.0 for _ in effective_etch_values]
    total_etch_values = [
        max(0.0, float(direct_a) + float(reflected_a))
        for direct_a, reflected_a in zip(effective_etch_values, reflected_ion_values)
    ]

    max_etch_a = max(float(deposition_a) * 2.0, float(reparam_ds_a) * 4.0)
    proposed: List[Point] = []
    has_negative_net = False
    for idx, (x, y) in enumerate(grown_surface):
        nx, ny = normals[idx] if idx < len(normals) else (0.0, 1.0)
        etch_a = min(max_etch_a, max(0.0, float(total_etch_values[idx])))
        net_from_previous = float(deposition_a) - etch_a
        if net_from_previous < 0.0:
            has_negative_net = True
        x2 = float(x - etch_a * nx)
        y2 = float(y - etch_a * ny)
        if idx == 0 or idx == (len(grown_surface) - 1):
            x2 = float(x)
        proposed.append((x2, y2))

    clean_surface, clean_solid = TopologyCleanup().cleanup(
        proposed,
        state,
        solid_ref_paths_i=grown_solid,
        solid_merge_mode=("candidate" if has_negative_net else "union"),
    )
    state.surface.points = equal_arc_resample(clean_surface, reparam_ds_a)
    if clean_solid:
        state.solid_paths_i = clean_solid
    state.meta["direct_sputter_debug_fields_last"] = _debug_field_payload(
        grown_surface,
        deposition_a=deposition_a,
        sputter_raw=etch_values,
        ion_factors=ion_factors,
        sputter_effective=effective_etch_values,
        reflection_source=reflection_source_values,
        reflected_ion=reflected_ion_values,
    )
    state.meta["direct_sputter_debug_summary_last"] = {
        "ion_factor": _field_summary_by_depth(grown_surface, ion_factors),
        "sputter_raw": _field_summary_by_depth(grown_surface, etch_values),
        "sputter_effective": _field_summary_by_depth(grown_surface, effective_etch_values),
        "reflection_source": _field_summary_for_reflection_zones(
            grown_surface,
            normals,
            reflection_source_values,
            reparam_ds_a=reparam_ds_a,
        ),
        "reflected_ion": _field_summary_for_reflection_zones(
            grown_surface,
            normals,
            reflected_ion_values,
            reparam_ds_a=reparam_ds_a,
        ),
        "total_etch": _field_summary_by_depth(grown_surface, total_etch_values),
        "net_growth": _field_summary_by_depth(
            grown_surface,
            [float(deposition_a) - float(v) for v in total_etch_values],
        ),
    }
    state.meta["reflected_ion_active_last"] = bool(reflected_active and max(reflected_ion_values, default=0.0) > 0.0)
    state.meta["reflected_ion_total_last"] = float(sum(reflected_ion_values))
    state.meta["direct_sputter_total_last"] = float(sum(effective_etch_values))
    return angles, responses, max_etch_a


def _clone_simulation_state(state: SimulationState) -> SimulationState:
    return SimulationState(
        surface=Surface(
            points=[(float(x), float(y)) for x, y in state.surface.points],
            direction=state.surface.direction,
            wall_tags=list(state.surface.wall_tags),
        ),
        scale=int(state.scale),
        x_left_i=int(state.x_left_i),
        x_right_i=int(state.x_right_i),
        y_top_i=int(state.y_top_i),
        y_bot_i=int(state.y_bot_i),
        roi_path_i=list(state.roi_path_i),
        solid_paths_i=[list(path) for path in state.solid_paths_i],
        meta=dict(state.meta),
    )


def _model6_arc_coordinates(points: Sequence[Point]) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return []
    coords = [0.0]
    for a, b in zip(pts, pts[1:]):
        coords.append(coords[-1] + math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1])))
    return coords


def _model6_reflection_axis(normal: Point) -> Point:
    nx, ny = float(normal[0]), float(normal[1])
    length = math.hypot(nx, ny)
    if length <= 1e-12:
        nx, ny = 0.0, 1.0
    else:
        nx, ny = nx / length, ny / length
    incoming = (0.0, -1.0)
    dot_in = (incoming[0] * nx) + (incoming[1] * ny)
    rx = incoming[0] - (2.0 * dot_in * nx)
    ry = incoming[1] - (2.0 * dot_in * ny)
    rlen = math.hypot(rx, ry)
    if rlen <= 1e-12:
        return (nx, ny)
    return (rx / rlen, ry / rlen)


def _model6_blended_emission_axis(normal: Point, specular_bias: float) -> Point:
    nx, ny = float(normal[0]), float(normal[1])
    nlen = math.hypot(nx, ny)
    if nlen <= 1e-12:
        nx, ny = 0.0, 1.0
    else:
        nx, ny = nx / nlen, ny / nlen
    rx, ry = _model6_reflection_axis((nx, ny))
    beta = max(-1.0, min(1.0, float(specular_bias)))
    ax = ((1.0 - beta) * nx) + (beta * rx)
    ay = ((1.0 - beta) * ny) + (beta * ry)
    alen = math.hypot(ax, ay)
    if alen <= 1e-12:
        return (rx, ry)
    return (ax / alen, ay / alen)


def _model6_ray_segment_intersection(
    origin: Point,
    direction: Point,
    a: Point,
    b: Point,
    *,
    eps: float = 1e-9,
) -> Optional[Tuple[float, float]]:
    ox, oy = float(origin[0]), float(origin[1])
    dx, dy = float(direction[0]), float(direction[1])
    ax, ay = float(a[0]), float(a[1])
    sx = float(b[0]) - ax
    sy = float(b[1]) - ay
    denom = (dx * sy) - (dy * sx)
    if abs(denom) <= eps:
        return None
    qx = ax - ox
    qy = ay - oy
    t = ((qx * sy) - (qy * sx)) / denom
    u = ((qx * dy) - (qy * dx)) / denom
    if t <= eps or u < -1e-9 or u > 1.0 + 1e-9:
        return None
    return float(t), float(max(0.0, min(1.0, u)))


def _model6_first_opposite_reflection_hit(
    points: Sequence[Point],
    normals: Sequence[Point],
    *,
    source_index: int,
    direction: Point,
    center_x: float,
    neighbor_exclusion: int,
    max_distance_a: float,
) -> Optional[Tuple[int, float, float, Point, Point]]:
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < 2 or source_index < 0 or source_index >= len(pts):
        return None
    sx, sy = pts[source_index]
    source_side = -1 if sx < center_x else 1
    best: Optional[Tuple[int, float, float, Point, Point]] = None
    max_dist = max(1e-9, float(max_distance_a))
    skip = max(0, int(neighbor_exclusion))
    for seg_idx in range(len(pts) - 1):
        if abs(seg_idx - source_index) <= skip or abs((seg_idx + 1) - source_index) <= skip:
            continue
        hit = _model6_ray_segment_intersection(pts[source_index], direction, pts[seg_idx], pts[seg_idx + 1])
        if hit is None:
            continue
        dist, u = hit
        if dist <= 1e-9 or dist > max_dist:
            continue
        hx = pts[seg_idx][0] + (u * (pts[seg_idx + 1][0] - pts[seg_idx][0]))
        hy = pts[seg_idx][1] + (u * (pts[seg_idx + 1][1] - pts[seg_idx][1]))
        hit_side = -1 if hx < center_x else 1
        if hit_side == source_side:
            continue
        if best is not None and dist >= best[2]:
            continue
        n0 = normals[seg_idx] if seg_idx < len(normals) else (0.0, 1.0)
        n1 = normals[seg_idx + 1] if (seg_idx + 1) < len(normals) else n0
        nx = ((1.0 - u) * float(n0[0])) + (u * float(n1[0]))
        ny = ((1.0 - u) * float(n0[1])) + (u * float(n1[1]))
        nlen = math.hypot(nx, ny)
        hit_normal = (nx / nlen, ny / nlen) if nlen > 1e-12 else (0.0, 1.0)
        if abs(float(hit_normal[0])) < 0.20:
            continue
        best = (int(seg_idx), float(u), float(dist), (float(hx), float(hy)), hit_normal)
    return best


def _apply_model6_reflection_gaussian_redepo_step(
    state: SimulationState,
    *,
    deposition_a: float,
    sputter_strength_a: float,
    sputter_peak_pct: float,
    sputter_peak_angle_deg: float,
    sputter_width_deg: float,
    sputter_smoothing_a: float,
    reparam_ds_a: float,
    ion_transmission_enabled: bool = False,
    ion_transmission_override: Optional[float] = None,
    ion_transmission_start_depth_pct: float = 0.0,
    ion_transmission_end_depth_pct: float = 100.0,
    ion_transmission_decay_strength_pct: float = 100.0,
    ion_transmission_floor_pct: float = 0.0,
    ion_transmission_curve_power: float = 1.0,
    ion_transmission_aperture_shadow_pct: float = 100.0,
    ion_transmission_lateral_shadow_pct: float = 100.0,
    ion_transmission_edge_shadow_pct: float = 100.0,
    redepo_efficiency_pct: float = 0.0,
    angular_spread_deg: float = 22.0,
    specular_bias_pct: float = 25.0,
    redepo_neighbor_exclusion: int = 2,
    redepo_max_distance_a: float = 1800.0,
) -> Tuple[List[float], List[float], float]:
    source_state = _clone_simulation_state(state)
    angles, responses, etch_clamp_a = _apply_direct_sputter_step(
        source_state,
        deposition_a=deposition_a,
        sputter_strength_a=sputter_strength_a,
        sputter_peak_pct=sputter_peak_pct,
        sputter_peak_angle_deg=sputter_peak_angle_deg,
        sputter_width_deg=sputter_width_deg,
        sputter_smoothing_a=sputter_smoothing_a,
        reparam_ds_a=reparam_ds_a,
        ion_transmission_enabled=ion_transmission_enabled,
        ion_transmission_override=ion_transmission_override,
        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
        ion_transmission_floor_pct=ion_transmission_floor_pct,
        ion_transmission_curve_power=ion_transmission_curve_power,
        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
        reflected_ion_enabled=False,
        reflected_ion_strength_pct=0.0,
    )
    source_fields = dict(source_state.meta.get("direct_sputter_debug_fields_last", {}))

    grown_solid = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=deposition_a)
    grown_surface = _extract_surface_from_solid(state, grown_solid, state.surface.points)
    grown_surface = equal_arc_resample(grown_surface, reparam_ds_a)
    if not grown_surface:
        state.surface.points = [(float(x), float(y)) for x, y in source_state.surface.points]
        state.solid_paths_i = [list(path) for path in source_state.solid_paths_i]
        state.meta.update(source_state.meta)
        return angles, responses, etch_clamp_a

    dh_source = [max(0.0, float(v)) for v in source_fields.get("sputter_effective_field", [])]
    if len(dh_source) != len(grown_surface):
        dh_source = [0.0 for _ in grown_surface]
    dh_etch = [min(float(etch_clamp_a), max(0.0, value)) for value in dh_source]

    areas = [max(1e-9, float(v)) for v in compute_arc_weights(grown_surface)]
    smooth_radius = max(0, int(round(float(sputter_smoothing_a) / max(float(reparam_ds_a), 1e-9))))
    normals = _smooth_unit_vectors(vertex_air_normals(grown_surface), smooth_radius)
    arc_s = _model6_arc_coordinates(grown_surface)
    xs = [float(x) for x, _y in grown_surface]
    center_x = (min(xs) + max(xs)) * 0.5 if xs else 0.0

    removed_mass = [max(0.0, float(dh)) * area for dh, area in zip(dh_etch, areas)]
    total_removed_mass = float(sum(removed_mass))
    efficiency = max(0.0, min(100.0, float(redepo_efficiency_pct))) / 100.0
    specular_bias = max(-100.0, min(100.0, float(specular_bias_pct))) / 100.0
    angular_spread = max(1.0, min(80.0, float(angular_spread_deg)))
    spread_rad = math.radians(angular_spread)
    max_distance = max(1.0, float(redepo_max_distance_a))
    source_cutoff = max(1e-12, total_removed_mass * 1e-9)

    center_hit_mass = [0.0 for _ in grown_surface]
    footprint_mass = [0.0 for _ in grown_surface]
    transport_lines: List[TransportLineSample] = []
    active_source_count = 0
    active_hit_count = 0
    hit_source_removed_mass = 0.0
    escaped_mass = 0.0
    raw_hit_mass = 0.0
    for idx, mass in enumerate(removed_mass):
        if mass <= source_cutoff:
            continue
        active_source_count += 1
        direction = _model6_blended_emission_axis(
            normals[idx] if idx < len(normals) else (0.0, 1.0),
            specular_bias,
        )
        hit = _model6_first_opposite_reflection_hit(
            grown_surface,
            normals,
            source_index=idx,
            direction=direction,
            center_x=center_x,
            neighbor_exclusion=redepo_neighbor_exclusion,
            max_distance_a=max_distance,
        )
        if hit is None:
            escaped_mass += float(mass)
            continue
        seg_idx, u, distance, hit_point, hit_normal = hit
        if distance <= 1e-9:
            escaped_mass += float(mass)
            continue
        receive = max(
            0.0,
            -(
                float(hit_normal[0]) * float(direction[0])
                + float(hit_normal[1]) * float(direction[1])
            ),
        )
        if receive <= 1e-9:
            escaped_mass += float(mass)
            continue
        distance_soft = 1.0 / math.sqrt(max(1.0, distance / max(float(reparam_ds_a), 1e-9)))
        hit_mass = float(mass) * receive * distance_soft
        if hit_mass <= 0.0:
            escaped_mass += float(mass)
            continue
        active_hit_count += 1
        hit_source_removed_mass += float(mass)
        raw_hit_mass += hit_mass
        left_weight = max(0.0, min(1.0, 1.0 - float(u)))
        right_weight = max(0.0, min(1.0, float(u)))
        if 0 <= seg_idx < len(center_hit_mass):
            center_hit_mass[seg_idx] += hit_mass * left_weight
        if 0 <= seg_idx + 1 < len(center_hit_mass):
            center_hit_mass[seg_idx + 1] += hit_mass * right_weight

        hit_s = (
            ((1.0 - float(u)) * float(arc_s[seg_idx])) + (float(u) * float(arc_s[seg_idx + 1]))
            if arc_s and 0 <= seg_idx < len(arc_s) - 1
            else 0.0
        )
        hit_side = -1 if float(hit_point[0]) < center_x else 1
        footprint_sigma = max(
            float(reparam_ds_a) * 1.5,
            min(max_distance, float(distance) * math.tan(spread_rad)),
        )
        footprint_radius = max(float(reparam_ds_a) * 2.0, footprint_sigma * 3.0)
        target_weights: List[Tuple[int, float]] = []
        for target_idx, (tx, _ty) in enumerate(grown_surface):
            if target_idx >= len(arc_s):
                continue
            if (-1 if float(tx) < center_x else 1) != hit_side:
                continue
            if target_idx < len(normals) and abs(float(normals[target_idx][0])) < 0.12:
                continue
            ds = abs(float(arc_s[target_idx]) - hit_s)
            if ds > footprint_radius:
                continue
            weight = areas[target_idx] * math.exp(-0.5 * (ds / max(footprint_sigma, 1e-9)) ** 2)
            if weight > 0.0:
                target_weights.append((target_idx, weight))
        if not target_weights:
            if 0 <= seg_idx < len(grown_surface):
                target_weights.append((seg_idx, max(1e-9, left_weight)))
            if 0 <= seg_idx + 1 < len(grown_surface):
                target_weights.append((seg_idx + 1, max(1e-9, right_weight)))
        weight_sum = float(sum(weight for _target_idx, weight in target_weights))
        if weight_sum > 1e-12:
            for target_idx, weight in target_weights:
                footprint_mass[target_idx] += hit_mass * (weight / weight_sum)
        sx, sy = grown_surface[idx]
        hx, hy = hit_point
        transport_lines.append((float(sx), float(sy), float(hx), float(hy), float(hit_mass)))

    target_total_mass = efficiency * hit_source_removed_mass if raw_hit_mass > 1e-12 else 0.0

    center_hit_sum = float(sum(center_hit_mass))
    footprint_sum = float(sum(footprint_mass))
    redepo_mass = (
        [(value / footprint_sum) * target_total_mass for value in footprint_mass]
        if footprint_sum > 1e-12 and target_total_mass > 0.0
        else [0.0 for _ in grown_surface]
    )
    peak_idx = max(range(len(redepo_mass)), key=lambda i: redepo_mass[i]) if any(v > 0.0 for v in redepo_mass) else -1
    gaussian_mass = (
        [(value / footprint_sum) * target_total_mass for value in footprint_mass]
        if footprint_sum > 1e-12 and target_total_mass > 0.0
        else [0.0 for _ in grown_surface]
    )
    ballistic_norm = (
        [(value / center_hit_sum) * target_total_mass for value in center_hit_mass]
        if center_hit_sum > 1e-12 and target_total_mass > 0.0
        else [0.0 for _ in grown_surface]
    )
    redepo_sum = float(sum(redepo_mass))
    if redepo_sum > target_total_mass + 1e-12 and redepo_sum > 0.0:
        scale = target_total_mass / redepo_sum
        redepo_mass = [value * scale for value in redepo_mass]
        redepo_sum = float(sum(redepo_mass))

    dh_redepo = [
        max(0.0, float(mass)) / max(1e-9, float(area))
        for mass, area in zip(redepo_mass, areas)
    ]
    profile_delta = [
        max(0.0, float(redepo)) - max(0.0, float(etch))
        for redepo, etch in zip(dh_redepo, dh_etch)
    ]

    proposed: List[Point] = []
    has_negative_net = False
    for idx, (x, y) in enumerate(grown_surface):
        nx, ny = normals[idx] if idx < len(normals) else (0.0, 1.0)
        move_delta = float(profile_delta[idx]) if idx < len(profile_delta) else 0.0
        if float(deposition_a) + move_delta < 0.0:
            has_negative_net = True
        x2 = float(x + move_delta * nx)
        y2 = float(y + move_delta * ny)
        if idx == 0 or idx == (len(grown_surface) - 1):
            x2 = float(x)
        proposed.append((x2, y2))

    clean_surface, clean_solid = TopologyCleanup().cleanup(
        proposed,
        state,
        solid_ref_paths_i=grown_solid,
        solid_merge_mode=("candidate" if has_negative_net else "union"),
    )
    state.surface.points = equal_arc_resample(clean_surface, reparam_ds_a)
    if clean_solid:
        state.solid_paths_i = clean_solid

    total_etch = [max(0.0, etch - redepo) for etch, redepo in zip(dh_etch, dh_redepo)]
    fields = dict(source_fields)
    fields["x"] = [round(float(x), 6) for x, _y in grown_surface]
    fields["y"] = [round(float(y), 6) for _x, y in grown_surface]
    fields["depo_field"] = [round(float(deposition_a), 6) for _ in grown_surface]
    fields["sputter_effective_field"] = [round(float(v), 6) for v in dh_etch]
    fields["direct_sputter_field"] = [round(float(v), 6) for v in dh_etch]
    fields["redepo_source_etch_field"] = [round(float(v), 6) for v in dh_etch]
    fields["removed_mass_field"] = [round(float(v), 6) for v in removed_mass]
    fields["reflection_hit_mass_field"] = [round(float(v), 6) for v in center_hit_mass]
    fields["source_lobe_redepo_mass_field"] = [round(float(v), 6) for v in footprint_mass]
    fields["gaussian_redepo_mass_field"] = [round(float(v), 6) for v in gaussian_mass]
    fields["ballistic_redepo_mass_field"] = [round(float(v), 6) for v in ballistic_norm]
    fields["redepo_mass_field"] = [round(float(v), 6) for v in redepo_mass]
    fields["gaussian_redepo_field"] = [
        round(float(mass) / max(1e-9, float(area)), 6)
        for mass, area in zip(gaussian_mass, areas)
    ]
    fields["ballistic_redepo_field"] = [
        round(float(mass) / max(1e-9, float(area)), 6)
        for mass, area in zip(ballistic_norm, areas)
    ]
    fields["redepo_field"] = [round(float(v), 6) for v in dh_redepo]
    fields["profile_delta_field"] = [round(float(v), 6) for v in profile_delta]
    fields["total_etch_field"] = [round(float(v), 6) for v in total_etch]
    fields["net_growth_field"] = [
        round(float(deposition_a) + float(delta), 6)
        for delta in profile_delta
    ]
    fields["reflection_transport_lines"] = [
        [round(float(x1), 6), round(float(y1), 6), round(float(x2), 6), round(float(y2), 6), round(float(v), 6)]
        for x1, y1, x2, y2, v in sorted(transport_lines, key=lambda item: item[4], reverse=True)[:64]
    ]

    peak_point = grown_surface[peak_idx] if 0 <= peak_idx < len(grown_surface) else (0.0, 0.0)
    active_target_count = sum(1 for value in redepo_mass if value > max(1e-12, target_total_mass * 1e-9))
    reflection_summary = {
        "total_removed_mass": float(total_removed_mass),
        "total_redepo_mass": float(redepo_sum),
        "redepo_capture_ratio": float(redepo_sum / total_removed_mass) if total_removed_mass > 1e-12 else 0.0,
        "target_total_mass": float(target_total_mass),
        "efficiency": float(efficiency),
        "angular_spread_deg": float(angular_spread),
        "specular_bias_pct": float(specular_bias * 100.0),
        "hit_source_removed_mass": float(hit_source_removed_mass),
        "active_source_count": int(active_source_count),
        "active_hit_count": int(active_hit_count),
        "active_target_count": int(active_target_count),
        "peak_target_index": int(peak_idx),
        "peak_target_x": float(peak_point[0]),
        "peak_target_y": float(peak_point[1]),
        "escaped_mass": float(escaped_mass),
        "raw_hit_mass": float(raw_hit_mass),
        "transport_line_count": int(len(transport_lines)),
    }
    summary = dict(source_state.meta.get("direct_sputter_debug_summary_last", {}))
    summary["reflection_redepo"] = dict(reflection_summary)
    summary["total_etch"] = _field_summary_by_depth(grown_surface, total_etch)
    summary["net_growth"] = _field_summary_by_depth(
        grown_surface,
        [float(deposition_a) + float(delta) for delta in profile_delta],
    )

    state.meta["direct_sputter_debug_fields_last"] = fields
    state.meta["direct_sputter_debug_summary_last"] = summary
    state.meta["model6_reflection_redepo_debug_fields_last"] = fields
    state.meta["model6_reflection_redepo_debug_summary_last"] = summary
    state.meta["model6_reflection_redepo_total_removed_mass_last"] = float(total_removed_mass)
    state.meta["model6_reflection_redepo_total_mass_last"] = float(redepo_sum)
    state.meta["model6_reflection_redepo_active_source_count_last"] = int(active_source_count)
    state.meta["model6_reflection_redepo_active_target_count_last"] = int(active_target_count)
    state.meta["model6_reflection_redepo_transport_model_last"] = "normal_specular_lobe_los"
    state.meta["direct_sputter_total_last"] = float(sum(dh_etch))
    return angles, responses, etch_clamp_a


def _redepo_source_model_key(_value: str) -> str:
    return "model2"


def _apply_model4_redeposition_step(
    state: SimulationState,
    *,
    deposition_a: float,
    sputter_strength_a: float,
    sputter_peak_pct: float,
    sputter_peak_angle_deg: float,
    sputter_width_deg: float,
    sputter_smoothing_a: float,
    reparam_ds_a: float,
    redepo_source_model: str,
    redepo_efficiency_pct: float,
    redepo_emit_power: float,
    redepo_distance_power: float,
    redepo_neighbor_exclusion: int,
    redepo_max_distance_a: float,
    redepo_soft_los_radius_points: int,
    redepo_transport_model: str,
    redepo_ray_count: int,
    redepo_footprint_sigma_a: float,
    redepo_footprint_radius_sigma: float,
    ion_transmission_start_depth_pct: float = 0.0,
    ion_transmission_end_depth_pct: float = 100.0,
    ion_transmission_decay_strength_pct: float = 100.0,
    ion_transmission_floor_pct: float = 0.0,
    ion_transmission_curve_power: float = 1.0,
    ion_transmission_aperture_shadow_pct: float = 100.0,
    ion_transmission_lateral_shadow_pct: float = 100.0,
    ion_transmission_edge_shadow_pct: float = 100.0,
) -> Tuple[List[float], List[float], float]:
    source_model = _redepo_source_model_key(redepo_source_model)
    source_state = _clone_simulation_state(state)
    angles, responses, etch_clamp_a = _apply_direct_sputter_step(
        source_state,
        deposition_a=deposition_a,
        sputter_strength_a=sputter_strength_a,
        sputter_peak_pct=sputter_peak_pct,
        sputter_peak_angle_deg=sputter_peak_angle_deg,
        sputter_width_deg=sputter_width_deg,
        sputter_smoothing_a=sputter_smoothing_a,
        reparam_ds_a=reparam_ds_a,
        ion_transmission_enabled=True,
        ion_transmission_override=None,
        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
        ion_transmission_floor_pct=ion_transmission_floor_pct,
        ion_transmission_curve_power=ion_transmission_curve_power,
        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
        reflected_ion_enabled=False,
        reflected_ion_strength_pct=0.0,
    )
    fields = dict(source_state.meta.get("direct_sputter_debug_fields_last", {}))
    grown_solid = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=deposition_a)
    grown_surface = _extract_surface_from_solid(state, grown_solid, state.surface.points)
    grown_surface = equal_arc_resample(grown_surface, reparam_ds_a)
    if not grown_surface:
        state.surface.points = [(float(x), float(y)) for x, y in source_state.surface.points]
        state.solid_paths_i = [list(path) for path in source_state.solid_paths_i]
        state.meta.update(source_state.meta)
        return angles, responses, etch_clamp_a

    dh_source = [max(0.0, float(v)) for v in fields.get("sputter_effective_field", [])]
    if len(dh_source) != len(grown_surface):
        dh_source = [0.0 for _ in grown_surface]
    dh_etch = [
        min(float(etch_clamp_a), max(0.0, value))
        for value in dh_source
    ]

    smooth_radius = max(0, int(round(float(sputter_smoothing_a) / max(float(reparam_ds_a), 1e-9))))
    normals = _smooth_unit_vectors(vertex_air_normals(grown_surface), smooth_radius)
    redepo = compute_redeposition(
        grown_surface,
        normals,
        dh_etch,
        Model4RedepositionParams(
            redepo_efficiency=max(0.0, min(100.0, float(redepo_efficiency_pct))) / 100.0,
            emit_power=max(0.0, float(redepo_emit_power)),
            distance_power=max(0.0, float(redepo_distance_power)),
            neighbor_exclusion=max(0, int(redepo_neighbor_exclusion)),
            max_redepo_distance=max(0.0, float(redepo_max_distance_a)),
            lateral_spread_a=max(0.0, float(redepo_footprint_sigma_a)),
            transport_model=str(redepo_transport_model or "gapsim_binned_lobe_los"),
            ray_count=max(3, int(redepo_ray_count)),
            footprint_radius_sigma=max(1.0, float(redepo_footprint_radius_sigma)),
            soft_los_radius_points=max(0, int(redepo_soft_los_radius_points)),
        ),
    )
    dh_redepo = redepo.dh_redepo if len(redepo.dh_redepo) == len(grown_surface) else [0.0 for _ in grown_surface]
    raw_profile_delta = [
        max(0.0, float(dh_redepo[idx])) - max(0.0, float(dh_etch[idx]))
        for idx in range(len(grown_surface))
    ]
    profile_smooth_radius = max(0, min(24, smooth_radius))
    if profile_smooth_radius > 0 and len(raw_profile_delta) == len(grown_surface):
        top_y = max((float(y) for _x, y in grown_surface), default=0.0)
        active = [
            (float(y) < top_y - max(1e-6, float(reparam_ds_a) * 0.5))
            or abs(float(normals[idx][0])) >= 0.18
            for idx, (_x, y) in enumerate(grown_surface)
        ]
        profile_delta = _smooth_active_scalar_values(raw_profile_delta, profile_smooth_radius, active)
    else:
        profile_delta = list(raw_profile_delta)
    proposed: List[Point] = []
    has_negative_net = False
    for idx, (x, y) in enumerate(grown_surface):
        nx, ny = normals[idx] if idx < len(normals) else (0.0, 1.0)
        etch_a = max(0.0, float(dh_etch[idx]))
        redepo_a = max(0.0, float(dh_redepo[idx]))
        move_delta = float(profile_delta[idx]) if idx < len(profile_delta) else (redepo_a - etch_a)
        net_from_previous = float(deposition_a) + move_delta
        if net_from_previous < 0.0:
            has_negative_net = True
        x2 = float(x + move_delta * nx)
        y2 = float(y + move_delta * ny)
        if idx == 0 or idx == (len(grown_surface) - 1):
            x2 = float(x)
        proposed.append((x2, y2))

    clean_surface, clean_solid = TopologyCleanup().cleanup(
        proposed,
        state,
        solid_ref_paths_i=grown_solid,
        solid_merge_mode=("candidate" if has_negative_net else "union"),
    )
    state.surface.points = equal_arc_resample(clean_surface, reparam_ds_a)
    if clean_solid:
        state.solid_paths_i = clean_solid

    total_etch = [max(0.0, etch - redepo) for etch, redepo in zip(dh_etch, dh_redepo)]
    fields["x"] = [round(float(x), 6) for x, _y in grown_surface]
    fields["y"] = [round(float(y), 6) for _x, y in grown_surface]
    fields["sputter_effective_field"] = [round(float(v), 6) for v in dh_etch]
    fields["direct_sputter_field"] = [round(float(v), 6) for v in dh_etch]
    fields["redepo_field"] = [round(float(v), 6) for v in dh_redepo]
    fields["redepo_mass_field"] = list(redepo.debug_fields.get("redepo_mass_field", []))
    fields["removed_mass_field"] = list(redepo.debug_fields.get("removed_mass_field", []))
    fields["redepo_source_etch_field"] = list(redepo.debug_fields.get("redepo_source_etch_field", []))
    fields["redepo_source_mass_field"] = list(redepo.debug_fields.get("redepo_source_mass_field", []))
    fields["profile_delta_field"] = [round(float(v), 6) for v in profile_delta]
    fields["total_etch_field"] = [round(float(v), 6) for v in total_etch]
    fields["net_growth_field"] = [
        round(float(deposition_a) + float(delta), 6)
        for delta in profile_delta
    ]
    summary = dict(source_state.meta.get("direct_sputter_debug_summary_last", {}))
    summary["redepo"] = dict(redepo.debug_summary)
    summary["redepo"]["profile_smooth_radius_points"] = int(profile_smooth_radius)
    summary["total_etch"] = _field_summary_by_depth(grown_surface, total_etch)
    summary["net_growth"] = _field_summary_by_depth(
        grown_surface,
        [float(deposition_a) + float(delta) for delta in profile_delta],
    )
    state.meta["direct_sputter_debug_fields_last"] = fields
    state.meta["direct_sputter_debug_summary_last"] = summary
    state.meta["model4_redepo_debug_fields_last"] = fields
    state.meta["model4_redepo_debug_summary_last"] = summary
    state.meta["model4_redepo_source_model_last"] = source_model
    state.meta["model4_redepo_total_removed_mass_last"] = float(redepo.debug_summary.get("total_removed_mass", 0.0))
    state.meta["model4_redepo_total_mass_last"] = float(redepo.debug_summary.get("total_redepo_mass", 0.0))
    state.meta["model4_redepo_active_source_count_last"] = int(redepo.debug_summary.get("active_source_count", 0))
    state.meta["model4_redepo_transport_model_last"] = str(redepo.debug_summary.get("transport_model", redepo_transport_model))
    state.meta["direct_sputter_total_last"] = float(sum(dh_etch))
    return angles, responses, etch_clamp_a


def _normal_change_field(normals: Sequence[Point]) -> List[float]:
    values = [(float(nx), float(ny)) for nx, ny in normals]
    if not values:
        return []
    out: List[float] = []
    for idx in range(len(values)):
        left = values[max(0, idx - 1)]
        right = values[min(len(values) - 1, idx + 1)]
        out.append(math.hypot(right[0] - left[0], right[1] - left[1]))
    return out


def _profile_diagonal_a(points: Sequence[Point]) -> float:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return 0.0
    xs = [x for x, _y in pts]
    ys = [y for _x, y in pts]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _closure_transport_horizon_a(points: Sequence[Point], footprint_width_a: float) -> float:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return max(600.0, float(footprint_width_a) * 6.0)
    xs = [float(x) for x, _y in pts]
    ys = [float(y) for _x, y in pts]
    center_x = 0.5 * (min(xs) + max(xs))
    surface_y = max(ys)
    bottom_y = min(ys)
    depth_span = max(surface_y - bottom_y, 1e-9)
    probe_depth = max(40.0, min(300.0, depth_span * 0.02))
    opening_width, _center, _left, _right = _gap_for_point_at_y(pts, center_x, surface_y - probe_depth)
    local_range = (0.70 * max(1.0, float(opening_width))) + (2.4 * max(0.0, float(footprint_width_a)))
    return max(600.0, min(_profile_diagonal_a(pts), local_range))


def _lf_overhang_side_indices(points: Sequence[Point], center_x: float, side: int) -> List[int]:
    return [
        idx
        for idx, (x, _y) in enumerate(points)
        if (float(x) - float(center_x)) * float(side) >= 0.0
    ]


def _lf_overhang_toe_scores(
    points: Sequence[Point],
    normals: Sequence[Point],
    ion_factors: Sequence[float],
    *,
    center_x: float,
) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n == 0:
        return []
    if len(normals) != n or len(ion_factors) != n:
        return [0.0 for _ in pts]
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, 1e-9)
    depth_frac = [_clamp01((surface_y - y) / depth_span) for _x, y in pts]
    normal_change = _normal_change_field(normals)
    scores = [0.0 for _ in pts]
    for side in (-1, 1):
        side_indices = _lf_overhang_side_indices(pts, center_x, side)
        ordered = sorted(side_indices, key=lambda idx: depth_frac[idx])
        previous_visibility = 1.0
        for idx in ordered:
            nx, _ny = normals[idx]
            depth = depth_frac[idx]
            lateral = abs(float(nx))
            if depth < 0.025 or depth > 0.72 or lateral < 0.10:
                previous_visibility = max(previous_visibility, _clamp01(float(ion_factors[idx])))
                continue
            visibility = _clamp01(float(ion_factors[idx]))
            visibility_drop = max(0.0, previous_visibility - visibility)
            kink = max(0.0, float(normal_change[idx]))
            upper_bias = 1.0 - _clamp01(max(0.0, depth - 0.12) / 0.58)
            scores[idx] = kink * (0.20 + 0.80 * visibility_drop) * (0.30 + 0.70 * lateral) * (0.50 + 0.50 * upper_bias)
            previous_visibility = max(visibility, previous_visibility * 0.96)
    return scores


def _select_lf_overhang_toe_index(
    points: Sequence[Point],
    normals: Sequence[Point],
    scores: Sequence[float],
    *,
    center_x: float,
    side: int,
) -> Optional[int]:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return None
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, 1e-9)
    side_indices = _lf_overhang_side_indices(pts, center_x, side)
    candidates: List[Tuple[float, int]] = []
    for idx in side_indices:
        depth = _clamp01((surface_y - pts[idx][1]) / depth_span)
        if depth < 0.025 or depth > 0.72:
            continue
        lateral = abs(float(normals[idx][0])) if idx < len(normals) else 0.0
        if lateral < 0.08:
            continue
        score = float(scores[idx]) if idx < len(scores) else 0.0
        candidates.append((score, idx))
    if not candidates:
        return None
    best_score, best_idx = max(candidates, key=lambda item: item[0])
    if best_score > 1e-12:
        return int(best_idx)
    target_depth = 0.20
    return int(
        min(
            (idx for _score, idx in candidates),
            key=lambda idx: abs(_clamp01((surface_y - pts[idx][1]) / depth_span) - target_depth),
        )
    )


def _compute_lf_overhang_proxy_fields(
    points: Sequence[Point],
    normals: Sequence[Point],
    ion_factors: Sequence[float],
    dh_etch: Sequence[float],
    *,
    redepo_fraction_pct: float,
    survival_penalty: float,
    width_a: float,
) -> Tuple[List[float], Dict[str, Any], Dict[str, float]]:
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n == 0:
        return [], {}, {}
    normal_values = [(float(nx), float(ny)) for nx, ny in normals]
    if len(normal_values) != n:
        normal_values = vertex_air_normals(pts)
    ions = [_clamp01(float(v)) for v in ion_factors]
    if len(ions) != n:
        ions = [1.0 for _ in pts]
    etch = [max(0.0, float(v)) for v in dh_etch]
    if len(etch) != n:
        etch = [0.0 for _ in pts]
    areas = compute_arc_weights(pts)
    xs = [x for x, _y in pts]
    center_x = 0.5 * (min(xs) + max(xs))
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, 1e-9)
    depth_frac = [_clamp01((surface_y - y) / depth_span) for _x, y in pts]
    toe_scores = _lf_overhang_toe_scores(pts, normal_values, ions, center_x=center_x)
    survival = [_clamp01(1.0 - max(0.0, float(survival_penalty)) * ion) for ion in ions]
    source_field = [0.0 for _ in pts]
    source_mass_field = [0.0 for _ in pts]
    source_mass_by_side = {-1: 0.0, 1: 0.0}

    for idx, ((x, _y), (nx, _ny), etch_a, area) in enumerate(zip(pts, normal_values, etch, areas)):
        if etch_a <= 0.0:
            continue
        depth = depth_frac[idx]
        if depth > 0.62:
            continue
        lateral = abs(float(nx))
        upper_gate = 1.0 - _clamp01(depth / 0.62)
        facet_gate = 0.25 + 0.75 * lateral
        source_mass = max(0.0, etch_a) * max(0.0, float(area)) * upper_gate * facet_gate * max(0.20, ions[idx])
        if source_mass <= 0.0:
            continue
        side = -1 if float(x) < center_x else 1
        source_field[idx] = source_mass / max(float(area), 1e-12)
        source_mass_field[idx] = source_mass
        source_mass_by_side[side] += source_mass

    fraction = _clamp01(float(redepo_fraction_pct) / 100.0)
    spread_a = max(0.0, float(width_a))
    dh_redepo = [0.0 for _ in pts]
    target_mass = [0.0 for _ in pts]
    transport_lines: List[TransportLineSample] = []
    toe_indices: Dict[int, Optional[int]] = {}

    for side in (-1, 1):
        toe_indices[side] = _select_lf_overhang_toe_index(
            pts,
            normal_values,
            toe_scores,
            center_x=center_x,
            side=side,
        )

    if fraction > 0.0 and max(source_field, default=0.0) > 0.0:
        redepo = compute_redeposition(
            pts,
            normal_values,
            source_field,
            Model4RedepositionParams(
                redepo_efficiency=fraction,
                emit_power=1.0,
                distance_power=1.0,
                neighbor_exclusion=2,
                max_redepo_distance=max(250.0, _profile_diagonal_a(pts)),
                lateral_spread_a=spread_a,
                transport_model="gapsim_binned_lobe_los",
                ray_count=7,
                footprint_radius_sigma=3.0,
                max_transport_sources=80,
                max_los_candidates_per_source=192,
                los_candidate_weight_fraction=0.985,
                soft_los_radius_points=0,
            ),
        )
        raw_mass = [max(0.0, float(v)) for v in redepo.debug_fields.get("redepo_mass_field", [])]
        if len(raw_mass) != n:
            raw_mass = [
                max(0.0, float(dh)) * max(float(area), 1e-12)
                for dh, area in zip(redepo.dh_redepo, areas)
            ]
        if len(raw_mass) != n:
            raw_mass = [0.0 for _ in pts]
        target_mass = [
            max(0.0, float(mass)) * max(0.0, float(survival[idx]))
            for idx, mass in enumerate(raw_mass)
        ]

        for source_side in (-1, 1):
            source_mass = source_mass_by_side[source_side]
            if source_mass <= 1e-12:
                continue
            sx = sum(pts[idx][0] * source_mass_field[idx] for idx in range(n) if source_mass_field[idx] > 0.0 and ((pts[idx][0] < center_x) == (source_side < 0))) / source_mass
            sy = sum(pts[idx][1] * source_mass_field[idx] for idx in range(n) if source_mass_field[idx] > 0.0 and ((pts[idx][0] < center_x) == (source_side < 0))) / source_mass
            opposite_targets = [
                idx
                for idx, mass in enumerate(target_mass)
                if mass > 0.0 and ((pts[idx][0] - center_x) * float(source_side) < 0.0)
            ]
            target_indices = opposite_targets or [idx for idx, mass in enumerate(target_mass) if mass > 0.0]
            target_total = sum(target_mass[idx] for idx in target_indices)
            if target_total <= 1e-12:
                continue
            tx = sum(pts[idx][0] * target_mass[idx] for idx in target_indices) / target_total
            ty = sum(pts[idx][1] * target_mass[idx] for idx in target_indices) / target_total
            transport_lines.append((float(sx), float(sy), float(tx), float(ty), float(target_total)))

    for idx, mass in enumerate(target_mass):
        dh_redepo[idx] = max(0.0, float(mass)) / max(float(areas[idx]), 1e-12)

    debug_fields: Dict[str, Any] = {
        "lf_source_field": [round(float(v), 6) for v in source_field],
        "lf_toe_score_field": [round(float(v), 6) for v in toe_scores],
        "lf_survival_field": [round(float(v), 6) for v in survival],
        "lf_redepo_field": [round(float(v), 6) for v in dh_redepo],
        "lf_redepo_mass_field": [round(float(v), 6) for v in target_mass],
        "lf_transport_lines": [
            [round(float(x1), 6), round(float(y1), 6), round(float(x2), 6), round(float(y2), 6), round(float(value), 6)]
            for x1, y1, x2, y2, value in transport_lines
        ],
    }
    summary = {
        "lf_source_mass_left": float(source_mass_by_side[-1]),
        "lf_source_mass_right": float(source_mass_by_side[1]),
        "lf_total_source_mass": float(source_mass_by_side[-1] + source_mass_by_side[1]),
        "lf_total_redepo_mass": float(sum(target_mass)),
        "lf_redepo_fraction": float(fraction),
        "lf_active_source_count": float(sum(1 for value in source_field if value > 0.0)),
        "lf_active_target_count": float(sum(1 for value in target_mass if value > 0.0)),
        "lf_transport_line_count": float(len(transport_lines)),
        "lf_transport_model": "normal_lobe_los_survival",
        "lf_width_a": float(spread_a),
        "lf_toe_left_index": float(-1 if toe_indices.get(-1) is None else int(toe_indices[-1])),
        "lf_toe_right_index": float(-1 if toe_indices.get(1) is None else int(toe_indices[1])),
    }
    return dh_redepo, debug_fields, summary


def _closure_target_capture_weights(
    points: Sequence[Point],
    normals: Sequence[Point],
    ion_factors: Sequence[float],
    *,
    shadow_gain: float,
    survival_penalty: float,
) -> Tuple[List[float], List[float], List[float], List[float], List[float], List[float], List[float]]:
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n == 0:
        return [], [], [], [], [], [], []
    normal_values = [(float(nx), float(ny)) for nx, ny in normals]
    if len(normal_values) != n:
        normal_values = vertex_air_normals(pts)
    ions = [_clamp01(float(v)) for v in ion_factors]
    if len(ions) != n:
        ions = [1.0 for _ in pts]
    xs = [x for x, _y in pts]
    center_x = 0.5 * (min(xs) + max(xs))
    surface_y = max(y for _x, y in pts)
    depth_a = [max(0.0, float(surface_y - y)) for _x, y in pts]
    normal_change = _normal_change_field(normal_values)
    visibility_drop = [0.0 for _ in pts]

    for side in (-1, 1):
        side_indices = _lf_overhang_side_indices(pts, center_x, side)
        ordered = sorted(side_indices, key=lambda idx: depth_a[idx])
        previous_visibility = 1.0
        for idx in ordered:
            visibility = ions[idx]
            visibility_drop[idx] = max(0.0, previous_visibility - visibility)
            previous_visibility = max(visibility, previous_visibility * 0.985)

    side_drop_peak = [0.0 for _ in pts]
    side_kink_peak = [0.0 for _ in pts]
    for side in (-1, 1):
        side_indices = _lf_overhang_side_indices(pts, center_x, side)
        max_drop = max((visibility_drop[idx] for idx in side_indices), default=0.0)
        max_kink = max((normal_change[idx] for idx in side_indices), default=0.0)
        for idx in side_indices:
            if max_drop > 1e-9:
                side_drop_peak[idx] = _clamp01(visibility_drop[idx] / max_drop)
            if max_kink > 1e-9:
                side_kink_peak[idx] = _clamp01(normal_change[idx] / max_kink)

    survival = [_clamp01(1.0 - max(0.0, float(survival_penalty)) * ion) for ion in ions]
    capture_signal: List[float] = []
    capture_weights: List[float] = []
    gain = max(0.0, float(shadow_gain))
    survival_signal: List[float] = []
    inward_wall_gate: List[float] = []
    exposed_suppression: List[float] = []
    for idx, ((nx, _ny), ion, drop, kink) in enumerate(
        zip(normal_values, ions, visibility_drop, normal_change)
    ):
        x, _y = pts[idx]
        lateral = abs(float(nx))
        wall_gate = _clamp01(lateral) ** 1.35
        side_sign = -1.0 if float(x) > center_x else 1.0
        inward_gate = _clamp01(max(0.0, side_sign * float(nx)) / 0.18)
        shadow_signal = max(0.0, float(side_drop_peak[idx])) ** 2.0
        kink_signal = min(1.0, max(0.0, float(side_kink_peak[idx]))) ** 1.4
        low_ion_survival = 1.0 - ion
        survival_gate = _clamp01(float(survival[idx]) ** 2.2)
        signal = max(
            0.0,
            inward_gate
            * wall_gate
            * survival_gate
            * (
                (0.82 * shadow_signal * (0.35 + 0.65 * kink_signal))
                + (0.18 * kink_signal * (low_ion_survival**2.0))
            ),
        )
        weight = _clamp01(signal * (0.20 + gain))
        inward_wall_gate.append(inward_gate * wall_gate)
        exposed_suppression.append(survival_gate)
        survival_signal.append(low_ion_survival)
        capture_signal.append(signal)
        capture_weights.append(weight)
    return (
        capture_weights,
        capture_signal,
        survival,
        visibility_drop,
        survival_signal,
        inward_wall_gate,
        exposed_suppression,
    )


def _smooth_profile_field_by_arc(
    points: Sequence[Point],
    values: Sequence[float],
    smoothing_a: float,
) -> List[float]:
    vals = [float(v) for v in values]
    pts = [(float(x), float(y)) for x, y in points]
    if len(vals) <= 2 or len(pts) != len(vals) or float(smoothing_a) <= 0.0:
        return vals
    distances = [
        math.hypot(pts[idx][0] - pts[idx - 1][0], pts[idx][1] - pts[idx - 1][1])
        for idx in range(1, len(pts))
    ]
    positive = [value for value in distances if value > 1e-9]
    if not positive:
        return vals
    avg_ds = sum(positive) / len(positive)
    radius = max(1, int(round(float(smoothing_a) / max(avg_ds, 1e-9))))
    return _smooth_scalar_values(vals, radius)


def _closure_shadow_boundary_envelope(
    points: Sequence[Point],
    capture_signal: Sequence[float],
    width_a: float,
) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    signals = [max(0.0, float(v)) for v in capture_signal]
    n = len(pts)
    if n == 0 or len(signals) != n:
        return [1.0 for _ in pts]
    xs = [x for x, _y in pts]
    surface_y = max(y for _x, y in pts)
    center_x = 0.5 * (min(xs) + max(xs))
    arc = [0.0]
    for idx in range(1, n):
        arc.append(
            arc[-1]
            + math.hypot(pts[idx][0] - pts[idx - 1][0], pts[idx][1] - pts[idx - 1][1])
        )
    sigma = max(1.0, float(width_a) * 0.42)
    envelope = [0.0 for _ in pts]
    for side in (-1, 1):
        side_indices = _lf_overhang_side_indices(pts, center_x, side)
        if not side_indices:
            continue
        peak_value = max((signals[idx] for idx in side_indices), default=0.0)
        if peak_value <= 1e-9:
            for idx in side_indices:
                envelope[idx] = max(envelope[idx], 1.0)
            continue
        significant = [
            idx
            for idx in side_indices
            if signals[idx] >= max(peak_value * 0.10, 1e-9)
        ]
        peak_idx = min(
            significant or side_indices,
            key=lambda idx: (max(0.0, surface_y - pts[idx][1]), -signals[idx]),
        )
        peak_s = arc[peak_idx]
        for idx in side_indices:
            ds = abs(float(arc[idx]) - float(peak_s))
            envelope[idx] = max(envelope[idx], math.exp(-0.5 * (ds / sigma) ** 2))
    return [max(0.0, min(1.0, value)) for value in envelope]


def _compute_closure_redepo_fields(
    points: Sequence[Point],
    normals: Sequence[Point],
    ion_factors: Sequence[float],
    dh_etch: Sequence[float],
    *,
    efficiency_pct: float,
    shadow_gain: float,
    width_a: float,
    survival_penalty: float,
    smoothing_a: float,
) -> Tuple[List[float], Dict[str, Any], Dict[str, float]]:
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n == 0:
        return [], {}, {}
    normal_values = [(float(nx), float(ny)) for nx, ny in normals]
    if len(normal_values) != n:
        normal_values = vertex_air_normals(pts)
    ions = [_clamp01(float(v)) for v in ion_factors]
    if len(ions) != n:
        ions = [1.0 for _ in pts]
    etch = [max(0.0, float(v)) for v in dh_etch]
    if len(etch) != n:
        etch = [0.0 for _ in pts]
    areas = compute_arc_weights(pts)
    removed_mass = [
        max(0.0, float(etch_a)) * max(0.0, float(area))
        for etch_a, area in zip(etch, areas)
    ]
    total_removed_mass = float(sum(removed_mass))
    efficiency = _clamp01(float(efficiency_pct) / 100.0)
    budget_mass = efficiency * total_removed_mass
    source_count = int(sum(1 for mass in removed_mass if mass > 1e-12))
    (
        capture_weights,
        capture_signal,
        survival,
        visibility_drop,
        low_ion_survival,
        inward_wall_gate,
        exposed_suppression,
    ) = _closure_target_capture_weights(
        pts,
        normal_values,
        ions,
        shadow_gain=shadow_gain,
        survival_penalty=survival_penalty,
    )
    shadow_boundary_envelope = _closure_shadow_boundary_envelope(pts, capture_signal, width_a)
    capture_weights = [
        _clamp01(float(weight)) * _clamp01(float(envelope))
        for weight, envelope in zip(capture_weights, shadow_boundary_envelope)
    ]
    if budget_mass <= 1e-12 or source_count <= 0:
        zeros = [0.0 for _ in pts]
        fields = {
            "closure_source_etch_field": [round(float(v), 6) for v in etch],
            "closure_removed_mass_field": [round(float(v), 6) for v in removed_mass],
            "closure_capture_field": [round(float(v), 6) for v in capture_signal],
            "closure_shadow_boundary_envelope_field": [round(float(v), 6) for v in shadow_boundary_envelope],
            "closure_low_ion_survival_signal_field": [round(float(v), 6) for v in low_ion_survival],
            "closure_inward_wall_gate_field": [round(float(v), 6) for v in inward_wall_gate],
            "closure_exposed_suppression_field": [round(float(v), 6) for v in exposed_suppression],
            "closure_survival_field": [round(float(v), 6) for v in survival],
            "closure_visibility_drop_field": [round(float(v), 6) for v in visibility_drop],
            "closure_weighted_redepo_mass_raw_field": [0.0 for _ in pts],
            "closure_weighted_redepo_mass_smoothed_field": [0.0 for _ in pts],
            "closure_redepo_field": [0.0 for _ in pts],
            "closure_redepo_mass_field": [0.0 for _ in pts],
            "closure_transport_lines": [],
        }
        summary = {
            "closure_total_removed_mass": total_removed_mass,
            "closure_budget_mass": budget_mass,
            "closure_total_redepo_mass": 0.0,
            "closure_efficiency": efficiency,
            "closure_active_source_count": float(source_count),
            "closure_active_target_count": 0.0,
            "closure_smoothing_a": float(smoothing_a),
            "closure_transport_horizon_a": float(_closure_transport_horizon_a(pts, width_a)),
            "closure_transport_model": "all_etch_sources_first_hit_normal_lobe_survival",
        }
        return zeros, fields, summary

    redepo = compute_redeposition(
        pts,
        normal_values,
        etch,
        Model4RedepositionParams(
            redepo_efficiency=efficiency,
            emit_power=1.0,
            distance_power=2.0,
            neighbor_exclusion=2,
            max_redepo_distance=_closure_transport_horizon_a(pts, width_a),
            lateral_spread_a=max(0.0, float(width_a)),
            transport_model="fast_first_hit_cone",
            ray_count=7,
            footprint_radius_sigma=3.0,
            max_transport_sources=128,
            max_los_candidates_per_source=224,
            los_candidate_weight_fraction=0.990,
            soft_los_radius_points=0,
            emission_axis_model="normal_reflection_mix",
        ),
    )
    raw_target_mass = [max(0.0, float(v)) for v in redepo.debug_fields.get("redepo_mass_field", [])]
    if len(raw_target_mass) != n:
        raw_target_mass = [
            max(0.0, float(dh)) * max(float(area), 1e-12)
            for dh, area in zip(redepo.dh_redepo, areas)
        ]
    if len(raw_target_mass) != n:
        raw_target_mass = [0.0 for _ in pts]
    weighted_target_mass_raw = [
        max(0.0, float(mass)) * max(0.0, float(weight))
        for mass, weight in zip(raw_target_mass, capture_weights)
    ]
    weighted_target_mass = list(weighted_target_mass_raw)
    if float(smoothing_a) > 0.0:
        weighted_target_mass = _smooth_profile_field_by_arc(pts, weighted_target_mass, float(smoothing_a))
        weighted_target_mass = [
            max(0.0, float(mass)) * _clamp01(float(weight))
            for mass, weight in zip(weighted_target_mass, capture_weights)
        ]
    weighted_total = float(sum(weighted_target_mass))
    max_capture_weight = max((_clamp01(float(v)) for v in capture_weights), default=0.0)
    retained_budget_mass = min(budget_mass, budget_mass * (max_capture_weight ** 0.85))
    if weighted_total > 1e-12 and retained_budget_mass > 1e-12:
        scale = retained_budget_mass / weighted_total
        target_mass = [max(0.0, float(mass)) * scale for mass in weighted_target_mass]
    else:
        target_mass = [0.0 for _ in pts]
    target_total = float(sum(target_mass))
    total_redepo_mass = min(target_total, budget_mass)
    if target_total > total_redepo_mass + 1e-12 and target_total > 1e-12:
        correction = total_redepo_mass / target_total
        target_mass = [float(mass) * correction for mass in target_mass]
    dh_redepo = [
        max(0.0, float(mass)) / max(float(area), 1e-12)
        for mass, area in zip(target_mass, areas)
    ]

    xs = [x for x, _y in pts]
    center_x = 0.5 * (min(xs) + max(xs))
    transport_lines: List[TransportLineSample] = []
    for side in (-1, 1):
        source_indices = [
            idx
            for idx, mass in enumerate(removed_mass)
            if mass > 1e-12 and ((pts[idx][0] - center_x) * float(side) >= 0.0)
        ]
        if not source_indices:
            continue
        source_mass = sum(removed_mass[idx] for idx in source_indices)
        if source_mass <= 1e-12:
            continue
        sx = sum(pts[idx][0] * removed_mass[idx] for idx in source_indices) / source_mass
        sy = sum(pts[idx][1] * removed_mass[idx] for idx in source_indices) / source_mass
        target_indices = [
            idx
            for idx, mass in enumerate(target_mass)
            if mass > 1e-12 and ((pts[idx][0] - center_x) * float(side) < 0.0)
        ]
        if not target_indices:
            target_indices = [idx for idx, mass in enumerate(target_mass) if mass > 1e-12]
        target_total = sum(target_mass[idx] for idx in target_indices)
        if target_total <= 1e-12:
            continue
        tx = sum(pts[idx][0] * target_mass[idx] for idx in target_indices) / target_total
        ty = sum(pts[idx][1] * target_mass[idx] for idx in target_indices) / target_total
        transport_lines.append((float(sx), float(sy), float(tx), float(ty), float(target_total)))

    fields = {
        "closure_source_etch_field": [round(float(v), 6) for v in etch],
        "closure_removed_mass_field": [round(float(v), 6) for v in removed_mass],
        "closure_raw_redepo_mass_field": [round(float(v), 6) for v in raw_target_mass],
        "closure_capture_field": [round(float(v), 6) for v in capture_signal],
        "closure_capture_weight_field": [round(float(v), 6) for v in capture_weights],
        "closure_shadow_boundary_envelope_field": [round(float(v), 6) for v in shadow_boundary_envelope],
        "closure_low_ion_survival_signal_field": [round(float(v), 6) for v in low_ion_survival],
        "closure_inward_wall_gate_field": [round(float(v), 6) for v in inward_wall_gate],
        "closure_exposed_suppression_field": [round(float(v), 6) for v in exposed_suppression],
        "closure_survival_field": [round(float(v), 6) for v in survival],
        "closure_visibility_drop_field": [round(float(v), 6) for v in visibility_drop],
        "closure_weighted_redepo_mass_raw_field": [round(float(v), 6) for v in weighted_target_mass_raw],
        "closure_weighted_redepo_mass_smoothed_field": [round(float(v), 6) for v in weighted_target_mass],
        "closure_redepo_field": [round(float(v), 6) for v in dh_redepo],
        "closure_redepo_mass_field": [round(float(v), 6) for v in target_mass],
        "closure_ion_factor_field": [round(float(v), 6) for v in ions],
        "closure_transport_lines": [
            [round(float(x1), 6), round(float(y1), 6), round(float(x2), 6), round(float(y2), 6), round(float(value), 6)]
            for x1, y1, x2, y2, value in transport_lines
        ],
    }
    summary = {
        "closure_total_removed_mass": total_removed_mass,
        "closure_budget_mass": budget_mass,
        "closure_total_redepo_mass": float(sum(target_mass)),
        "closure_retained_budget_mass": float(retained_budget_mass),
        "closure_max_capture_weight": float(max_capture_weight),
        "closure_efficiency": efficiency,
        "closure_active_source_count": float(source_count),
        "closure_active_target_count": float(sum(1 for mass in target_mass if mass > 1e-12)),
        "closure_shadow_gain": float(shadow_gain),
        "closure_survival_penalty": float(survival_penalty),
        "closure_width_a": float(width_a),
        "closure_smoothing_a": float(smoothing_a),
        "closure_transport_horizon_a": float(_closure_transport_horizon_a(pts, width_a)),
        "closure_transport_model": "all_etch_sources_first_hit_normal_lobe_survival",
    }
    return dh_redepo, fields, summary


def _apply_model8_closure_redepo_step(
    state: SimulationState,
    *,
    deposition_a: float,
    sputter_strength_a: float,
    sputter_peak_pct: float,
    sputter_peak_angle_deg: float,
    sputter_width_deg: float,
    sputter_smoothing_a: float,
    reparam_ds_a: float,
    ion_transmission_enabled: bool,
    ion_transmission_override: Optional[float],
    ion_transmission_start_depth_pct: float,
    ion_transmission_end_depth_pct: float,
    ion_transmission_decay_strength_pct: float,
    ion_transmission_floor_pct: float,
    ion_transmission_curve_power: float,
    ion_transmission_aperture_shadow_pct: float,
    ion_transmission_lateral_shadow_pct: float,
    ion_transmission_edge_shadow_pct: float,
    closure_redepo_efficiency_pct: float,
    closure_redepo_shadow_gain: float,
    closure_redepo_width_a: float,
    closure_redepo_survival_penalty: float,
    closure_redepo_smoothing_a: float,
    closure_threshold_a: float,
    include_model4_redepo: bool = False,
    redepo_efficiency_pct: float = 0.0,
    redepo_emit_power: float = 1.0,
    redepo_distance_power: float = 1.0,
    redepo_neighbor_exclusion: int = 2,
    redepo_max_distance_a: float = 1800.0,
    redepo_soft_los_radius_points: int = 0,
    redepo_transport_model: str = "gapsim_binned_lobe_los",
    redepo_ray_count: int = 7,
    redepo_footprint_sigma_a: float = 55.0,
    redepo_footprint_radius_sigma: float = 3.0,
    include_lf_overhang: bool = False,
    lf_overhang_dose: float = 1.0,
    lf_overhang_sputter_gain: float = 1.0,
    lf_overhang_redepo_fraction_pct: float = 30.0,
    lf_overhang_survival_penalty: float = 0.75,
    lf_overhang_width_a: float = 180.0,
) -> Tuple[List[float], List[float], float]:
    if (
        float(closure_redepo_efficiency_pct) <= 0.0
        and not include_model4_redepo
        and not include_lf_overhang
    ):
        angles, responses, etch_clamp_a = _apply_direct_sputter_step(
            state,
            deposition_a=deposition_a,
            sputter_strength_a=sputter_strength_a,
            sputter_peak_pct=sputter_peak_pct,
            sputter_peak_angle_deg=sputter_peak_angle_deg,
            sputter_width_deg=sputter_width_deg,
            sputter_smoothing_a=sputter_smoothing_a,
            reparam_ds_a=reparam_ds_a,
            ion_transmission_enabled=ion_transmission_enabled,
            ion_transmission_override=ion_transmission_override,
            ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
            ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
            ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
            ion_transmission_floor_pct=ion_transmission_floor_pct,
            ion_transmission_curve_power=ion_transmission_curve_power,
            ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
            ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
            ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
            reflected_ion_enabled=False,
            reflected_ion_strength_pct=0.0,
        )
        fields = dict(state.meta.get("direct_sputter_debug_fields_last", {}))
        x_values = list(fields.get("x", []))
        zeros = [0.0 for _ in x_values]
        fields["closure_source_etch_field"] = list(fields.get("sputter_effective_field", zeros))
        fields["closure_redepo_field"] = zeros
        fields["closure_capture_field"] = zeros
        state.meta["model8_closure_redepo_debug_fields_last"] = fields
        state.meta["model8_closure_redepo_debug_summary_last"] = {
            "closure_total_removed_mass": float(state.meta.get("direct_sputter_total_last", 0.0) or 0.0),
            "closure_budget_mass": 0.0,
            "closure_total_redepo_mass": 0.0,
            "closure_efficiency": 0.0,
            "closure_active_source_count": float(sum(1 for value in fields.get("closure_source_etch_field", []) if float(value) > 0.0)),
            "closure_active_target_count": 0.0,
            "closure_transport_model": "off",
        }
        state.meta["model8_closure_redepo_total_removed_mass_last"] = float(
            state.meta.get("direct_sputter_total_last", 0.0) or 0.0
        )
        state.meta["model8_closure_redepo_total_mass_last"] = 0.0
        state.meta["model8_closure_redepo_active_source_count_last"] = int(
            state.meta["model8_closure_redepo_debug_summary_last"]["closure_active_source_count"]
        )
        state.meta["model8_closure_redepo_active_target_count_last"] = 0
        return angles, responses, etch_clamp_a

    source_state = _clone_simulation_state(state)
    angles, responses, etch_clamp_a = _apply_direct_sputter_step(
        source_state,
        deposition_a=deposition_a,
        sputter_strength_a=sputter_strength_a,
        sputter_peak_pct=sputter_peak_pct,
        sputter_peak_angle_deg=sputter_peak_angle_deg,
        sputter_width_deg=sputter_width_deg,
        sputter_smoothing_a=sputter_smoothing_a,
        reparam_ds_a=reparam_ds_a,
        ion_transmission_enabled=ion_transmission_enabled,
        ion_transmission_override=ion_transmission_override,
        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
        ion_transmission_floor_pct=ion_transmission_floor_pct,
        ion_transmission_curve_power=ion_transmission_curve_power,
        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
        reflected_ion_enabled=False,
        reflected_ion_strength_pct=0.0,
    )
    source_fields = dict(source_state.meta.get("direct_sputter_debug_fields_last", {}))

    grown_solid = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=deposition_a)
    grown_surface = _extract_surface_from_solid(state, grown_solid, state.surface.points)
    grown_surface = equal_arc_resample(grown_surface, reparam_ds_a)
    if not grown_surface:
        state.surface.points = [(float(x), float(y)) for x, y in source_state.surface.points]
        state.solid_paths_i = [list(path) for path in source_state.solid_paths_i]
        state.meta.update(source_state.meta)
        return angles, responses, etch_clamp_a

    smooth_radius = max(0, int(round(float(sputter_smoothing_a) / max(float(reparam_ds_a), 1e-9))))
    normals = _smooth_unit_vectors(vertex_air_normals(grown_surface), smooth_radius)
    dh_etch = [max(0.0, float(v)) for v in source_fields.get("sputter_effective_field", [])]
    if len(dh_etch) != len(grown_surface):
        dh_etch = [0.0 for _ in grown_surface]
    closure_ion_factors = compute_ion_transmission_factors(
        grown_surface,
        enabled=True,
        override=ion_transmission_override,
        start_depth_pct=ion_transmission_start_depth_pct,
        end_depth_pct=ion_transmission_end_depth_pct,
        decay_strength_pct=ion_transmission_decay_strength_pct,
        floor_pct=ion_transmission_floor_pct,
        curve_power=ion_transmission_curve_power,
        aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
        lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
        edge_shadow_pct=ion_transmission_edge_shadow_pct,
        reparam_ds_a=reparam_ds_a,
    )
    dh_redepo, closure_fields, closure_summary = _compute_closure_redepo_fields(
        grown_surface,
        normals,
        closure_ion_factors,
        dh_etch,
        efficiency_pct=closure_redepo_efficiency_pct,
        shadow_gain=closure_redepo_shadow_gain,
        width_a=closure_redepo_width_a,
        survival_penalty=closure_redepo_survival_penalty,
        smoothing_a=closure_redepo_smoothing_a,
    )
    dh_model4_redepo = [0.0 for _ in grown_surface]
    model4_summary: Dict[str, Any] = {}
    model4_fields: Dict[str, Any] = {}
    if include_model4_redepo and redepo_efficiency_pct > 0.0 and max(dh_etch, default=0.0) > 0.0:
        redepo = compute_redeposition(
            grown_surface,
            normals,
            dh_etch,
            Model4RedepositionParams(
                redepo_efficiency=max(0.0, min(100.0, float(redepo_efficiency_pct))) / 100.0,
                emit_power=max(0.0, float(redepo_emit_power)),
                distance_power=max(0.0, float(redepo_distance_power)),
                neighbor_exclusion=max(0, int(redepo_neighbor_exclusion)),
                max_redepo_distance=max(0.0, float(redepo_max_distance_a)),
                lateral_spread_a=max(0.0, float(redepo_footprint_sigma_a)),
                transport_model=str(redepo_transport_model or "gapsim_binned_lobe_los"),
                ray_count=max(3, int(redepo_ray_count)),
                footprint_radius_sigma=max(1.0, float(redepo_footprint_radius_sigma)),
                soft_los_radius_points=max(0, int(redepo_soft_los_radius_points)),
            ),
        )
        if len(redepo.dh_redepo) == len(grown_surface):
            dh_model4_redepo = [max(0.0, float(v)) for v in redepo.dh_redepo]
        model4_summary = dict(redepo.debug_summary)
        model4_fields = dict(redepo.debug_fields)

    dh_lf_redepo = [0.0 for _ in grown_surface]
    lf_fields: Dict[str, Any] = {}
    lf_summary: Dict[str, float] = {}
    lf_dose_scale = max(0.0, float(lf_overhang_dose)) * max(0.0, float(lf_overhang_sputter_gain))
    if include_lf_overhang and lf_dose_scale > 1e-12 and max(dh_etch, default=0.0) > 0.0:
        max_etch_a = max(float(deposition_a) * 2.0, float(reparam_ds_a) * 4.0)
        lf_source_etch = [
            min(max_etch_a, max(0.0, float(value)) * lf_dose_scale)
            for value in dh_etch
        ]
        dh_lf_redepo, lf_fields, lf_summary = _compute_lf_overhang_proxy_fields(
            grown_surface,
            normals,
            closure_ion_factors,
            lf_source_etch,
            redepo_fraction_pct=lf_overhang_redepo_fraction_pct,
            survival_penalty=lf_overhang_survival_penalty,
            width_a=lf_overhang_width_a,
        )
    dh_total_redepo = [
        max(0.0, float(closure_v)) + max(0.0, float(model4_v)) + max(0.0, float(lf_v))
        for closure_v, model4_v, lf_v in zip(dh_redepo, dh_model4_redepo, dh_lf_redepo)
    ]
    profile_delta = [
        max(0.0, float(redepo_a)) - max(0.0, float(etch_a))
        for redepo_a, etch_a in zip(dh_total_redepo, dh_etch)
    ]
    proposed: List[Point] = []
    has_negative_net = False
    for idx, (x, y) in enumerate(grown_surface):
        nx, ny = normals[idx] if idx < len(normals) else (0.0, 1.0)
        move_delta = float(profile_delta[idx]) if idx < len(profile_delta) else 0.0
        if float(deposition_a) + move_delta < 0.0:
            has_negative_net = True
        x2 = float(x + move_delta * nx)
        y2 = float(y + move_delta * ny)
        if idx == 0 or idx == (len(grown_surface) - 1):
            x2 = float(x)
        proposed.append((x2, y2))

    clean_surface, clean_solid = TopologyCleanup().cleanup(
        proposed,
        state,
        solid_ref_paths_i=grown_solid,
        solid_merge_mode=("candidate" if has_negative_net else "union"),
    )
    state.surface.points = equal_arc_resample(clean_surface, reparam_ds_a)
    if clean_solid:
        state.solid_paths_i = clean_solid

    fields = dict(source_fields)
    fields["x"] = [round(float(x), 6) for x, _y in grown_surface]
    fields["y"] = [round(float(y), 6) for _x, y in grown_surface]
    fields["depo_field"] = [round(float(deposition_a), 6) for _ in grown_surface]
    fields["sputter_effective_field"] = [round(float(v), 6) for v in dh_etch]
    fields["direct_sputter_field"] = [round(float(v), 6) for v in dh_etch]
    fields["redepo_field"] = [round(float(v), 6) for v in dh_total_redepo]
    fields["model4_redepo_field"] = [round(float(v), 6) for v in dh_model4_redepo]
    fields["lf_overhang_redepo_field"] = [round(float(v), 6) for v in dh_lf_redepo]
    fields["redepo_source_etch_field"] = [round(float(v), 6) for v in dh_etch]
    fields["profile_delta_field"] = [round(float(v), 6) for v in profile_delta]
    fields["total_etch_field"] = [round(max(0.0, float(e) - float(r)), 6) for e, r in zip(dh_etch, dh_total_redepo)]
    fields["net_growth_field"] = [round(float(deposition_a) + float(delta), 6) for delta in profile_delta]
    fields.update(closure_fields)
    fields.update(lf_fields)
    if model4_fields:
        fields["model4_redepo_mass_field"] = list(model4_fields.get("redepo_mass_field", []))
        fields["model4_removed_mass_field"] = list(model4_fields.get("removed_mass_field", []))

    summary = dict(source_state.meta.get("direct_sputter_debug_summary_last", {}))
    summary["closure_redepo"] = dict(closure_summary)
    if model4_summary:
        summary["redepo"] = model4_summary
    if lf_summary:
        summary["lf_overhang"] = dict(lf_summary)
    summary["total_etch"] = _field_summary_by_depth(grown_surface, [max(0.0, e - r) for e, r in zip(dh_etch, dh_total_redepo)])
    summary["net_growth"] = _field_summary_by_depth(
        grown_surface,
        [float(deposition_a) + float(delta) for delta in profile_delta],
    )
    probe = detect_depth_deposition_closure(
        state.surface.points,
        closure_threshold_a=max(0.0, float(closure_threshold_a)),
        reparam_ds_a=reparam_ds_a,
    )
    summary["closure_probe"] = dict(probe)
    state.meta["direct_sputter_debug_fields_last"] = fields
    state.meta["direct_sputter_debug_summary_last"] = summary
    state.meta["model8_closure_redepo_debug_fields_last"] = fields
    state.meta["model8_closure_redepo_debug_summary_last"] = summary
    state.meta["model8_closure_redepo_total_removed_mass_last"] = float(
        closure_summary.get("closure_total_removed_mass", 0.0)
    )
    state.meta["model8_closure_redepo_total_mass_last"] = float(
        closure_summary.get("closure_total_redepo_mass", 0.0)
    )
    state.meta["model8_closure_redepo_active_source_count_last"] = int(
        closure_summary.get("closure_active_source_count", 0.0)
    )
    state.meta["model8_closure_redepo_active_target_count_last"] = int(
        closure_summary.get("closure_active_target_count", 0.0)
    )
    state.meta["model8_closure_redepo_closure_probe_last"] = probe
    if include_model4_redepo:
        model4_total_mass = sum(
            max(0.0, float(v)) * max(0.0, float(a))
            for v, a in zip(dh_model4_redepo, compute_arc_weights(grown_surface))
        )
        state.meta["model4_redepo_debug_fields_last"] = fields
        state.meta["model4_redepo_debug_summary_last"] = summary
        state.meta["model4_redepo_total_removed_mass_last"] = float(
            closure_summary.get("closure_total_removed_mass", 0.0)
        )
        state.meta["model4_redepo_total_mass_last"] = float(model4_total_mass)
        state.meta["model4_redepo_active_source_count_last"] = int(
            model4_summary.get("active_source_count", 0) or 0
        )
        state.meta["model4_redepo_transport_model_last"] = str(
            model4_summary.get("transport_model", redepo_transport_model)
        )
    if include_lf_overhang:
        lf_total_mass = sum(
            max(0.0, float(v)) * max(0.0, float(a))
            for v, a in zip(dh_lf_redepo, compute_arc_weights(grown_surface))
        )
        state.meta["model7_lf_overhang_debug_fields_last"] = fields
        state.meta["model7_lf_overhang_debug_summary_last"] = summary
        state.meta["model7_lf_overhang_total_removed_mass_last"] = float(
            closure_summary.get("closure_total_removed_mass", 0.0)
        )
        state.meta["model7_lf_overhang_total_redepo_mass_last"] = float(lf_total_mass)
        state.meta["model7_lf_overhang_active_source_count_last"] = int(
            lf_summary.get("lf_active_source_count", 0.0)
        )
        state.meta["model7_lf_overhang_active_target_count_last"] = int(
            lf_summary.get("lf_active_target_count", 0.0)
        )
    state.meta["direct_sputter_total_last"] = float(sum(dh_etch))
    return angles, responses, etch_clamp_a


def _apply_model7_lf_overhang_step(
    state: SimulationState,
    *,
    deposition_a: float,
    sputter_strength_a: float,
    sputter_peak_pct: float,
    sputter_peak_angle_deg: float,
    sputter_width_deg: float,
    sputter_smoothing_a: float,
    reparam_ds_a: float,
    ion_transmission_enabled: bool,
    ion_transmission_override: Optional[float],
    ion_transmission_start_depth_pct: float,
    ion_transmission_end_depth_pct: float,
    ion_transmission_decay_strength_pct: float,
    ion_transmission_floor_pct: float,
    ion_transmission_curve_power: float,
    ion_transmission_aperture_shadow_pct: float,
    ion_transmission_lateral_shadow_pct: float,
    ion_transmission_edge_shadow_pct: float,
    lf_overhang_dose: float,
    lf_overhang_sputter_gain: float,
    lf_overhang_redepo_fraction_pct: float,
    lf_overhang_survival_penalty: float,
    lf_overhang_width_a: float,
    include_model4_redepo: bool = False,
    redepo_source_model: str = "model2",
    redepo_efficiency_pct: float = 0.0,
    redepo_emit_power: float = 1.0,
    redepo_distance_power: float = 1.0,
    redepo_neighbor_exclusion: int = 2,
    redepo_max_distance_a: float = 1800.0,
    redepo_soft_los_radius_points: int = 0,
    redepo_transport_model: str = "gapsim_binned_lobe_los",
    redepo_ray_count: int = 7,
    redepo_footprint_sigma_a: float = 55.0,
    redepo_footprint_radius_sigma: float = 3.0,
) -> Tuple[List[float], List[float], float]:
    source_state = _clone_simulation_state(state)
    angles, responses, etch_clamp_a = _apply_direct_sputter_step(
        source_state,
        deposition_a=deposition_a,
        sputter_strength_a=sputter_strength_a,
        sputter_peak_pct=sputter_peak_pct,
        sputter_peak_angle_deg=sputter_peak_angle_deg,
        sputter_width_deg=sputter_width_deg,
        sputter_smoothing_a=sputter_smoothing_a,
        reparam_ds_a=reparam_ds_a,
        ion_transmission_enabled=ion_transmission_enabled,
        ion_transmission_override=ion_transmission_override,
        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
        ion_transmission_floor_pct=ion_transmission_floor_pct,
        ion_transmission_curve_power=ion_transmission_curve_power,
        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
        reflected_ion_enabled=False,
        reflected_ion_strength_pct=0.0,
    )
    source_fields = dict(source_state.meta.get("direct_sputter_debug_fields_last", {}))

    grown_solid = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=deposition_a)
    grown_surface = _extract_surface_from_solid(state, grown_solid, state.surface.points)
    grown_surface = equal_arc_resample(grown_surface, reparam_ds_a)
    if not grown_surface:
        state.surface.points = [(float(x), float(y)) for x, y in source_state.surface.points]
        state.solid_paths_i = [list(path) for path in source_state.solid_paths_i]
        state.meta.update(source_state.meta)
        return angles, responses, etch_clamp_a

    dose_scale = max(0.0, float(lf_overhang_dose)) * max(0.0, float(lf_overhang_sputter_gain))
    if dose_scale <= 1e-12:
        ion_factors = [_clamp01(float(v)) for v in source_fields.get("ion_factor_field", [])]
        if len(ion_factors) != len(grown_surface):
            ion_factors = [1.0 for _ in grown_surface]
        zeros = [0.0 for _ in grown_surface]
        fields = _debug_field_payload(
            grown_surface,
            deposition_a=deposition_a,
            sputter_raw=zeros,
            ion_factors=ion_factors,
            sputter_effective=zeros,
        )
        fields["redepo_field"] = [0.0 for _ in grown_surface]
        fields["redepo_source_etch_field"] = [0.0 for _ in grown_surface]
        state.surface.points = grown_surface
        if grown_solid:
            state.solid_paths_i = grown_solid
        summary = {
            "ion_factor": _field_summary_by_depth(grown_surface, ion_factors),
            "sputter_raw": _field_summary_by_depth(grown_surface, zeros),
            "sputter_effective": _field_summary_by_depth(grown_surface, zeros),
            "lf_overhang": {
                "lf_total_source_mass": 0.0,
                "lf_total_redepo_mass": 0.0,
                "lf_redepo_fraction": _clamp01(float(lf_overhang_redepo_fraction_pct) / 100.0),
                "lf_active_source_count": 0.0,
                "lf_active_target_count": 0.0,
                "lf_width_a": float(lf_overhang_width_a),
            },
            "total_etch": _field_summary_by_depth(grown_surface, zeros),
            "net_growth": _field_summary_by_depth(grown_surface, [float(deposition_a) for _ in grown_surface]),
        }
        state.meta["direct_sputter_debug_fields_last"] = fields
        state.meta["direct_sputter_debug_summary_last"] = summary
        state.meta["model7_lf_overhang_debug_fields_last"] = fields
        state.meta["model7_lf_overhang_debug_summary_last"] = summary
        state.meta["model7_lf_overhang_total_removed_mass_last"] = 0.0
        state.meta["model7_lf_overhang_total_redepo_mass_last"] = 0.0
        state.meta["model7_lf_overhang_active_source_count_last"] = 0
        state.meta["model7_lf_overhang_active_target_count_last"] = 0
        state.meta["direct_sputter_total_last"] = 0.0
        return angles, responses, etch_clamp_a

    smooth_radius = max(0, int(round(float(sputter_smoothing_a) / max(float(reparam_ds_a), 1e-9))))
    normals = _smooth_unit_vectors(vertex_air_normals(grown_surface), smooth_radius)
    source_etch = [max(0.0, float(v)) for v in source_fields.get("sputter_effective_field", [])]
    if len(source_etch) != len(grown_surface):
        source_etch = [0.0 for _ in grown_surface]
    ion_factors = [_clamp01(float(v)) for v in source_fields.get("ion_factor_field", [])]
    if len(ion_factors) != len(grown_surface):
        ion_factors = compute_ion_transmission_factors(
            grown_surface,
            enabled=ion_transmission_enabled,
            override=ion_transmission_override,
            start_depth_pct=ion_transmission_start_depth_pct,
            end_depth_pct=ion_transmission_end_depth_pct,
            decay_strength_pct=ion_transmission_decay_strength_pct,
            floor_pct=ion_transmission_floor_pct,
            curve_power=ion_transmission_curve_power,
            aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
            lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
            edge_shadow_pct=ion_transmission_edge_shadow_pct,
            reparam_ds_a=reparam_ds_a,
        )

    max_etch_a = max(float(deposition_a) * 2.0, float(reparam_ds_a) * 4.0)
    dh_etch = [
        min(max_etch_a, max(0.0, float(value) * dose_scale))
        for value in source_etch
    ]
    dh_lf_redepo, lf_fields, lf_summary = _compute_lf_overhang_proxy_fields(
        grown_surface,
        normals,
        ion_factors,
        dh_etch,
        redepo_fraction_pct=lf_overhang_redepo_fraction_pct,
        survival_penalty=lf_overhang_survival_penalty,
        width_a=lf_overhang_width_a,
    )
    dh_model4_redepo = [0.0 for _ in grown_surface]
    model4_summary: Dict[str, Any] = {}
    model4_fields: Dict[str, Any] = {}
    if include_model4_redepo and redepo_efficiency_pct > 0.0 and max(dh_etch, default=0.0) > 0.0:
        redepo = compute_redeposition(
            grown_surface,
            normals,
            dh_etch,
            Model4RedepositionParams(
                redepo_efficiency=max(0.0, min(100.0, float(redepo_efficiency_pct))) / 100.0,
                emit_power=max(0.0, float(redepo_emit_power)),
                distance_power=max(0.0, float(redepo_distance_power)),
                neighbor_exclusion=max(0, int(redepo_neighbor_exclusion)),
                max_redepo_distance=max(0.0, float(redepo_max_distance_a)),
                lateral_spread_a=max(0.0, float(redepo_footprint_sigma_a)),
                transport_model=str(redepo_transport_model or "gapsim_binned_lobe_los"),
                ray_count=max(3, int(redepo_ray_count)),
                footprint_radius_sigma=max(1.0, float(redepo_footprint_radius_sigma)),
                soft_los_radius_points=max(0, int(redepo_soft_los_radius_points)),
            ),
        )
        if len(redepo.dh_redepo) == len(grown_surface):
            dh_model4_redepo = [max(0.0, float(v)) for v in redepo.dh_redepo]
        model4_summary = dict(redepo.debug_summary)
        model4_fields = dict(redepo.debug_fields)

    dh_total_redepo = [
        max(0.0, float(model4_v)) + max(0.0, float(lf_v))
        for model4_v, lf_v in zip(dh_model4_redepo, dh_lf_redepo)
    ]
    profile_delta = [
        max(0.0, float(redepo_a)) - max(0.0, float(etch_a))
        for redepo_a, etch_a in zip(dh_total_redepo, dh_etch)
    ]

    proposed: List[Point] = []
    has_negative_net = False
    for idx, (x, y) in enumerate(grown_surface):
        nx, ny = normals[idx] if idx < len(normals) else (0.0, 1.0)
        move_delta = float(profile_delta[idx]) if idx < len(profile_delta) else 0.0
        if float(deposition_a) + move_delta < 0.0:
            has_negative_net = True
        x2 = float(x + move_delta * nx)
        y2 = float(y + move_delta * ny)
        if idx == 0 or idx == (len(grown_surface) - 1):
            x2 = float(x)
        proposed.append((x2, y2))

    clean_surface, clean_solid = TopologyCleanup().cleanup(
        proposed,
        state,
        solid_ref_paths_i=grown_solid,
        solid_merge_mode=("candidate" if has_negative_net else "union"),
    )
    state.surface.points = equal_arc_resample(clean_surface, reparam_ds_a)
    if clean_solid:
        state.solid_paths_i = clean_solid

    total_removed_mass = sum(
        max(0.0, float(etch_a)) * max(0.0, float(area))
        for etch_a, area in zip(dh_etch, compute_arc_weights(grown_surface))
    )
    total_redepo_mass = sum(
        max(0.0, float(redepo_a)) * max(0.0, float(area))
        for redepo_a, area in zip(dh_total_redepo, compute_arc_weights(grown_surface))
    )
    fields = dict(source_fields)
    fields["x"] = [round(float(x), 6) for x, _y in grown_surface]
    fields["y"] = [round(float(y), 6) for _x, y in grown_surface]
    fields["depo_field"] = [round(float(deposition_a), 6) for _ in grown_surface]
    fields["sputter_effective_field"] = [round(float(v), 6) for v in dh_etch]
    fields["direct_sputter_field"] = [round(float(v), 6) for v in dh_etch]
    fields["redepo_field"] = [round(float(v), 6) for v in dh_total_redepo]
    fields["model4_redepo_field"] = [round(float(v), 6) for v in dh_model4_redepo]
    fields["lf_overhang_redepo_field"] = [round(float(v), 6) for v in dh_lf_redepo]
    fields["redepo_source_etch_field"] = [round(float(v), 6) for v in dh_etch]
    fields["profile_delta_field"] = [round(float(v), 6) for v in profile_delta]
    fields["total_etch_field"] = [round(max(0.0, float(e) - float(r)), 6) for e, r in zip(dh_etch, dh_total_redepo)]
    fields["net_growth_field"] = [round(float(deposition_a) + float(delta), 6) for delta in profile_delta]
    fields.update(lf_fields)
    if model4_fields:
        fields["model4_redepo_mass_field"] = list(model4_fields.get("redepo_mass_field", []))
        fields["model4_removed_mass_field"] = list(model4_fields.get("removed_mass_field", []))

    summary = dict(source_state.meta.get("direct_sputter_debug_summary_last", {}))
    summary["lf_overhang"] = dict(lf_summary)
    if model4_summary:
        summary["redepo"] = model4_summary
    summary["total_etch"] = _field_summary_by_depth(grown_surface, [max(0.0, e - r) for e, r in zip(dh_etch, dh_total_redepo)])
    summary["net_growth"] = _field_summary_by_depth(
        grown_surface,
        [float(deposition_a) + float(delta) for delta in profile_delta],
    )
    state.meta["direct_sputter_debug_fields_last"] = fields
    state.meta["direct_sputter_debug_summary_last"] = summary
    state.meta["model7_lf_overhang_debug_fields_last"] = fields
    state.meta["model7_lf_overhang_debug_summary_last"] = summary
    if include_model4_redepo:
        state.meta["model4_redepo_debug_fields_last"] = fields
        state.meta["model4_redepo_debug_summary_last"] = summary
        state.meta["model4_redepo_total_removed_mass_last"] = float(total_removed_mass)
        state.meta["model4_redepo_total_mass_last"] = float(sum(
            max(0.0, float(v)) * max(0.0, float(a))
            for v, a in zip(dh_model4_redepo, compute_arc_weights(grown_surface))
        ))
        state.meta["model4_redepo_active_source_count_last"] = int(model4_summary.get("active_source_count", 0) or 0)
        state.meta["model4_redepo_transport_model_last"] = str(model4_summary.get("transport_model", redepo_transport_model))
    state.meta["model7_lf_overhang_total_removed_mass_last"] = float(total_removed_mass)
    state.meta["model7_lf_overhang_total_redepo_mass_last"] = float(total_redepo_mass)
    state.meta["model7_lf_overhang_active_source_count_last"] = int(lf_summary.get("lf_active_source_count", 0.0))
    state.meta["model7_lf_overhang_active_target_count_last"] = int(lf_summary.get("lf_active_target_count", 0.0))
    state.meta["direct_sputter_total_last"] = float(sum(dh_etch))
    return angles, responses, etch_clamp_a


def _snapshot_profile(points: Sequence[Point]) -> List[Point]:
    return [(float(x), float(y)) for x, y in points]


def _snapshot_voids(state) -> List[List[Point]]:
    return [[(float(x), float(y)) for x, y in poly] for poly in OffsetBoolean.void_polygons_float(state)]


def _snapshot_field_overlay_samples(
    meta: Dict[str, Any],
    field_names: Sequence[str],
    *,
    max_points: int = 1800,
    threshold_fraction: float = 0.10,
) -> List[FieldOverlaySample]:
    fields: Optional[Dict[str, Any]] = None
    for meta_key in (
        "model6_reflection_redepo_debug_fields_last",
        "model8_closure_redepo_debug_fields_last",
        "model7_lf_overhang_debug_fields_last",
        "model4_redepo_debug_fields_last",
        "direct_sputter_debug_fields_last",
        "redepo_debug_fields_last",
    ):
        candidate = meta.get(meta_key)
        if isinstance(candidate, dict):
            fields = candidate
            break
    if fields is None:
        return []

    xs = fields.get("x", [])
    ys = fields.get("y", [])
    values: Any = []
    for field_name in field_names:
        candidate = fields.get(str(field_name), [])
        if isinstance(candidate, Sequence) and len(candidate) > 0:
            values = candidate
            break
    if not isinstance(xs, Sequence) or not isinstance(ys, Sequence) or not isinstance(values, Sequence):
        return []

    n = min(len(xs), len(ys), len(values))
    if n <= 0:
        return []

    parsed: List[RedepoOverlaySample] = []
    max_value = 0.0
    for idx in range(n):
        try:
            value = max(0.0, float(values[idx]))
            x = float(xs[idx])
            y = float(ys[idx])
        except (TypeError, ValueError):
            continue
        if value <= 0.0:
            continue
        max_value = max(max_value, value)
        parsed.append((x, y, value))

    if max_value <= 0.0 or not parsed:
        return []

    threshold = max(1e-9, max_value * max(0.0, float(threshold_fraction)))
    filtered = [sample for sample in parsed if sample[2] > threshold]

    limit = max(1, int(max_points))
    if len(filtered) <= limit:
        return filtered

    return _thin_overlay_samples_by_order(filtered, limit)


def _thin_overlay_samples_by_order(
    samples: Sequence[FieldOverlaySample],
    max_points: int,
) -> List[FieldOverlaySample]:
    limit = max(1, int(max_points))
    if len(samples) <= limit:
        return list(samples)
    if limit == 1:
        return [samples[len(samples) // 2]]
    last = len(samples) - 1
    selected: List[FieldOverlaySample] = []
    used_indices = set()
    for out_idx in range(limit):
        idx = int(round((float(out_idx) * float(last)) / float(limit - 1)))
        if idx in used_indices:
            continue
        used_indices.add(idx)
        selected.append(samples[idx])
    return selected


def _snapshot_redepo_overlay_samples(meta: Dict[str, Any], *, max_points: int = 1800) -> List[RedepoOverlaySample]:
    return _snapshot_field_overlay_samples(
        meta,
        ("redepo_field", "dh_redepo_field"),
        max_points=min(max(1, int(max_points)), 520),
        threshold_fraction=0.10,
    )


def _snapshot_etch_overlay_samples(meta: Dict[str, Any], *, max_points: int = 1800) -> List[FieldOverlaySample]:
    return _snapshot_field_overlay_samples(
        meta,
        ("redepo_source_etch_field", "sputter_effective_field"),
        max_points=min(max(1, int(max_points)), 520),
        threshold_fraction=0.10,
    )


def _compact_redepo_overlay_samples(
    samples: Sequence[FieldOverlaySample],
    *,
    max_points: int = 650,
) -> List[FieldOverlaySample]:
    parsed: List[FieldOverlaySample] = []
    for sample in samples:
        if len(sample) < 3:
            continue
        try:
            value = max(0.0, float(sample[2]))
            if value <= 0.0:
                continue
            parsed.append((float(sample[0]), float(sample[1]), value))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return []

    max_value = max((value for _x, _y, value in parsed), default=0.0)
    threshold = max(1e-9, max_value * 0.10)
    parsed = [sample for sample in parsed if sample[2] > threshold]
    if not parsed:
        return []

    limit = max(1, int(max_points))
    if len(parsed) <= limit:
        return parsed

    return _thin_overlay_samples_by_order(parsed, limit)


def _snapshot_transport_line_samples(meta: Dict[str, Any], *, max_lines: int = 16) -> List[TransportLineSample]:
    fields = meta.get("model6_reflection_redepo_debug_fields_last")
    line_key = "reflection_transport_lines"
    if not isinstance(fields, dict):
        fields = meta.get("model8_closure_redepo_debug_fields_last")
        line_key = "closure_transport_lines"
    if not isinstance(fields, dict):
        fields = meta.get("model7_lf_overhang_debug_fields_last")
        line_key = "lf_transport_lines"
    if not isinstance(fields, dict):
        fields = meta.get("lf_overhang_debug_fields_last")
        line_key = "lf_transport_lines"
    if not isinstance(fields, dict):
        return []
    raw_lines = fields.get(line_key, [])
    if not isinstance(raw_lines, Sequence):
        return []
    parsed: List[TransportLineSample] = []
    for sample in raw_lines:
        if not isinstance(sample, Sequence) or len(sample) < 5:
            continue
        try:
            value = max(0.0, float(sample[4]))
            if value <= 0.0:
                continue
            parsed.append(
                (
                    float(sample[0]),
                    float(sample[1]),
                    float(sample[2]),
                    float(sample[3]),
                    value,
                )
            )
        except (TypeError, ValueError):
            continue
    parsed.sort(key=lambda item: item[4], reverse=True)
    return parsed[: max(1, int(max_lines))]


def _direct_sputter_internal_substeps(deposition_a: float, sputter_strength_a: float, reparam_ds_a: float) -> int:
    target_a = max(1.0, float(reparam_ds_a) * 0.75)
    max_move_a = max(abs(float(deposition_a)), abs(float(sputter_strength_a)))
    if max_move_a <= target_a:
        return 1
    return max(1, min(64, int(math.ceil(max_move_a / target_a))))


def _model4_redepo_internal_substeps(deposition_a: float, sputter_strength_a: float, reparam_ds_a: float) -> int:
    target_a = max(16.0, float(reparam_ds_a) * 6.0)
    max_move_a = max(abs(float(deposition_a)), abs(float(sputter_strength_a)))
    if max_move_a <= target_a:
        return 1
    return max(1, min(12, int(math.ceil(max_move_a / target_a))))


def _sweep_values(start: float, stop: float, step: float, *, max_cases: int) -> List[float]:
    start_f = _coerce_finite_float(start, name="sweep start")
    stop_f = _coerce_finite_float(stop, name="sweep stop")
    step_f = _coerce_positive_float(step, name="sweep step")
    max_n = _coerce_cycles(max_cases)
    if max_n <= 0:
        raise ValueError("max_cases must be positive")

    if math.isclose(start_f, stop_f, rel_tol=0.0, abs_tol=1e-12):
        return [start_f]

    direction = 1.0 if stop_f >= start_f else -1.0
    step_signed = abs(step_f) * direction
    values: List[float] = []
    epsilon = abs(step_signed) * 1e-9 + 1e-9
    idx = 0
    while True:
        value = start_f + step_signed * idx
        if direction > 0.0:
            if value > stop_f + epsilon:
                break
        else:
            if value < stop_f - epsilon:
                break
        rounded = 0.0 if abs(value) < 1e-12 else round(value, 10)
        values.append(float(rounded))
        if len(values) > max_n:
            raise ValueError(f"sweep creates more than {max_n} cases")
        idx += 1

    if not values:
        raise ValueError("sweep produced no cases")
    return values


def _validate_sweep_value(parameter: str, value: float) -> float:
    if parameter == "cycles":
        return float(_coerce_cycles(value))
    if parameter == "angstrom_per_cycle":
        return _coerce_non_negative_float(value, name="angstrom_per_cycle")
    if parameter == "sputter_strength_a_per_cycle":
        return _coerce_non_negative_float(value, name="sputter_strength_a_per_cycle")
    if parameter == "sputter_peak_pct":
        peak_pct = _coerce_finite_float(value, name="sputter_peak_pct")
        if peak_pct < 0.0 or peak_pct > 100.0:
            raise ValueError("sputter_peak_pct must be between 0 and 100")
        return peak_pct
    if parameter == "sputter_peak_angle_deg":
        peak = _coerce_finite_float(value, name="sputter_peak_angle_deg")
        if peak < 0.0 or peak > 89.9:
            raise ValueError("sputter_peak_angle_deg must be between 0 and 89.9")
        return peak
    if parameter == "sputter_width_deg":
        return _coerce_positive_float(value, name="sputter_width_deg")
    if parameter in _ION_TRANSMISSION_SWEEP_PARAMETERS:
        if parameter == "ion_transmission_curve_power":
            curve = _coerce_finite_float(value, name=parameter)
            if curve < 0.2 or curve > 6.0:
                raise ValueError(f"{parameter} must be between 0.2 and 6")
            return curve
        percent = _coerce_finite_float(value, name=parameter)
        if percent < 0.0 or percent > 100.0:
            raise ValueError(f"{parameter} must be between 0 and 100")
        return percent
    if parameter == "reflected_ion_strength_pct":
        strength = _coerce_finite_float(value, name="reflected_ion_strength_pct")
        if strength < 0.0 or strength > 100.0:
            raise ValueError("reflected_ion_strength_pct must be between 0 and 100")
        return strength
    if parameter == "reflected_ion_bowing_weight":
        return _coerce_non_negative_float(value, name="reflected_ion_bowing_weight")
    if parameter == "reflected_ion_microtrench_weight":
        return _coerce_non_negative_float(value, name="reflected_ion_microtrench_weight")
    if parameter == "reflected_ion_range_a":
        return _coerce_positive_float(value, name="reflected_ion_range_a")
    if parameter == "redepo_efficiency_pct":
        strength = _coerce_finite_float(value, name="redepo_efficiency_pct")
        if strength < 0.0 or strength > 100.0:
            raise ValueError("redepo_efficiency_pct must be between 0 and 100")
        return strength
    if parameter == "redepo_emit_power":
        return _coerce_non_negative_float(value, name=parameter)
    if parameter == "redepo_distance_power":
        return _coerce_finite_float(value, name=parameter)
    if parameter == "redepo_neighbor_exclusion":
        return float(_coerce_cycles(value))
    if parameter == "redepo_max_distance_a":
        return _coerce_non_negative_float(value, name="redepo_max_distance_a")
    if parameter == "redepo_soft_los_radius_points":
        return float(max(0, min(2, _coerce_cycles(value))))
    if parameter == "redepo_ray_count":
        return float(max(3, _coerce_cycles(value)))
    if parameter == "redepo_footprint_sigma_a":
        return _coerce_non_negative_float(value, name="redepo_footprint_sigma_a")
    if parameter in {"lf_overhang_dose", "lf_overhang_sputter_gain"}:
        return _coerce_non_negative_float(value, name=parameter)
    if parameter == "lf_overhang_redepo_fraction_pct":
        percent = _coerce_finite_float(value, name=parameter)
        if percent < 0.0 or percent > 100.0:
            raise ValueError(f"{parameter} must be between 0 and 100")
        return percent
    if parameter == "lf_overhang_survival_penalty":
        penalty = _coerce_finite_float(value, name=parameter)
        if penalty < 0.0 or penalty > 4.0:
            raise ValueError(f"{parameter} must be between 0 and 4")
        return penalty
    if parameter == "lf_overhang_width_a":
        return _coerce_positive_float(value, name=parameter)
    if parameter == "closure_redepo_efficiency_pct":
        percent = _coerce_finite_float(value, name=parameter)
        if percent < 0.0 or percent > 100.0:
            raise ValueError(f"{parameter} must be between 0 and 100")
        return percent
    if parameter == "closure_redepo_shadow_gain":
        return _coerce_non_negative_float(value, name=parameter)
    if parameter == "closure_redepo_width_a":
        return _coerce_positive_float(value, name=parameter)
    if parameter == "closure_redepo_survival_penalty":
        penalty = _coerce_finite_float(value, name=parameter)
        if penalty < 0.0 or penalty > 4.0:
            raise ValueError(f"{parameter} must be between 0 and 4")
        return penalty
    if parameter == "closure_redepo_smoothing_a":
        return _coerce_non_negative_float(value, name=parameter)
    if parameter == "deposition_depth_decay_k":
        return _coerce_non_negative_float(value, name="deposition_depth_decay_k")
    if parameter == "deposition_depth_decay_power":
        power = _coerce_finite_float(value, name="deposition_depth_decay_power")
        if power < 0.05 or power > 8.0:
            raise ValueError("deposition_depth_decay_power must be between 0.05 and 8")
        return power
    if parameter in {
        "deposition_min_ratio",
        "deposition_post_closure_fill_pct_hole",
        "deposition_post_closure_fill_pct_line",
        "deposition_line_open_path_factor",
    }:
        ratio = _coerce_finite_float(value, name=parameter)
        if ratio < 0.0 or ratio > 1.0:
            raise ValueError(f"{parameter} must be between 0 and 1")
        return ratio
    if parameter in {"deposition_closure_threshold_a", "deposition_residual_fill_decay_length_a"}:
        return _coerce_non_negative_float(value, name=parameter)
    if parameter in {
        "inhibition_strength_pct",
        "inhibition_bottom_boost_pct",
        "inhibition_peald_recombination_pct",
    }:
        percent = _coerce_finite_float(value, name=parameter)
        if percent < 0.0 or percent > 100.0:
            raise ValueError(f"{parameter} must be between 0 and 100")
        return percent
    if parameter == "inhibition_penetration_depth_a":
        return _coerce_positive_float(value, name=parameter)
    if parameter == "inhibition_min_growth_ratio":
        ratio = _coerce_finite_float(value, name=parameter)
        if ratio < 0.0 or ratio > 1.0:
            raise ValueError(f"{parameter} must be between 0 and 1")
        return ratio
    if parameter == "inhibition_smoothing_a":
        return _coerce_non_negative_float(value, name=parameter)
    raise ValueError(f"unsupported sweep parameter: {parameter}")


def _replace_sweep_config(base_config: TrenchDepoConfig, parameter: str, value: float) -> TrenchDepoConfig:
    value = _validate_sweep_value(parameter, value)
    kwargs: Dict[str, Any] = {}
    if parameter == "cycles":
        kwargs[parameter] = int(value)
    else:
        kwargs[parameter] = float(value)
    if parameter in _SPUTTER_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = True
    if parameter in _ION_TRANSMISSION_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = True
        kwargs["ion_transmission_enabled"] = True
    if parameter in _REFLECTED_ION_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = True
        kwargs["reflected_ion_enabled"] = True
    if parameter in _REDEPO_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = True
        kwargs["redepo_enabled"] = True
    if parameter in _LF_OVERHANG_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = True
        kwargs["lf_overhang_enabled"] = True
    if parameter in _CLOSURE_REDEPO_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = True
        kwargs["closure_redepo_enabled"] = True
    if parameter in _DEPTH_DEPOSITION_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = False
        kwargs["redepo_enabled"] = False
        kwargs["reflected_ion_enabled"] = False
        kwargs["ion_transmission_enabled"] = False
        kwargs["deposition_depth_enabled"] = True
    if parameter in _INHIBITION_SWEEP_PARAMETERS:
        kwargs["sputter_enabled"] = False
        kwargs["redepo_enabled"] = False
        kwargs["reflected_ion_enabled"] = False
        kwargs["ion_transmission_enabled"] = False
        kwargs["deposition_depth_enabled"] = True
        kwargs["inhibition_enabled"] = True
    return replace(base_config, **kwargs)


def build_trench_depo_sweep_configs(
    base_config: Optional[TrenchDepoConfig],
    parameter: str,
    start: float,
    stop: float,
    step: float,
    *,
    max_cases: int = 36,
) -> List[TrenchSweepConfig]:
    parameter_key = str(parameter)
    if parameter_key not in SWEEP_PARAMETER_LABELS:
        raise ValueError(f"unsupported sweep parameter: {parameter_key}")
    cfg = base_config or TrenchDepoConfig()
    values = _sweep_values(start, stop, step, max_cases=max_cases)
    label = SWEEP_PARAMETER_LABELS[parameter_key]
    return [
        TrenchSweepConfig(
            parameter=parameter_key,
            label=label,
            value=_validate_sweep_value(parameter_key, value),
            config=_replace_sweep_config(cfg, parameter_key, value),
        )
        for value in values
    ]


def run_trench_depo_sweep(
    base_config: Optional[TrenchDepoConfig],
    parameter: str,
    start: float,
    stop: float,
    step: float,
    *,
    max_cases: int = 36,
    progress_cb: Optional[Callable[[int, int, TrenchSweepConfig], None]] = None,
) -> List[TrenchSweepResult]:
    configs = build_trench_depo_sweep_configs(
        base_config,
        parameter,
        start,
        stop,
        step,
        max_cases=max_cases,
    )
    out: List[TrenchSweepResult] = []
    total = len(configs)
    for idx, sweep_cfg in enumerate(configs, start=1):
        if progress_cb is not None:
            progress_cb(idx, total, sweep_cfg)
        result = run_trench_depo(sweep_cfg.config)
        out.append(
            TrenchSweepResult(
                parameter=sweep_cfg.parameter,
                label=sweep_cfg.label,
                value=sweep_cfg.value,
                config=sweep_cfg.config,
                result=result,
            )
        )
    return out


def run_trench_depo(
    config: Optional[TrenchDepoConfig] = None,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    detail_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> TrenchDepoResult:
    cfg = config or TrenchDepoConfig()
    emulator_number = int(getattr(cfg, "emulator_number", 0) or 0)
    allowed_sputter = emulator_number in (0, 2, 3, 6)
    allowed_ion_transmission = emulator_number in (0, 3)
    allowed_depth_deposition = emulator_number in (0, 4, 5)
    allowed_inhibition = emulator_number in (0, 5)
    allowed_reflection_redepo = emulator_number in (0, 6)
    cycles = _coerce_cycles(cfg.cycles)
    angstrom_per_cycle = _coerce_non_negative_float(cfg.angstrom_per_cycle, name="angstrom_per_cycle")
    reparam_ds_a = _coerce_positive_float(cfg.reparam_ds_a, name="reparam_ds_a")
    sputter_strength_a = _coerce_non_negative_float(
        cfg.sputter_strength_a_per_cycle,
        name="sputter_strength_a_per_cycle",
    )
    sputter_peak_pct = max(0.0, min(100.0, float(cfg.sputter_peak_pct)))
    sputter_peak_angle_deg = max(0.0, min(89.9, float(cfg.sputter_peak_angle_deg)))
    sputter_width_deg = _coerce_positive_float(cfg.sputter_width_deg, name="sputter_width_deg")
    sputter_smoothing_a = _coerce_non_negative_float(cfg.sputter_smoothing_a, name="sputter_smoothing_a")
    ion_transmission_enabled = bool(allowed_ion_transmission and cfg.ion_transmission_enabled)
    ion_transmission_override = (
        None
        if cfg.ion_transmission_override is None
        else _clamp01(_coerce_finite_float(cfg.ion_transmission_override, name="ion_transmission_override"))
    )
    ion_transmission_start_depth_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.ion_transmission_start_depth_pct,
                name="ion_transmission_start_depth_pct",
            ),
        ),
    )
    ion_transmission_end_depth_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.ion_transmission_end_depth_pct,
                name="ion_transmission_end_depth_pct",
            ),
        ),
    )
    ion_transmission_decay_strength_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.ion_transmission_decay_strength_pct,
                name="ion_transmission_decay_strength_pct",
            ),
        ),
    )
    ion_transmission_floor_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.ion_transmission_floor_pct,
                name="ion_transmission_floor_pct",
            ),
        ),
    )
    ion_transmission_curve_power = max(
        0.2,
        min(
            6.0,
            _coerce_finite_float(
                cfg.ion_transmission_curve_power,
                name="ion_transmission_curve_power",
            ),
        ),
    )
    ion_transmission_aperture_shadow_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.ion_transmission_aperture_shadow_pct,
                name="ion_transmission_aperture_shadow_pct",
            ),
        ),
    )
    ion_transmission_lateral_shadow_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.ion_transmission_lateral_shadow_pct,
                name="ion_transmission_lateral_shadow_pct",
            ),
        ),
    )
    ion_transmission_edge_shadow_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.ion_transmission_edge_shadow_pct,
                name="ion_transmission_edge_shadow_pct",
            ),
        ),
    )
    reflected_ion_strength_pct = max(
        0.0,
        min(100.0, _coerce_finite_float(cfg.reflected_ion_strength_pct, name="reflected_ion_strength_pct")),
    )
    reflected_ion_bowing_weight = _coerce_non_negative_float(
        cfg.reflected_ion_bowing_weight,
        name="reflected_ion_bowing_weight",
    )
    reflected_ion_microtrench_weight = _coerce_non_negative_float(
        cfg.reflected_ion_microtrench_weight,
        name="reflected_ion_microtrench_weight",
    )
    reflected_ion_range_a = _coerce_positive_float(cfg.reflected_ion_range_a, name="reflected_ion_range_a")
    redepo_source_model = _redepo_source_model_key(cfg.redepo_source_model)
    redepo_efficiency_pct = max(
        0.0,
        min(100.0, _coerce_finite_float(cfg.redepo_efficiency_pct, name="redepo_efficiency_pct")),
    )
    redepo_emit_power = _coerce_non_negative_float(cfg.redepo_emit_power, name="redepo_emit_power")
    redepo_distance_power = _coerce_finite_float(cfg.redepo_distance_power, name="redepo_distance_power")
    redepo_neighbor_exclusion = _coerce_cycles(cfg.redepo_neighbor_exclusion)
    redepo_max_distance_a = _coerce_non_negative_float(cfg.redepo_max_distance_a, name="redepo_max_distance_a")
    redepo_soft_los_radius_points = max(0, min(2, _coerce_cycles(cfg.redepo_soft_los_radius_points)))
    redepo_transport_model = str(cfg.redepo_transport_model or "gapsim_binned_lobe_los")
    redepo_ray_count = max(3, _coerce_cycles(cfg.redepo_ray_count))
    redepo_footprint_sigma_a = _coerce_non_negative_float(
        cfg.redepo_footprint_sigma_a,
        name="redepo_footprint_sigma_a",
    )
    redepo_footprint_radius_sigma = max(
        1.0,
        _coerce_positive_float(cfg.redepo_footprint_radius_sigma, name="redepo_footprint_radius_sigma"),
    )
    lf_overhang_dose = _coerce_non_negative_float(cfg.lf_overhang_dose, name="lf_overhang_dose")
    lf_overhang_sputter_gain = _coerce_non_negative_float(
        cfg.lf_overhang_sputter_gain,
        name="lf_overhang_sputter_gain",
    )
    lf_overhang_redepo_fraction_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.lf_overhang_redepo_fraction_pct,
                name="lf_overhang_redepo_fraction_pct",
            ),
        ),
    )
    lf_overhang_survival_penalty = max(
        0.0,
        min(
            4.0,
            _coerce_finite_float(
                cfg.lf_overhang_survival_penalty,
                name="lf_overhang_survival_penalty",
            ),
        ),
    )
    lf_overhang_width_a = _coerce_positive_float(cfg.lf_overhang_width_a, name="lf_overhang_width_a")
    closure_redepo_efficiency_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.closure_redepo_efficiency_pct,
                name="closure_redepo_efficiency_pct",
            ),
        ),
    )
    closure_redepo_shadow_gain = _coerce_non_negative_float(
        cfg.closure_redepo_shadow_gain,
        name="closure_redepo_shadow_gain",
    )
    closure_redepo_width_a = _coerce_positive_float(
        cfg.closure_redepo_width_a,
        name="closure_redepo_width_a",
    )
    closure_redepo_survival_penalty = max(
        0.0,
        min(
            4.0,
            _coerce_finite_float(
                cfg.closure_redepo_survival_penalty,
                name="closure_redepo_survival_penalty",
            ),
        ),
    )
    closure_redepo_smoothing_a = _coerce_non_negative_float(
        cfg.closure_redepo_smoothing_a,
        name="closure_redepo_smoothing_a",
    )
    deposition_feature_type = _feature_type_key(cfg.deposition_feature_type)
    deposition_feature_width_a = _coerce_positive_float(
        cfg.deposition_feature_width_a,
        name="deposition_feature_width_a",
    )
    deposition_feature_depth_a = _coerce_positive_float(
        cfg.deposition_feature_depth_a,
        name="deposition_feature_depth_a",
    )
    deposition_feature_length_a = (
        None
        if cfg.deposition_feature_length_a is None
        else _coerce_positive_float(cfg.deposition_feature_length_a, name="deposition_feature_length_a")
    )
    deposition_attenuation_model = str(cfg.deposition_attenuation_model or "exponential").strip().lower()
    if deposition_attenuation_model not in {"exponential", "logistic", "power"}:
        deposition_attenuation_model = "exponential"
    deposition_depth_decay_k = _coerce_non_negative_float(
        cfg.deposition_depth_decay_k,
        name="deposition_depth_decay_k",
    )
    deposition_depth_decay_power = max(
        0.05,
        min(8.0, _coerce_finite_float(cfg.deposition_depth_decay_power, name="deposition_depth_decay_power")),
    )
    deposition_min_ratio = _clamp01(_coerce_finite_float(cfg.deposition_min_ratio, name="deposition_min_ratio"))
    deposition_closure_threshold_a = _coerce_non_negative_float(
        cfg.deposition_closure_threshold_a,
        name="deposition_closure_threshold_a",
    )
    deposition_post_closure_fill_pct_hole = _clamp01(
        _coerce_finite_float(
            cfg.deposition_post_closure_fill_pct_hole,
            name="deposition_post_closure_fill_pct_hole",
        )
    )
    deposition_post_closure_fill_pct_line = _clamp01(
        _coerce_finite_float(
            cfg.deposition_post_closure_fill_pct_line,
            name="deposition_post_closure_fill_pct_line",
        )
    )
    deposition_line_open_path_factor = _clamp01(
        _coerce_finite_float(cfg.deposition_line_open_path_factor, name="deposition_line_open_path_factor")
    )
    deposition_residual_fill_decay_length_a = _coerce_positive_float(
        cfg.deposition_residual_fill_decay_length_a,
        name="deposition_residual_fill_decay_length_a",
    )
    deposition_residual_fill_distribution = str(
        cfg.deposition_residual_fill_distribution or "exponential_from_closure"
    ).strip().lower()
    if deposition_residual_fill_distribution not in {"exponential_from_closure", "uniform_below_closure"}:
        deposition_residual_fill_distribution = "exponential_from_closure"
    deposition_max_depo_per_cell_a = (
        None
        if cfg.deposition_max_depo_per_cell_a is None
        else _coerce_non_negative_float(cfg.deposition_max_depo_per_cell_a, name="deposition_max_depo_per_cell_a")
    )
    inhibition_process_model = _inhibition_process_key(cfg.inhibition_process_model)
    inhibition_strength_pct = max(
        0.0,
        min(100.0, _coerce_finite_float(cfg.inhibition_strength_pct, name="inhibition_strength_pct")),
    )
    inhibition_penetration_depth_a = _coerce_positive_float(
        cfg.inhibition_penetration_depth_a,
        name="inhibition_penetration_depth_a",
    )
    inhibition_decay_power = max(
        0.05,
        min(8.0, _coerce_finite_float(cfg.inhibition_decay_power, name="inhibition_decay_power")),
    )
    inhibition_min_growth_ratio = _clamp01(
        _coerce_finite_float(cfg.inhibition_min_growth_ratio, name="inhibition_min_growth_ratio")
    )
    inhibition_bottom_boost_pct = max(
        0.0,
        min(100.0, _coerce_finite_float(cfg.inhibition_bottom_boost_pct, name="inhibition_bottom_boost_pct")),
    )
    inhibition_peald_recombination_pct = max(
        0.0,
        min(
            100.0,
            _coerce_finite_float(
                cfg.inhibition_peald_recombination_pct,
                name="inhibition_peald_recombination_pct",
            ),
        ),
    )
    inhibition_smoothing_a = _coerce_non_negative_float(
        cfg.inhibition_smoothing_a,
        name="inhibition_smoothing_a",
    )
    sputter_active = bool(allowed_sputter and cfg.sputter_enabled) and sputter_strength_a > 0.0
    reflected_ion_requested = False
    model6_redepo_requested = bool(allowed_reflection_redepo and cfg.redepo_enabled)
    model6_redepo_active = bool(model6_redepo_requested and sputter_active and redepo_efficiency_pct > 0.0)
    redepo_active = bool(model6_redepo_active)
    lf_overhang_requested = False
    lf_overhang_active = bool(lf_overhang_requested and lf_overhang_dose > 0.0 and lf_overhang_sputter_gain > 0.0)
    closure_redepo_requested = False
    closure_redepo_active = bool(closure_redepo_requested and closure_redepo_efficiency_pct > 0.0)
    inhibition_active = bool(allowed_inhibition and cfg.inhibition_enabled) and angstrom_per_cycle > 0.0
    depth_deposition_active = (
        bool(allowed_depth_deposition and cfg.deposition_depth_enabled)
        and not inhibition_active
        and angstrom_per_cycle > 0.0
    )
    initial_points = _coerce_points(cfg.points)
    depth_cfg = replace(
        cfg,
        deposition_feature_type=deposition_feature_type,
        deposition_feature_width_a=deposition_feature_width_a,
        deposition_feature_depth_a=deposition_feature_depth_a,
        deposition_feature_length_a=deposition_feature_length_a,
        deposition_attenuation_model=deposition_attenuation_model,
        deposition_depth_decay_k=deposition_depth_decay_k,
        deposition_depth_decay_power=deposition_depth_decay_power,
        deposition_min_ratio=deposition_min_ratio,
        deposition_closure_threshold_a=deposition_closure_threshold_a,
        deposition_post_closure_fill_pct_hole=deposition_post_closure_fill_pct_hole,
        deposition_post_closure_fill_pct_line=deposition_post_closure_fill_pct_line,
        deposition_line_open_path_factor=deposition_line_open_path_factor,
        deposition_residual_fill_decay_length_a=deposition_residual_fill_decay_length_a,
        deposition_residual_fill_distribution=deposition_residual_fill_distribution,
        deposition_max_depo_per_cell_a=deposition_max_depo_per_cell_a,
        inhibition_process_model=inhibition_process_model,
        inhibition_strength_pct=inhibition_strength_pct,
        inhibition_penetration_depth_a=inhibition_penetration_depth_a,
        inhibition_decay_power=inhibition_decay_power,
        inhibition_min_growth_ratio=inhibition_min_growth_ratio,
        inhibition_bottom_boost_pct=inhibition_bottom_boost_pct,
        inhibition_peald_recombination_pct=inhibition_peald_recombination_pct,
        inhibition_smoothing_a=inhibition_smoothing_a,
    )

    OffsetBoolean.require_backend()

    state = init_simulation_state(initial_points, units="A", reparam_ds_a=reparam_ds_a)
    frame_steps: List[int] = []
    frame_profiles: List[List[Point]] = []
    frame_voids: List[List[List[Point]]] = []
    frame_redepo_overlays: List[List[RedepoOverlaySample]] = []
    frame_etch_overlays: List[List[FieldOverlaySample]] = []
    frame_transport_lines: List[List[TransportLineSample]] = []
    pending_redepo_overlay: List[RedepoOverlaySample] = []
    pending_etch_overlay: List[FieldOverlaySample] = []
    pending_transport_lines: List[TransportLineSample] = []

    def canceled() -> bool:
        return bool(cancel_check()) if cancel_check is not None else False

    for step in range(cycles + 1):
        if canceled():
            raise SimulationCanceled()

        pts_now = _snapshot_profile(state.surface.points)
        frame_steps.append(int(step))
        frame_profiles.append(pts_now)
        frame_voids.append(_snapshot_voids(state))
        frame_redepo_overlays.append(
            _compact_redepo_overlay_samples(pending_redepo_overlay)
        )
        frame_etch_overlays.append(
            _compact_redepo_overlay_samples(pending_etch_overlay)
        )
        frame_transport_lines.append(list(pending_transport_lines))
        pending_redepo_overlay = []
        pending_etch_overlay = []
        pending_transport_lines = []

        if progress_cb is not None:
            progress_cb(int(step), int(cycles))
        if detail_cb is not None:
            detail_cb({"kind": "cycle", "step": int(step), "total": int(cycles), "points": int(len(pts_now))})

        if step == cycles:
            break

        if sputter_active:
            substeps = _direct_sputter_internal_substeps(
                angstrom_per_cycle,
                sputter_strength_a * (1.0 + (reflected_ion_strength_pct / 100.0 if reflected_ion_requested else 0.0)),
                reparam_ds_a,
            )
            if redepo_active:
                substeps = _model4_redepo_internal_substeps(
                    angstrom_per_cycle,
                    sputter_strength_a,
                    reparam_ds_a,
                )
            if closure_redepo_requested:
                substeps = max(
                    substeps,
                    _model4_redepo_internal_substeps(
                        angstrom_per_cycle,
                        sputter_strength_a,
                        reparam_ds_a,
                    ),
                )
            if lf_overhang_requested:
                substeps = max(
                    substeps,
                    _model4_redepo_internal_substeps(
                        angstrom_per_cycle,
                        sputter_strength_a * max(1.0, lf_overhang_dose * lf_overhang_sputter_gain),
                        reparam_ds_a,
                    ),
                )
            state.meta["direct_sputter_internal_substeps"] = int(substeps)
            deposition_sub_a = angstrom_per_cycle / float(substeps)
            sputter_sub_a = sputter_strength_a / float(substeps)
            cycle_redepo_overlay: List[RedepoOverlaySample] = []
            cycle_etch_overlay: List[FieldOverlaySample] = []
            cycle_transport_lines: List[TransportLineSample] = []
            if inhibition_active:
                state.meta["inhibition_internal_substeps"] = int(substeps)
            elif depth_deposition_active:
                state.meta["depth_deposition_internal_substeps"] = int(substeps)
            for substep_idx in range(substeps):
                if canceled():
                    raise SimulationCanceled()
                sputter_deposition_sub_a = deposition_sub_a
                if inhibition_active:
                    _apply_inhibition_deposition_step(
                        state,
                        depth_cfg,
                        deposition_a=deposition_sub_a,
                        reparam_ds_a=reparam_ds_a,
                        cycle_index=int(step + 1),
                    )
                    sputter_deposition_sub_a = 0.0
                elif depth_deposition_active:
                    _apply_depth_deposition_step(
                        state,
                        depth_cfg,
                        deposition_a=deposition_sub_a,
                        reparam_ds_a=reparam_ds_a,
                        cycle_index=int(step + 1),
                    )
                    sputter_deposition_sub_a = 0.0
                detail_kind = (
                    "integrated_inhibition_model8_closure_redepo_substep"
                    if inhibition_active and closure_redepo_requested
                    else "integrated_depth_model8_closure_redepo_substep"
                    if depth_deposition_active and closure_redepo_requested
                    else "model8_closure_redepo_substep"
                    if closure_redepo_requested
                    else
                    "integrated_inhibition_model7_lf_overhang_substep"
                    if inhibition_active and lf_overhang_requested
                    else "integrated_depth_model7_lf_overhang_substep"
                    if depth_deposition_active and lf_overhang_requested
                    else "model7_lf_overhang_substep"
                    if lf_overhang_requested
                    else "integrated_inhibition_model4_redepo_substep"
                    if inhibition_active and redepo_active and not model6_redepo_active
                    else "integrated_depth_model4_redepo_substep"
                    if depth_deposition_active and redepo_active and not model6_redepo_active
                    else "integrated_inhibition_model6_redepo_substep"
                    if inhibition_active and model6_redepo_active
                    else "integrated_depth_model6_redepo_substep"
                    if depth_deposition_active and model6_redepo_active
                    else "model6_reflection_redepo_substep"
                    if model6_redepo_active
                    else "integrated_inhibition_direct_sputter_substep"
                    if inhibition_active
                    else "integrated_depth_direct_sputter_substep"
                    if depth_deposition_active
                    else "model4_redepo_substep"
                    if redepo_active
                    else "direct_sputter_substep"
                )
                if detail_cb is not None:
                    detail_cb(
                        {
                            "kind": f"{detail_kind}_start",
                            "phase": "start",
                            "step": int(step),
                            "substep": int(substep_idx + 1),
                            "substeps": int(substeps),
                            "points": int(len(state.surface.points)),
                        }
                    )
                if closure_redepo_requested:
                    angles, responses, etch_clamp_a = _apply_model8_closure_redepo_step(
                        state,
                        deposition_a=sputter_deposition_sub_a,
                        sputter_strength_a=sputter_sub_a,
                        sputter_peak_pct=sputter_peak_pct,
                        sputter_peak_angle_deg=sputter_peak_angle_deg,
                        sputter_width_deg=sputter_width_deg,
                        sputter_smoothing_a=sputter_smoothing_a,
                        reparam_ds_a=reparam_ds_a,
                        ion_transmission_enabled=ion_transmission_enabled,
                        ion_transmission_override=ion_transmission_override,
                        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
                        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
                        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
                        ion_transmission_floor_pct=ion_transmission_floor_pct,
                        ion_transmission_curve_power=ion_transmission_curve_power,
                        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
                        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
                        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
                        closure_redepo_efficiency_pct=closure_redepo_efficiency_pct,
                        closure_redepo_shadow_gain=closure_redepo_shadow_gain,
                        closure_redepo_width_a=closure_redepo_width_a,
                        closure_redepo_survival_penalty=closure_redepo_survival_penalty,
                        closure_redepo_smoothing_a=closure_redepo_smoothing_a,
                        closure_threshold_a=deposition_closure_threshold_a,
                        include_model4_redepo=redepo_active,
                        redepo_efficiency_pct=redepo_efficiency_pct,
                        redepo_emit_power=redepo_emit_power,
                        redepo_distance_power=redepo_distance_power,
                        redepo_neighbor_exclusion=redepo_neighbor_exclusion,
                        redepo_max_distance_a=redepo_max_distance_a,
                        redepo_soft_los_radius_points=redepo_soft_los_radius_points,
                        redepo_transport_model=redepo_transport_model,
                        redepo_ray_count=redepo_ray_count,
                        redepo_footprint_sigma_a=redepo_footprint_sigma_a,
                        redepo_footprint_radius_sigma=redepo_footprint_radius_sigma,
                        include_lf_overhang=lf_overhang_requested,
                        lf_overhang_dose=lf_overhang_dose,
                        lf_overhang_sputter_gain=lf_overhang_sputter_gain,
                        lf_overhang_redepo_fraction_pct=lf_overhang_redepo_fraction_pct,
                        lf_overhang_survival_penalty=lf_overhang_survival_penalty,
                        lf_overhang_width_a=lf_overhang_width_a,
                    )
                    cycle_redepo_overlay.extend(_snapshot_redepo_overlay_samples(state.meta))
                    cycle_etch_overlay.extend(_snapshot_etch_overlay_samples(state.meta))
                    cycle_transport_lines.extend(_snapshot_transport_line_samples(state.meta))
                elif lf_overhang_requested:
                    angles, responses, etch_clamp_a = _apply_model7_lf_overhang_step(
                        state,
                        deposition_a=sputter_deposition_sub_a,
                        sputter_strength_a=sputter_sub_a,
                        sputter_peak_pct=sputter_peak_pct,
                        sputter_peak_angle_deg=sputter_peak_angle_deg,
                        sputter_width_deg=sputter_width_deg,
                        sputter_smoothing_a=sputter_smoothing_a,
                        reparam_ds_a=reparam_ds_a,
                        ion_transmission_enabled=ion_transmission_enabled,
                        ion_transmission_override=ion_transmission_override,
                        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
                        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
                        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
                        ion_transmission_floor_pct=ion_transmission_floor_pct,
                        ion_transmission_curve_power=ion_transmission_curve_power,
                        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
                        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
                        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
                        lf_overhang_dose=lf_overhang_dose,
                        lf_overhang_sputter_gain=lf_overhang_sputter_gain,
                        lf_overhang_redepo_fraction_pct=lf_overhang_redepo_fraction_pct,
                        lf_overhang_survival_penalty=lf_overhang_survival_penalty,
                        lf_overhang_width_a=lf_overhang_width_a,
                        include_model4_redepo=redepo_active,
                        redepo_source_model=redepo_source_model,
                        redepo_efficiency_pct=redepo_efficiency_pct,
                        redepo_emit_power=redepo_emit_power,
                        redepo_distance_power=redepo_distance_power,
                        redepo_neighbor_exclusion=redepo_neighbor_exclusion,
                        redepo_max_distance_a=redepo_max_distance_a,
                        redepo_soft_los_radius_points=redepo_soft_los_radius_points,
                        redepo_transport_model=redepo_transport_model,
                        redepo_ray_count=redepo_ray_count,
                        redepo_footprint_sigma_a=redepo_footprint_sigma_a,
                        redepo_footprint_radius_sigma=redepo_footprint_radius_sigma,
                    )
                    cycle_redepo_overlay.extend(_snapshot_redepo_overlay_samples(state.meta))
                    cycle_etch_overlay.extend(_snapshot_etch_overlay_samples(state.meta))
                    cycle_transport_lines.extend(_snapshot_transport_line_samples(state.meta))
                elif model6_redepo_active:
                    angles, responses, etch_clamp_a = _apply_model6_reflection_gaussian_redepo_step(
                        state,
                        deposition_a=sputter_deposition_sub_a,
                        sputter_strength_a=sputter_sub_a,
                        sputter_peak_pct=sputter_peak_pct,
                        sputter_peak_angle_deg=sputter_peak_angle_deg,
                        sputter_width_deg=sputter_width_deg,
                        sputter_smoothing_a=sputter_smoothing_a,
                        reparam_ds_a=reparam_ds_a,
                        ion_transmission_enabled=ion_transmission_enabled,
                        ion_transmission_override=ion_transmission_override,
                        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
                        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
                        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
                        ion_transmission_floor_pct=ion_transmission_floor_pct,
                        ion_transmission_curve_power=ion_transmission_curve_power,
                        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
                        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
                        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
                        redepo_efficiency_pct=redepo_efficiency_pct,
                        angular_spread_deg=redepo_emit_power,
                        specular_bias_pct=redepo_distance_power,
                        redepo_neighbor_exclusion=redepo_neighbor_exclusion,
                        redepo_max_distance_a=redepo_max_distance_a,
                    )
                    cycle_redepo_overlay.extend(_snapshot_redepo_overlay_samples(state.meta))
                    cycle_etch_overlay.extend(_snapshot_etch_overlay_samples(state.meta))
                    cycle_transport_lines.extend(_snapshot_transport_line_samples(state.meta))
                elif redepo_active:
                    angles, responses, etch_clamp_a = _apply_model4_redeposition_step(
                        state,
                        deposition_a=sputter_deposition_sub_a,
                        sputter_strength_a=sputter_sub_a,
                        sputter_peak_pct=sputter_peak_pct,
                        sputter_peak_angle_deg=sputter_peak_angle_deg,
                        sputter_width_deg=sputter_width_deg,
                        sputter_smoothing_a=sputter_smoothing_a,
                        reparam_ds_a=reparam_ds_a,
                        redepo_source_model=redepo_source_model,
                        redepo_efficiency_pct=redepo_efficiency_pct,
                        redepo_emit_power=redepo_emit_power,
                        redepo_distance_power=redepo_distance_power,
                        redepo_neighbor_exclusion=redepo_neighbor_exclusion,
                        redepo_max_distance_a=redepo_max_distance_a,
                        redepo_soft_los_radius_points=redepo_soft_los_radius_points,
                        redepo_transport_model=redepo_transport_model,
                        redepo_ray_count=redepo_ray_count,
                        redepo_footprint_sigma_a=redepo_footprint_sigma_a,
                        redepo_footprint_radius_sigma=redepo_footprint_radius_sigma,
                        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
                        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
                        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
                        ion_transmission_floor_pct=ion_transmission_floor_pct,
                        ion_transmission_curve_power=ion_transmission_curve_power,
                        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
                        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
                        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
                    )
                    cycle_redepo_overlay.extend(_snapshot_redepo_overlay_samples(state.meta))
                    cycle_etch_overlay.extend(_snapshot_etch_overlay_samples(state.meta))
                else:
                    angles, responses, etch_clamp_a = _apply_direct_sputter_step(
                        state,
                        deposition_a=sputter_deposition_sub_a,
                        sputter_strength_a=sputter_sub_a,
                        sputter_peak_pct=sputter_peak_pct,
                        sputter_peak_angle_deg=sputter_peak_angle_deg,
                        sputter_width_deg=sputter_width_deg,
                        sputter_smoothing_a=sputter_smoothing_a,
                        reparam_ds_a=reparam_ds_a,
                        ion_transmission_enabled=ion_transmission_enabled,
                        ion_transmission_override=ion_transmission_override,
                        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
                        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
                        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
                        ion_transmission_floor_pct=ion_transmission_floor_pct,
                        ion_transmission_curve_power=ion_transmission_curve_power,
                        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
                        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
                        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
                        reflected_ion_enabled=reflected_ion_requested,
                        reflected_ion_strength_pct=reflected_ion_strength_pct,
                        reflected_ion_bowing_weight=reflected_ion_bowing_weight,
                        reflected_ion_microtrench_weight=reflected_ion_microtrench_weight,
                        reflected_ion_range_a=reflected_ion_range_a,
                    )
                    cycle_etch_overlay.extend(_snapshot_etch_overlay_samples(state.meta))
                if detail_cb is not None:
                    detail_cb(
                        {
                            "kind": detail_kind,
                            "phase": "done",
                            "step": int(step),
                            "substep": int(substep_idx + 1),
                            "substeps": int(substeps),
                            "points": int(len(state.surface.points)),
                        }
                    )
                if angles:
                    state.meta["sputter_last_incident_angle_min_deg"] = min(angles)
                    state.meta["sputter_last_incident_angle_max_deg"] = max(angles)
                if responses:
                    state.meta["sputter_last_response_max"] = max(responses)
                state.meta["sputter_etch_clamp_a_per_cycle"] = float(etch_clamp_a * substeps)
            pending_redepo_overlay = cycle_redepo_overlay
            pending_etch_overlay = cycle_etch_overlay
            pending_transport_lines = cycle_transport_lines
        else:
            if inhibition_active:
                substeps = _depth_depo_internal_substeps(angstrom_per_cycle, reparam_ds_a)
                state.meta["inhibition_internal_substeps"] = int(substeps)
                deposition_sub_a = angstrom_per_cycle / float(substeps)
                for substep_idx in range(substeps):
                    if canceled():
                        raise SimulationCanceled()
                    _apply_inhibition_deposition_step(
                        state,
                        depth_cfg,
                        deposition_a=deposition_sub_a,
                        reparam_ds_a=reparam_ds_a,
                        cycle_index=int(step + 1),
                    )
                    if detail_cb is not None:
                        detail_cb(
                            {
                                "kind": "inhibition_deposition_substep",
                                "step": int(step),
                                "substep": int(substep_idx + 1),
                                "substeps": int(substeps),
                                "points": int(len(state.surface.points)),
                            }
                        )
            elif depth_deposition_active:
                substeps = _depth_depo_internal_substeps(angstrom_per_cycle, reparam_ds_a)
                state.meta["depth_deposition_internal_substeps"] = int(substeps)
                deposition_sub_a = angstrom_per_cycle / float(substeps)
                for substep_idx in range(substeps):
                    if canceled():
                        raise SimulationCanceled()
                    _apply_depth_deposition_step(
                        state,
                        depth_cfg,
                        deposition_a=deposition_sub_a,
                        reparam_ds_a=reparam_ds_a,
                        cycle_index=int(step + 1),
                    )
                    if detail_cb is not None:
                        detail_cb(
                            {
                                "kind": "depth_deposition_substep",
                                "step": int(step),
                                "substep": int(substep_idx + 1),
                                "substeps": int(substeps),
                                "points": int(len(state.surface.points)),
                            }
                        )
            elif angstrom_per_cycle > 0.0:
                grown_solid = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=angstrom_per_cycle)
                grown_surface = _extract_surface_from_solid(state, grown_solid, state.surface.points)
                state.surface.points = equal_arc_resample(grown_surface, reparam_ds_a)
                if grown_solid:
                    state.solid_paths_i = grown_solid
        state.meta["step_idx"] = int(state.meta.get("step_idx", 0)) + 1
        state.meta["dr"] = float(angstrom_per_cycle)

    final_profile = _snapshot_profile(frame_profiles[-1] if frame_profiles else state.surface.points)
    sputter_excluded_effects = [
        "full ray tracing",
        "multi-bounce reflection",
        "full ARDE transport solver",
        "diffusion attenuation",
        "charging",
    ]
    if not redepo_active:
        sputter_excluded_effects.insert(4, "redeposition")
    if not lf_overhang_requested:
        sputter_excluded_effects.insert(4, "LF-bias overhang proxy")
    if not closure_redepo_requested:
        sputter_excluded_effects.insert(4, "etch+redepo closure proxy")
    model4_source_uses_ion_transmission = bool(redepo_active and redepo_source_model == "model2")
    reported_ion_transmission_enabled = bool(
        ion_transmission_enabled or model4_source_uses_ion_transmission or closure_redepo_requested
    )
    if not reported_ion_transmission_enabled:
        sputter_excluded_effects.extend(["depth attenuation", "visibility", "geometric shadowing"])
    reflected_ion_active = bool(
        sputter_active
        and reflected_ion_requested
        and state.meta.get("reflected_ion_active_last", False)
    )
    if not reflected_ion_active:
        sputter_excluded_effects.insert(0, "reflected ion")
        sputter_excluded_effects.insert(1, "microtrenching")
    reflected_total = float(state.meta.get("reflected_ion_total_last", 0.0) or 0.0)
    direct_total = float(state.meta.get("direct_sputter_total_last", 0.0) or 0.0)
    redepo_summary = dict(
        state.meta.get(
            "model6_reflection_redepo_debug_summary_last",
            state.meta.get("model4_redepo_debug_summary_last", {}),
        )
    )
    redepo_total_removed_mass = float(
        state.meta.get(
            "model6_reflection_redepo_total_removed_mass_last",
            state.meta.get("model4_redepo_total_removed_mass_last", 0.0),
        )
        or 0.0
    )
    redepo_total_mass = float(
        state.meta.get(
            "model6_reflection_redepo_total_mass_last",
            state.meta.get("model4_redepo_total_mass_last", 0.0),
        )
        or 0.0
    )
    lf_overhang_summary = dict(state.meta.get("model7_lf_overhang_debug_summary_last", {}))
    lf_overhang_total_removed_mass = float(
        state.meta.get("model7_lf_overhang_total_removed_mass_last", 0.0) or 0.0
    )
    lf_overhang_total_redepo_mass = float(
        state.meta.get("model7_lf_overhang_total_redepo_mass_last", 0.0) or 0.0
    )
    closure_redepo_summary = dict(state.meta.get("model8_closure_redepo_debug_summary_last", {}))
    closure_redepo_total_removed_mass = float(
        state.meta.get("model8_closure_redepo_total_removed_mass_last", 0.0) or 0.0
    )
    closure_redepo_total_mass = float(
        state.meta.get("model8_closure_redepo_total_mass_last", 0.0) or 0.0
    )
    depth_closure_probe = dict(state.meta.get("depth_closure_probe_last", {}))
    growth_model = (
        "integrated_inhibition_depo_sputter_closure_redepo"
        if sputter_active and closure_redepo_requested and inhibition_active
        else "integrated_depth_depo_sputter_closure_redepo"
        if sputter_active and closure_redepo_requested and depth_deposition_active
        else "etch_redepo_closure"
        if sputter_active and closure_redepo_requested
        else
        "integrated_inhibition_depo_sputter_redepo_lf_overhang"
        if sputter_active and lf_overhang_requested and redepo_active and inhibition_active
        else "integrated_depth_depo_sputter_redepo_lf_overhang"
        if sputter_active and lf_overhang_requested and redepo_active and depth_deposition_active
        else "integrated_depo_sputter_redepo_lf_overhang"
        if sputter_active and lf_overhang_requested and redepo_active
        else "integrated_inhibition_depo_sputter_lf_overhang"
        if sputter_active and lf_overhang_requested and inhibition_active
        else "integrated_depth_depo_sputter_lf_overhang"
        if sputter_active and lf_overhang_requested and depth_deposition_active
        else "lf_bias_overhang_proxy"
        if sputter_active and lf_overhang_requested
        else "integrated_inhibition_depo_sputter_redepo"
        if sputter_active and redepo_active and inhibition_active
        else "integrated_depth_depo_sputter_redepo"
        if sputter_active and redepo_active and depth_deposition_active
        else "integrated_depo_sputter_redepo"
        if sputter_active and redepo_active and not model6_redepo_active
        else "normal_specular_lobe_redepo"
        if sputter_active and model6_redepo_active
        else "integrated_inhibition_depo_sputter"
        if sputter_active and inhibition_active
        else "integrated_depth_depo_sputter"
        if sputter_active and depth_deposition_active
        else "ion_transmission_direct_sputter"
        if sputter_active and ion_transmission_enabled
        else "direct_angle_sputter"
        if sputter_active
        else "inhibition_weighted_deposition"
        if inhibition_active
        else "depth_dependent_deposition"
        if depth_deposition_active
        else "conformal_offset"
    )
    propagation = (
        "offset_boolean_plus_inhibition_depo_direct_angle_sputter_closure_redepo"
        if sputter_active and closure_redepo_requested and inhibition_active
        else "offset_boolean_plus_depth_depo_direct_angle_sputter_closure_redepo"
        if sputter_active and closure_redepo_requested and depth_deposition_active
        else "offset_boolean_plus_direct_angle_sputter_closure_redepo"
        if sputter_active and closure_redepo_requested
        else
        "offset_boolean_plus_inhibition_depo_direct_angle_sputter_redepo_lf_overhang"
        if sputter_active and lf_overhang_requested and redepo_active and inhibition_active
        else "offset_boolean_plus_depth_depo_direct_angle_sputter_redepo_lf_overhang"
        if sputter_active and lf_overhang_requested and redepo_active and depth_deposition_active
        else "offset_boolean_plus_direct_angle_sputter_redepo_lf_overhang"
        if sputter_active and lf_overhang_requested and redepo_active
        else "offset_boolean_plus_inhibition_depo_direct_angle_sputter_lf_overhang"
        if sputter_active and lf_overhang_requested and inhibition_active
        else "offset_boolean_plus_depth_depo_direct_angle_sputter_lf_overhang"
        if sputter_active and lf_overhang_requested and depth_deposition_active
        else "offset_boolean_plus_direct_angle_sputter_lf_overhang"
        if sputter_active and lf_overhang_requested
        else "offset_boolean_plus_inhibition_depo_direct_angle_sputter_redepo"
        if sputter_active and redepo_active and inhibition_active
        else "offset_boolean_plus_depth_depo_direct_angle_sputter_redepo"
        if sputter_active and redepo_active and depth_deposition_active and not model6_redepo_active
        else "offset_boolean_plus_direct_angle_sputter_normal_specular_lobe_redepo"
        if sputter_active and model6_redepo_active
        else "offset_boolean_plus_inhibition_depo_direct_angle_sputter"
        if sputter_active and inhibition_active
        else "offset_boolean_plus_depth_depo_direct_angle_sputter"
        if sputter_active and depth_deposition_active
        else "offset_boolean_plus_direct_angle_sputter_redepo"
        if redepo_active
        else "offset_boolean_plus_direct_angle_sputter"
        if sputter_active
        else "vertex_normal_inhibition_depo_post_closure_fill"
        if inhibition_active
        else "vertex_normal_depth_depo_post_closure_fill"
        if depth_deposition_active
        else "offset_boolean_external_air_limited"
    )
    return TrenchDepoResult(
        frame_steps=frame_steps,
        frame_profiles=frame_profiles,
        frame_voids=frame_voids,
        final_profile=final_profile,
        meta={
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "growth_model": growth_model,
            "propagation": propagation,
            "cycles": int(cycles),
            "emulator_number": int(emulator_number),
            "angstrom_per_cycle": float(angstrom_per_cycle),
            "reparam_ds_a": float(reparam_ds_a),
            "sputter_enabled": bool(allowed_sputter and cfg.sputter_enabled),
            "sputter_active": bool(sputter_active),
            "sputter_model": "direct_angle_gaussian" if sputter_active else "off",
            "sputter_strength_a_per_cycle": float(sputter_strength_a),
            "sputter_peak_pct": float(sputter_peak_pct),
            "sputter_peak_angle_deg": float(sputter_peak_angle_deg),
            "sputter_width_deg": float(sputter_width_deg),
            "sputter_smoothing_a": float(sputter_smoothing_a),
            "ion_transmission_enabled": bool(reported_ion_transmission_enabled),
            "ion_transmission_override": (
                None if ion_transmission_override is None else float(ion_transmission_override)
            ),
            "ion_transmission_start_depth_pct": float(ion_transmission_start_depth_pct),
            "ion_transmission_end_depth_pct": float(ion_transmission_end_depth_pct),
            "ion_transmission_decay_strength_pct": float(ion_transmission_decay_strength_pct),
            "ion_transmission_floor_pct": float(ion_transmission_floor_pct),
            "ion_transmission_curve_power": float(ion_transmission_curve_power),
            "ion_transmission_aperture_shadow_pct": float(ion_transmission_aperture_shadow_pct),
            "ion_transmission_lateral_shadow_pct": float(ion_transmission_lateral_shadow_pct),
            "ion_transmission_edge_shadow_pct": float(ion_transmission_edge_shadow_pct),
            "ion_transmission_model": (
                "depth_curve_opening_width_sky_visibility"
                if reported_ion_transmission_enabled and sputter_active
                else "off"
            ),
            "ion_debug_fields_last": dict(state.meta.get("direct_sputter_debug_fields_last", {})),
            "ion_debug_summary_last": dict(state.meta.get("direct_sputter_debug_summary_last", {})),
            "reflected_ion_enabled": False,
            "reflected_ion_active": bool(reflected_ion_active),
            "reflected_ion_model": "zone_weighted_one_bounce" if reflected_ion_active else "off",
            "reflected_ion_strength_pct": float(reflected_ion_strength_pct),
            "reflected_ion_bowing_weight": float(reflected_ion_bowing_weight),
            "reflected_ion_microtrench_weight": float(reflected_ion_microtrench_weight),
            "reflected_ion_range_a": float(reflected_ion_range_a),
            "reflected_ion_debug_fields_last": dict(state.meta.get("direct_sputter_debug_fields_last", {})),
            "reflected_ion_debug_summary_last": dict(state.meta.get("direct_sputter_debug_summary_last", {})),
            "reflected_ion_total_last": float(reflected_total),
            "direct_sputter_total_last": float(direct_total),
            "reflected_direct_ratio_last": float(reflected_total / direct_total) if direct_total > 1e-12 else 0.0,
            "redepo_enabled": bool(model6_redepo_requested),
            "redepo_active": bool(redepo_active and redepo_total_mass > 0.0),
            "redepo_model": (
                "normal_specular_lobe_los"
                if model6_redepo_active
                else str(state.meta.get("model4_redepo_transport_model_last", redepo_transport_model))
                if redepo_active
                else "off"
            ),
            "redepo_source_model": str(redepo_source_model),
            "redepo_efficiency_pct": float(redepo_efficiency_pct),
            "redepo_emit_power": float(redepo_emit_power),
            "redepo_distance_power": float(redepo_distance_power),
            "redepo_neighbor_exclusion": int(redepo_neighbor_exclusion),
            "redepo_max_distance_a": float(redepo_max_distance_a),
            "redepo_soft_los_radius_points": int(redepo_soft_los_radius_points),
            "redepo_transport_model": str(redepo_transport_model),
            "redepo_ray_count": int(redepo_ray_count),
            "redepo_footprint_sigma_a": float(redepo_footprint_sigma_a),
            "redepo_footprint_radius_sigma": float(redepo_footprint_radius_sigma),
            "redepo_debug_fields_last": dict(
                state.meta.get(
                    "model6_reflection_redepo_debug_fields_last",
                    state.meta.get("model4_redepo_debug_fields_last", {}),
                )
            ),
            "redepo_debug_summary_last": redepo_summary,
            "frame_redepo_overlays": [
                [[float(x), float(y), float(value)] for x, y, value in overlay]
                for overlay in frame_redepo_overlays
            ],
            "frame_etch_overlays": [
                [[float(x), float(y), float(value)] for x, y, value in overlay]
                for overlay in frame_etch_overlays
            ],
            "frame_transport_lines": [
                [
                    [float(x1), float(y1), float(x2), float(y2), float(value)]
                    for x1, y1, x2, y2, value in lines
                ]
                for lines in frame_transport_lines
            ],
            "redepo_overlay_description": (
                "Positive redeposition target samples collected during the cycle that produced each frame."
            ),
            "etch_overlay_description": (
                "Effective etch source samples collected during the cycle that produced each frame."
            ),
            "redepo_total_removed_mass_last": float(redepo_total_removed_mass),
            "redepo_total_mass_last": float(redepo_total_mass),
            "redepo_capture_ratio_last": (
                float(redepo_total_mass / redepo_total_removed_mass)
                if redepo_total_removed_mass > 1e-12
                else 0.0
            ),
            "redepo_active_source_count_last": int(
                state.meta.get(
                    "model6_reflection_redepo_active_source_count_last",
                    state.meta.get("model4_redepo_active_source_count_last", 0),
                )
            ),
            "redepo_active_target_count_last": int(
                state.meta.get("model6_reflection_redepo_active_target_count_last", 0)
            ),
            "lf_overhang_enabled": False,
            "lf_overhang_requested": bool(lf_overhang_requested),
            "lf_overhang_active": bool(lf_overhang_active),
            "lf_overhang_model": "upper_source_normal_lobe_los_survival" if lf_overhang_requested else "off",
            "lf_overhang_dose": float(lf_overhang_dose),
            "lf_overhang_sputter_gain": float(lf_overhang_sputter_gain),
            "lf_overhang_redepo_fraction_pct": float(lf_overhang_redepo_fraction_pct),
            "lf_overhang_survival_penalty": float(lf_overhang_survival_penalty),
            "lf_overhang_width_a": float(lf_overhang_width_a),
            "lf_overhang_debug_fields_last": dict(state.meta.get("model7_lf_overhang_debug_fields_last", {})),
            "lf_overhang_debug_summary_last": lf_overhang_summary,
            "lf_overhang_total_removed_mass_last": float(lf_overhang_total_removed_mass),
            "lf_overhang_total_redepo_mass_last": float(lf_overhang_total_redepo_mass),
            "lf_overhang_capture_ratio_last": (
                float(lf_overhang_total_redepo_mass / lf_overhang_total_removed_mass)
                if lf_overhang_total_removed_mass > 1e-12
                else 0.0
            ),
            "lf_overhang_active_source_count_last": int(
                state.meta.get("model7_lf_overhang_active_source_count_last", 0)
            ),
            "lf_overhang_active_target_count_last": int(
                state.meta.get("model7_lf_overhang_active_target_count_last", 0)
            ),
            "closure_redepo_enabled": False,
            "closure_redepo_requested": bool(closure_redepo_requested),
            "closure_redepo_active": bool(closure_redepo_active and closure_redepo_total_mass > 0.0),
            "closure_redepo_model": (
                "all_positive_etch_sources_first_hit_normal_lobe_survival"
                if closure_redepo_requested
                else "off"
            ),
            "closure_redepo_efficiency_pct": float(closure_redepo_efficiency_pct),
            "closure_redepo_shadow_gain": float(closure_redepo_shadow_gain),
            "closure_redepo_width_a": float(closure_redepo_width_a),
            "closure_redepo_survival_penalty": float(closure_redepo_survival_penalty),
            "closure_redepo_smoothing_a": float(closure_redepo_smoothing_a),
            "closure_redepo_debug_fields_last": dict(
                state.meta.get("model8_closure_redepo_debug_fields_last", {})
            ),
            "closure_redepo_debug_summary_last": closure_redepo_summary,
            "closure_redepo_total_removed_mass_last": float(closure_redepo_total_removed_mass),
            "closure_redepo_total_mass_last": float(closure_redepo_total_mass),
            "closure_redepo_capture_ratio_last": (
                float(closure_redepo_total_mass / closure_redepo_total_removed_mass)
                if closure_redepo_total_removed_mass > 1e-12
                else 0.0
            ),
            "closure_redepo_active_source_count_last": int(
                state.meta.get("model8_closure_redepo_active_source_count_last", 0)
            ),
            "closure_redepo_active_target_count_last": int(
                state.meta.get("model8_closure_redepo_active_target_count_last", 0)
            ),
            "closure_redepo_closure_probe_last": dict(
                state.meta.get("model8_closure_redepo_closure_probe_last", {})
            ),
            "deposition_depth_enabled": bool(allowed_depth_deposition and cfg.deposition_depth_enabled),
            "deposition_depth_active": bool(depth_deposition_active),
            "deposition_feature_type": str(deposition_feature_type),
            "deposition_feature_width_a": float(deposition_feature_width_a),
            "deposition_feature_depth_a": float(deposition_feature_depth_a),
            "deposition_feature_length_a": (
                None if deposition_feature_length_a is None else float(deposition_feature_length_a)
            ),
            "deposition_attenuation_model": str(deposition_attenuation_model),
            "deposition_depth_decay_k": float(deposition_depth_decay_k),
            "deposition_depth_decay_power": float(deposition_depth_decay_power),
            "deposition_min_ratio": float(deposition_min_ratio),
            "deposition_use_equivalent_ar": bool(cfg.deposition_use_equivalent_ar),
            "deposition_closure_threshold_a": float(deposition_closure_threshold_a),
            "deposition_closure_probe_last": depth_closure_probe,
            "deposition_closure_detected": bool(state.meta.get("depth_closure_detected", False)),
            "deposition_closure_step": (
                None
                if state.meta.get("depth_closure_step") is None
                else int(state.meta.get("depth_closure_step", 0))
            ),
            "deposition_closure_depth_a": float(state.meta.get("depth_closure_depth_a", 0.0) or 0.0),
            "deposition_closure_void_area_a2": float(state.meta.get("depth_closure_void_area_a2", 0.0) or 0.0),
            "deposition_post_closure_fill_pct_hole": float(deposition_post_closure_fill_pct_hole),
            "deposition_post_closure_fill_pct_line": float(deposition_post_closure_fill_pct_line),
            "deposition_line_open_path_factor": float(deposition_line_open_path_factor),
            "deposition_residual_fill_decay_length_a": float(deposition_residual_fill_decay_length_a),
            "deposition_residual_fill_distribution": str(deposition_residual_fill_distribution),
            "deposition_max_depo_per_cell_a": (
                None if deposition_max_depo_per_cell_a is None else float(deposition_max_depo_per_cell_a)
            ),
            "deposition_conserve_volume": bool(cfg.deposition_conserve_volume),
            "deposition_post_closure_allowed_fill_area_a2": float(
                state.meta.get("depth_post_closure_allowed_fill_area_a2", 0.0) or 0.0
            ),
            "deposition_post_closure_budget_used_area_a2": float(
                state.meta.get("depth_post_closure_budget_used_area_a2", 0.0) or 0.0
            ),
            "deposition_post_closure_last_fill_area_a2": float(
                state.meta.get("depth_post_closure_last_fill_area_a2", 0.0) or 0.0
            ),
            "deposition_depth_debug_fields_last": dict(state.meta.get("depth_deposition_debug_fields_last", {})),
            "deposition_depth_debug_summary_last": dict(state.meta.get("depth_deposition_debug_summary_last", {})),
            "deposition_depth_internal_substeps": int(state.meta.get("depth_deposition_internal_substeps", 1)),
            "inhibition_enabled": bool(allowed_inhibition and cfg.inhibition_enabled),
            "inhibition_active": bool(inhibition_active),
            "inhibition_process_model": str(inhibition_process_model),
            "inhibition_strength_pct": float(inhibition_strength_pct),
            "inhibition_penetration_depth_a": float(inhibition_penetration_depth_a),
            "inhibition_decay_power": float(inhibition_decay_power),
            "inhibition_min_growth_ratio": float(inhibition_min_growth_ratio),
            "inhibition_bottom_boost_pct": float(inhibition_bottom_boost_pct),
            "inhibition_peald_recombination_pct": float(inhibition_peald_recombination_pct),
            "inhibition_smoothing_a": float(inhibition_smoothing_a),
            "inhibition_debug_fields_last": dict(state.meta.get("inhibition_debug_fields_last", {})),
            "inhibition_debug_summary_last": dict(state.meta.get("inhibition_debug_summary_last", {})),
            "inhibition_internal_substeps": int(state.meta.get("inhibition_internal_substeps", 1)),
            "direct_sputter_internal_substeps": int(state.meta.get("direct_sputter_internal_substeps", 1)),
            "sputter_excluded_effects": sputter_excluded_effects,
            "initial_points": int(len(initial_points)),
            "final_points": int(len(final_profile)),
        },
    )


def run_trench_depo_legacy_sputter(
    config: Optional[TrenchDepoConfig] = None,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    detail_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> TrenchDepoResult:
    cfg = config or TrenchDepoConfig()
    cycles = _coerce_cycles(cfg.cycles)
    angstrom_per_cycle = _coerce_non_negative_float(cfg.angstrom_per_cycle, name="angstrom_per_cycle")
    reparam_ds_a = _coerce_positive_float(cfg.reparam_ds_a, name="reparam_ds_a")
    sputter_strength_a = _coerce_non_negative_float(
        cfg.sputter_strength_a_per_cycle,
        name="sputter_strength_a_per_cycle",
    )
    sputter_peak_pct = max(0.0, min(100.0, float(cfg.sputter_peak_pct)))
    sputter_peak_angle_deg = max(0.0, min(89.9, float(cfg.sputter_peak_angle_deg)))
    sputter_width_deg = _coerce_positive_float(cfg.sputter_width_deg, name="sputter_width_deg")
    sputter_active = bool(cfg.sputter_enabled) and sputter_strength_a > 0.0
    initial_points = _coerce_points(cfg.points)

    OffsetBoolean.require_backend()

    state = init_simulation_state(initial_points, units="A", reparam_ds_a=reparam_ds_a)
    # GapSim angle-only comparison: keep the existing engine's substep and
    # cleanup path, but disable depth attenuation, visibility, and redeposition.
    step_scale_a = max(float(angstrom_per_cycle), float(sputter_strength_a) if sputter_active else 0.0)
    deposition_flux_scale = float(angstrom_per_cycle) / step_scale_a if step_scale_a > 0.0 else 0.0
    legacy_strength_pct = 0.0
    if sputter_active and step_scale_a > 0.0:
        legacy_strength_pct = (
            100.0
            * float(sputter_strength_a)
            * (float(sputter_peak_pct) / 100.0)
            / max(step_scale_a * 3.0, 1e-9)
        )
    model = SputterRedepositionFluxModel(
        _ConstantFluxModel(deposition_flux_scale),
        etch_reference_model=_ConstantFluxModel(1.0),
        sputter_enabled=sputter_active,
        sputter_strength_pct=legacy_strength_pct,
        sputter_peak_angle_deg=sputter_peak_angle_deg,
        sputter_angle_sigma_deg=sputter_width_deg,
        sputter_depth_decay_length_a=0.0,
        sputter_vis_exponent=0.0,
        redepo_enabled=False,
    )
    propagator = VertexNormalPropagator()
    cleanup = TopologyCleanup()

    frame_steps: List[int] = []
    frame_profiles: List[List[Point]] = []
    frame_voids: List[List[List[Point]]] = []

    def canceled() -> bool:
        return bool(cancel_check()) if cancel_check is not None else False

    for step in range(cycles + 1):
        if canceled():
            raise SimulationCanceled()

        pts_now = _snapshot_profile(state.surface.points)
        frame_steps.append(int(step))
        frame_profiles.append(pts_now)
        frame_voids.append(_snapshot_voids(state))

        if progress_cb is not None:
            progress_cb(int(step), int(cycles))
        if detail_cb is not None:
            detail_cb(
                {
                    "kind": "legacy_cycle",
                    "step": int(step),
                    "total": int(cycles),
                    "points": int(len(pts_now)),
                }
            )

        if step == cycles:
            break

        state = deposit_step(
            step_scale_a,
            state,
            model=model,
            propagator=propagator,
            cleanup=cleanup,
            detail_cb=detail_cb,
            cancel_check=cancel_check,
        )

    final_profile = _snapshot_profile(frame_profiles[-1] if frame_profiles else state.surface.points)
    return TrenchDepoResult(
        frame_steps=frame_steps,
        frame_profiles=frame_profiles,
        frame_voids=frame_voids,
        final_profile=final_profile,
        meta={
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "growth_model": "gapsim_angle_only_sputter_compare",
            "propagation": "gapsim_deposit_step_vertex_normal_substeps",
            "cycles": int(cycles),
            "emulator_number": int(getattr(cfg, "emulator_number", 0) or 0),
            "angstrom_per_cycle": float(angstrom_per_cycle),
            "legacy_step_scale_a": float(step_scale_a),
            "legacy_deposition_flux_scale": float(deposition_flux_scale),
            "reparam_ds_a": float(reparam_ds_a),
            "sputter_enabled": bool(cfg.sputter_enabled),
            "sputter_active": bool(sputter_active),
            "sputter_model": "gapsim_angle_only_sputter" if sputter_active else "off",
            "sputter_strength_a_per_cycle": float(sputter_strength_a),
            "sputter_peak_pct": float(sputter_peak_pct),
            "legacy_sputter_strength_pct": float(legacy_strength_pct),
            "sputter_peak_angle_deg": float(sputter_peak_angle_deg),
            "sputter_width_deg": float(sputter_width_deg),
            "sputter_depth_decay_length_a": 0.0,
            "sputter_vis_exponent": 0.0,
            "redepo_enabled": False,
            "initial_points": int(len(initial_points)),
            "final_points": int(len(final_profile)),
            "legacy_ion_substeps_last": int(state.meta.get("ion_substeps", 1)),
        },
    )


def run_trench_depo_legacy_redeposition(
    config: Optional[TrenchDepoConfig] = None,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    detail_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> TrenchDepoResult:
    cfg = config or TrenchDepoConfig()
    cycles = _coerce_cycles(cfg.cycles)
    angstrom_per_cycle = _coerce_non_negative_float(cfg.angstrom_per_cycle, name="angstrom_per_cycle")
    requested_reparam_ds_a = _coerce_positive_float(cfg.reparam_ds_a, name="reparam_ds_a")
    reparam_ds_a = max(float(requested_reparam_ds_a), 20.0)
    sputter_strength_a = _coerce_non_negative_float(
        cfg.sputter_strength_a_per_cycle,
        name="sputter_strength_a_per_cycle",
    )
    sputter_peak_pct = max(0.0, min(100.0, float(cfg.sputter_peak_pct)))
    sputter_peak_angle_deg = max(0.0, min(89.9, float(cfg.sputter_peak_angle_deg)))
    sputter_width_deg = _coerce_positive_float(cfg.sputter_width_deg, name="sputter_width_deg")
    redepo_efficiency_pct = max(0.0, min(100.0, float(cfg.redepo_efficiency_pct)))
    redepo_emit_power = max(0.0, float(cfg.redepo_emit_power))
    redepo_lobe_sigma_deg = max(
        1.0,
        min(60.0, 24.0 / max(0.25, redepo_emit_power) if redepo_emit_power > 0.0 else 60.0),
    )
    sputter_active = bool(cfg.sputter_enabled) and sputter_strength_a > 0.0
    redepo_active = bool(cfg.redepo_enabled) and sputter_active and redepo_efficiency_pct > 0.0
    initial_points = _coerce_points(cfg.points)

    OffsetBoolean.require_backend()

    state = init_simulation_state(initial_points, units="A", reparam_ds_a=reparam_ds_a)
    # Original GapSim redeposition comparison: use the engine flux model's
    # unbinned per-vertex LOS redepo path, while keeping the same geometry and
    # user-facing mini-emulator etch/redepo settings.
    step_scale_a = max(float(angstrom_per_cycle), float(sputter_strength_a) if sputter_active else 0.0)
    deposition_flux_scale = float(angstrom_per_cycle) / step_scale_a if step_scale_a > 0.0 else 0.0
    legacy_strength_pct = 0.0
    if sputter_active and step_scale_a > 0.0:
        legacy_strength_pct = (
            100.0
            * float(sputter_strength_a)
            * (float(sputter_peak_pct) / 100.0)
            / max(step_scale_a * 3.0, 1e-9)
        )
    model = SputterRedepositionFluxModel(
        _ConstantFluxModel(deposition_flux_scale),
        etch_reference_model=_ConstantFluxModel(1.0),
        sputter_enabled=sputter_active,
        sputter_strength_pct=legacy_strength_pct,
        sputter_peak_angle_deg=sputter_peak_angle_deg,
        sputter_angle_sigma_deg=sputter_width_deg,
        sputter_depth_decay_length_a=0.0,
        sputter_vis_exponent=0.0,
        redepo_enabled=redepo_active,
        redepo_efficiency_pct=redepo_efficiency_pct,
        redepo_lobe_sigma_deg=redepo_lobe_sigma_deg,
    )
    propagator = VertexNormalPropagator()
    cleanup = TopologyCleanup()

    frame_steps: List[int] = []
    frame_profiles: List[List[Point]] = []
    frame_voids: List[List[List[Point]]] = []

    def canceled() -> bool:
        return bool(cancel_check()) if cancel_check is not None else False

    for step in range(cycles + 1):
        if canceled():
            raise SimulationCanceled()

        pts_now = _snapshot_profile(state.surface.points)
        frame_steps.append(int(step))
        frame_profiles.append(pts_now)
        frame_voids.append(_snapshot_voids(state))

        if progress_cb is not None:
            progress_cb(int(step), int(cycles))
        if detail_cb is not None:
            detail_cb(
                {
                    "kind": "legacy_redepo_cycle",
                    "step": int(step),
                    "total": int(cycles),
                    "points": int(len(pts_now)),
                }
            )

        if step == cycles:
            break

        state = deposit_step(
            step_scale_a,
            state,
            model=model,
            propagator=propagator,
            cleanup=cleanup,
            detail_cb=detail_cb,
            cancel_check=cancel_check,
        )

    final_profile = _snapshot_profile(frame_profiles[-1] if frame_profiles else state.surface.points)
    total_etch_mass = float(state.meta.get("redepo_total_etch_mass", 0.0) or 0.0)
    total_redepo_mass = float(state.meta.get("redepo_total_mass", 0.0) or 0.0)
    return TrenchDepoResult(
        frame_steps=frame_steps,
        frame_profiles=frame_profiles,
        frame_voids=frame_voids,
        final_profile=final_profile,
        meta={
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "growth_model": "gapsim_legacy_sputter_redeposition_compare",
            "propagation": "gapsim_deposit_step_vertex_normal_substeps",
            "cycles": int(cycles),
            "emulator_number": int(getattr(cfg, "emulator_number", 0) or 0),
            "angstrom_per_cycle": float(angstrom_per_cycle),
            "legacy_step_scale_a": float(step_scale_a),
            "legacy_deposition_flux_scale": float(deposition_flux_scale),
            "reparam_ds_a": float(reparam_ds_a),
            "sputter_enabled": bool(cfg.sputter_enabled),
            "sputter_active": bool(sputter_active),
            "sputter_model": "gapsim_angle_sputter" if sputter_active else "off",
            "sputter_strength_a_per_cycle": float(sputter_strength_a),
            "sputter_peak_pct": float(sputter_peak_pct),
            "legacy_sputter_strength_pct": float(legacy_strength_pct),
            "sputter_peak_angle_deg": float(sputter_peak_angle_deg),
            "sputter_width_deg": float(sputter_width_deg),
            "sputter_depth_decay_length_a": 0.0,
            "sputter_vis_exponent": 0.0,
            "redepo_enabled": bool(cfg.redepo_enabled),
            "redepo_active": bool(redepo_active and total_redepo_mass > 0.0),
            "redepo_model": "gapsim_original_per_vertex_los" if redepo_active else "off",
            "redepo_efficiency_pct": float(redepo_efficiency_pct),
            "redepo_emit_power": float(redepo_emit_power),
            "legacy_redepo_lobe_sigma_deg": float(redepo_lobe_sigma_deg),
            "redepo_total_removed_mass_last": float(total_etch_mass),
            "redepo_total_mass_last": float(total_redepo_mass),
            "redepo_capture_ratio_last": (
                float(total_redepo_mass / total_etch_mass)
                if total_etch_mass > 1e-12
                else 0.0
            ),
            "redepo_active_source_count_last": int(state.meta.get("redepo_active_source_count", 0) or 0),
            "redepo_mean_flux_last": float(state.meta.get("redepo_mean_flux", 0.0) or 0.0),
            "initial_points": int(len(initial_points)),
            "final_points": int(len(final_profile)),
            "legacy_ion_substeps_last": int(state.meta.get("ion_substeps", 1)),
            "legacy_ion_substep_policy_last": str(state.meta.get("ion_substep_policy", "")),
        },
    )
