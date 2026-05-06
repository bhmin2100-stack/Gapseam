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
    max_transport_sources: int = 64
    max_los_candidates_per_source: int = 256
    los_candidate_weight_fraction: float = 0.990
    soft_los_radius_points: int = 0
    eps: float = 1e-9


@dataclass(frozen=True)
class Model4RedepositionResult:
    dh_redepo: List[float]
    debug_fields: Dict[str, Any]
    debug_summary: Dict[str, Any]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_vec(x: float, y: float, default: Point = (0.0, 1.0)) -> Point:
    length = math.hypot(float(x), float(y))
    if length <= _EPS:
        return (float(default[0]), float(default[1]))
    return (float(x) / length, float(y) / length)


def _reflection_axis(normal: Point) -> Point:
    nnx, nny = _normalize_vec(float(normal[0]), float(normal[1]))
    incoming = (0.0, -1.0)
    dot_in = (incoming[0] * nnx) + (incoming[1] * nny)
    rx = incoming[0] - (2.0 * dot_in * nnx)
    ry = incoming[1] - (2.0 * dot_in * nny)
    if (rx * nnx) + (ry * nny) <= _EPS:
        tx = rx - (((rx * nnx) + (ry * nny)) * nnx)
        ty = ry - (((rx * nnx) + (ry * nny)) * nny)
        if math.hypot(tx, ty) <= _EPS:
            return (nnx, nny)
        rx = tx + (0.25 * nnx)
        ry = ty + (0.25 * nny)
    return _normalize_vec(rx, ry, default=(nnx, nny))


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


def _symmetric_vertex_pairs(points: Sequence[Point], center_x: float) -> List[Tuple[int, int]]:
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < 4:
        return []
    lookup: Dict[Tuple[float, float], List[int]] = {}
    for idx, (x, y) in enumerate(pts):
        lookup.setdefault((round(x, 3), round(y, 3)), []).append(idx)
    pairs: List[Tuple[int, int]] = []
    used = set()
    for idx, (x, y) in enumerate(pts):
        if idx in used:
            continue
        mx = (2.0 * float(center_x)) - x
        candidates = lookup.get((round(mx, 3), round(y, 3)), [])
        match = next((candidate for candidate in candidates if candidate not in used and candidate != idx), None)
        if match is None:
            if abs(x - center_x) <= 1e-3:
                used.add(idx)
            continue
        used.add(idx)
        used.add(match)
        pairs.append((idx, match))
    paired_vertices = 2 * len(pairs)
    if paired_vertices < max(4, int(round(0.80 * len(pts)))):
        return []
    return pairs


def _source_field_is_symmetric(pairs: Sequence[Tuple[int, int]], values: Sequence[float]) -> bool:
    if not pairs:
        return False
    delta = 0.0
    scale = 0.0
    for i, j in pairs:
        vi = max(0.0, float(values[i]))
        vj = max(0.0, float(values[j]))
        delta += abs(vi - vj)
        scale += max(vi, vj)
    if scale <= _EPS:
        return False
    return delta <= max(1e-9, 0.01 * scale)


def _symmetrize_mass_field(
    masses: Sequence[float],
    areas: Sequence[float],
    pairs: Sequence[Tuple[int, int]],
) -> List[float]:
    out = [max(0.0, float(v)) for v in masses]
    for i, j in pairs:
        area_i = max(_EPS, float(areas[i]))
        area_j = max(_EPS, float(areas[j]))
        total = out[i] + out[j]
        dh = total / max(_EPS, area_i + area_j)
        out[i] = dh * area_i
        out[j] = dh * area_j
    return out


