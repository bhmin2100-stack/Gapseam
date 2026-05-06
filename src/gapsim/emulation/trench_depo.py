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
    deposit_step,
    _extract_surface_from_solid,
    equal_arc_resample,
    init_simulation_state,
    normalize_surface_order,
)
from gapsim.emulation.model4_redeposition import (
    Model4RedepositionParams,
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


@dataclass(frozen=True)
class TrenchDepoConfig:
    points: Sequence[Point] = DEFAULT_TRENCH_POINTS
    cycles: int = 20
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
    redepo_source_model: str = "model1"
    redepo_efficiency_pct: float = 25.0
    redepo_emit_power: float = 1.0
    redepo_distance_power: float = 1.0
    redepo_neighbor_exclusion: int = 2
    redepo_max_distance_a: float = 1800.0


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


def _redepo_source_model_key(value: str) -> str:
    raw = str(value or "model1").strip().lower().replace("-", "").replace("_", "")
    if raw in {"2", "model2", "m2", "ion", "iontransmission"}:
        return "model2"
    return "model1"


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
    use_model2_source = source_model == "model2"
    angles, responses, etch_clamp_a = _apply_direct_sputter_step(
        source_state,
        deposition_a=deposition_a,
        sputter_strength_a=sputter_strength_a,
        sputter_peak_pct=sputter_peak_pct,
        sputter_peak_angle_deg=sputter_peak_angle_deg,
        sputter_width_deg=sputter_width_deg,
        sputter_smoothing_a=sputter_smoothing_a,
        reparam_ds_a=reparam_ds_a,
        ion_transmission_enabled=use_model2_source,
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
        ),
    )
    dh_redepo = redepo.dh_redepo if len(redepo.dh_redepo) == len(grown_surface) else [0.0 for _ in grown_surface]
    proposed: List[Point] = []
    has_negative_net = False
    for idx, (x, y) in enumerate(grown_surface):
        nx, ny = normals[idx] if idx < len(normals) else (0.0, 1.0)
        etch_a = max(0.0, float(dh_etch[idx]))
        redepo_a = max(0.0, float(dh_redepo[idx]))
        net_from_previous = float(deposition_a) - etch_a + redepo_a
        if net_from_previous < 0.0:
            has_negative_net = True
        x2 = float(x + (redepo_a - etch_a) * nx)
        y2 = float(y + (redepo_a - etch_a) * ny)
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
    fields["total_etch_field"] = [round(float(v), 6) for v in total_etch]
    fields["net_growth_field"] = [
        round(float(deposition_a) - float(etch) + float(redepo_a), 6)
        for etch, redepo_a in zip(dh_etch, dh_redepo)
    ]
    summary = dict(source_state.meta.get("direct_sputter_debug_summary_last", {}))
    summary["redepo"] = dict(redepo.debug_summary)
    summary["total_etch"] = _field_summary_by_depth(grown_surface, total_etch)
    summary["net_growth"] = _field_summary_by_depth(
        grown_surface,
        [float(deposition_a) - float(etch) + float(redepo_a) for etch, redepo_a in zip(dh_etch, dh_redepo)],
    )
    state.meta["direct_sputter_debug_fields_last"] = fields
    state.meta["direct_sputter_debug_summary_last"] = summary
    state.meta["model4_redepo_debug_fields_last"] = fields
    state.meta["model4_redepo_debug_summary_last"] = summary
    state.meta["model4_redepo_source_model_last"] = source_model
    state.meta["model4_redepo_total_removed_mass_last"] = float(redepo.debug_summary.get("total_removed_mass", 0.0))
    state.meta["model4_redepo_total_mass_last"] = float(redepo.debug_summary.get("total_redepo_mass", 0.0))
    state.meta["model4_redepo_active_source_count_last"] = int(redepo.debug_summary.get("active_source_count", 0))
    state.meta["direct_sputter_total_last"] = float(sum(dh_etch))
    return angles, responses, etch_clamp_a


def _snapshot_profile(points: Sequence[Point]) -> List[Point]:
    return [(float(x), float(y)) for x, y in points]


def _snapshot_voids(state) -> List[List[Point]]:
    return [[(float(x), float(y)) for x, y in poly] for poly in OffsetBoolean.void_polygons_float(state)]


def _direct_sputter_internal_substeps(deposition_a: float, sputter_strength_a: float, reparam_ds_a: float) -> int:
    target_a = max(1.0, float(reparam_ds_a) * 0.75)
    max_move_a = max(abs(float(deposition_a)), abs(float(sputter_strength_a)))
    if max_move_a <= target_a:
        return 1
    return max(1, min(64, int(math.ceil(max_move_a / target_a))))


