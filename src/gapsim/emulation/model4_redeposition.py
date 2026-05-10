from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from gapsim.engine.deposition_pipeline import REPARAM_DS_A
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
    transport_model: str = "gapsim_original_per_vertex_los"
    ray_count: int = 7
    footprint_radius_sigma: float = 3.0
    max_transport_sources: int = 64
    max_los_candidates_per_source: int = 256
    los_candidate_weight_fraction: float = 0.990
    soft_los_radius_points: int = 0
    emission_axis_model: str = "normal"
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


def _normal_lobe_axis(normal: Point) -> Point:
    return _normalize_vec(float(normal[0]), float(normal[1]), default=(0.0, 1.0))


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


def _emission_axis(normal: Point, model: str) -> Point:
    key = str(model or "normal").strip().lower()
    normal_axis = _normal_lobe_axis(normal)
    if key in {"reflection", "specular", "forward"}:
        return _reflection_axis(normal)
    if key in {"mixed", "normal_reflection_mix", "forward_mix"}:
        rx, ry = _reflection_axis(normal)
        return _normalize_vec(
            (0.65 * normal_axis[0]) + (0.35 * rx),
            (0.65 * normal_axis[1]) + (0.35 * ry),
            default=normal_axis,
        )
    return normal_axis


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


def _arc_coordinates(points: Sequence[Point]) -> List[float]:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return []
    coords = [0.0]
    for idx in range(len(pts) - 1):
        x0, y0 = pts[idx]
        x1, y1 = pts[idx + 1]
        coords.append(coords[-1] + math.hypot(x1 - x0, y1 - y0))
    return coords


def _transport_source_spacing_a(
    transport_sources: Sequence[Tuple[int, float, Point, Point]],
    *,
    center_x: float,
) -> float:
    side_positions: Dict[int, List[Point]] = {}
    for _idx, mass, source, _axis in transport_sources:
        if float(mass) <= _EPS:
            continue
        side = -1 if float(source[0]) < float(center_x) else 1
        side_positions.setdefault(side, []).append((float(source[0]), float(source[1])))

    gaps: List[float] = []
    for positions in side_positions.values():
        if len(positions) < 2:
            continue
        ordered = sorted(positions, key=lambda point: point[1])
        for a, b in zip(ordered, ordered[1:]):
            gap = math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
            if gap > _EPS:
                gaps.append(gap)
    return _median_positive(gaps, fallback=0.0) if gaps else 0.0


def _rotate_vector(vec: Point, angle_rad: float) -> Point:
    c = math.cos(float(angle_rad))
    s = math.sin(float(angle_rad))
    x, y = float(vec[0]), float(vec[1])
    return _normalize_vec((c * x) - (s * y), (s * x) + (c * y), default=vec)