def _smooth_exposed_surface_mass(
    points: Sequence[Point],
    normals: Sequence[Point],
    masses: Sequence[float],
    *,
    radius_points: int,
) -> List[float]:
    vals = [max(0.0, float(v)) for v in masses]
    if radius_points <= 0 or len(vals) <= 2:
        return vals
    pts = [(float(x), float(y)) for x, y in points]
    normal_values = [(float(nx), float(ny)) for nx, ny in normals]
    areas = compute_arc_weights(pts)
    top_y = max(y for _x, y in pts)
    typical_ds = _median_positive(
        areas,
        fallback=max(1.0, _geometry_diagonal(pts) / max(1, len(pts) - 1)),
    )
    top_tol = max(1e-6, typical_ds * 0.5)
    exposed_trench = [
        (y < top_y - top_tol) or abs(nx) >= 0.18
        for (_x, y), (nx, _ny) in zip(pts, normal_values)
    ]
    radius = min(int(radius_points), max(1, len(vals) // 4))
    out = list(vals)
    idx = 0
    while idx < len(vals):
        if not exposed_trench[idx]:
            idx += 1
            continue
        start = idx
        while idx < len(vals) and exposed_trench[idx]:
            idx += 1
        stop = idx
        if stop - start <= 2:
            continue
        dh_values = [
            vals[j] / max(float(areas[j]), _EPS)
            for j in range(start, stop)
        ]
        smoothed_dh: List[float] = []
        for local_idx in range(stop - start):
            left = max(0, local_idx - radius)
            right = min((stop - start) - 1, local_idx + radius)
            weight_sum = 0.0
            value_sum = 0.0
            for local_j in range(left, right + 1):
                weight = float(radius + 1 - abs(local_j - local_idx))
                weight_sum += weight
                value_sum += dh_values[local_j] * weight
            smoothed_dh.append(value_sum / max(weight_sum, _EPS))
        original_mass = sum(vals[j] for j in range(start, stop))
        smoothed_mass = sum(
            smoothed_dh[local_idx] * areas[start + local_idx]
            for local_idx in range(stop - start)
        )
        scale = original_mass / max(smoothed_mass, _EPS) if original_mass > _EPS else 0.0
        for local_idx, dh in enumerate(smoothed_dh):
            out[start + local_idx] = max(0.0, dh * areas[start + local_idx] * scale)
    return out


def _line_of_sight_engine(points: Sequence[Point], normals: Sequence[Point]) -> PathLOS:
    return PathLOS(points, normals=normals)


def line_of_sight(points: Sequence[Point], normals: Sequence[Point], i: int, j: int) -> bool:
    return _line_of_sight_engine(points, normals).visible_indices(int(i), int(j))


def _soft_los_weight(
    los: PathLOS,
    source_index: int,
    target_index: int,
    *,
    point_count: int,
    width_a: float,
) -> Tuple[float, int]:
    hard_visible = los.visible_indices(source_index, target_index)
    width = max(0.0, float(width_a))
    if width <= _EPS:
        return (1.0 if hard_visible else 0.0), 1

    hard_samples = 1
    near_boundary = False
    for offset in (-1, 1):
        sample_index = target_index + offset
        if sample_index < 0 or sample_index >= point_count or sample_index == source_index:
            continue
        sample_visible = los.visible_indices(source_index, sample_index)
        hard_samples += 1
        if sample_visible != hard_visible:
            near_boundary = True

    if not near_boundary:
        return (1.0 if hard_visible else 0.0), hard_samples
    return los.soft_visibility_indices(source_index, target_index, width), hard_samples + 3


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
    neighbor_exclusion = max(0, int(cfg.neighbor_exclusion))
    eps = max(_EPS, float(cfg.eps))
    diag = _geometry_diagonal(pts)
    max_dist = max(250.0, diag)

    mass_to_target = [0.0 for _ in pts]
    los = _line_of_sight_engine(pts, normal_values)
    source_cutoff = max(1e-9, total_removed_mass * 1e-6)
    raw_source_indices = [
        idx
        for idx, mass in enumerate(removed_mass)
        if mass > source_cutoff
    ]
    center_x = (min(x for x, _y in pts) + max(x for x, _y in pts)) * 0.5
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, _EPS)
    max_transport_sources = max(16, min(256, int(cfg.max_transport_sources)))
    if len(raw_source_indices) <= max_transport_sources:
        transport_sources = [
            (idx, removed_mass[idx], pts[idx], _reflection_axis(normal_values[idx]))
            for idx in raw_source_indices
        ]
    else:
        bins_per_group = max(1, int(math.floor(max_transport_sources / 3)))
        buckets: Dict[Tuple[int, int], List[int]] = {}
        for idx in raw_source_indices:
            x, y = pts[idx]
            if abs(x - center_x) <= max(1e-6, diag * 1e-9):
                side = 0
            else:
                side = -1 if x < center_x else 1
            depth = _clamp01((surface_y - y) / depth_span)
            bin_idx = min(bins_per_group - 1, int(math.floor(depth * bins_per_group)))
            buckets.setdefault((side, bin_idx), []).append(idx)

        transport_sources: List[Tuple[int, float, Point, Point]] = []
        for key in sorted(buckets):
            indices = buckets[key]
            total_mass = sum(removed_mass[idx] for idx in indices)
            if total_mass <= source_cutoff:
                continue
            x_centroid = sum(pts[idx][0] * removed_mass[idx] for idx in indices) / total_mass
            y_centroid = sum(pts[idx][1] * removed_mass[idx] for idx in indices) / total_mass
            representative = min(
                indices,
                key=lambda idx: (
                    ((pts[idx][0] - x_centroid) / max(diag, 1.0)) ** 2
                    + ((pts[idx][1] - y_centroid) / max(diag, 1.0)) ** 2
                ),
            )
            nx_centroid = sum(normal_values[idx][0] * removed_mass[idx] for idx in indices) / total_mass
            ny_centroid = sum(normal_values[idx][1] * removed_mass[idx] for idx in indices) / total_mass
            source_axis = _reflection_axis(
                _normalize_vec(nx_centroid, ny_centroid, normal_values[representative])
            )
            transport_sources.append(
                (representative, total_mass, (x_centroid, y_centroid), source_axis)
            )
    transported_removed_mass = float(
        sum(mass for _idx, mass, _source, _axis in transport_sources)
    )
    transported_source_mass_field = [0.0 for _ in pts]
    for idx, mass, _source, _axis in transport_sources:
        transported_source_mass_field[idx] += float(mass)
    active_source_count = 0
    total_valid_target_count = 0
    total_rough_target_count = 0
    total_los_candidate_count = 0
    # GapSim simulator uses a single lobe sigma parameter.  The emulator keeps
    # the older "emit power" knob, mapped so 1.0 keeps the simulator-like 24 deg
    # lobe and higher values narrow the reflection lobe.
    sigma = max(1e-6, min(90.0, 24.0 / max(0.25, emit_power) if emit_power > 0.0 else 60.0))
    cone_cut_deg = max(18.0, min(89.0, 4.0 * sigma))
    max_los_candidates = max(0, int(cfg.max_los_candidates_per_source))
    los_weight_fraction = _clamp01(float(cfg.los_candidate_weight_fraction))
    soft_los_radius = max(0, min(2, int(cfg.soft_los_radius_points)))
    typical_los_ds = _median_positive(area, fallback=max(1.0, diag / max(1, n - 1)))
    soft_los_width_a = (
        float(soft_los_radius)
        * min(8.0, max(0.5, typical_los_ds * 0.25))
    )
    total_soft_los_sample_count = 0
    total_soft_los_partial_count = 0

    for i, mass_i, source, axis in transport_sources:
        rough_targets: List[Tuple[int, float]] = []
        for j, target in enumerate(pts):
            if j == i or abs(j - i) <= neighbor_exclusion:
                continue
            nj = normal_values[j]
            dx = target[0] - source[0]
            dy = target[1] - source[1]
            dist = math.hypot(dx, dy)
            if dist <= eps or dist > max_dist:
                continue
            ex = dx / dist
            ey = dy / dist
            front = (axis[0] * ex) + (axis[1] * ey)
            if front <= _EPS:
                continue
            dev_deg = math.degrees(math.acos(max(-1.0, min(1.0, front))))
            if dev_deg > cone_cut_deg:
                continue
            cos_receive = (nj[0] * -ex) + (nj[1] * -ey)
            if cos_receive <= _EPS:
                continue
            angular_weight = math.exp(-((dev_deg / sigma) ** 2))
            weight = max(0.0, cos_receive) * angular_weight
            if weight > _EPS:
                rough_targets.append((j, weight))
        if not rough_targets:
            continue

        total_rough_target_count += len(rough_targets)
        if max_los_candidates > 0 and len(rough_targets) > max_los_candidates:
            rough_targets.sort(key=lambda item: item[1], reverse=True)
            rough_sum = sum(weight for _j, weight in rough_targets)
            keep_weight = rough_sum * los_weight_fraction
            cumulative = 0.0
            los_candidates: List[Tuple[int, float]] = []
            for j, weight in rough_targets:
                los_candidates.append((j, weight))
                cumulative += weight
                if len(los_candidates) >= max_los_candidates:
                    break
                if cumulative >= keep_weight and len(los_candidates) >= 64:
                    break
        else:
            los_candidates = rough_targets
        total_los_candidate_count += len(los_candidates)

        valid_targets: List[Tuple[int, float]] = []
        for j, weight in los_candidates:
            visibility, soft_sample_count = _soft_los_weight(
                los,
                i,
                j,
                point_count=n,
                width_a=soft_los_width_a,
            )
            total_soft_los_sample_count += soft_sample_count
            if _EPS < visibility < (1.0 - _EPS):
                total_soft_los_partial_count += 1
            if visibility > _EPS:
                valid_targets.append((j, weight * visibility))
        weight_sum = sum(weight for _j, weight in valid_targets)
        if weight_sum <= _EPS:
            continue
        source_mass = mass_i * efficiency
        if source_mass <= _EPS:
            continue
        active_source_count += 1
        total_valid_target_count += len(valid_targets)
        scale = source_mass / weight_sum
        for j, weight in valid_targets:
            mass_to_target[j] += scale * weight

    spread_a = max(0.0, float(cfg.lateral_spread_a))
    typical_ds = _median_positive(area, fallback=max(1.0, diag / max(1, n - 1)))
    spread_radius = int(round(spread_a / max(typical_ds, eps)))
    if spread_radius > 0:
        mass_to_target = _smooth_exposed_surface_mass(
            pts,
            normal_values,
            mass_to_target,
            radius_points=spread_radius,
        )

    symmetry_pairs = _symmetric_vertex_pairs(pts, center_x)
    symmetry_preserved = _source_field_is_symmetric(symmetry_pairs, removed_mass)
    if symmetry_preserved:
        mass_to_target = _symmetrize_mass_field(mass_to_target, area, symmetry_pairs)

    max_dh_etch = max(etch_values, default=0.0)
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
        "transport_source_stride": 0,
        "transport_model": "gapsim_binned_lobe_los",
        "transport_source_position_model": "mass_centroid_lobe",
        "max_transport_sources": int(max_transport_sources),
        "redepo_lobe_sigma_deg": float(sigma),
        "redepo_cone_cut_deg": float(cone_cut_deg),
        "redepo_max_distance_a": float(max_dist),
        "max_los_candidates_per_source": int(max_los_candidates),
        "los_candidate_weight_fraction": float(los_weight_fraction),
        "soft_los_radius_points": int(soft_los_radius),
        "soft_los_width_a": float(soft_los_width_a),
        "soft_los_candidate_samples": int(total_soft_los_sample_count),
        "soft_los_partial_candidate_count": int(total_soft_los_partial_count),
        "mean_rough_targets_per_source": (
            float(total_rough_target_count / len(transport_sources))
            if transport_sources
            else 0.0
        ),
        "mean_los_candidates_per_source": (
            float(total_los_candidate_count / len(transport_sources))
            if transport_sources
            else 0.0
        ),
        "distance_power_ignored": float(cfg.distance_power),
        "redepo_lateral_spread_a": float(spread_a),
        "redepo_spread_radius_points": int(max(0, spread_radius)),
        "redepo_cap_ignored_ratio": float(cfg.max_redepo_to_etch_ratio),
        "symmetry_preserved": bool(symmetry_preserved),
        "symmetry_pair_count": int(len(symmetry_pairs)),
        "mean_valid_targets_per_active_source": (
            float(total_valid_target_count / active_source_count)
            if active_source_count > 0
            else 0.0
        ),
        "transported_removed_mass": float(transported_removed_mass),
        "transported_removed_mass_ratio": (
            float(transported_removed_mass / total_removed_mass)
            if total_removed_mass > _EPS
            else 0.0
        ),
        "max_dh_etch": max_dh_etch,
        "max_dh_redepo": max(dh_redepo, default=0.0),
        "mean_dh_redepo": float(sum(dh_redepo) / n) if n > 0 else 0.0,
        "redepo_cap_a": 0.0,
        **_mass_summary_by_source_zone(pts, transported_source_mass_field),
    }
    debug_fields = {
        "arc_weight_field": [round(v, 6) for v in area],
        "removed_mass_field": [round(v, 6) for v in removed_mass],
        "redepo_mass_field": [round(v, 6) for v in mass_to_target],
        "dh_redepo_field": [round(v, 6) for v in dh_redepo],
    }
    return Model4RedepositionResult(dh_redepo, debug_fields, summary)