def _model4_redepo_internal_substeps(deposition_a: float, sputter_strength_a: float, reparam_ds_a: float) -> int:
    target_a = max(8.0, float(reparam_ds_a) * 4.0)
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
    if parameter in {"redepo_emit_power", "redepo_distance_power"}:
        return _coerce_non_negative_float(value, name=parameter)
    if parameter == "redepo_neighbor_exclusion":
        return float(_coerce_cycles(value))
    if parameter == "redepo_max_distance_a":
        return _coerce_non_negative_float(value, name="redepo_max_distance_a")
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
    ion_transmission_enabled = bool(cfg.ion_transmission_enabled)
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
    redepo_distance_power = _coerce_non_negative_float(cfg.redepo_distance_power, name="redepo_distance_power")
    redepo_neighbor_exclusion = _coerce_cycles(cfg.redepo_neighbor_exclusion)
    redepo_max_distance_a = _coerce_non_negative_float(cfg.redepo_max_distance_a, name="redepo_max_distance_a")
    sputter_active = bool(cfg.sputter_enabled) and sputter_strength_a > 0.0
    reflected_ion_requested = bool(cfg.reflected_ion_enabled) and reflected_ion_strength_pct > 0.0
    redepo_active = bool(cfg.redepo_enabled) and sputter_active and redepo_efficiency_pct > 0.0
    initial_points = _coerce_points(cfg.points)

    OffsetBoolean.require_backend()

    state = init_simulation_state(initial_points, units="A", reparam_ds_a=reparam_ds_a)
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
            state.meta["direct_sputter_internal_substeps"] = int(substeps)
            deposition_sub_a = angstrom_per_cycle / float(substeps)
            sputter_sub_a = sputter_strength_a / float(substeps)
            for substep_idx in range(substeps):
                if canceled():
                    raise SimulationCanceled()
                if redepo_active:
                    angles, responses, etch_clamp_a = _apply_model4_redeposition_step(
                        state,
                        deposition_a=deposition_sub_a,
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
                        ion_transmission_start_depth_pct=ion_transmission_start_depth_pct,
                        ion_transmission_end_depth_pct=ion_transmission_end_depth_pct,
                        ion_transmission_decay_strength_pct=ion_transmission_decay_strength_pct,
                        ion_transmission_floor_pct=ion_transmission_floor_pct,
                        ion_transmission_curve_power=ion_transmission_curve_power,
                        ion_transmission_aperture_shadow_pct=ion_transmission_aperture_shadow_pct,
                        ion_transmission_lateral_shadow_pct=ion_transmission_lateral_shadow_pct,
                        ion_transmission_edge_shadow_pct=ion_transmission_edge_shadow_pct,
                    )
                else:
                    angles, responses, etch_clamp_a = _apply_direct_sputter_step(
                        state,
                        deposition_a=deposition_sub_a,
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
                if detail_cb is not None:
                    detail_cb(
                        {
                            "kind": "model4_redepo_substep" if redepo_active else "direct_sputter_substep",
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
        else:
            if angstrom_per_cycle > 0.0:
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
    if not ion_transmission_enabled:
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
    redepo_summary = dict(state.meta.get("model4_redepo_debug_summary_last", {}))
    redepo_total_removed_mass = float(state.meta.get("model4_redepo_total_removed_mass_last", 0.0) or 0.0)
    redepo_total_mass = float(state.meta.get("model4_redepo_total_mass_last", 0.0) or 0.0)
    return TrenchDepoResult(
        frame_steps=frame_steps,
        frame_profiles=frame_profiles,
        frame_voids=frame_voids,
        final_profile=final_profile,
        meta={
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "growth_model": "conformal_offset",
            "propagation": (
                "offset_boolean_plus_direct_angle_sputter_redepo"
                if redepo_active
                else "offset_boolean_plus_direct_angle_sputter"
                if sputter_active
                else "offset_boolean_external_air_limited"
            ),
            "cycles": int(cycles),
            "angstrom_per_cycle": float(angstrom_per_cycle),
            "reparam_ds_a": float(reparam_ds_a),
            "sputter_enabled": bool(cfg.sputter_enabled),
            "sputter_active": bool(sputter_active),
            "sputter_model": "direct_angle_gaussian" if sputter_active else "off",
            "sputter_strength_a_per_cycle": float(sputter_strength_a),
            "sputter_peak_pct": float(sputter_peak_pct),
            "sputter_peak_angle_deg": float(sputter_peak_angle_deg),
            "sputter_width_deg": float(sputter_width_deg),
            "sputter_smoothing_a": float(sputter_smoothing_a),
            "ion_transmission_enabled": bool(ion_transmission_enabled),
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
                if ion_transmission_enabled and sputter_active
                else "off"
            ),
            "ion_debug_fields_last": dict(state.meta.get("direct_sputter_debug_fields_last", {})),
            "ion_debug_summary_last": dict(state.meta.get("direct_sputter_debug_summary_last", {})),
            "reflected_ion_enabled": bool(cfg.reflected_ion_enabled),
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
            "redepo_enabled": bool(cfg.redepo_enabled),
            "redepo_active": bool(redepo_active and redepo_total_mass > 0.0),
            "redepo_model": "single_bounce_normal_lobe_los" if redepo_active else "off",
            "redepo_source_model": str(redepo_source_model),
            "redepo_efficiency_pct": float(redepo_efficiency_pct),
            "redepo_emit_power": float(redepo_emit_power),
            "redepo_distance_power": float(redepo_distance_power),
            "redepo_neighbor_exclusion": int(redepo_neighbor_exclusion),
            "redepo_max_distance_a": float(redepo_max_distance_a),
            "redepo_debug_fields_last": dict(state.meta.get("model4_redepo_debug_fields_last", {})),
            "redepo_debug_summary_last": redepo_summary,
            "redepo_total_removed_mass_last": float(redepo_total_removed_mass),
            "redepo_total_mass_last": float(redepo_total_mass),
            "redepo_capture_ratio_last": (
                float(redepo_total_mass / redepo_total_removed_mass)
                if redepo_total_removed_mass > 1e-12
                else 0.0
            ),
            "redepo_active_source_count_last": int(state.meta.get("model4_redepo_active_source_count_last", 0)),
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
