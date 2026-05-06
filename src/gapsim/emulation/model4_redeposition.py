from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from gapsim.engine.ion_los import PathLOS

Point = Tuple[float, float]

_EPS = 1e-12


@dataclass(frozen=True)
class Model4RedepositionParams:
    redepo_efficiency: float = 0.25
    emit_power: float = 1.0
    distance_power: float = 1.0
    neighbor_exclusion: int = 2
    max_redepo_distance: float = 1800.0
    lateral_spread_a: float = 55.0
    max_redepo_to_etch_ratio: float = 0.70
    eps: float = 1e-9


@dataclass(frozen=True)
class Model4RedepositionResult:
    dh_redepo: List[float]
    debug_fields: Dict[str, Any]
    debug_summary: Dict[str, Any]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def compute_arc_weights(points: Sequence[Point]) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    seg_lens = [
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(n - 1)
    ]
    out = [0.0] * n
    out[0] = 0.5 * seg_lens[0]
    out[-1] = 0.5 * seg_lens[-1]
    for i in range(1, n - 1):
        out[i] = 0.5 * (seg_lens[i - 1] + seg_lens[i])
    positive = [v for v in out if v > _EPS]
    fallback = min(positive) if positive else 1.0
    return [max(fallback, float(v)) for v in out]


def _geometry_diagonal(points: Sequence[Point]) -> float:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return 0.0
    xs = [x for x, _y in pts]
    ys = [y for _x, y in pts]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _source_zone(points: Sequence[Point], idx: int) -> str:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts or idx < 0 or idx >= len(pts):
        return "mid"
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, _EPS)
    depth = _clamp01((surface_y - pts[idx][1]) / depth_span)
    if depth < 0.18:
        return "top"
    if depth < 0.45:
        return "upper_sidewall"
    if depth < 0.78:
        return "mid_sidewall"
    return "bottom"


def _mass_summary_by_source_zone(points: Sequence[Point], masses: Sequence[float]) -> Dict[str, float]:
    out = {
        "top_source_mass": 0.0,
        "upper_sidewall_source_mass": 0.0,
        "mid_sidewall_source_mass": 0.0,
        "bottom_source_mass": 0.0,
    }
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return out
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, _EPS)
    for idx, mass in enumerate(masses):
        if idx < 0 or idx >= len(pts):
            zone = "mid"
        else:
            depth = _clamp01((surface_y - pts[idx][1]) / depth_span)
            if depth < 0.18:
                zone = "top"
            elif depth < 0.45:
                zone = "upper_sidewall"
            elif depth < 0.78:
                zone = "mid_sidewall"
            else:
                zone = "bottom"
        key = f"{zone}_source_mass"
        if key in out:
            out[key] += max(0.0, float(mass))
    return {key: float(value) for key, value in out.items()}


def _median_positive(values: Sequence[float], fallback: float) -> float:
    positive = sorted(float(v) for v in values if float(v) > _EPS)
    if not positive:
        return float(fallback)
    mid = len(positive) // 2
    if len(positive) % 2:
        return float(positive[mid])
    return float(0.5 * (positive[mid - 1] + positive[mid]))


