from __future__ import annotations

from collections import defaultdict
import math
from dataclasses import dataclass
from typing import DefaultDict, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

_EPS = 1e-12


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return (ax * by) - (ay * bx)


def _dot(ax: float, ay: float, bx: float, by: float) -> float:
    return (ax * bx) + (ay * by)


def _segment_intersects(p0: Point, p1: Point, q0: Point, q1: Point, *, eps: float) -> bool:
    rx = float(p1[0] - p0[0])
    ry = float(p1[1] - p0[1])
    sx = float(q1[0] - q0[0])
    sy = float(q1[1] - q0[1])
    qpx = float(q0[0] - p0[0])
    qpy = float(q0[1] - p0[1])

    rxs = _cross(rx, ry, sx, sy)
    qpxr = _cross(qpx, qpy, rx, ry)

    if abs(rxs) <= eps and abs(qpxr) <= eps:
        rr = _dot(rx, ry, rx, ry)
        if rr <= eps:
            return (abs(p0[0] - q0[0]) <= eps) and (abs(p0[1] - q0[1]) <= eps)
        t0 = _dot(qpx, qpy, rx, ry) / rr
        t1 = t0 + (_dot(sx, sy, rx, ry) / rr)
        t_min = min(t0, t1)
        t_max = max(t0, t1)
        return max(0.0, t_min) <= min(1.0, t_max)

    if abs(rxs) <= eps:
        return False

    t = _cross(qpx, qpy, sx, sy) / rxs
    u = _cross(qpx, qpy, rx, ry) / rxs
    return (-eps <= t <= 1.0 + eps) and (-eps <= u <= 1.0 + eps)


@dataclass(frozen=True)
class OpeningSegment:
    y0: float
    x_left: float
    x_right: float
    left_index: int
    right_index: int
    tol_y: float

    @property
    def length(self) -> float:
        return max(0.0, float(self.x_right - self.x_left))


@dataclass(frozen=True)
class _SurfaceSegment:
    index: int
    a: Point
    b: Point
    min_x: float
    max_x: float
    min_y: float
    max_y: float


@dataclass(frozen=True)
class _GridIndex:
    origin_x: float
    origin_y: float
    cell_size: float
    buckets: Dict[Tuple[int, int], Tuple[int, ...]]


def _build_segment_grid_index(segments: Sequence[_SurfaceSegment], *, eps_air: float) -> Optional[_GridIndex]:
    if len(segments) < 8:
        return None

    min_x = min(seg.min_x for seg in segments)
    max_x = max(seg.max_x for seg in segments)
    min_y = min(seg.min_y for seg in segments)
    max_y = max(seg.max_y for seg in segments)
    span_x = max(eps_air, max_x - min_x)
    span_y = max(eps_air, max_y - min_y)
    area = max(eps_air * eps_air, span_x * span_y)
    cell_size = max(eps_air, math.sqrt(area / max(1, len(segments))))
    origin_x = min_x - eps_air
    origin_y = min_y - eps_air

    buckets: DefaultDict[Tuple[int, int], List[int]] = defaultdict(list)
    for seg in segments:
        ix0 = int(math.floor((seg.min_x - origin_x) / cell_size))
        ix1 = int(math.floor((seg.max_x - origin_x) / cell_size))
        iy0 = int(math.floor((seg.min_y - origin_y) / cell_size))
        iy1 = int(math.floor((seg.max_y - origin_y) / cell_size))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                buckets[(ix, iy)].append(seg.index)

    frozen = {key: tuple(indices) for key, indices in buckets.items()}
    return _GridIndex(
        origin_x=origin_x,
        origin_y=origin_y,
        cell_size=cell_size,
        buckets=frozen,
    )