def _ray_segment_intersection(
    origin: Point,
    direction: Point,
    a: Point,
    b: Point,
    *,
    eps: float,
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


def _ray_first_hit(
    points: Sequence[Point],
    normals: Sequence[Point],
    *,
    source_index: int,
    source: Point,
    direction: Point,
    max_distance: float,
    neighbor_exclusion: int,
    eps: float,
) -> Optional[Tuple[int, float, float, Point, Point]]:
    pts = points
    normal_values = normals
    if len(pts) < 2:
        return None
    best: Optional[Tuple[int, float, float, Point, Point]] = None
    max_dist = float(max_distance)
    skip_width = max(0, int(neighbor_exclusion))
    source_idx = int(source_index)
    ox, oy = float(source[0]), float(source[1])
    dx, dy = float(direction[0]), float(direction[1])
    for seg_idx in range(len(pts) - 1):
        if (
            abs(seg_idx - source_idx) <= skip_width
            or abs((seg_idx + 1) - source_idx) <= skip_width
        ):
            continue
        a = pts[seg_idx]
        b = pts[seg_idx + 1]
        if math.hypot(b[0] - a[0], b[1] - a[1]) <= eps:
            continue
        ax = float(a[0]) - ox
        ay = float(a[1]) - oy
        bx = float(b[0]) - ox
        by = float(b[1]) - oy
        ta = (ax * dx) + (ay * dy)
        tb = (bx * dx) + (by * dy)
        if max(ta, tb) <= eps:
            continue
        if min(ta, tb) > min(max_dist, best[2] if best is not None else max_dist):
            continue
        ca = (dx * ay) - (dy * ax)
        cb = (dx * by) - (dy * bx)
        if ca * cb > 0.0:
            continue
        hit = _ray_segment_intersection(source, direction, a, b, eps=eps)
        if hit is None:
            continue
        dist, u = hit
        if dist <= eps or dist > max_dist:
            continue
        if best is not None and dist >= best[2]:
            continue
        n0 = normal_values[seg_idx] if seg_idx < len(normal_values) else (0.0, 1.0)
        n1 = normal_values[seg_idx + 1] if (seg_idx + 1) < len(normal_values) else n0
        nx = ((1.0 - u) * n0[0]) + (u * n1[0])
        ny = ((1.0 - u) * n0[1]) + (u * n1[1])
        hit_normal = _normalize_vec(nx, ny)
        hit_point = (
            a[0] + (u * (b[0] - a[0])),
            a[1] + (u * (b[1] - a[1])),
        )
        best = (int(seg_idx), float(u), float(dist), hit_point, hit_normal)
    return best


def _deposit_gaussian_footprint(
    mass_to_target: List[float],
    areas: Sequence[float],
    arc_coords: Sequence[float],
    *,
    hit_s: float,
    mass: float,
    sigma_a: float,
    radius_sigma: float,
    source_index: int,
    neighbor_exclusion: int,
    eps: float,
) -> int:
    if mass <= eps or not arc_coords:
        return 0
    if sigma_a <= eps:
        target_idx = min(range(len(arc_coords)), key=lambda idx: abs(float(arc_coords[idx]) - float(hit_s)))
        if abs(target_idx - int(source_index)) <= max(0, int(neighbor_exclusion)):
            return 0
        mass_to_target[target_idx] += float(mass)
        return 1

    radius_a = max(float(sigma_a), float(radius_sigma) * float(sigma_a))
    left = bisect_left(arc_coords, float(hit_s) - radius_a)
    right = bisect_right(arc_coords, float(hit_s) + radius_a)
    candidates: List[Tuple[int, float]] = []
    for idx in range(max(0, left), min(len(arc_coords), right)):
        if abs(idx - int(source_index)) <= max(0, int(neighbor_exclusion)):
            continue
        ds = abs(float(arc_coords[idx]) - float(hit_s))
        kernel = math.exp(-0.5 * ((ds / max(float(sigma_a), eps)) ** 2))
        weight = max(0.0, float(areas[idx])) * kernel
        if weight > eps:
            candidates.append((idx, weight))
    if not candidates:
        target_idx = min(range(len(arc_coords)), key=lambda idx: abs(float(arc_coords[idx]) - float(hit_s)))
        if abs(target_idx - int(source_index)) <= max(0, int(neighbor_exclusion)):
            return 0
        mass_to_target[target_idx] += float(mass)
        return 1
    weight_sum = sum(weight for _idx, weight in candidates)
    if weight_sum <= eps:
        return 0
    scale = float(mass) / weight_sum
    for idx, weight in candidates:
        mass_to_target[idx] += scale * weight
    return len(candidates)


def _deposit_directional_gaussian_footprint_los(
    mass_to_target: List[float],
    areas: Sequence[float],
    arc_coords: Sequence[float],
    points: Sequence[Point],
    normals: Sequence[Point],
    los: PathLOS,
    *,
    source_index: int,
    source: Point,
    axis: Point,
    hit_s: float,
    mass: float,
    sigma_a: float,
    radius_sigma: float,
    max_distance: float,
    distance_power: float,
    neighbor_exclusion: int,
    soft_los_width_a: float,
    eps: float,
) -> Tuple[int, int, int]:
    if mass <= eps or not arc_coords:
        return 0, 0, 0

    source_idx = int(source_index)
    radius_a = 0.0 if sigma_a <= eps else max(float(sigma_a), float(radius_sigma) * float(sigma_a))
    if radius_a <= eps:
        center_idx = min(range(len(arc_coords)), key=lambda idx: abs(float(arc_coords[idx]) - float(hit_s)))
        left = max(0, center_idx - 1)
        right = min(len(arc_coords), center_idx + 2)
    else:
        left = bisect_left(arc_coords, float(hit_s) - radius_a)
        right = bisect_right(arc_coords, float(hit_s) + radius_a)

    ax, ay = _normalize_vec(axis[0], axis[1])
    candidates: List[Tuple[int, float]] = []
    soft_samples = 0
    soft_partials = 0
    for idx in range(max(0, left), min(len(arc_coords), right)):
        if abs(idx - source_idx) <= max(0, int(neighbor_exclusion)):
            continue
        tx, ty = points[idx]
        dx = float(tx) - float(source[0])
        dy = float(ty) - float(source[1])
        dist = math.hypot(dx, dy)
        if dist <= eps or dist > max_distance:
            continue
        ex = dx / dist
        ey = dy / dist
        if (ax * ex) + (ay * ey) <= eps:
            continue
        nx, ny = normals[idx]
        cos_receive = (float(nx) * -ex) + (float(ny) * -ey)
        if cos_receive <= eps:
            continue
        visibility, sample_count = _soft_los_weight(
            los,
            source_idx,
            idx,
            point_count=len(points),
            width_a=soft_los_width_a,
        )
        soft_samples += sample_count
        if eps < visibility < (1.0 - eps):
            soft_partials += 1
        if visibility <= eps:
            continue
        ds = abs(float(arc_coords[idx]) - float(hit_s))
        kernel = 1.0 if sigma_a <= eps else math.exp(-0.5 * ((ds / max(float(sigma_a), eps)) ** 2))
        dist_weight = 1.0 / ((dist + eps) ** max(0.0, float(distance_power)))
        weight = max(0.0, float(areas[idx])) * kernel * max(0.0, cos_receive) * dist_weight * visibility
        if weight > eps:
            candidates.append((idx, weight))

    if not candidates:
        return 0, soft_samples, soft_partials

    weight_sum = sum(weight for _idx, weight in candidates)
    if weight_sum <= eps:
        return 0, soft_samples, soft_partials
    scale = float(mass) / weight_sum
    for idx, weight in candidates:
        mass_to_target[idx] += scale * weight
    return len(candidates), soft_samples, soft_partials


def _compute_gapsim_original_per_vertex_los(
    points: Sequence[Point],
    normals: Sequence[Point],
    etch_values: Sequence[float],
    areas: Sequence[float],
    removed_mass: Sequence[float],
    total_removed_mass: float,
    *,
    efficiency: float,
    emit_power: float,
    eps: float,
) -> Model4RedepositionResult:
    pts = [(float(x), float(y)) for x, y in points]
    normal_values = [(float(nx), float(ny)) for nx, ny in normals]
    n = len(pts)
    if n <= 0:
        return Model4RedepositionResult([], {}, {})

    mass_to_target = [0.0 for _ in pts]
    mass_prune_eps = max(1e-9, float(total_removed_mass) * 1e-6)
    source_indices = [
        idx
        for idx, mass in enumerate(removed_mass)
        if max(0.0, float(mass)) > mass_prune_eps
    ]
    source_index_set = set(source_indices)
    source_etch_field = [
        float(etch_values[idx]) if idx in source_index_set else 0.0
        for idx in range(n)
    ]
    source_removed_mass_field = [
        float(removed_mass[idx]) if idx in source_index_set else 0.0
        for idx in range(n)
    ]

    sigma = max(1e-6, min(90.0, 24.0 / max(0.25, emit_power) if emit_power > 0.0 else 60.0))
    cone_cut_deg = max(18.0, min(89.0, 4.0 * sigma))
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) if xs and ys else 0.0
    max_dist = max(250.0, diag)
    path_los = PathLOS(pts, normals=normal_values)

    active_source_count = 0
    active_source_with_targets = 0
    total_valid_target_count = 0
    total_candidate_target_count = 0
    for i in source_indices:
        mass_i = max(0.0, float(removed_mass[i]))
        if mass_i <= mass_prune_eps:
            continue
        active_source_count += 1
        source = pts[i]
        axis = _reflection_axis(normal_values[i])
        valid_targets: List[Tuple[int, float]] = []
        for j, target in enumerate(pts):
            if j == i or abs(j - i) <= 2:
                continue
            dx = float(target[0] - source[0])
            dy = float(target[1] - source[1])
            dist = math.hypot(dx, dy)
            if dist <= eps or dist > max_dist:
                continue
            ux = dx / dist
            uy = dy / dist
            front = (axis[0] * ux) + (axis[1] * uy)
            if front <= _EPS:
                continue
            dev_deg = math.degrees(math.acos(max(-1.0, min(1.0, front))))
            if dev_deg > cone_cut_deg:
                continue
            target_face = max(0.0, (normal_values[j][0] * (-ux)) + (normal_values[j][1] * (-uy)))
            if target_face <= _EPS:
                continue
            total_candidate_target_count += 1
            if path_los.los_indices(i, j) == 0:
                continue
            angular_weight = math.exp(-((dev_deg / sigma) ** 2))
            weight = target_face * angular_weight
            if weight > _EPS:
                valid_targets.append((j, weight))
        weight_sum = sum(weight for _, weight in valid_targets)
        if weight_sum <= _EPS:
            continue
        active_source_with_targets += 1
        total_valid_target_count += len(valid_targets)
        scale = (float(efficiency) * mass_i) / weight_sum
        for j, weight in valid_targets:
            mass_to_target[j] += scale * weight

    dh_redepo = [
        float(mass_to_target[j]) / max(float(areas[j]), REPARAM_DS_A)
        for j in range(n)
    ]
    total_redepo_mass = float(sum(mass_to_target))
    active_target_count = sum(1 for mass in mass_to_target if mass > mass_prune_eps)
    summary = {
        "total_removed_mass": float(total_removed_mass),
        "total_redepo_mass": total_redepo_mass,
        "redepo_capture_ratio": float(total_redepo_mass / total_removed_mass) if total_removed_mass > _EPS else 0.0,
        "active_source_count": int(active_source_count),
        "active_source_with_targets_count": int(active_source_with_targets),
        "active_target_count": int(active_target_count),
        "positive_source_count": int(sum(1 for value in etch_values if float(value) > 0.0)),
        "source_activation_etch_cutoff": 0.0,
        "source_activation_mass_cutoff": float(mass_prune_eps),
        "raw_source_count": int(len(source_indices)),
        "transport_source_count": int(len(source_indices)),
        "transport_source_stride": 0,
        "transport_model": "gapsim_original_per_vertex_los",
        "transport_source_position_model": "per_vertex_reflection_axis",
        "max_transport_sources": int(len(source_indices)),
        "redepo_lobe_sigma_deg": float(sigma),
        "redepo_cone_cut_deg": float(cone_cut_deg),
        "redepo_max_distance_a": float(max_dist),
        "max_los_candidates_per_source": 0,
        "los_candidate_weight_fraction": 1.0,
        "soft_los_radius_points": 0,
        "soft_los_width_a": 0.0,
        "soft_los_candidate_samples": 0,
        "soft_los_partial_candidate_count": 0,
        "mean_rough_targets_per_source": (
            float(total_candidate_target_count / active_source_count)
            if active_source_count > 0
            else 0.0
        ),
        "mean_los_candidates_per_source": (
            float(total_valid_target_count / active_source_count)
            if active_source_count > 0
            else 0.0
        ),
        "mean_valid_targets_per_active_source": (
            float(total_valid_target_count / active_source_with_targets)
            if active_source_with_targets > 0
            else 0.0
        ),
        "distance_power_ignored": 0.0,
        "redepo_lateral_spread_a": 0.0,
        "redepo_spread_radius_points": 0,
        "redepo_cap_ignored_ratio": 0.0,
        "symmetry_preserved": False,
        "symmetry_pair_count": 0,
        "transported_removed_mass": float(sum(source_removed_mass_field)),
        "transported_removed_mass_ratio": (
            float(sum(source_removed_mass_field) / total_removed_mass)
            if total_removed_mass > _EPS
            else 0.0
        ),
        "max_dh_etch": max((float(v) for v in etch_values), default=0.0),
        "max_dh_redepo": max(dh_redepo, default=0.0),
        "mean_dh_redepo": float(sum(dh_redepo) / n) if n > 0 else 0.0,
        "redepo_cap_a": 0.0,
        **_mass_summary_by_source_zone(pts, source_removed_mass_field),
    }
    debug_fields = {
        "arc_weight_field": [round(float(v), 6) for v in areas],
        "removed_mass_field": [round(float(v), 6) for v in removed_mass],
        "redepo_source_etch_field": [round(float(v), 6) for v in source_etch_field],
        "redepo_source_mass_field": [round(float(v), 6) for v in source_removed_mass_field],
        "redepo_mass_field": [round(float(v), 6) for v in mass_to_target],
        "dh_redepo_field": [round(float(v), 6) for v in dh_redepo],
    }
    return Model4RedepositionResult(dh_redepo, debug_fields, summary)


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
    max_etch_value = max(etch_values, default=0.0)
    max_removed_mass = max(removed_mass, default=0.0)
    if total_removed_mass <= _EPS or efficiency <= _EPS:
        zero = [0.0 for _ in pts]
        summary = {
            "total_removed_mass": total_removed_mass,
            "total_redepo_mass": 0.0,
            "redepo_capture_ratio": 0.0,
            "active_source_count": 0,
            "active_target_count": 0,
            "positive_source_count": sum(1 for value in etch_values if value > 0.0),
            "source_activation_etch_cutoff": 0.0,
            "source_activation_mass_cutoff": 0.0,
            "max_dh_etch": max_etch_value,
            "max_dh_redepo": 0.0,
            "mean_dh_redepo": 0.0,
            **_mass_summary_by_source_zone(pts, removed_mass),
        }
        return Model4RedepositionResult(
            zero,
            {
                "arc_weight_field": [round(v, 6) for v in area],
                "removed_mass_field": [round(v, 6) for v in removed_mass],
                "redepo_source_etch_field": [0.0 for _ in pts],
                "redepo_source_mass_field": [0.0 for _ in pts],
                "redepo_mass_field": [0.0 for _ in pts],
                "dh_redepo_field": [0.0 for _ in pts],
            },
            summary,
        )

    emit_power = max(0.0, float(cfg.emit_power))
    transport_model = str(cfg.transport_model or "gapsim_original_per_vertex_los").strip().lower()
    if transport_model in {
        "gapsim_original_per_vertex_los",
        "gapsim_original",
        "original_gapsim",
        "per_vertex_los",
    }:
        return _compute_gapsim_original_per_vertex_los(
            pts,
            normal_values,
            etch_values,
            area,
            removed_mass,
            total_removed_mass,
            efficiency=efficiency,
            emit_power=emit_power,
            eps=max(_EPS, float(cfg.eps)),
        )

    neighbor_exclusion = max(0, int(cfg.neighbor_exclusion))
    eps = max(_EPS, float(cfg.eps))
    diag = _geometry_diagonal(pts)
    configured_max_dist = max(0.0, float(cfg.max_redepo_distance))
    max_dist = max(250.0, configured_max_dist if configured_max_dist > _EPS else diag)

    mass_to_target = [0.0 for _ in pts]
    positive_source_count = sum(1 for value in etch_values if value > 0.0)
    source_etch_cutoff = max(1e-9, max_etch_value * 0.05)
    source_cutoff = max(1e-9, total_removed_mass * 1e-6, max_removed_mass * 0.02)
    raw_source_indices = [
        idx
        for idx, mass in enumerate(removed_mass)
        if etch_values[idx] >= source_etch_cutoff and mass >= source_cutoff
    ]
    source_index_set = set(raw_source_indices)
    source_etch_field = [
        float(etch_values[idx]) if idx in source_index_set else 0.0
        for idx in range(n)
    ]
    source_removed_mass_field = [
        float(removed_mass[idx]) if idx in source_index_set else 0.0
        for idx in range(n)
    ]
    center_x = (min(x for x, _y in pts) + max(x for x, _y in pts)) * 0.5
    surface_y = max(y for _x, y in pts)
    bottom_y = min(y for _x, y in pts)
    depth_span = max(surface_y - bottom_y, _EPS)
    max_transport_sources = max(16, min(256, int(cfg.max_transport_sources)))
    emission_axis_model = str(cfg.emission_axis_model or "normal")
    if len(raw_source_indices) <= max_transport_sources:
        transport_sources = [
            (idx, removed_mass[idx], pts[idx], _emission_axis(normal_values[idx], emission_axis_model))
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
            source_axis = _emission_axis(
                _normalize_vec(nx_centroid, ny_centroid, normal_values[representative]),
                emission_axis_model,
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
    # GapSim simulator uses a single lobe sigma parameter. The emulator keeps
    # the older "emit power" knob, mapped so 1.0 keeps a broad normal-centered
    # sputtered-neutral lobe and higher values narrow that lobe.
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
    typical_ds = _median_positive(area, fallback=max(1.0, diag / max(1, n - 1)))
    total_soft_los_sample_count = 0
    total_soft_los_partial_count = 0

    if transport_model in {
        "single_direction_gaussian_los",
        "single_axis_gaussian_los",
        "directional_gaussian_los",
    }:
        arc_coords = _arc_coordinates(pts)
        footprint_sigma_a = max(0.0, float(cfg.lateral_spread_a))
        footprint_radius_sigma = max(1.0, min(6.0, float(cfg.footprint_radius_sigma)))
        active_source_count = 0
        total_ray_count = 0
        total_hit_ray_count = 0
        total_footprint_point_count = 0
        total_valid_target_count = 0
        total_source_mass = 0.0
        total_captured_source_mass = 0.0
        total_soft_los_sample_count = 0
        total_soft_los_partial_count = 0
        los = _line_of_sight_engine(pts, normal_values)

        for i, mass_i, source, axis in transport_sources:
            source_mass = float(mass_i) * efficiency
            if source_mass <= _EPS:
                continue
            total_source_mass += source_mass
            total_ray_count += 1
            axis_vec = _normalize_vec(axis[0], axis[1])
            hit = _ray_first_hit(
                pts,
                normal_values,
                source_index=i,
                source=source,
                direction=axis_vec,
                max_distance=max_dist,
                neighbor_exclusion=neighbor_exclusion,
                eps=eps,
            )
            if hit is None:
                continue
            seg_idx, u, _dist, _hit_point, hit_normal = hit
            cos_receive = (hit_normal[0] * -axis_vec[0]) + (hit_normal[1] * -axis_vec[1])
            if cos_receive <= _EPS:
                continue
            seg_len = arc_coords[seg_idx + 1] - arc_coords[seg_idx]
            hit_s = arc_coords[seg_idx] + (u * seg_len)
            affected, soft_samples, soft_partials = _deposit_directional_gaussian_footprint_los(
                mass_to_target,
                area,
                arc_coords,
                pts,
                normal_values,
                los,
                source_index=i,
                source=source,
                axis=axis_vec,
                hit_s=hit_s,
                mass=source_mass,
                sigma_a=footprint_sigma_a,
                radius_sigma=footprint_radius_sigma,
                max_distance=max_dist,
                distance_power=max(0.0, float(cfg.distance_power)),
                neighbor_exclusion=neighbor_exclusion,
                soft_los_width_a=soft_los_width_a,
                eps=eps,
            )
            total_soft_los_sample_count += soft_samples
            total_soft_los_partial_count += soft_partials
            if affected <= 0:
                continue
            active_source_count += 1
            total_hit_ray_count += 1
            total_valid_target_count += 1
            total_footprint_point_count += affected
            total_captured_source_mass += source_mass

        deband_spacing_a = _transport_source_spacing_a(transport_sources, center_x=center_x)
        deband_radius_a = 0.0
        deband_radius_points = 0
        if (
            len(raw_source_indices) > len(transport_sources)
            and footprint_sigma_a > _EPS
            and deband_spacing_a > _EPS
        ):
            deband_radius_a = max(
                footprint_sigma_a,
                min(footprint_radius_sigma * footprint_sigma_a, 0.75 * deband_spacing_a),
            )
            deband_radius_points = int(round(deband_radius_a / max(typical_ds, eps)))
            if deband_radius_points > 0:
                mass_to_target = _smooth_exposed_surface_mass(
                    pts,
                    normal_values,
                    mass_to_target,
                    radius_points=deband_radius_points,
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
        spread_radius = int(round((footprint_radius_sigma * footprint_sigma_a) / max(typical_ds, eps))) if footprint_sigma_a > 0 else 0
        summary = {
            "total_removed_mass": total_removed_mass,
            "total_redepo_mass": total_redepo_mass,
            "redepo_capture_ratio": float(total_redepo_mass / total_removed_mass) if total_removed_mass > _EPS else 0.0,
            "active_source_count": int(active_source_count),
            "active_target_count": int(active_target_count),
            "positive_source_count": int(positive_source_count),
            "source_activation_etch_cutoff": float(source_etch_cutoff),
            "source_activation_mass_cutoff": float(source_cutoff),
            "raw_source_count": int(len(raw_source_indices)),
            "transport_source_count": int(len(transport_sources)),
            "transport_source_stride": 0,
            "transport_model": "single_direction_gaussian_los",
            "transport_source_position_model": "mass_centroid_surface_normal_axis",
            "max_transport_sources": int(max_transport_sources),
            "redepo_lobe_sigma_deg": float(sigma),
            "redepo_cone_cut_deg": 0.0,
            "redepo_max_distance_a": float(max_dist),
            "redepo_ray_count": 1,
            "redepo_ray_span_deg": 0.0,
            "redepo_total_ray_count": int(total_ray_count),
            "redepo_hit_ray_count": int(total_hit_ray_count),
            "redepo_hit_ray_ratio": float(total_hit_ray_count / total_ray_count) if total_ray_count > 0 else 0.0,
            "redepo_captured_emit_weight_ratio": (
                float(total_captured_source_mass / total_source_mass)
                if total_source_mass > _EPS
                else 0.0
            ),
            "mean_valid_targets_per_active_source": (
                float(total_valid_target_count / active_source_count)
                if active_source_count > 0
                else 0.0
            ),
            "mean_footprint_points_per_hit": (
                float(total_footprint_point_count / total_valid_target_count)
                if total_valid_target_count > 0
                else 0.0
            ),
            "soft_los_radius_points": int(soft_los_radius),
            "soft_los_width_a": float(soft_los_width_a),
            "soft_los_candidate_samples": int(total_soft_los_sample_count),
            "soft_los_partial_candidate_count": int(total_soft_los_partial_count),
            "distance_power_used": float(cfg.distance_power),
            "redepo_lateral_spread_a": float(footprint_sigma_a),
            "redepo_footprint_sigma_a": float(footprint_sigma_a),
            "redepo_footprint_radius_sigma": float(footprint_radius_sigma),
            "redepo_spread_radius_points": int(max(0, spread_radius)),
            "redepo_deband_spacing_a": float(deband_spacing_a),
            "redepo_deband_smoothing_radius_a": float(deband_radius_a),
            "redepo_deband_smoothing_radius_points": int(max(0, deband_radius_points)),
            "redepo_cap_ignored_ratio": float(cfg.max_redepo_to_etch_ratio),
            "symmetry_preserved": bool(symmetry_preserved),
            "symmetry_pair_count": int(len(symmetry_pairs)),
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
            "redepo_source_etch_field": [round(v, 6) for v in source_etch_field],
            "redepo_source_mass_field": [round(v, 6) for v in source_removed_mass_field],
            "redepo_mass_field": [round(v, 6) for v in mass_to_target],
            "dh_redepo_field": [round(v, 6) for v in dh_redepo],
        }
        return Model4RedepositionResult(dh_redepo, debug_fields, summary)

    if transport_model in {"fast_first_hit_cone", "first_hit_cone", "ray_first_hit"}:
        ray_count = max(3, min(31, int(cfg.ray_count)))
        if ray_count % 2 == 0:
            ray_count += 1
        ray_span_rad = math.radians(min(80.0, max(12.0, cone_cut_deg)))
        offsets = [
            -ray_span_rad + ((2.0 * ray_span_rad * idx) / max(1, ray_count - 1))
            for idx in range(ray_count)
        ]
        arc_coords = _arc_coordinates(pts)
        footprint_sigma_a = max(0.0, float(cfg.lateral_spread_a))
        footprint_radius_sigma = max(1.0, min(6.0, float(cfg.footprint_radius_sigma)))
        active_source_count = 0
        total_ray_count = 0
        total_hit_ray_count = 0
        total_footprint_point_count = 0
        total_valid_target_count = 0
        total_captured_emit_weight = 0.0
        total_emit_weight = 0.0

        for i, mass_i, source, axis in transport_sources:
            source_mass = float(mass_i) * efficiency
            if source_mass <= _EPS:
                continue
            ray_hits: List[Tuple[int, float, float, float]] = []
            source_emit_weight = 0.0
            source_captured_emit_weight = 0.0
            axis_vec = _normalize_vec(axis[0], axis[1])
            for offset in offsets:
                total_ray_count += 1
                ray_dir = _rotate_vector(axis_vec, offset)
                dev_deg = abs(math.degrees(offset))
                emit_weight = math.exp(-((dev_deg / sigma) ** 2))
                if emit_weight <= _EPS:
                    continue
                source_emit_weight += emit_weight
                hit = _ray_first_hit(
                    pts,
                    normal_values,
                    source_index=i,
                    source=source,
                    direction=ray_dir,
                    max_distance=max_dist,
                    neighbor_exclusion=neighbor_exclusion,
                    eps=eps,
                )
                if hit is None:
                    continue
                seg_idx, u, dist, _hit_point, hit_normal = hit
                cos_receive = (hit_normal[0] * -ray_dir[0]) + (hit_normal[1] * -ray_dir[1])
                if cos_receive <= _EPS:
                    continue
                dist_weight = 1.0 / ((dist + eps) ** max(0.0, float(cfg.distance_power)))
                distribution_weight = emit_weight * cos_receive * dist_weight
                if distribution_weight <= _EPS:
                    continue
                seg_len = arc_coords[seg_idx + 1] - arc_coords[seg_idx]
                hit_s = arc_coords[seg_idx] + (u * seg_len)
                ray_hits.append((seg_idx, hit_s, emit_weight, distribution_weight))
                source_captured_emit_weight += emit_weight
                total_hit_ray_count += 1

            if not ray_hits or source_emit_weight <= _EPS:
                total_emit_weight += source_emit_weight
                continue
            total_emit_weight += source_emit_weight
            total_captured_emit_weight += source_captured_emit_weight
            captured_mass = source_mass * _clamp01(source_captured_emit_weight / max(source_emit_weight, _EPS))
            hit_weight_sum = sum(weight for _seg_idx, _hit_s, _emit_w, weight in ray_hits)
            if captured_mass <= _EPS or hit_weight_sum <= _EPS:
                continue
            active_source_count += 1
            for _seg_idx, hit_s, _emit_weight, weight in ray_hits:
                hit_mass = captured_mass * (weight / hit_weight_sum)
                affected = _deposit_gaussian_footprint(
                    mass_to_target,
                    area,
                    arc_coords,
                    hit_s=hit_s,
                    mass=hit_mass,
                    sigma_a=footprint_sigma_a,
                    radius_sigma=footprint_radius_sigma,
                    source_index=i,
                    neighbor_exclusion=neighbor_exclusion,
                    eps=eps,
                )
                total_footprint_point_count += affected
                if affected > 0:
                    total_valid_target_count += 1

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
        spread_radius = int(round((footprint_radius_sigma * footprint_sigma_a) / max(typical_ds, eps))) if footprint_sigma_a > 0 else 0
        summary = {
            "total_removed_mass": total_removed_mass,
            "total_redepo_mass": total_redepo_mass,
            "redepo_capture_ratio": float(total_redepo_mass / total_removed_mass) if total_removed_mass > _EPS else 0.0,
            "active_source_count": int(active_source_count),
            "active_target_count": int(active_target_count),
            "positive_source_count": int(positive_source_count),
            "source_activation_etch_cutoff": float(source_etch_cutoff),
            "source_activation_mass_cutoff": float(source_cutoff),
            "raw_source_count": int(len(raw_source_indices)),
            "transport_source_count": int(len(transport_sources)),
            "transport_source_stride": 0,
            "transport_model": "fast_first_hit_cone",
            "transport_source_position_model": "mass_centroid_surface_normal_ray",
            "max_transport_sources": int(max_transport_sources),
            "redepo_lobe_sigma_deg": float(sigma),
            "redepo_cone_cut_deg": float(cone_cut_deg),
            "redepo_max_distance_a": float(max_dist),
            "redepo_ray_count": int(ray_count),
            "redepo_ray_span_deg": float(math.degrees(ray_span_rad)),
            "redepo_total_ray_count": int(total_ray_count),
            "redepo_hit_ray_count": int(total_hit_ray_count),
            "redepo_hit_ray_ratio": float(total_hit_ray_count / total_ray_count) if total_ray_count > 0 else 0.0,
            "redepo_captured_emit_weight_ratio": (
                float(total_captured_emit_weight / total_emit_weight)
                if total_emit_weight > _EPS
                else 0.0
            ),
            "mean_valid_targets_per_active_source": (
                float(total_valid_target_count / active_source_count)
                if active_source_count > 0
                else 0.0
            ),
            "mean_footprint_points_per_hit": (
                float(total_footprint_point_count / total_valid_target_count)
                if total_valid_target_count > 0
                else 0.0
            ),
            "distance_power_used": float(cfg.distance_power),
            "redepo_lateral_spread_a": float(footprint_sigma_a),
            "redepo_footprint_sigma_a": float(footprint_sigma_a),
            "redepo_footprint_radius_sigma": float(footprint_radius_sigma),
            "redepo_spread_radius_points": int(max(0, spread_radius)),
            "redepo_cap_ignored_ratio": float(cfg.max_redepo_to_etch_ratio),
            "symmetry_preserved": bool(symmetry_preserved),
            "symmetry_pair_count": int(len(symmetry_pairs)),
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
            "redepo_source_etch_field": [round(v, 6) for v in source_etch_field],
            "redepo_source_mass_field": [round(v, 6) for v in source_removed_mass_field],
            "redepo_mass_field": [round(v, 6) for v in mass_to_target],
            "dh_redepo_field": [round(v, 6) for v in dh_redepo],
        }
        return Model4RedepositionResult(dh_redepo, debug_fields, summary)

    los = _line_of_sight_engine(pts, normal_values)

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
        "positive_source_count": int(positive_source_count),
        "source_activation_etch_cutoff": float(source_etch_cutoff),
        "source_activation_mass_cutoff": float(source_cutoff),
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
        "redepo_source_etch_field": [round(v, 6) for v in source_etch_field],
        "redepo_source_mass_field": [round(v, 6) for v in source_removed_mass_field],
        "redepo_mass_field": [round(v, 6) for v in mass_to_target],
        "dh_redepo_field": [round(v, 6) for v in dh_redepo],
    }
    return Model4RedepositionResult(dh_redepo, debug_fields, summary)
