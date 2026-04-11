from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from gapsim.engine.ion_los import OpeningLOS, PathLOS, build_opening_segment
from gapsim.engine.source_transport import resolve_source_transport

try:
    import pyclipper
except Exception:  # noqa: BLE001
    pyclipper = None  # type: ignore[assignment]

Point = Tuple[float, float]
IntPoint = Tuple[int, int]
IntPath = List[IntPoint]

_EPS = 1e-12
_ETCH_FLUX_PRUNE_EPS = 1e-4
_REDEPO_MASS_PRUNE_REL = 1e-6
_SPUTTER_STRENGTH_GAIN = 3.0

# SiO2 continuum representation limits (Angstrom)
SIO2_L_MIN_A = 5.0
REPARAM_DS_A = 0.5 * SIO2_L_MIN_A


class SimulationCanceled(RuntimeError):
    pass


def _dedupe_consecutive(points: Sequence[Point], *, eps: float = 1e-10) -> List[Point]:
    out: List[Point] = []
    for x, y in points:
        p = (float(x), float(y))
        if out and abs(out[-1][0] - p[0]) <= eps and abs(out[-1][1] - p[1]) <= eps:
            continue
        out.append(p)
    return out


def normalize_surface_order(points: Sequence[Point]) -> List[Point]:
    pts = _dedupe_consecutive(points)
    if len(pts) >= 2 and pts[0][0] > pts[-1][0]:
        pts = list(reversed(pts))
    return pts


def _clamp_reparam_ds(value: float) -> float:
    return max(0.5, min(200.0, float(value)))


def _state_reparam_ds(state: SimulationState) -> float:
    return _clamp_reparam_ds(float(state.meta.get("reparam_ds", REPARAM_DS_A)))


def equal_arc_resample(points: Sequence[Point], ds: float) -> List[Point]:
    pts = normalize_surface_order(points)
    if len(pts) < 2:
        return pts
    ds = float(ds)
    if ds <= _EPS:
        return pts

    seg_lens: List[float] = []
    total = 0.0
    for i in range(len(pts) - 1):
        l = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        seg_lens.append(l)
        total += l
    if total <= _EPS:
        return pts

    n_seg = max(1, int(math.ceil(total / ds)))
    step = total / float(n_seg)

    out: List[Point] = [pts[0]]
    seg_i = 0
    seg_start_s = 0.0
    for k in range(1, n_seg):
        target_s = step * float(k)
        while seg_i < (len(seg_lens) - 1) and (seg_start_s + seg_lens[seg_i]) < target_s:
            seg_start_s += seg_lens[seg_i]
            seg_i += 1

        l = seg_lens[seg_i]
        if l <= _EPS:
            out.append(pts[seg_i + 1])
            continue
        u = (target_s - seg_start_s) / l
        u = max(0.0, min(1.0, u))
        x0, y0 = pts[seg_i]
        x1, y1 = pts[seg_i + 1]
        out.append((x0 + (x1 - x0) * u, y0 + (y1 - y0) * u))

    out.append(pts[-1])
    out = normalize_surface_order(out)
    return out if len(out) >= 2 else pts


def _int_path_area(path: Sequence[IntPoint]) -> int:
    area2 = 0
    n = len(path)
    for i in range(n):
        x1, y1 = path[i]
        x2, y2 = path[(i + 1) % n]
        area2 += x1 * y2 - x2 * y1
    return area2


def _normalize_int_path(path: Sequence[IntPoint]) -> IntPath:
    out: IntPath = []
    for x, y in path:
        p = (int(x), int(y))
        if out and out[-1] == p:
            continue
        out.append(p)
    if len(out) >= 2 and out[0] == out[-1]:
        out.pop()
    if len(out) < 3:
        return []
    if _int_path_area(out) == 0:
        return []
    return out


def _normalize_int_paths(paths: Iterable[Sequence[IntPoint]]) -> List[IntPath]:
    out: List[IntPath] = []
    for p in paths:
        q = _normalize_int_path(p)
        if q:
            out.append(q)
    return out


def _to_int_points(points: Sequence[Point], scale: int) -> IntPath:
    return [(int(round(x * scale)), int(round(y * scale))) for x, y in points]


def _to_float_points(path: Sequence[IntPoint], scale: int) -> List[Point]:
    inv = 1.0 / float(scale)
    return [(x * inv, y * inv) for x, y in path]