def _smooth_sidewall_mass(
    points: Sequence[Point],
    normals: Sequence[Point],
    masses: Sequence[float],
    *,
    radius_points: int,
    center_x: float,
) -> List[float]:
    vals = [max(0.0, float(v)) for v in masses]
    if radius_points <= 0 or len(vals) <= 2:
        return vals
    pts = [(float(x), float(y)) for x, y in points]
    normal_values = [(float(nx), float(ny)) for nx, ny in normals]
    side = [
        -1 if x < center_x else (1 if x > center_x else 0)
        for x, _y in pts
    ]
    sidewall = [abs(nx) >= 0.18 for nx, _ny in normal_values]
    radius = min(int(radius_points), max(1, len(vals) // 4))
    out = [0.0 for _ in vals]
    for idx, value in enumerate(vals):
        if value <= _EPS:
            continue
        left = max(0, idx - radius)
        right = min(len(vals) - 1, idx + radius)
        targets: List[Tuple[int, float]] = []
        for j in range(left, right + 1):
            if not sidewall[j] or side[j] == 0 or side[j] != side[idx]:
                continue
            weight = float(radius + 1 - abs(j - idx))
            if weight > 0.0:
                targets.append((j, weight))
        weight_sum = sum(weight for _j, weight in targets)
        if weight_sum <= _EPS:
            out[idx] += value
            continue
        scale = value / weight_sum
        for j, weight in targets:
            out[j] += scale * weight
    return out


def _line_of_sight_engine(points: Sequence[Point], normals: Sequence[Point]) -> PathLOS:
    return PathLOS(points, normals=normals)


def line_of_sight(points: Sequence[Point], normals: Sequence[Point], i: int, j: int) -> bool:
    return _line_of_sight_engine(points, normals).visible_indices(int(i), int(j))


def compute_redeposition(
    points: Sequence[Point],
    normals: Sequence[Point],
    dh_etch: Sequence[float],
    params: Optional[Model4RedepositionParams] = None,
) -> Model4RedepositionResult:
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n <= 0:
        return Model4RedepositionResult([], {}, {})
    normal_values = [(float(nx), float(ny)) for nx, ny in normals]
    if len(normal_values) != n:
        normal_values = [(0.0, 1.0) for _ in pts]
    etch_values = [max(0.0, float(v)) for v in dh_etch]
    if len(etch_values) != n:
        etch_values = [0.0 for _ in pts]

    cfg = params or Model4RedepositionParams()
    efficiency = _clamp01(cfg.redepo_efficiency)
    area = compute_arc_weights(pts)
    removed_mass = [max(0.0, etch_values[i]) * area[i] for i in range(n)]
    total_removed_mass = float(sum(removed_mass))
    if total_removed_mass <= _EPS or efficiency <= _EPS:
        zero = [0.0 for _ in pts]
        summary = {
            "total_removed_mass": total_removed_mass,
            "total_redepo_mass": 0.0,
            "redepo_capture_ratio": 0.0,
            "active_source_count": 0,
            "active_target_count": 0,
            "max_dh_etch": max(etch_values, default=0.0),
            "max_dh_redepo": 0.0,
            "mean_dh_redepo": 0.0,
            **_mass_summary_by_source_zone(pts, removed_mass),
        }
        return Model4RedepositionResult(
            zero,
            {
                "arc_weight_field": [round(v, 6) for v in area],
                "removed_mass_field": [round(v, 6) for v in removed_mass],
                "redepo_mass_field": [0.0 for _ in pts],
                "dh_redepo_field": [0.0 for _ in pts],
            },
            summary,
        )

    emit_power = max(0.0, float(cfg.emit_power))
    distance_power = max(0.0, float(cfg.distance_power))
    neighbor_exclusion = max(0, int(cfg.neighbor_exclusion))
    eps = max(_EPS, float(cfg.eps))
    spread_a = max(0.0, float(cfg.lateral_spread_a))
    max_redepo_to_etch_ratio = max(0.0, float(cfg.max_redepo_to_etch_ratio))
    max_dist = float(cfg.max_redepo_distance)
    diag = _geometry_diagonal(pts)
    if max_dist <= 0.0:
        max_dist = max(250.0, diag)

    use_grid = max_dist < max(diag * 0.98, 250.0)
    cell_size = max(80.0, min(450.0, max_dist / 4.0 if max_dist > 0.0 else 300.0))
    inv_cell = 1.0 / max(cell_size, eps)
    grid: Dict[Tuple[int, int], List[int]] = {}
    if use_grid:
        for idx, (x, y) in enumerate(pts):
            key = (int(math.floor(x * inv_cell)), int(math.floor(y * inv_cell)))
            grid.setdefault(key, []).append(idx)

    def candidate_indices(source: Point) -> List[int]:
        if not use_grid:
            return list(range(n))
        cx = int(math.floor(source[0] * inv_cell))
        cy = int(math.floor(source[1] * inv_cell))
        ring = max(1, int(math.ceil(max_dist / cell_size)))
        out: List[int] = []
        seen = set()
        for gx in range(cx - ring, cx + ring + 1):
            for gy in range(cy - ring, cy + ring + 1):
                for idx in grid.get((gx, gy), ()):
                    if idx in seen:
                        continue
                    seen.add(idx)
                    out.append(idx)
        return out

    mass_to_target = [0.0 for _ in pts]
    los = _line_of_sight_engine(pts, normal_values)
    source_cutoff = max(1e-12, total_removed_mass * 1e-9)
    center_x = (min(x for x, _y in pts) + max(x for x, _y in pts)) * 0.5
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, _EPS)
    sidewall_mask = [abs(nx) >= 0.18 for nx, _ny in normal_values]
    raw_source_indices = [
        idx
        for idx, mass in enumerate(removed_mass)
        if (
            mass > source_cutoff
            and sidewall_mask[idx]
            and ((surface_y - pts[idx][1]) / depth_span) <= 0.72
        )
    ]
    max_transport_sources = 24
    source_stride = max(1, int(math.ceil(len(raw_source_indices) / max_transport_sources)))
    transport_sources: List[Tuple[int, float]] = []
    for start in range(0, len(raw_source_indices), source_stride):
        chunk = raw_source_indices[start : start + source_stride]
        if not chunk:
            continue
        representative = max(chunk, key=lambda idx: removed_mass[idx])
        transport_sources.append((representative, sum(removed_mass[idx] for idx in chunk)))
    transported_removed_mass = float(sum(mass for _idx, mass in transport_sources))
    transported_source_mass_field = [0.0 for _ in pts]
    for idx, mass in transport_sources:
        transported_source_mass_field[idx] += float(mass)
    active_source_count = 0

    for i, mass_i in transport_sources:
        source = pts[i]
        ni = normal_values[i]
        sx = -1 if source[0] < center_x else (1 if source[0] > center_x else 0)
        if sx == 0:
            continue
        source_depth = (surface_y - source[1]) / depth_span
        rough_targets: List[Tuple[int, float]] = []
        for j in candidate_indices(source):
            target = pts[j]
            if j == i or abs(j - i) <= neighbor_exclusion:
                continue
            tx = -1 if target[0] < center_x else (1 if target[0] > center_x else 0)
            if tx == 0 or tx == sx:
                continue
            nj = normal_values[j]
            if abs(nj[0]) < 0.18:
                continue
            target_depth = (surface_y - target[1]) / depth_span
            depth_delta = target_depth - source_depth
            if depth_delta < 0.012:
                continue
            dx = target[0] - source[0]
            dy = target[1] - source[1]
            dist = math.hypot(dx, dy)
            if dist <= eps or dist > max_dist:
                continue
            ex = dx / dist
            ey = dy / dist
            cos_emit = (ni[0] * ex) + (ni[1] * ey)
            if cos_emit <= 0.0:
                continue
            cos_receive = (nj[0] * -ex) + (nj[1] * -ey)
            if cos_receive <= 0.0:
                continue
            below_weight = 0.25 + 0.75 * _clamp01(depth_delta / 0.28)
            weight = (
                (max(0.0, cos_emit) ** emit_power)
                * max(0.0, cos_receive)
                * below_weight
                * area[j]
                / ((dist + eps) ** distance_power)
            )
            if weight > _EPS:
                rough_targets.append((j, weight))

        if not rough_targets:
            continue

        rough_targets.sort(key=lambda item: item[1], reverse=True)
        peak_weight = rough_targets[0][1]
        los_candidates = [
            (j, weight)
            for j, weight in rough_targets[:32]
            if weight >= peak_weight * 0.18
        ]

        valid_targets: List[Tuple[int, float]] = []
        for j, weight in los_candidates:
            if los.visible_indices(i, j):
                valid_targets.append((j, weight))
            if len(valid_targets) >= 10:
                break
        weight_sum = sum(weight for _j, weight in valid_targets)
        if weight_sum <= _EPS:
            continue
        escape_weight = 0.12 + 0.55 * ((1.0 - _clamp01(source_depth)) ** 2.0)
        capture_fraction = weight_sum / (weight_sum + escape_weight)
        source_mass = mass_i * efficiency * _clamp01(capture_fraction)
        if source_mass <= _EPS:
            continue
        active_source_count += 1
        scale = source_mass / weight_sum
        for j, weight in valid_targets:
            mass_to_target[j] += scale * weight

    typical_ds = _median_positive(area, fallback=max(1.0, diag / max(1, n - 1)))
    spread_radius = int(round(spread_a / max(typical_ds, eps)))
    if spread_radius > 0:
        mass_to_target = _smooth_sidewall_mass(
            pts,
            normal_values,
            mass_to_target,
            radius_points=spread_radius,
            center_x=center_x,
        )

    dh_redepo_raw = [
        float(mass_to_target[j]) / max(area[j], eps)
        for j in range(n)
    ]
    max_dh_etch = max(etch_values, default=0.0)
    redepo_cap = (
        max_dh_etch * max_redepo_to_etch_ratio
        if max_redepo_to_etch_ratio > 0.0 and max_dh_etch > _EPS
        else 0.0
    )
    if redepo_cap > _EPS:
        for j, value in enumerate(dh_redepo_raw):
            if value > redepo_cap:
                mass_to_target[j] = redepo_cap * area[j]
    dh_redepo = [
        float(mass_to_target[j]) / max(area[j], eps)
        for j in range(n)
    ]
    total_redepo_mass = float(sum(mass_to_target))
    active_target_count = sum(1 for mass in mass_to_target if mass > source_cutoff)
    summary = {
        "total_removed_mass": total_removed_mass,
        "total_redepo_mass": total_redepo_mass,
        "redepo_capture_ratio": float(total_redepo_mass / total_removed_mass) if total_removed_mass > _EPS else 0.0,
        "active_source_count": int(active_source_count),
        "active_target_count": int(active_target_count),
        "raw_source_count": int(len(raw_source_indices)),
        "transport_source_count": int(len(transport_sources)),
        "transport_source_stride": int(source_stride),
        "transported_removed_mass": float(transported_removed_mass),
        "max_dh_etch": max_dh_etch,
        "max_dh_redepo": max(dh_redepo, default=0.0),
        "mean_dh_redepo": float(sum(dh_redepo) / n) if n > 0 else 0.0,
        "redepo_lateral_spread_a": float(spread_a),
        "redepo_spread_radius_points": int(max(0, spread_radius)),
        "redepo_cap_a": float(redepo_cap),
        **_mass_summary_by_source_zone(pts, transported_source_mass_field),
    }
    debug_fields = {
        "arc_weight_field": [round(v, 6) for v in area],
        "removed_mass_field": [round(v, 6) for v in removed_mass],
        "redepo_mass_field": [round(v, 6) for v in mass_to_target],
        "dh_redepo_field": [round(v, 6) for v in dh_redepo],
    }
    return Model4RedepositionResult(dh_redepo, debug_fields, summary)