def _grid_bbox_candidate_indices(
    grid_index: Optional[_GridIndex],
    segment_count: int,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> List[int]:
    if grid_index is None:
        return list(range(segment_count))
    ix0 = int(math.floor((float(min_x) - grid_index.origin_x) / grid_index.cell_size))
    ix1 = int(math.floor((float(max_x) - grid_index.origin_x) / grid_index.cell_size))
    iy0 = int(math.floor((float(min_y) - grid_index.origin_y) / grid_index.cell_size))
    iy1 = int(math.floor((float(max_y) - grid_index.origin_y) / grid_index.cell_size))
    seen = set()
    out: List[int] = []
    for ix in range(ix0, ix1 + 1):
        for iy in range(iy0, iy1 + 1):
            for seg_index in grid_index.buckets.get((ix, iy), ()):
                if seg_index in seen:
                    continue
                seen.add(seg_index)
                out.append(seg_index)
    return out


def _lip_candidates(points: Sequence[Point], y0: float, tol_y: float) -> List[int]:
    out: List[int] = []
    n = len(points)
    for k, (_x, y) in enumerate(points):
        if abs(float(y) - y0) > tol_y:
            continue
        left_drop = k > 0 and (float(points[k - 1][1]) < (y0 - tol_y))
        right_drop = k < (n - 1) and (float(points[k + 1][1]) < (y0 - tol_y))
        if left_drop or right_drop:
            out.append(k)
    return out


def build_opening_segment(
    points: Sequence[Point],
    *,
    source_height: float = 0.0,
    tol_y: float = 1e-6,
) -> Optional[OpeningSegment]:
    if len(points) < 2:
        return None
    ys = [float(p[1]) for p in points]
    xs = [float(p[0]) for p in points]
    top_y = max(ys)
    source_y = top_y + max(0.0, float(source_height))
    center_x = 0.5 * (min(xs) + max(xs))

    candidates = _lip_candidates(points, top_y, tol_y)
    if len(candidates) < 2:
        candidates = [i for i, p in enumerate(points) if abs(float(p[1]) - top_y) <= tol_y]
    if len(candidates) < 2:
        return None

    cand_sorted = sorted(set(candidates), key=lambda i: (points[i][0], i))
    left = [i for i in cand_sorted if points[i][0] < center_x]
    right = [i for i in cand_sorted if points[i][0] > center_x]

    if left and right:
        li = max(left, key=lambda i: points[i][0])
        ri = min(right, key=lambda i: points[i][0])
    else:
        li = cand_sorted[0]
        ri = cand_sorted[-1]
        best_mid = abs((points[li][0] + points[ri][0]) * 0.5 - center_x)
        for idx in range(len(cand_sorted) - 1):
            a = cand_sorted[idx]
            b = cand_sorted[idx + 1]
            xa = points[a][0]
            xb = points[b][0]
            if xb - xa <= tol_y:
                continue
            mid_err = abs((xa + xb) * 0.5 - center_x)
            if mid_err < best_mid:
                li = a
                ri = b
                best_mid = mid_err

    x_left = float(points[li][0])
    x_right = float(points[ri][0])
    if x_right <= x_left + tol_y:
        return None
    return OpeningSegment(y0=source_y, x_left=x_left, x_right=x_right, left_index=int(li), right_index=int(ri), tol_y=tol_y)


class OpeningLOS:
    def __init__(
        self,
        points: Sequence[Point],
        *,
        normals: Optional[Sequence[Point]] = None,
        source_height: float = 0.0,
        tol_y: Optional[float] = None,
        eps_air: Optional[float] = None,
    ) -> None:
        self.points: List[Point] = [(float(x), float(y)) for x, y in points]
        self.normals: List[Point] = [(float(nx), float(ny)) for nx, ny in (normals or [])]
        self.source_height = max(0.0, float(source_height))
        self.tol_y = max(1e-9, float(tol_y if tol_y is not None else 1e-6))
        self.eps_air = max(1e-8, float(eps_air if eps_air is not None else 1e-4))
        self.segments: List[_SurfaceSegment] = []
        for i in range(max(0, len(self.points) - 1)):
            a = self.points[i]
            b = self.points[i + 1]
            self.segments.append(
                _SurfaceSegment(
                    index=i,
                    a=a,
                    b=b,
                    min_x=min(a[0], b[0]),
                    max_x=max(a[0], b[0]),
                    min_y=min(a[1], b[1]),
                    max_y=max(a[1], b[1]),
                )
            )
        self._grid_index = _build_segment_grid_index(self.segments, eps_air=self.eps_air)
        self.opening = build_opening_segment(self.points, source_height=self.source_height, tol_y=self.tol_y)

    def _offset_point(self, index: int) -> Point:
        p = self.points[index]
        if 0 <= index < len(self.normals):
            nx, ny = self.normals[index]
            nl = math.hypot(nx, ny)
            if nl > _EPS:
                return (p[0] + (self.eps_air * nx / nl), p[1] + (self.eps_air * ny / nl))
        return p

    def _project_x_to_opening(self, p: Point, q: Point) -> Optional[float]:
        if self.opening is None:
            return None
        dy = float(q[1] - p[1])
        if abs(dy) <= self.tol_y:
            if abs(float(q[0] - p[0])) <= self.tol_y:
                return None
            return self.opening.x_left if q[0] < p[0] else self.opening.x_right
        t = (self.opening.y0 - float(p[1])) / dy
        x = float(p[0]) + (float(q[0] - p[0]) * t)
        return x

    def _blocks_interval_midpoint(self, point_index: int, p: Point, x_mid: float, seg: _SurfaceSegment) -> bool:
        q_top = (float(x_mid), float(self.opening.y0)) if self.opening is not None else (float(x_mid), p[1])
        if seg.index in {point_index - 1, point_index}:
            return False
        return _segment_intersects(p, q_top, seg.a, seg.b, eps=self.eps_air)

    def _candidate_segment_indices(self, p: Point) -> List[int]:
        if self.opening is None:
            return []
        min_x = min(float(p[0]), float(self.opening.x_left), float(self.opening.x_right)) - self.eps_air
        max_x = max(float(p[0]), float(self.opening.x_left), float(self.opening.x_right)) + self.eps_air
        min_y = min(float(p[1]), float(self.opening.y0)) - self.eps_air
        max_y = max(float(p[1]), float(self.opening.y0)) + self.eps_air
        return _grid_bbox_candidate_indices(
            self._grid_index,
            len(self.segments),
            min_x,
            max_x,
            min_y,
            max_y,
        )

    @staticmethod
    def _merge_intervals(intervals: Sequence[Tuple[float, float]], *, eps: float) -> List[Tuple[float, float]]:
        if not intervals:
            return []
        ordered = sorted((float(a), float(b)) for a, b in intervals if b > a + eps)
        merged: List[Tuple[float, float]] = [ordered[0]]
        for a, b in ordered[1:]:
            la, lb = merged[-1]
            if a <= lb + eps:
                merged[-1] = (la, max(lb, b))
            else:
                merged.append((a, b))
        return merged

    def visibility(self, point_index: int) -> float:
        if self.opening is None or self.opening.length <= self.tol_y:
            return 0.0
        if point_index < 0 or point_index >= len(self.points):
            return 0.0

        p_raw = self.points[point_index]
        if abs(self.opening.y0 - p_raw[1]) <= self.tol_y:
            return 1.0

        p = self._offset_point(point_index)
        if self.opening.y0 <= p[1] + self.tol_y:
            return 1.0

        intervals: List[Tuple[float, float]] = []
        for seg_index in self._candidate_segment_indices(p):
            seg = self.segments[seg_index]
            if seg.index in {point_index - 1, point_index}:
                continue
            if seg.max_y <= p[1] + self.tol_y:
                continue
            if seg.min_y >= self.opening.y0 - self.tol_y and seg.max_y >= self.opening.y0 - self.tol_y:
                continue

            xa = self._project_x_to_opening(p, seg.a)
            xb = self._project_x_to_opening(p, seg.b)
            if xa is None and xb is None:
                continue
            if xa is None:
                xa = self.opening.x_left if seg.a[0] < p[0] else self.opening.x_right
            if xb is None:
                xb = self.opening.x_left if seg.b[0] < p[0] else self.opening.x_right

            lo = max(self.opening.x_left, min(xa, xb))
            hi = min(self.opening.x_right, max(xa, xb))
            if hi <= lo + self.tol_y:
                continue
            x_mid = 0.5 * (lo + hi)
            if self._blocks_interval_midpoint(point_index, p, x_mid, seg):
                intervals.append((lo, hi))

        blocked = 0.0
        for lo, hi in self._merge_intervals(intervals, eps=self.tol_y):
            blocked += max(0.0, hi - lo)
        visible = max(0.0, self.opening.length - blocked)
        return _clamp01(visible / max(self.opening.length, self.tol_y))

    def opening_visibility(self, point_index: int) -> float:
        return self.visibility(point_index)

    def visibility_all(self) -> List[float]:
        return [self.visibility(i) for i in range(len(self.points))]

    def visibility_selected(self, indices: Sequence[int], *, default: float = 0.0) -> List[float]:
        out = [float(default)] * len(self.points)
        for i in indices:
            if 0 <= int(i) < len(self.points):
                out[int(i)] = self.visibility(int(i))
        return out

    def opening_visibility_all(self) -> List[float]:
        return self.visibility_all()


class PathLOS:
    def __init__(
        self,
        points: Sequence[Point],
        *,
        normals: Optional[Sequence[Point]] = None,
        eps_air: Optional[float] = None,
    ) -> None:
        self.points: List[Point] = [(float(x), float(y)) for x, y in points]
        self.normals: List[Point] = [(float(nx), float(ny)) for nx, ny in (normals or [])]
        self.eps_air = max(1e-8, float(eps_air if eps_air is not None else 1e-4))
        self.segments: List[_SurfaceSegment] = []
        for i in range(max(0, len(self.points) - 1)):
            a = self.points[i]
            b = self.points[i + 1]
            self.segments.append(
                _SurfaceSegment(
                    index=i,
                    a=a,
                    b=b,
                    min_x=min(a[0], b[0]),
                    max_x=max(a[0], b[0]),
                    min_y=min(a[1], b[1]),
                    max_y=max(a[1], b[1]),
                )
            )
        self._grid_index = self._build_grid_index()
        self._pair_cache: Dict[Tuple[int, int], bool] = {}
        self._offset_pair_cache: Dict[Tuple[int, int, int], bool] = {}
        self._soft_pair_cache: Dict[Tuple[int, int, int], float] = {}

    def _build_grid_index(self) -> Optional[_GridIndex]:
        return _build_segment_grid_index(self.segments, eps_air=self.eps_air)

    def _candidate_segment_indices(self, p: Point, q: Point) -> List[int]:
        if self._grid_index is None:
            return list(range(len(self.segments)))

        seen = set()
        ordered: List[int] = []

        def _collect(ix: int, iy: int) -> None:
            for seg_index in self._grid_index.buckets.get((ix, iy), ()):
                if seg_index in seen:
                    continue
                seen.add(seg_index)
                ordered.append(seg_index)

        cell = self._grid_index.cell_size
        x0 = (float(p[0]) - self._grid_index.origin_x) / cell
        y0 = (float(p[1]) - self._grid_index.origin_y) / cell
        x1 = (float(q[0]) - self._grid_index.origin_x) / cell
        y1 = (float(q[1]) - self._grid_index.origin_y) / cell

        ix = int(math.floor(x0))
        iy = int(math.floor(y0))
        tx = int(math.floor(x1))
        ty = int(math.floor(y1))
        _collect(ix, iy)
        if ix == tx and iy == ty:
            return ordered

        dx = float(q[0] - p[0])
        dy = float(q[1] - p[1])

        if abs(dx) <= self.eps_air:
            step_x = 0
            t_max_x = math.inf
            t_delta_x = math.inf
        else:
            step_x = 1 if dx > 0.0 else -1
            next_ix = ix + (1 if step_x > 0 else 0)
            boundary_x = self._grid_index.origin_x + (next_ix * cell)
            t_max_x = (boundary_x - float(p[0])) / dx
            t_delta_x = cell / abs(dx)

        if abs(dy) <= self.eps_air:
            step_y = 0
            t_max_y = math.inf
            t_delta_y = math.inf
        else:
            step_y = 1 if dy > 0.0 else -1
            next_iy = iy + (1 if step_y > 0 else 0)
            boundary_y = self._grid_index.origin_y + (next_iy * cell)
            t_max_y = (boundary_y - float(p[1])) / dy
            t_delta_y = cell / abs(dy)

        guard = max(4, len(self._grid_index.buckets) + len(self.segments))
        while (ix != tx or iy != ty) and guard > 0:
            guard -= 1
            if t_max_x < t_max_y:
                ix += step_x
                t_max_x += t_delta_x
            elif t_max_y < t_max_x:
                iy += step_y
                t_max_y += t_delta_y
            else:
                ix += step_x
                iy += step_y
                t_max_x += t_delta_x
                t_max_y += t_delta_y
            _collect(ix, iy)
        return ordered

    def _offset_point(self, index: int) -> Point:
        p = self.points[index]
        if 0 <= index < len(self.normals):
            nx, ny = self.normals[index]
            nl = math.hypot(nx, ny)
            if nl > _EPS:
                return (p[0] + (self.eps_air * nx / nl), p[1] + (self.eps_air * ny / nl))
        return p

    def _visible_points(self, p: Point, q: Point, ignore: set[int]) -> bool:
        min_x = min(p[0], q[0]) - self.eps_air
        max_x = max(p[0], q[0]) + self.eps_air
        min_y = min(p[1], q[1]) - self.eps_air
        max_y = max(p[1], q[1]) + self.eps_air

        for seg_index in self._candidate_segment_indices(p, q):
            seg = self.segments[seg_index]
            if seg.index in ignore:
                continue
            if seg.max_x < min_x or seg.min_x > max_x or seg.max_y < min_y or seg.min_y > max_y:
                continue
            if _segment_intersects(p, q, seg.a, seg.b, eps=self.eps_air):
                return False
        return True

    def visible_indices(self, i: int, j: int) -> bool:
        if i == j:
            return False
        if i < 0 or j < 0 or i >= len(self.points) or j >= len(self.points):
            return False
        key = (i, j) if i < j else (j, i)
        cached = self._pair_cache.get(key)
        if cached is not None:
            return cached

        p = self._offset_point(i)
        q = self._offset_point(j)
        min_x = min(p[0], q[0]) - self.eps_air
        max_x = max(p[0], q[0]) + self.eps_air
        min_y = min(p[1], q[1]) - self.eps_air
        max_y = max(p[1], q[1]) + self.eps_air
        ignore = {i - 1, i, j - 1, j}

        for seg_index in self._candidate_segment_indices(p, q):
            seg = self.segments[seg_index]
            if seg.index in ignore:
                continue
            if seg.max_x < min_x or seg.min_x > max_x or seg.max_y < min_y or seg.min_y > max_y:
                continue
            if _segment_intersects(p, q, seg.a, seg.b, eps=self.eps_air):
                self._pair_cache[key] = False
                return False
        self._pair_cache[key] = True
        return True

    def visible_indices_offset(self, i: int, j: int, offset_a: float) -> bool:
        if i == j:
            return False
        if i < 0 or j < 0 or i >= len(self.points) or j >= len(self.points):
            return False
        offset = float(offset_a)
        if abs(offset) <= self.eps_air:
            return self.visible_indices(i, j)
        offset_key = int(round(offset / max(self.eps_air, 1e-9)))
        key = (int(i), int(j), offset_key)
        cached = self._offset_pair_cache.get(key)
        if cached is not None:
            return cached

        p = self._offset_point(i)
        q = self._offset_point(j)
        dx = float(q[0] - p[0])
        dy = float(q[1] - p[1])
        length = math.hypot(dx, dy)
        if length <= _EPS:
            return False
        px = -dy / length
        py = dx / length
        p_shift = (p[0] + offset * px, p[1] + offset * py)
        q_shift = (q[0] + offset * px, q[1] + offset * py)
        visible = self._visible_points(p_shift, q_shift, {i - 1, i, j - 1, j})
        self._offset_pair_cache[key] = visible
        return visible

    def soft_visibility_indices(self, i: int, j: int, width_a: float) -> float:
        width = max(0.0, float(width_a))
        if width <= self.eps_air:
            return 1.0 if self.visible_indices(i, j) else 0.0
        width_key = int(round(width / max(self.eps_air, 1e-9)))
        key = (int(i), int(j), width_key)
        cached = self._soft_pair_cache.get(key)
        if cached is not None:
            return cached

        total = 0.0
        weight_sum = 0.0
        for offset, weight in ((-width, 1.0), (0.0, 2.0), (width, 1.0)):
            weight_sum += weight
            if self.visible_indices_offset(i, j, offset):
                total += weight
        visibility = _clamp01(total / max(weight_sum, _EPS))
        self._soft_pair_cache[key] = visibility
        return visibility

    def los_indices(self, i: int, j: int) -> int:
        return 1 if self.visible_indices(i, j) else 0