def _clip_execute(
    subject_paths: Sequence[Sequence[IntPoint]],
    clip_paths: Sequence[Sequence[IntPoint]],
    clip_type: int,
) -> List[IntPath]:
    OffsetBoolean.require_backend()

    subjects = _normalize_int_paths(subject_paths)
    clips = _normalize_int_paths(clip_paths)
    if not subjects and clip_type != pyclipper.CT_UNION:
        return []
    if clip_type == pyclipper.CT_UNION and not subjects:
        return clips

    pc = pyclipper.Pyclipper()
    if subjects:
        pc.AddPaths(subjects, pyclipper.PT_SUBJECT, True)
    if clips:
        pc.AddPaths(clips, pyclipper.PT_CLIP, True)

    result = pc.Execute(clip_type, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
    cleaned = pyclipper.CleanPolygons(result, 1.0)
    return _normalize_int_paths(cleaned)


def _clip_difference_tree(
    subject_paths: Sequence[Sequence[IntPoint]],
    clip_paths: Sequence[Sequence[IntPoint]],
):
    OffsetBoolean.require_backend()

    subjects = _normalize_int_paths(subject_paths)
    clips = _normalize_int_paths(clip_paths)
    pc = pyclipper.Pyclipper()
    if subjects:
        pc.AddPaths(subjects, pyclipper.PT_SUBJECT, True)
    if clips:
        pc.AddPaths(clips, pyclipper.PT_CLIP, True)
    return pc.Execute2(pyclipper.CT_DIFFERENCE, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def _clip_union(a: Sequence[Sequence[IntPoint]], b: Sequence[Sequence[IntPoint]]) -> List[IntPath]:
    return _clip_execute(a, b, pyclipper.CT_UNION)


def _clip_intersection(a: Sequence[Sequence[IntPoint]], b: Sequence[Sequence[IntPoint]]) -> List[IntPath]:
    return _clip_execute(a, b, pyclipper.CT_INTERSECTION)


def _clip_difference(a: Sequence[Sequence[IntPoint]], b: Sequence[Sequence[IntPoint]]) -> List[IntPath]:
    return _clip_execute(a, b, pyclipper.CT_DIFFERENCE)


def _clip_offset(paths: Sequence[Sequence[IntPoint]], delta: int, arc_tolerance: float) -> List[IntPath]:
    OffsetBoolean.require_backend()
    src = _normalize_int_paths(paths)
    if not src:
        return []
    if delta == 0:
        return src
    pco = pyclipper.PyclipperOffset(miter_limit=2.0, arc_tolerance=arc_tolerance)
    pco.AddPaths(src, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    out = pco.Execute(delta)
    cleaned = pyclipper.CleanPolygons(out, 1.0)
    return _normalize_int_paths(cleaned)


def _iter_polytree_nodes(root) -> Iterable[Any]:
    stack = list(getattr(root, "Childs", []))
    while stack:
        node = stack.pop()
        yield node
        stack.extend(getattr(node, "Childs", []))


@dataclass
class Surface:
    points: List[Point]
    direction: str = "left_to_right"
    wall_tags: List[str] = field(default_factory=list)


@dataclass
class SimulationState:
    surface: Surface
    scale: int
    x_left_i: int
    x_right_i: int
    y_top_i: int
    y_bot_i: int
    roi_path_i: IntPath
    solid_paths_i: List[IntPath]
    meta: Dict[str, Any] = field(default_factory=dict)


def init_simulation_state(
    pts: Sequence[Point],
    *,
    scale: int = 2000,
    step_idx: int = 0,
    units: str = "A",
    reparam_ds_a: float = REPARAM_DS_A,
) -> SimulationState:
    surface = normalize_surface_order(pts)
    if len(surface) < 2:
        raise ValueError("Surface must have at least 2 points")

    x_left = float(surface[0][0])
    x_right = float(surface[-1][0])
    if x_right - x_left <= _EPS:
        raise ValueError("Surface endpoints must define a positive x-span")

    ys = [p[1] for p in surface]
    y_min = min(ys)
    y_max = max(ys)
    y_span = max(y_max - y_min, 1.0)
    y_margin = max(1000.0, y_span * 2.0)
    y_top = y_max + y_margin
    y_bot = y_min - y_margin

    roi = [(x_left, y_top), (x_right, y_top), (x_right, y_bot), (x_left, y_bot)]
    roi_i = _normalize_int_path(_to_int_points(roi, scale))
    if not roi_i:
        raise ValueError("Failed to initialize ROI polygon")

    solid_paths = OffsetBoolean.surface_to_solid(surface, scale=scale, y_bot_i=roi_i[2][1], roi_path_i=roi_i)
    if not solid_paths:
        raise ValueError("Failed to initialize solid polygon from surface")

    return SimulationState(
        surface=Surface(points=list(surface)),
        scale=scale,
        x_left_i=roi_i[0][0],
        x_right_i=roi_i[1][0],
        y_top_i=roi_i[0][1],
        y_bot_i=roi_i[2][1],
        roi_path_i=roi_i,
        solid_paths_i=solid_paths,
        meta={
            "step_idx": int(step_idx),
            "dr": 0.0,
            "units": str(units),
            "l_min": SIO2_L_MIN_A,
            "reparam_ds": _clamp_reparam_ds(reparam_ds_a),
        },
    )


class FluxModel:
    def compute_flux(self, state: SimulationState) -> List[float]:
        raise NotImplementedError

    def recommended_substeps(self, state: SimulationState, dr: float) -> int:
        return 1


class ConformalFluxModel(FluxModel):
    def compute_flux(self, state: SimulationState) -> List[float]:
        n = len(state.surface.points)
        if n <= 0:
            return []
        return [1.0] * n


class ZeroFluxModel(FluxModel):
    def compute_flux(self, state: SimulationState) -> List[float]:
        n = len(state.surface.points)
        if n <= 0:
            return []
        return [0.0] * n


class SealingFluxModel(FluxModel):
    def __init__(
        self,
        *,
        epsilon: float,
        sealed_model: str = "a",
        decay_k: float = 1.0,
        source_kind: str = "none",
        source_onset_width_a: float = 0.0,
        source_decay_pct: float | None = None,
        source_distance_decay_pct: float = 0.0,
        source_distance_decay_len_a: float | None = None,  # legacy key
        source_block_width_a: float | None = None,  # legacy key
        source_gamma: float | None = None,  # legacy key
    ) -> None:
        self.epsilon = max(0.0, float(epsilon))
        self.sealed_model = str(sealed_model or "a").lower()
        self.decay_k = max(0.0, float(decay_k))
        sid, ow, dp = resolve_source_transport(
            source_id=source_kind,
            onset_width_a=source_onset_width_a,
            decay_pct=source_decay_pct,
            block_width_a=source_block_width_a,
            gamma=source_gamma,
        )
        self.source_kind = sid
        self.source_onset_width_a = ow
        self.source_decay_pct = dp

        dist_pct = max(0.0, min(100.0, float(source_distance_decay_pct)))
        if dist_pct <= 0.0 and source_distance_decay_len_a is not None:
            # Legacy fallback: map L(A) to an equivalent percent at 100A reference.
            len_a = max(0.0, float(source_distance_decay_len_a))
            if len_a > 0.0:
                dist_pct = (1.0 - math.exp(-100.0 / max(len_a, 1e-9))) * 100.0
        self.source_distance_decay_pct = max(0.0, min(100.0, dist_pct))

        self._opening_transport_enabled = (self.source_kind != "none") or (
            self.source_onset_width_a > 0.0 and self.source_decay_pct > 0.0
        )
        self._distance_transport_enabled = self.source_distance_decay_pct > 0.0
        self._transport_enabled = self._opening_transport_enabled or self._distance_transport_enabled
        self._cell_a = max(REPARAM_DS_A * 4.0, 8.0)

    @staticmethod
    def _exp_decay_from_pct(q: float, decay_pct: float, width: float) -> float:
        t = max(0.0, min(1.0, float(q)))
        p = max(0.0, min(100.0, float(decay_pct)))
        if p <= 0.0:
            return 1.0
        if p >= 100.0:
            # Near-complete suppression at closed neck, still numerically stable.
            f = math.exp(-12.0 * t)
            if width <= 0.0:
                return 0.0
            return max(0.0, min(1.0, f))
        min_factor = max(1e-6, 1.0 - (p / 100.0))
        k = -math.log(min_factor)
        return max(0.0, min(1.0, math.exp(-k * t)))

    @staticmethod
    def _fill_missing(vals: List[float], default_val: float) -> List[float]:
        n = len(vals)
        if n <= 0:
            return []
        out: List[float] = [float(v) for v in vals]

        last = None
        for i in range(n):
            if math.isfinite(out[i]):
                last = out[i]
            elif last is not None:
                out[i] = last

        last = None
        for i in range(n - 1, -1, -1):
            if math.isfinite(out[i]):
                last = out[i]
            elif last is not None:
                out[i] = last

        dv = float(max(default_val, 0.0))
        for i in range(n):
            if not math.isfinite(out[i]):
                out[i] = dv
        return out

    @staticmethod
    def _is_facing_pair(pi: Point, ni: Point, pj: Point, nj: Point) -> bool:
        dx = float(pj[0] - pi[0])
        dy = float(pj[1] - pi[1])
        d = math.hypot(dx, dy)
        if d <= _EPS:
            return False
        ux = dx / d
        uy = dy / d
        # Both normals should face each other across the local opening.
        if (ni[0] * ux + ni[1] * uy) < 0.12:
            return False
        if (nj[0] * (-ux) + nj[1] * (-uy)) < 0.12:
            return False
        if (ni[0] * nj[0] + ni[1] * nj[1]) > -0.05:
            return False
        return True

    def _isotropic_local_openings(self, pts: Sequence[Point], default_opening: float) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        if n == 1:
            return [max(default_opening, 0.0)]

        normals = VertexNormalPropagator._vertex_air_normals(pts)
        if len(normals) != n:
            normals = [(0.0, 1.0)] * n

        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        # Fallback should stay close to physical opening scale; using full-diagonal can mask attenuation.
        default_w = max(float(default_opening), self.source_onset_width_a)

        # Slightly wider search radius improves opposite-wall pairing near oblique/curved necks.
        radius = max(self.source_onset_width_a * 2.5, 48.0)
        cell = max(self._cell_a, radius / 6.0)
        inv_cell = 1.0 / cell
        ring = max(1, int(math.ceil(radius / cell)))
        index_exclusion = 6

        grid: Dict[Tuple[int, int], List[int]] = {}
        for i, (x, y) in enumerate(pts):
            cx = int(math.floor(float(x) * inv_cell))
            cy = int(math.floor(float(y) * inv_cell))
            grid.setdefault((cx, cy), []).append(i)

        out = [math.inf] * n
        for i, (x, y) in enumerate(pts):
            cx = int(math.floor(float(x) * inv_cell))
            cy = int(math.floor(float(y) * inv_cell))

            best_strict = math.inf
            best_loose = math.inf
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    candidates = grid.get((cx + dx, cy + dy))
                    if not candidates:
                        continue
                    for j in candidates:
                        if i == j or abs(i - j) <= index_exclusion:
                            continue
                        pj = pts[j]
                        d = math.hypot(float(pj[0] - x), float(pj[1] - y))
                        if d <= _EPS or d > radius:
                            continue
                        ni = normals[i]
                        nj = normals[j]
                        ux = float(pj[0] - x) / d
                        uy = float(pj[1] - y) / d
                        dot_i = ni[0] * ux + ni[1] * uy
                        dot_j = nj[0] * (-ux) + nj[1] * (-uy)
                        n_dot = ni[0] * nj[0] + ni[1] * nj[1]

                        if self._is_facing_pair((float(x), float(y)), ni, pj, nj):
                            if d < best_strict:
                                best_strict = d
                            continue

                        # Loose fallback: directional approach is valid, while rejecting near-parallel same-wall pairs.
                        if dot_i > 0.02 and dot_j > 0.02 and n_dot < 0.7:
                            if d < best_loose:
                                best_loose = d
            if math.isfinite(best_strict):
                out[i] = best_strict
            elif math.isfinite(best_loose):
                out[i] = best_loose

        return self._fill_missing(out, default_w)

    def _transport_factor(self, w: float, ow: float, decay_pct: float) -> float:
        if ow <= 0.0:
            return 1.0
        if w >= ow:
            return 1.0
        q = (ow - max(0.0, float(w))) / max(ow, 1e-12)
        return self._exp_decay_from_pct(q, decay_pct, w)

    def _transport_factor_vector(self, openings: Sequence[float]) -> List[float]:
        ow = max(0.0, float(self.source_onset_width_a))
        dp = max(0.0, min(100.0, float(self.source_decay_pct)))
        return [self._transport_factor(max(0.0, float(w)), ow, dp) for w in openings]

    @staticmethod
    def _cumulative_arc_lengths(pts: Sequence[Point]) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        out = [0.0] * n
        for i in range(1, n):
            out[i] = out[i - 1] + math.hypot(
                float(pts[i][0] - pts[i - 1][0]),
                float(pts[i][1] - pts[i - 1][1]),
            )
        return out

    @staticmethod
    def _entrance_indices_from_top_band(pts: Sequence[Point]) -> List[int]:
        n = len(pts)
        if n <= 0:
            return []
        ys = [float(p[1]) for p in pts]
        y_max = max(ys)
        y_min = min(ys)
        y_span = max(1.0, y_max - y_min)
        band = max(2.0 * REPARAM_DS_A, 0.02 * y_span)
        idx = [i for i, y in enumerate(ys) if (y_max - y) <= band]
        if 0 not in idx:
            idx.append(0)
        if (n - 1) not in idx:
            idx.append(n - 1)
        idx.sort()
        return idx

    @classmethod
    def _distance_from_entrance_along_surface(cls, pts: Sequence[Point]) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        if n == 1:
            return [0.0]

        arc = cls._cumulative_arc_lengths(pts)
        entrance_idx = cls._entrance_indices_from_top_band(pts)
        if not entrance_idx:
            total = arc[-1]
            return [min(s, max(0.0, total - s)) for s in arc]

        marked = [False] * n
        for i in entrance_idx:
            if 0 <= i < n:
                marked[i] = True

        out = [math.inf] * n
        prev_s: float | None = None
        for i in range(n):
            if marked[i]:
                prev_s = arc[i]
                out[i] = 0.0
            elif prev_s is not None:
                out[i] = arc[i] - prev_s

        next_s: float | None = None
        for i in range(n - 1, -1, -1):
            if marked[i]:
                next_s = arc[i]
            elif next_s is not None:
                out[i] = min(out[i], next_s - arc[i])

        total = arc[-1]
        for i in range(n):
            if not math.isfinite(out[i]):
                out[i] = min(arc[i], max(0.0, total - arc[i]))
        return out

    def _distance_decay_factors(self, pts: Sequence[Point]) -> Tuple[List[float], float]:
        n = len(pts)
        if n <= 0:
            return [], 0.0
        p = max(0.0, min(100.0, float(self.source_distance_decay_pct)))
        if p <= 0.0:
            return [1.0] * n, 0.0

        dists = self._distance_from_entrance_along_surface(pts)
        max_dist = max(dists) if dists else 0.0
        if max_dist <= 1e-9:
            return [1.0] * n, float(max_dist)

        # Interpret source_distance_decay_pct as:
        # "attenuation at the farthest reachable point from entrance".
        # dist=0 -> factor=1.0, dist=max_dist -> factor=(1 - p/100).
        min_factor = max(1e-6, 1.0 - (p / 100.0))
        inv_ref = 1.0 / max_dist
        factors = [max(0.0, min(1.0, math.pow(min_factor, max(0.0, d) * inv_ref))) for d in dists]
        return factors, float(max_dist)

    def _transport_flux_factors(self, pts: Sequence[Point], global_opening: float) -> Tuple[List[float], float]:
        n = len(pts)
        if n <= 0:
            return [], 0.0
        if not self._opening_transport_enabled:
            return [1.0] * n, float(global_opening)

        local_openings = self._isotropic_local_openings(pts, float(global_opening))
        bottleneck = [max(0.0, float(v)) for v in local_openings]
        factors = self._transport_factor_vector(bottleneck)
        return factors, (min(bottleneck) if bottleneck else float(global_opening))

    def compute_flux(self, state: SimulationState) -> List[float]:
        pts = state.surface.points
        n = len(pts)
        if n <= 0:
            return []

        xs = [p[0] for p in pts]
        opening = float(max(xs) - min(xs)) if xs else 0.0
        factor = 1.0
        mode = "open"
        if opening <= self.epsilon:
            mode = "sealed"
            if self.sealed_model.startswith("a"):
                factor = 0.0
            else:
                factor = math.exp(-self.decay_k * (self.epsilon - opening))
        transport, min_bottleneck = self._transport_flux_factors(pts, opening)
        if len(transport) != n:
            transport = [1.0] * n
        distance_factors, max_entrance_dist = self._distance_decay_factors(pts)
        if len(distance_factors) != n:
            distance_factors = [1.0] * n

        state.meta["mode"] = mode
        state.meta["opening"] = opening
        state.meta["flux_factor"] = factor
        state.meta["source_kind"] = self.source_kind
        state.meta["source_onset_width_a"] = self.source_onset_width_a
        state.meta["source_decay_pct"] = self.source_decay_pct
        state.meta["source_distance_decay_pct"] = self.source_distance_decay_pct
        state.meta["source_min_bottleneck_opening"] = float(min_bottleneck)
        state.meta["source_max_entrance_distance_a"] = float(max_entrance_dist)
        return [factor * transport[i] * distance_factors[i] for i in range(n)]


class DirectionalRayHelper:
    @staticmethod
    def normalize_ray_count(value: str | int) -> int:
        try:
            iv = int(value)
        except Exception:
            iv = 1
        if iv <= 4:
            return 1
        if iv <= 9:
            return 7
        if iv <= 13:
            return 11
        return 15

    @staticmethod
    def upward_ray_dirs(ray_count: int, spread_deg: float) -> List[Point]:
        ray_count = max(1, int(ray_count))
        spread_deg = max(0.0, float(spread_deg))
        if ray_count <= 1 or spread_deg <= _EPS:
            return [(0.0, 1.0)]

        spread_rad = math.radians(spread_deg)
        out: List[Point] = []
        for i in range(ray_count):
            t = i / float(ray_count - 1)
            ang = -spread_rad + (2.0 * spread_rad * t)
            out.append((math.sin(ang), math.cos(ang)))
        return out

    @staticmethod
    def point_projection(p: Point, axis: Point) -> float:
        return float(p[0]) * float(axis[0]) + float(p[1]) * float(axis[1])

    @classmethod
    def visibility_for_dir(cls, pts: Sequence[Point], ray_dir_up: Point) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        if n == 1:
            return [1.0]

        dx, dy = float(ray_dir_up[0]), float(ray_dir_up[1])
        dl = math.hypot(dx, dy)
        if dl <= _EPS:
            return [1.0] * n
        dx /= dl
        dy /= dl
        perp = (-dy, dx)

        bin_size = max(REPARAM_DS_A, 2.0)
        tol_v = max(1.0, REPARAM_DS_A * 0.75)
        max_v_by_bin: Dict[int, float] = {}

        for i in range(n - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            seg_len = math.hypot(float(bx - ax), float(by - ay))
            samples = max(1, int(math.ceil(seg_len / bin_size)))
            for si in range(samples + 1):
                t = si / float(samples)
                sx = float(ax + (bx - ax) * t)
                sy = float(ay + (by - ay) * t)
                u = sx * perp[0] + sy * perp[1]
                v = sx * dx + sy * dy
                bidx = int(round(u / bin_size))
                prev = max_v_by_bin.get(bidx)
                if prev is None or v > prev:
                    max_v_by_bin[bidx] = v

        out = [1.0] * n
        for i, p in enumerate(pts):
            u = cls.point_projection(p, perp)
            v = cls.point_projection(p, (dx, dy))
            bidx = int(round(u / bin_size))
            env_v = v
            for nb in (bidx - 1, bidx, bidx + 1):
                cand = max_v_by_bin.get(nb)
                if cand is not None and cand > env_v:
                    env_v = cand
            out[i] = 1.0 if (env_v - v) <= tol_v else 0.0
        return out

    @classmethod
    def shadow_visibility(cls, pts: Sequence[Point], ray_count: int, spread_deg: float) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        dirs = cls.upward_ray_dirs(ray_count, spread_deg)
        if not dirs:
            return [1.0] * n

        acc = [0.0] * n
        for d in dirs:
            vis = cls.visibility_for_dir(pts, d)
            if len(vis) != n:
                continue
            for i in range(n):
                acc[i] += max(0.0, min(1.0, float(vis[i])))
        inv = 1.0 / float(max(1, len(dirs)))
        return [max(0.0, min(1.0, v * inv)) for v in acc]

    @staticmethod
    def point_arc_weights(pts: Sequence[Point]) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        if n == 1:
            return [REPARAM_DS_A]
        seg_lens = [
            math.hypot(float(pts[i + 1][0] - pts[i][0]), float(pts[i + 1][1] - pts[i][1]))
            for i in range(n - 1)
        ]
        out = [0.0] * n
        out[0] = 0.5 * seg_lens[0]
        out[-1] = 0.5 * seg_lens[-1]
        for i in range(1, n - 1):
            out[i] = 0.5 * (seg_lens[i - 1] + seg_lens[i])
        return [max(REPARAM_DS_A, float(v)) for v in out]

    @classmethod
    def nearest_facing_partners(
        cls,
        pts: Sequence[Point],
        normals: Sequence[Point],
        max_radius: float,
        source_indices: Optional[Sequence[int]] = None,
    ) -> List[int]:
        n = len(pts)
        if n <= 0:
            return []
        if len(normals) != n:
            normals = VertexNormalPropagator._vertex_air_normals(pts)
        radius = max(40.0, float(max_radius))
        cell = max(REPARAM_DS_A * 6.0, min(120.0, radius / 4.0))
        inv_cell = 1.0 / max(cell, 1e-9)
        ring = max(1, int(math.ceil(radius / cell)))
        index_exclusion = 6

        grid: Dict[Tuple[int, int], List[int]] = {}
        for i, (x, y) in enumerate(pts):
            cx = int(math.floor(float(x) * inv_cell))
            cy = int(math.floor(float(y) * inv_cell))
            grid.setdefault((cx, cy), []).append(i)

        out = [-1] * n
        indices = list(range(n)) if source_indices is None else [int(i) for i in source_indices if 0 <= int(i) < n]
        for i in indices:
            x, y = pts[i]
            cx = int(math.floor(float(x) * inv_cell))
            cy = int(math.floor(float(y) * inv_cell))
            ni = normals[i]
            best_strict_d = math.inf
            best_strict_j = -1
            best_loose_d = math.inf
            best_loose_j = -1
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    candidates = grid.get((cx + dx, cy + dy))
                    if not candidates:
                        continue
                    for j in candidates:
                        if i == j or abs(i - j) <= index_exclusion:
                            continue
                        pj = pts[j]
                        d = math.hypot(float(pj[0] - x), float(pj[1] - y))
                        if d <= _EPS or d > radius:
                            continue
                        nj = normals[j]
                        ux = float(pj[0] - x) / d
                        uy = float(pj[1] - y) / d
                        dot_i = ni[0] * ux + ni[1] * uy
                        dot_j = nj[0] * (-ux) + nj[1] * (-uy)
                        n_dot = ni[0] * nj[0] + ni[1] * nj[1]
                        if SealingFluxModel._is_facing_pair((float(x), float(y)), ni, pj, nj):
                            if d < best_strict_d:
                                best_strict_d = d
                                best_strict_j = j
                            continue
                        if dot_i > 0.02 and dot_j > 0.02 and n_dot < 0.7 and d < best_loose_d:
                            best_loose_d = d
                            best_loose_j = j
            out[i] = best_strict_j if best_strict_j >= 0 else best_loose_j
        return out


class OverhangFluxModel(FluxModel):
    def __init__(
        self,
        base_model: FluxModel,
        *,
        directional_pct: float = 50.0,
        angle_pct: float = 22.222,
        shadow_pct: float = 100.0,
        ray_count: str | int = "1",
        ray_spread_deg: float = 0.0,
        flux_floor_pct: float = 5.0,
    ) -> None:
        self.base_model = base_model
        self.directional_pct = max(0.0, min(100.0, float(directional_pct)))
        self.angle_pct = max(0.0, min(100.0, float(angle_pct)))
        self.angle_power = 1.0 + 9.0 * (self.angle_pct / 100.0)
        self.shadow_pct = max(0.0, min(100.0, float(shadow_pct)))
        self.ray_count = DirectionalRayHelper.normalize_ray_count(ray_count)
        self.ray_spread_deg = max(0.0, min(30.0, float(ray_spread_deg)))
        self.flux_floor_pct = max(0.0, min(100.0, float(flux_floor_pct)))

    def compute_flux(self, state: SimulationState) -> List[float]:
        base_flux = [max(0.0, float(v)) for v in self.base_model.compute_flux(state)]
        pts = state.surface.points
        n = len(pts)
        if n <= 0:
            return []
        if len(base_flux) != n:
            base_flux = [1.0] * n

        p_dir = self.directional_pct / 100.0
        p_sh = self.shadow_pct / 100.0
        if p_dir <= _EPS:
            return base_flux

        normals = VertexNormalPropagator._vertex_air_normals(pts)
        if len(normals) != n:
            normals = [(0.0, 1.0)] * n

        angle_terms = [max(0.0, min(1.0, float(ny))) ** self.angle_power for _, ny in normals]
        vis = DirectionalRayHelper.shadow_visibility(pts, self.ray_count, self.ray_spread_deg)
        if len(vis) != n:
            vis = [1.0] * n

        avg_base = sum(base_flux) / float(n) if n > 0 else 0.0
        floor_abs = avg_base * (self.flux_floor_pct / 100.0)
        out: List[float] = []
        for i in range(n):
            shadow_term = (1.0 - p_sh) + p_sh * vis[i]
            mix = (1.0 - p_dir) + p_dir * angle_terms[i] * shadow_term
            flux_i = base_flux[i] * max(0.0, mix)
            floor_i = min(base_flux[i], floor_abs)
            out.append(max(flux_i, floor_i))

        state.meta["overhang_enabled"] = True
        state.meta["overhang_directional_pct"] = self.directional_pct
        state.meta["overhang_angle_pct"] = self.angle_pct
        state.meta["overhang_angle_power"] = self.angle_power
        state.meta["overhang_shadow_pct"] = self.shadow_pct
        state.meta["overhang_ray_count"] = self.ray_count
        state.meta["overhang_ray_spread_deg"] = self.ray_spread_deg
        state.meta["overhang_flux_floor_pct"] = self.flux_floor_pct
        state.meta["overhang_shadow_mean_visibility"] = sum(vis) / float(n) if n > 0 else 1.0
        return out


class InhibitionFluxModel(FluxModel):
    def __init__(
        self,
        base_model: FluxModel,
        *,
        i_max: float = 0.5,
        lambda_a: float = 500.0,
    ) -> None:
        self.base_model = base_model
        self.i_max = max(0.0, min(1.0, float(i_max)))
        self.lambda_a = max(0.0, float(lambda_a))

    @staticmethod
    def _arc_lengths(pts: Sequence[Point]) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        out = [0.0] * n
        for i in range(1, n):
            out[i] = out[i - 1] + math.hypot(
                float(pts[i][0] - pts[i - 1][0]),
                float(pts[i][1] - pts[i - 1][1]),
            )
        return out

    def _inhibition_profile(self, pts: Sequence[Point]) -> Tuple[List[float], float, int, int]:
        n = len(pts)
        if n <= 0 or self.i_max <= _EPS:
            return [], 0.0, -1, -1

        ys = [float(p[1]) for p in pts]
        top_y = max(ys)
        y_span = max(1.0, top_y - min(ys))
        tol_y = max(1e-6, min(REPARAM_DS_A, 0.02 * y_span))
        opening = build_opening_segment(pts, source_height=0.0, tol_y=tol_y)
        arc = self._arc_lengths(pts)

        li = int(opening.left_index) if opening is not None else -1
        ri = int(opening.right_index) if opening is not None else -1
        if li < 0 or ri < 0 or ri <= li:
            top_band = [i for i, (_x, y) in enumerate(pts) if abs(float(y) - top_y) <= tol_y]
            if top_band:
                li = min(top_band)
                ri = max(top_band)
            else:
                li = 0
                ri = n - 1

        out = [0.0] * n
        for i, (_x, y) in enumerate(pts):
            yv = float(y)
            is_top_field = abs(yv - top_y) <= tol_y and (i <= li or i >= ri)
            if is_top_field:
                out[i] = self.i_max
                continue

            if li <= i <= ri:
                d_left = abs(arc[i] - arc[li])
                d_right = abs(arc[ri] - arc[i])
                d = min(d_left, d_right)
                if self.lambda_a <= _EPS:
                    inhib = self.i_max if d <= tol_y else 0.0
                else:
                    inhib = self.i_max * math.exp(-d / max(self.lambda_a, 1e-9))
                out[i] = max(0.0, min(self.i_max, inhib))

        return out, top_y, li, ri

    def compute_flux(self, state: SimulationState) -> List[float]:
        base_flux = [max(0.0, float(v)) for v in self.base_model.compute_flux(state)]
        pts = state.surface.points
        n = len(pts)
        if n <= 0:
            return []
        if len(base_flux) != n:
            base_flux = [1.0] * n
        if self.i_max <= _EPS:
            return base_flux

        inhibition, top_y, li, ri = self._inhibition_profile(pts)
        if len(inhibition) != n:
            inhibition = [0.0] * n
        out = [max(0.0, float(base_flux[i]) * max(0.0, 1.0 - float(inhibition[i]))) for i in range(n)]

        state.meta["inhibition_enabled"] = True
        state.meta["inhibition_i_max"] = self.i_max
        state.meta["inhibition_lambda_a"] = self.lambda_a
        state.meta["inhibition_field_y"] = float(top_y)
        state.meta["inhibition_left_lip_index"] = int(li)
        state.meta["inhibition_right_lip_index"] = int(ri)
        state.meta["inhibition_mean"] = sum(inhibition) / float(n) if n > 0 else 0.0
        state.meta["inhibition_max"] = max(inhibition) if inhibition else 0.0
        return out


class SputterRedepositionFluxModel(FluxModel):
    def __init__(
        self,
        base_model: FluxModel,
        *,
        etch_reference_model: FluxModel | None = None,
        sputter_enabled: bool = False,
        sputter_strength_pct: float = 0.0,
        sputter_peak_angle_deg: float = 55.0,
        sputter_angle_sigma_deg: float = 15.0,
        sputter_depth_decay_length_a: float = 1000.0,
        sputter_vis_exponent: float = 1.0,
        sputter_source_height_a: float = 10000.0,
        redepo_enabled: bool = False,
        redepo_efficiency_pct: float = 50.0,
        redepo_lobe_sigma_deg: float = 20.0,
    ) -> None:
        self.base_model = base_model
        self.etch_reference_model = etch_reference_model
        self.sputter_enabled = bool(sputter_enabled)
        self.sputter_strength_pct = max(0.0, min(10000.0, float(sputter_strength_pct)))
        self.sputter_peak_angle_deg = max(1.0, min(89.0, float(sputter_peak_angle_deg)))
        self.sputter_angle_sigma_deg = max(1e-3, min(90.0, float(sputter_angle_sigma_deg)))
        self.sputter_depth_decay_length_a = max(0.0, float(sputter_depth_decay_length_a))
        self.sputter_vis_exponent = max(0.0, min(8.0, float(sputter_vis_exponent)))
        self.sputter_source_height_a = max(0.0, float(sputter_source_height_a))
        self.redepo_enabled = bool(redepo_enabled)
        self.redepo_efficiency_pct = max(0.0, min(100.0, float(redepo_efficiency_pct)))
        self.redepo_lobe_sigma_deg = max(1e-3, min(90.0, float(redepo_lobe_sigma_deg)))
        self._last_redepo_active_source_count = 0
        self._cached_recommended_flux: List[float] | None = None
        self._cached_recommended_flux_points_id: int | None = None

    @staticmethod
    def _substeps_from_scale(dr: float, max_abs_flux: float, target_disp: float) -> int:
        if dr <= 0.0 or max_abs_flux <= _EPS or target_disp <= _EPS:
            return 1
        return max(1, min(64, int(math.ceil((dr * max_abs_flux) / target_disp))))

    @staticmethod
    def _adjacent_delta_percentile(values: Sequence[float], q: float) -> float:
        if len(values) < 2:
            return 0.0
        deltas = sorted(abs(float(values[i + 1]) - float(values[i])) for i in range(len(values) - 1))
        if not deltas:
            return 0.0
        q = max(0.0, min(1.0, float(q)))
        idx = min(len(deltas) - 1, int(round((len(deltas) - 1) * q)))
        return float(deltas[idx])

    @staticmethod
    def _abs_flux_percentile(values: Sequence[float], q: float) -> float:
        vals = sorted(abs(float(v)) for v in values)
        if not vals:
            return 0.0
        q = max(0.0, min(1.0, float(q)))
        idx = min(len(vals) - 1, int(round((len(vals) - 1) * q)))
        return float(vals[idx])

    def _legacy_target_disp(self, state: SimulationState) -> float:
        return max(0.75, _state_reparam_ds(state) * 0.5)

    def _legacy_recommended_substeps(self, state: SimulationState, dr: float, flux: Sequence[float]) -> int:
        max_abs_flux = max((abs(float(v)) for v in flux), default=0.0)
        return self._substeps_from_scale(dr, max_abs_flux, self._legacy_target_disp(state))

    def _opening_depth_ratio(self, state: SimulationState) -> float:
        pts = normalize_surface_order(state.surface.points)
        if len(pts) < 2:
            return 0.0
        opening = build_opening_segment(pts, source_height=0.0)
        if opening is None:
            return 0.0
        opening_width = max(0.0, float(opening.x_right - opening.x_left))
        top_y = max(float(p[1]) for p in pts)
        min_y = min(float(p[1]) for p in pts)
        depth = max(_EPS, top_y - min_y)
        return opening_width / depth

    def _outlier_relaxed_scale(self, state: SimulationState, flux: Sequence[float], max_abs_flux: float) -> float | None:
        if not self.redepo_enabled or max_abs_flux <= _EPS:
            return None
        n = len(flux)
        if n < 128:
            return None
        if _state_reparam_ds(state) > 5.0:
            return None

        active_sources = int(getattr(self, "_last_redepo_active_source_count", 0))
        if active_sources < max(64, int(math.ceil(0.8 * n))):
            return None

        mean_abs_flux = sum(abs(float(v)) for v in flux) / float(n)
        p99_abs_flux = self._abs_flux_percentile(flux, 0.99)
        if p99_abs_flux > (0.45 * max_abs_flux):
            return None
        if mean_abs_flux > (0.40 * max_abs_flux):
            return None

        p95_delta = self._adjacent_delta_percentile(flux, 0.95)
        if p95_delta > (0.12 * max_abs_flux):
            return None

        return max(p99_abs_flux, max_abs_flux - (0.25 * (max_abs_flux - p99_abs_flux)))

    def _can_relax_substeps(self, state: SimulationState, flux: Sequence[float], max_abs_flux: float, legacy_substeps: int) -> bool:
        if not self.redepo_enabled or max_abs_flux <= _EPS:
            return False
        if legacy_substeps < 24:
            return False
        n = len(flux)
        if n < 64:
            return False
        ds = _state_reparam_ds(state)
        if ds > 5.0:
            return False
        if int(state.meta.get("step_idx", 0)) < 1:
            return False
        if self._opening_depth_ratio(state) < 0.5:
            return False

        active_sources = int(getattr(self, "_last_redepo_active_source_count", 0))
        if active_sources < max(32, int(math.ceil(0.5 * n))):
            return False

        mean_abs_flux = sum(abs(float(v)) for v in flux) / float(n)
        if mean_abs_flux < (0.9 * max_abs_flux):
            return False

        p90_delta = self._adjacent_delta_percentile(flux, 0.90)
        if p90_delta > (0.02 * max_abs_flux):
            return False

        p95_delta = self._adjacent_delta_percentile(flux, 0.95)
        if p95_delta > (0.05 * max_abs_flux):
            return False

        return True

    @staticmethod
    def _normalize_vec(x: float, y: float, default: Point = (0.0, 1.0)) -> Point:
        l = math.hypot(float(x), float(y))
        if l <= _EPS:
            return (float(default[0]), float(default[1]))
        return (float(x) / l, float(y) / l)

    def _sputter_angle_terms(self, normals: Sequence[Point]) -> List[float]:
        n = len(normals)
        if n <= 0:
            return []
        src_up = (0.0, 1.0)
        sigma = max(1e-6, self.sputter_angle_sigma_deg)
        out: List[float] = []
        for nx, ny in normals:
            nnx, nny = self._normalize_vec(float(nx), float(ny))
            cos_theta = max(-1.0, min(1.0, (nnx * src_up[0]) + (nny * src_up[1])))
            theta = math.degrees(math.acos(cos_theta))
            out.append(math.exp(-((theta - self.sputter_peak_angle_deg) / sigma) ** 2))
        return out

    def _vertical_depth_factors(self, pts: Sequence[Point], y0: float) -> Tuple[List[float], float]:
        n = len(pts)
        if n <= 0:
            return [], 0.0
        depths = [max(0.0, float(y0 - p[1])) for p in pts]
        max_depth = max(depths) if depths else 0.0
        if self.sputter_depth_decay_length_a <= _EPS:
            return [1.0] * n, float(max_depth)
        inv_len = 1.0 / max(self.sputter_depth_decay_length_a, 1e-9)
        return [math.exp(-float(depth) * inv_len) for depth in depths], float(max_depth)

    def _sky_visibility_terms(self, pts: Sequence[Point], normals: Sequence[Point]) -> Tuple[List[float], float, float]:
        t0 = time.perf_counter()
        engine = OpeningLOS(pts, normals=normals, source_height=self.sputter_source_height_a)
        opening = engine.opening
        top_y = max((float(p[1]) for p in pts), default=0.0)
        if opening is None or opening.length <= _EPS:
            self._last_sky_visibility_time_s = time.perf_counter() - t0
            return [0.0] * len(pts), 0.0, top_y
        vis = engine.opening_visibility_all()
        if len(vis) != len(pts):
            vis = [0.0] * len(pts)
        # Sky visibility uses a virtual source plane above the trench, but
        # depth attenuation must still be measured from the actual top surface.
        self._last_sky_visibility_time_s = time.perf_counter() - t0
        return [max(0.0, min(1.0, float(v))) for v in vis], float(opening.length), float(top_y)

    def _sky_visibility_terms_selected(
        self,
        pts: Sequence[Point],
        normals: Sequence[Point],
        candidate_indices: Sequence[int],
    ) -> Tuple[List[float], float, float]:
        t0 = time.perf_counter()
        engine = OpeningLOS(pts, normals=normals, source_height=self.sputter_source_height_a)
        opening = engine.opening
        top_y = max((float(p[1]) for p in pts), default=0.0)
        if opening is None or opening.length <= _EPS:
            self._last_sky_visibility_time_s = time.perf_counter() - t0
            return [0.0] * len(pts), 0.0, top_y
        vis = engine.visibility_selected(candidate_indices, default=0.0)
        if len(vis) != len(pts):
            vis = [0.0] * len(pts)
        self._last_sky_visibility_time_s = time.perf_counter() - t0
        return [max(0.0, min(1.0, float(v))) for v in vis], float(opening.length), float(top_y)

    def _reflection_axis(self, normal: Point) -> Point:
        nnx, nny = self._normalize_vec(float(normal[0]), float(normal[1]))
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
        return self._normalize_vec(rx, ry, default=(nnx, nny))

    def _compute_redeposition_flux(
        self,
        pts: Sequence[Point],
        normals: Sequence[Point],
        etch_flux: Sequence[float],
    ) -> List[float]:
        n = len(pts)
        if n <= 0:
            return []
        if self.redepo_efficiency_pct <= _EPS:
            return [0.0] * n
        local_area = DirectionalRayHelper.point_arc_weights(pts)
        removed_mass = [max(0.0, float(etch_flux[i])) * local_area[i] for i in range(n)]
        total_removed_mass = sum(removed_mass)
        if total_removed_mass <= _EPS:
            return [0.0] * n

        eff = self.redepo_efficiency_pct / 100.0
        sigma = max(1e-6, self.redepo_lobe_sigma_deg)
        cone_cut_deg = max(18.0, min(89.0, 4.0 * sigma))
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) if xs and ys else 0.0
        max_dist = max(250.0, diag)
        path_los = PathLOS(pts, normals=normals)
        mass_to_target = [0.0] * n
        mass_prune_eps = max(1e-9, total_removed_mass * _REDEPO_MASS_PRUNE_REL)
        active_source_count = 0
        for i, mass_i in enumerate(removed_mass):
            if mass_i <= mass_prune_eps:
                continue
            active_source_count += 1
            source = pts[i]
            axis = self._reflection_axis(normals[i])
            valid_targets: List[Tuple[int, float]] = []
            for j, target in enumerate(pts):
                if j == i or abs(j - i) <= 2:
                    continue
                dx = float(target[0] - source[0])
                dy = float(target[1] - source[1])
                dist = math.hypot(dx, dy)
                if dist <= _EPS or dist > max_dist:
                    continue
                ux = dx / dist
                uy = dy / dist
                front = (axis[0] * ux) + (axis[1] * uy)
                if front <= _EPS:
                    continue
                dev_deg = math.degrees(math.acos(max(-1.0, min(1.0, front))))
                if dev_deg > cone_cut_deg:
                    continue
                target_face = max(0.0, (normals[j][0] * (-ux)) + (normals[j][1] * (-uy)))
                if target_face <= _EPS:
                    continue
                if path_los.los_indices(i, j) == 0:
                    continue
                ang_w = math.exp(-((dev_deg / sigma) ** 2))
                w = target_face * ang_w
                if w > _EPS:
                    valid_targets.append((j, w))
            if not valid_targets:
                continue
            wsum = sum(w for _, w in valid_targets)
            if wsum <= _EPS:
                continue
            scale = (eff * mass_i) / wsum
            for j, w in valid_targets:
                mass_to_target[j] += scale * w

        self._last_redepo_active_source_count = int(active_source_count)
        return [mass_to_target[j] / max(local_area[j], REPARAM_DS_A) for j in range(n)]

    def compute_flux(self, state: SimulationState) -> List[float]:
        t_flux0 = time.perf_counter()
        self._last_sky_visibility_time_s = 0.0
        deposition_flux = [max(0.0, float(v)) for v in self.base_model.compute_flux(state)]
        pts = state.surface.points
        n = len(pts)
        if n <= 0:
            return []
        if len(deposition_flux) != n:
            deposition_flux = [1.0] * n

        if self.etch_reference_model is None:
            etch_reference_flux = list(deposition_flux)
        else:
            etch_reference_flux = [max(0.0, float(v)) for v in self.etch_reference_model.compute_flux(state)]
            if len(etch_reference_flux) != n:
                etch_reference_flux = list(deposition_flux)

        normals = VertexNormalPropagator._vertex_air_normals(pts)
        if len(normals) != n:
            normals = [(0.0, 1.0)] * n

        dr = max(0.0, float(state.meta.get("dr", 0.0)))
        local_area = DirectionalRayHelper.point_arc_weights(pts)

        etch_flux = [0.0] * n
        sputter_vis = [0.0] * n
        sputter_vis_factor = [0.0] * n
        sputter_yield = [0.0] * n
        ion_depth_factors = [1.0] * n
        opening_length = 0.0
        ion_max_depth = 0.0
        candidate_indices: List[int] = []
        if self.sputter_enabled and self.sputter_strength_pct > _EPS:
            sputter_yield = self._sputter_angle_terms(normals)
            strength = self.sputter_strength_pct / 100.0
            top_y = max((float(p[1]) for p in pts), default=0.0)
            ion_depth_factors, ion_max_depth = self._vertical_depth_factors(pts, top_y)
            for i in range(n):
                potential_raw = (
                    strength
                    * float(etch_reference_flux[i])
                    * float(ion_depth_factors[i])
                    * max(0.0, float(sputter_yield[i]))
                )
                if potential_raw > _ETCH_FLUX_PRUNE_EPS:
                    candidate_indices.append(i)

            if self.sputter_vis_exponent <= _EPS:
                for i in candidate_indices:
                    sputter_vis[i] = 1.0
                opening_length = 0.0
            elif candidate_indices:
                sputter_vis, opening_length, _ = self._sky_visibility_terms_selected(pts, normals, candidate_indices)

            for i in candidate_indices:
                sputter_vis_factor[i] = math.pow(max(0.0, min(1.0, float(sputter_vis[i]))), self.sputter_vis_exponent)
                # Calibrate sputter strength against the current local deposition scale:
                # Additional gain keeps user-facing sputter strength responsive enough
                # for the current point-normal propagation model.
                raw_etch = (
                    (_SPUTTER_STRENGTH_GAIN * strength)
                    * float(etch_reference_flux[i])
                    * float(ion_depth_factors[i])
                    * sputter_vis_factor[i]
                    * max(0.0, float(sputter_yield[i]))
                )
                etch_flux[i] = max(0.0, raw_etch)

        redepo_flux = [0.0] * n
        if self.redepo_enabled and self.redepo_efficiency_pct > _EPS and any(v > _EPS for v in etch_flux):
            redepo_flux = self._compute_redeposition_flux(pts, normals, etch_flux)
            if len(redepo_flux) != n:
                redepo_flux = [0.0] * n

        net_flux = [float(deposition_flux[i]) - float(etch_flux[i]) + float(redepo_flux[i]) for i in range(n)]
        state.meta["sputter_enabled"] = self.sputter_enabled
        state.meta["sputter_strength_pct"] = self.sputter_strength_pct
        state.meta["sputter_peak_angle_deg"] = self.sputter_peak_angle_deg
        state.meta["sputter_angle_sigma_deg"] = self.sputter_angle_sigma_deg
        state.meta["sputter_depth_decay_length_a"] = self.sputter_depth_decay_length_a
        state.meta["sputter_vis_exponent"] = self.sputter_vis_exponent
        state.meta["sputter_sky_vis_exponent"] = self.sputter_vis_exponent
        state.meta["sputter_source_height_a"] = self.sputter_source_height_a
        state.meta["sputter_opening_length_a"] = float(opening_length)
        state.meta["sputter_max_depth_a"] = float(ion_max_depth)
        state.meta["sputter_mean_depth_factor"] = sum(ion_depth_factors) / float(n) if n > 0 else 1.0
        state.meta["sputter_mean_visibility"] = sum(sputter_vis) / float(n) if n > 0 else 1.0
        state.meta["sputter_mean_sky_visibility"] = sum(sputter_vis) / float(n) if n > 0 else 1.0
        state.meta["sputter_mean_vis_factor"] = sum(sputter_vis_factor) / float(n) if n > 0 else 0.0
        state.meta["sputter_mean_sky_vis_factor"] = sum(sputter_vis_factor) / float(n) if n > 0 else 0.0
        state.meta["sputter_mean_yield"] = sum(sputter_yield) / float(n) if n > 0 else 0.0
        state.meta["sputter_mean_etch_flux"] = sum(etch_flux) / float(n) if n > 0 else 0.0
        state.meta["sputter_candidate_count"] = int(len(candidate_indices))
        state.meta["redepo_enabled"] = self.redepo_enabled
        state.meta["redepo_efficiency_pct"] = self.redepo_efficiency_pct
        state.meta["redepo_lobe_sigma_deg"] = self.redepo_lobe_sigma_deg
        state.meta["redepo_active_source_count"] = int(getattr(self, "_last_redepo_active_source_count", 0))
        state.meta["redepo_total_etch_mass"] = sum(max(0.0, float(etch_flux[i])) * local_area[i] for i in range(n))
        state.meta["redepo_total_mass"] = sum(max(0.0, float(redepo_flux[i])) * local_area[i] for i in range(n))
        state.meta["redepo_mean_flux"] = sum(redepo_flux) / float(n) if n > 0 else 0.0
        state.meta["net_mean_flux"] = sum(net_flux) / float(n) if n > 0 else 0.0
        state.meta["timing_compute_flux_s"] = time.perf_counter() - t_flux0
        state.meta["timing_sky_visibility_s"] = float(getattr(self, "_last_sky_visibility_time_s", 0.0))
        return net_flux

    def consume_cached_recommended_flux(self, state: SimulationState) -> List[float] | None:
        points_id = id(state.surface.points)
        if self._cached_recommended_flux_points_id != points_id or self._cached_recommended_flux is None:
            return None
        flux = list(self._cached_recommended_flux)
        self._cached_recommended_flux = None
        self._cached_recommended_flux_points_id = None
        return flux

    def recommended_substeps(self, state: SimulationState, dr: float) -> int:
        dr = max(0.0, float(dr))
        if dr <= 0.0 or (not self.sputter_enabled and not self.redepo_enabled):
            return 1
        prev_dr = state.meta.get("dr", 0.0)
        state.meta["dr"] = dr
        try:
            flux = self.compute_flux(state)
        finally:
            state.meta["dr"] = prev_dr
        self._cached_recommended_flux = list(flux)
        self._cached_recommended_flux_points_id = id(state.surface.points)
        max_abs_flux = max((abs(float(v)) for v in flux), default=0.0)
        if max_abs_flux <= _EPS:
            return 1

        legacy_substeps = self._legacy_recommended_substeps(state, dr, flux)
        policy = "legacy"
        substeps = legacy_substeps
        target_disp = self._legacy_target_disp(state)
        outlier_scale = self._outlier_relaxed_scale(state, flux, max_abs_flux)
        if outlier_scale is not None and outlier_scale < (max_abs_flux - _EPS):
            substeps = self._substeps_from_scale(dr, outlier_scale, target_disp)
            policy = "redepo_outlier_p99"
            state.meta["ion_substep_scale_flux"] = float(outlier_scale)
        elif self._can_relax_substeps(state, flux, max_abs_flux, legacy_substeps):
            substeps = max(1, legacy_substeps - 1)
            policy = "smooth_redepo_minus_one"
            state.meta["ion_substep_scale_flux"] = float(max_abs_flux)
        else:
            state.meta["ion_substep_scale_flux"] = float(max_abs_flux)

        state.meta["ion_substeps_legacy"] = int(legacy_substeps)
        state.meta["ion_substep_policy"] = policy
        state.meta["ion_substep_target_disp_a"] = float(target_disp)
        return int(substeps)


class Propagator:
    def advance(self, surface: Sequence[Point], flux: Sequence[float], dr: float) -> List[Point]:
        raise NotImplementedError


class VertexNormalPropagator(Propagator):
    @staticmethod
    def _segment_air_normal(a: Point, b: Point) -> Point:
        dx = float(b[0] - a[0])
        dy = float(b[1] - a[1])
        l = math.hypot(dx, dy)
        if l <= _EPS:
            return (0.0, 1.0)
        # surface is ordered left->right; air side is left normal.
        return (-dy / l, dx / l)

    @classmethod
    def _vertex_air_normals(cls, pts: Sequence[Point]) -> List[Point]:
        n = len(pts)
        if n <= 0:
            return []
        if n == 1:
            return [(0.0, 1.0)]

        seg_normals: List[Point] = []
        for i in range(n - 1):
            seg_normals.append(cls._segment_air_normal(pts[i], pts[i + 1]))

        out: List[Point] = []
        for i in range(n):
            nx = 0.0
            ny = 0.0
            cnt = 0
            if i > 0:
                sx, sy = seg_normals[i - 1]
                nx += sx
                ny += sy
                cnt += 1
            if i < (n - 1):
                sx, sy = seg_normals[i]
                nx += sx
                ny += sy
                cnt += 1
            if cnt == 0:
                out.append((0.0, 1.0))
                continue
            l = math.hypot(nx, ny)
            if l <= _EPS:
                sx, sy = seg_normals[max(0, min(i, n - 2))]
                out.append((sx, sy))
            else:
                out.append((nx / l, ny / l))
        return out

    def advance(self, surface: Sequence[Point], flux: Sequence[float], dr: float) -> List[Point]:
        pts = normalize_surface_order(surface)
        n = len(pts)
        if n < 2 or dr <= 0.0:
            return pts

        normals = self._vertex_air_normals(pts)
        if len(flux) != n:
            local_flux = [1.0] * n
        else:
            local_flux = [float(v) for v in flux]

        moved: List[Point] = []
        for i in range(n):
            x, y = pts[i]
            nx, ny = normals[i]
            step = dr * local_flux[i]
            x2 = float(x + step * nx)
            y2 = float(y + step * ny)
            # keep cut-plane x anchors fixed
            if i == 0 or i == (n - 1):
                x2 = float(x)
            moved.append((x2, y2))

        return normalize_surface_order(moved)


class OffsetBoolean:
    @staticmethod
    def require_backend() -> None:
        if pyclipper is None:
            raise RuntimeError("pyclipper is required for deposition geometry. Install with: pip install pyclipper")

    @staticmethod
    def surface_to_solid(
        surface: Sequence[Point],
        *,
        scale: int,
        y_bot_i: int,
        roi_path_i: Sequence[IntPoint],
    ) -> List[IntPath]:
        pts = normalize_surface_order(surface)
        if len(pts) < 2:
            return []
        surf_i = _to_int_points(pts, scale)
        x_left_i = int(round(pts[0][0] * scale))
        x_right_i = int(round(pts[-1][0] * scale))
        solid_seed_i = _normalize_int_path(surf_i + [(x_right_i, y_bot_i), (x_left_i, y_bot_i)])
        if not solid_seed_i:
            return []
        out = _clip_intersection([solid_seed_i], [roi_path_i])
        return out if out else [solid_seed_i]

    @staticmethod
    def grow_solid(solid_paths_i: Sequence[Sequence[IntPoint]], dr_ref: float, scale: int) -> List[IntPath]:
        if dr_ref <= 0.0:
            return _normalize_int_paths(solid_paths_i)
        delta_i = int(round(dr_ref * scale))
        if delta_i <= 0:
            return _normalize_int_paths(solid_paths_i)
        return _clip_offset(solid_paths_i, delta_i, arc_tolerance=max(scale * 0.25, 1.0))

    @staticmethod
    def _touches_top_as_external(contour: Sequence[IntPoint], state: SimulationState, tol: int) -> bool:
        # Robust top connectivity test:
        # ignore single-point/top-noise contacts and require a meaningful top-edge span.
        if not contour:
            return False
        min_top_contact_len_i = max(2 * tol, int(round(state.scale * 2.0)))  # ~2 A
        top_xs: List[int] = []
        top_len = 0
        n = len(contour)
        for i in range(n):
            a = contour[i]
            b = contour[(i + 1) % n]
            a_top = abs(a[1] - state.y_top_i) <= tol
            b_top = abs(b[1] - state.y_top_i) <= tol
            if a_top:
                top_xs.append(int(a[0]))
            if a_top and b_top:
                top_len += abs(int(b[0]) - int(a[0]))

        if top_len >= min_top_contact_len_i:
            return True
        if len(top_xs) >= 2 and (max(top_xs) - min(top_xs)) >= min_top_contact_len_i:
            return True
        return False

    @staticmethod
    def _collect_air_components(
        state: SimulationState,
        solid_paths_i: Sequence[Sequence[IntPoint]],
    ) -> List[Tuple[IntPath, bool]]:
        tree = _clip_difference_tree([state.roi_path_i], solid_paths_i)
        tol = max(2, state.scale // 200)
        out: List[Tuple[IntPath, bool]] = []
        for node in _iter_polytree_nodes(tree):
            contour = _normalize_int_path(getattr(node, "Contour", []))
            if not contour:
                continue
            if bool(getattr(node, "IsHole", False)):
                continue
            is_external = OffsetBoolean._touches_top_as_external(contour, state, tol)
            out.append((contour, is_external))
        return out

    @staticmethod
    def collect_external_air(state: SimulationState) -> List[IntPath]:
        components = OffsetBoolean._collect_air_components(state, state.solid_paths_i)
        return _normalize_int_paths([contour for contour, is_external in components if is_external])

    @staticmethod
    def collect_void_air(state: SimulationState) -> List[IntPath]:
        components = OffsetBoolean._collect_air_components(state, state.solid_paths_i)
        return _normalize_int_paths([contour for contour, is_external in components if not is_external])

    @staticmethod
    def grow_solid_external_air_limited(state: SimulationState, dr_ref: float) -> List[IntPath]:
        base = _normalize_int_paths(state.solid_paths_i)
        if dr_ref <= 0.0:
            return base
        if not base:
            return base

        grown = OffsetBoolean.grow_solid(base, dr_ref=dr_ref, scale=state.scale)
        if not grown:
            return base
        add_raw = _clip_difference(grown, base)
        if not add_raw:
            return base

        ext_air = OffsetBoolean._collect_air_components(state, base)
        ext_air = _normalize_int_paths([contour for contour, is_external in ext_air if is_external])
        if not ext_air:
            return base

        add_external = _clip_intersection(add_raw, ext_air)
        if not add_external:
            return base

        merged = _clip_union(base, add_external)
        merged = _clip_to_roi_if_needed(merged, state)
        return merged if merged else base

    @staticmethod
    def void_polygons_float(state: SimulationState) -> List[List[Point]]:
        return [_to_float_points(vp, state.scale) for vp in OffsetBoolean.collect_void_air(state) if len(vp) >= 3]

    @staticmethod
    def union_paths(
        a: Sequence[Sequence[IntPoint]],
        b: Sequence[Sequence[IntPoint]],
    ) -> List[IntPath]:
        return _clip_union(a, b)

    @staticmethod
    def paths_to_float(paths_i: Sequence[Sequence[IntPoint]], scale: int) -> List[List[Point]]:
        return [_to_float_points(vp, scale) for vp in _normalize_int_paths(paths_i) if len(vp) >= 3]


def _edge_on_roi_boundary(a: IntPoint, b: IntPoint, state: SimulationState, tol_i: int) -> bool:
    ax, ay = a
    bx, by = b
    if abs(ax - state.x_left_i) <= tol_i and abs(bx - state.x_left_i) <= tol_i:
        return True
    if abs(ax - state.x_right_i) <= tol_i and abs(bx - state.x_right_i) <= tol_i:
        return True
    if abs(ay - state.y_top_i) <= tol_i and abs(by - state.y_top_i) <= tol_i:
        return True
    if abs(ay - state.y_bot_i) <= tol_i and abs(by - state.y_bot_i) <= tol_i:
        return True
    return False


def _dedupe_int_polyline(chain: Sequence[IntPoint]) -> IntPath:
    out: IntPath = []
    for p in chain:
        if out and out[-1] == p:
            continue
        out.append((int(p[0]), int(p[1])))
    return out


def _chains_from_contour_without_roi_edges(contour: Sequence[IntPoint], state: SimulationState) -> List[IntPath]:
    c = _normalize_int_path(contour)
    if len(c) < 3:
        return []

    tol_i = max(2, state.scale // 200)
    runs: List[IntPath] = []
    cur: IntPath = []
    n = len(c)

    for i in range(n):
        a = c[i]
        b = c[(i + 1) % n]
        keep = not _edge_on_roi_boundary(a, b, state, tol_i)
        if keep:
            if not cur:
                cur = [a, b]
            elif cur[-1] == a:
                cur.append(b)
            else:
                runs.append(_dedupe_int_polyline(cur))
                cur = [a, b]
        else:
            if cur:
                runs.append(_dedupe_int_polyline(cur))
                cur = []

    if cur:
        runs.append(_dedupe_int_polyline(cur))

    if len(runs) >= 2 and runs[0][0] == runs[-1][-1]:
        merged = _dedupe_int_polyline(runs[-1] + runs[0][1:])
        runs = [merged] + runs[1:-1]

    return [r for r in runs if len(r) >= 2]


def _polyline_len_i(chain: Sequence[IntPoint]) -> float:
    if len(chain) < 2:
        return 0.0
    s = 0.0
    for i in range(len(chain) - 1):
        x1, y1 = chain[i]
        x2, y2 = chain[i + 1]
        s += math.hypot(x2 - x1, y2 - y1)
    return s


def _select_surface_chain(chains: Sequence[Sequence[IntPoint]], state: SimulationState) -> Optional[IntPath]:
    if not chains:
        return None

    tol_i = max(2, state.scale // 200)
    best_chain: Optional[IntPath] = None
    best_score: Tuple[int, float, float, int] = (-1, -1.0, -1.0, -1)

    for raw in chains:
        chain = _dedupe_int_polyline(raw)
        if len(chain) < 2:
            continue
        if chain[0][0] > chain[-1][0]:
            chain = list(reversed(chain))

        left_touch = abs(chain[0][0] - state.x_left_i) <= tol_i or abs(chain[-1][0] - state.x_left_i) <= tol_i
        right_touch = abs(chain[0][0] - state.x_right_i) <= tol_i or abs(chain[-1][0] - state.x_right_i) <= tol_i
        touch_score = 2 if (left_touch and right_touch) else (1 if (left_touch or right_touch) else 0)
        span = abs(chain[-1][0] - chain[0][0])
        plen = _polyline_len_i(chain)
        score = (touch_score, float(span), plen, len(chain))
        if score > best_score:
            best_score = score
            best_chain = chain

    return best_chain


def _collect_external_air_contours(state: SimulationState, solid_paths_i: Sequence[Sequence[IntPoint]]) -> List[IntPath]:
    tree = _clip_difference_tree([state.roi_path_i], solid_paths_i)
    tol = max(2, state.scale // 200)
    contours: List[IntPath] = []

    for node in _iter_polytree_nodes(tree):
        contour = _normalize_int_path(getattr(node, "Contour", []))
        if not contour:
            continue
        if bool(getattr(node, "IsHole", False)):
            continue
        if not any(abs(p[1] - state.y_top_i) <= tol for p in contour):
            continue

        contours.append(contour)
        for child in getattr(node, "Childs", []):
            if not bool(getattr(child, "IsHole", False)):
                continue
            hole = _normalize_int_path(getattr(child, "Contour", []))
            if hole:
                contours.append(hole)

    return _normalize_int_paths(contours)


def _extract_surface_from_solid(
    state: SimulationState,
    solid_paths_i: Sequence[Sequence[IntPoint]],
    fallback_pts: Sequence[Point],
) -> List[Point]:
    hole_contours = _collect_external_air_contours(state, solid_paths_i)
    chains: List[IntPath] = []
    for contour in hole_contours:
        chains.extend(_chains_from_contour_without_roi_edges(contour, state))

    best = _select_surface_chain(chains, state)
    if not best:
        return normalize_surface_order(fallback_pts)

    tol_i = max(2, state.scale // 200)
    if best[0][0] > best[-1][0]:
        best = list(reversed(best))

    b0 = best[0]
    b1 = best[-1]
    if abs(b0[0] - state.x_left_i) <= tol_i:
        best[0] = (state.x_left_i, b0[1])
    if abs(b1[0] - state.x_right_i) <= tol_i:
        best[-1] = (state.x_right_i, b1[1])

    out = _dedupe_consecutive(_to_float_points(best, state.scale))
    if len(out) >= 2 and out[0][0] > out[-1][0]:
        out = list(reversed(out))
    return out if len(out) >= 2 else normalize_surface_order(fallback_pts)


def _surface_chain_score(pts: Sequence[Point], state: SimulationState) -> Tuple[int, float, int]:
    if len(pts) < 2:
        return (-1, -1.0, 0)
    tol = 2.0 / float(max(state.scale, 1))
    x0 = float(pts[0][0])
    x1 = float(pts[-1][0])
    xl = float(state.x_left_i) / float(state.scale)
    xr = float(state.x_right_i) / float(state.scale)
    left_touch = abs(x0 - xl) <= tol or abs(x1 - xl) <= tol
    right_touch = abs(x0 - xr) <= tol or abs(x1 - xr) <= tol
    touch_score = 2 if (left_touch and right_touch) else (1 if (left_touch or right_touch) else 0)
    span = abs(x1 - x0)
    return (touch_score, float(span), len(pts))


def _needs_reference_cleanup(score: Tuple[int, float, int], state: SimulationState) -> bool:
    touch_score, span, point_count = score
    if point_count < 2:
        return True
    if touch_score < 2:
        return True

    full_span = abs(float(state.x_right_i - state.x_left_i)) / float(max(state.scale, 1))
    if full_span <= _EPS:
        return False
    span_ratio = float(span) / float(full_span)
    return span_ratio < 0.9


def _int_paths_area(paths: Sequence[Sequence[IntPoint]]) -> float:
    area = 0.0
    for p in _normalize_int_paths(paths):
        area += abs(float(_int_path_area(p))) * 0.5
    return area


def _paths_within_roi_bounds(paths: Sequence[Sequence[IntPoint]], state: SimulationState) -> bool:
    x_min = min(state.x_left_i, state.x_right_i)
    x_max = max(state.x_left_i, state.x_right_i)
    y_min = min(state.y_bot_i, state.y_top_i)
    y_max = max(state.y_bot_i, state.y_top_i)
    for path in paths:
        for x, y in path:
            if x < x_min or x > x_max or y < y_min or y > y_max:
                return False
    return True


def _clip_to_roi_if_needed(paths: Sequence[Sequence[IntPoint]], state: SimulationState) -> List[IntPath]:
    if not paths:
        return []
    if _paths_within_roi_bounds(paths, state):
        return [list(path) for path in paths if len(path) >= 3]
    return _clip_intersection(paths, [state.roi_path_i])


class TopologyCleanup:
    def cleanup(
        self,
        proposed: Sequence[Point],
        state: SimulationState,
        *,
        solid_ref_paths_i: Optional[Sequence[Sequence[IntPoint]]] = None,
    ) -> Tuple[List[Point], List[IntPath]]:
        fallback = normalize_surface_order(proposed)

        candidate_from_surface = OffsetBoolean.surface_to_solid(
            fallback,
            scale=state.scale,
            y_bot_i=state.y_bot_i,
            roi_path_i=state.roi_path_i,
        )
        solid_candidate = _clip_union(state.solid_paths_i, candidate_from_surface)
        solid_candidate = _clip_to_roi_if_needed(solid_candidate, state)
        if not solid_candidate:
            solid_candidate = list(state.solid_paths_i)

        candidate_surface = _extract_surface_from_solid(state, solid_candidate, fallback)
        best_surface = candidate_surface
        best_solid = solid_candidate
        best_score = _surface_chain_score(candidate_surface, state)

        # Offset reference is assist-only: use it when candidate chain is ambiguous.
        if solid_ref_paths_i and _needs_reference_cleanup(best_score, state):
            solid_ref = _clip_union(state.solid_paths_i, solid_ref_paths_i)
            solid_ref = _clip_to_roi_if_needed(solid_ref, state)
            if solid_ref:
                ref_surface = _extract_surface_from_solid(state, solid_ref, fallback)
                ref_score = _surface_chain_score(ref_surface, state)
                if ref_score > best_score:
                    best_surface = ref_surface
                    best_solid = solid_ref
                    best_score = ref_score

        # Guard: if reference growth predicts trapped air but candidate filled it,
        # carve those void regions back out to prevent post pinch-off blue refill.
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
                        carved = _clip_to_roi_if_needed(carved, state)
                        if carved:
                            best_solid = carved
                            best_surface = _extract_surface_from_solid(state, best_solid, fallback)

        return best_surface, best_solid


def deposit_step(
    dr: float,
    state: SimulationState,
    *,
    model: FluxModel,
    propagator: Propagator,
    cleanup: TopologyCleanup,
    detail_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> SimulationState:
    state.meta["propagation"] = "vertex_normal_point_translation"
    state.meta["l_min"] = SIO2_L_MIN_A
    state.meta["reparam_ds"] = _state_reparam_ds(state)
    dr = max(0.0, float(dr))
    state.meta["dr"] = float(dr)
    reparam_ds = _state_reparam_ds(state)

    pts = normalize_surface_order(state.surface.points)
    if dr <= 0.0 or len(pts) < 2:
        state.surface.points = pts
        return state

    if cancel_check is not None and cancel_check():
        raise SimulationCanceled()

    substeps = max(1, int(model.recommended_substeps(state, dr)))
    state.meta["ion_substeps"] = substeps
    dr_sub = dr / float(substeps)

    for substep_idx in range(substeps):
        if cancel_check is not None and cancel_check():
            raise SimulationCanceled()
        pts = normalize_surface_order(state.surface.points)
        state.meta["dr"] = float(dr_sub)

        flux = None
        t_flux0 = time.perf_counter()
        if substep_idx == 0 and hasattr(model, "consume_cached_recommended_flux"):
            flux = model.consume_cached_recommended_flux(state)  # type: ignore[attr-defined]
        if flux is None:
            flux = model.compute_flux(state)
        flux_time_s = time.perf_counter() - t_flux0
        if len(flux) != len(pts):
            flux = [1.0] * len(pts)
        flux = [float(v) for v in flux]
        if detail_cb is not None:
            detail_cb(
                {
                    "kind": "ion_substep",
                    "substep": int(substep_idx + 1),
                    "substeps": int(substeps),
                    "points": int(len(pts)),
                    "etch_candidates": int(state.meta.get("sputter_candidate_count", 0)),
                    "redepo_sources": int(state.meta.get("redepo_active_source_count", 0)),
                    "flux_time_s": float(flux_time_s),
                    "sky_visibility_time_s": float(state.meta.get("timing_sky_visibility_s", 0.0)),
                }
            )

        proposed = propagator.advance(pts, flux, dr_sub)

        mean_flux = 1.0
        if flux:
            pos_flux = [max(0.0, float(v)) for v in flux]
            mean_flux = max(0.0, sum(pos_flux) / float(len(pos_flux)))
        solid_ref = OffsetBoolean.grow_solid_external_air_limited(state, dr_ref=dr_sub * mean_flux)

        if cancel_check is not None and cancel_check():
            raise SimulationCanceled()
        t_cleanup0 = time.perf_counter()
        clean_surface, clean_solid = cleanup.cleanup(proposed, state, solid_ref_paths_i=solid_ref)
        cleanup_time_s = time.perf_counter() - t_cleanup0
        t_resample0 = time.perf_counter()
        state.surface.points = equal_arc_resample(clean_surface, reparam_ds)
        resample_time_s = time.perf_counter() - t_resample0
        if clean_solid:
            state.solid_paths_i = clean_solid
        state.meta["timing_substep_flux_s"] = float(flux_time_s)
        state.meta["timing_substep_cleanup_s"] = float(cleanup_time_s)
        state.meta["timing_substep_resample_s"] = float(resample_time_s)

    state.meta["dr"] = float(dr)
    state.meta["step_idx"] = int(state.meta.get("step_idx", 0)) + 1
    return state
