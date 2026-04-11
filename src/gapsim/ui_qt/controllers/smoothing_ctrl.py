from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple, Optional

Point = Tuple[float, float]
_EPS = 1e-12

def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])

def _resample_uniform_by_segments(points: List[Point], segments: int) -> List[Point]:
    if len(points) < 2:
        return list(points)
    if segments < 1:
        return list(points)

    total = 0.0
    for i in range(len(points) - 1):
        total += _dist(points[i], points[i + 1])
    if total <= _EPS:
        return list(points)

    step = total / segments
    out = [points[0]]
    seg_i = 0
    cur = points[0]
    acc = 0.0
    target = step

    while len(out) < segments and seg_i < len(points) - 1:
        nxt = points[seg_i + 1]
        l = _dist(cur, nxt)
        if acc + l >= target:
            remain = target - acc
            t = 0.0 if l <= _EPS else remain / l
            x = cur[0] + (nxt[0] - cur[0]) * t
            y = cur[1] + (nxt[1] - cur[1]) * t
            out.append((x, y))
            cur = (x, y)
            acc = 0.0
            target = step
        else:
            acc += l
            seg_i += 1
            cur = nxt

    out.append(points[-1])
    return out

def _vertex_turn_magnitude(points: List[Point], i: int) -> float:
    if i <= 0 or i >= len(points) - 1:
        return 0.0
    ax = points[i][0] - points[i - 1][0]
    ay = points[i][1] - points[i - 1][1]
    bx = points[i + 1][0] - points[i][0]
    by = points[i + 1][1] - points[i][1]
    la = math.hypot(ax, ay)
    lb = math.hypot(bx, by)
    if la <= _EPS or lb <= _EPS:
        return 0.0
    cross = ax * by - ay * bx
    dot = ax * bx + ay * by
    angle = abs(math.atan2(cross, dot))  # 0..pi, concave/convex both positive
    return angle / math.pi

def _solve_local_fraction(local_metric: float, length: float, d0: float, d1: float) -> float:
    if length <= _EPS:
        return 0.0
    q = d1 - d0
    y = max(0.0, min(local_metric / length, 0.5 * (d0 + d1)))
    if abs(q) <= _EPS:
        if d0 <= _EPS:
            return 0.0
        return max(0.0, min(y / d0, 1.0))
    disc = d0 * d0 + 2.0 * q * y
    if disc < 0.0:
        disc = 0.0
    u = (-d0 + math.sqrt(disc)) / q
    return max(0.0, min(u, 1.0))

def _refine_high_curvature(points: List[Point], base_segments: int) -> List[Point]:
    if len(points) < 3:
        return points

    n = len(points)
    curv: List[float] = [0.0] * n
    for i in range(1, n - 1):
        curv[i] = _vertex_turn_magnitude(points, i)

    refined: List[Point] = [points[0]]
    for i in range(n - 1):
        p0 = points[i]
        p1 = points[i + 1]
        c_local = max(curv[i], curv[i + 1])
        # Add extra vertices around high-curvature regions.
        extra = int(round(6.0 * c_local))
        subdiv = max(1, 1 + extra)
        for j in range(1, subdiv + 1):
            t = float(j) / float(subdiv)
            x = p0[0] + (p1[0] - p0[0]) * t
            y = p0[1] + (p1[1] - p0[1]) * t
            refined.append((x, y))

    max_points = min(5000, max(len(points), int(2 * max(1, base_segments) + 1)))
    if len(refined) > max_points:
        return _resample_uniform_by_segments(refined, max_points - 1)
    return refined

def resample_by_segments(
    points: List[Point],
    segments: int,
    *,
    curvature_gain: float = 12.0,
    curvature_power: float = 2.0,
) -> List[Point]:
    if len(points) < 2:
        return list(points)
    if segments < 1:
        return list(points)

    n = len(points)
    seg_len: List[float] = [_dist(points[i], points[i + 1]) for i in range(n - 1)]
    if sum(seg_len) <= _EPS:
        return list(points)

    gain = max(0.0, float(curvature_gain))
    power = max(0.5, float(curvature_power))
    curv: List[float] = [0.0] * n
    for i in range(1, n - 1):
        curv[i] = _vertex_turn_magnitude(points, i)
    # Emphasize high-curvature vertices much more than gentle bends.
    density: List[float] = [1.0 + gain * (max(0.0, min(1.0, c)) ** power) for c in curv]

    seg_metric: List[float] = []
    total_metric = 0.0
    for i, length in enumerate(seg_len):
        if length <= _EPS:
            seg_metric.append(0.0)
            continue
        m = length * 0.5 * (density[i] + density[i + 1])
        seg_metric.append(m)
        total_metric += m

    if total_metric <= _EPS:
        return _resample_uniform_by_segments(points, segments)

    target_step = total_metric / segments
    out: List[Point] = [points[0]]
    seg_i = 0
    prefix = 0.0

    for k in range(1, segments):
        target = target_step * k
        while seg_i < len(seg_metric) - 1 and (prefix + seg_metric[seg_i]) < target:
            prefix += seg_metric[seg_i]
            seg_i += 1

        length = seg_len[seg_i]
        local = target - prefix
        d0 = density[seg_i]
        d1 = density[seg_i + 1]
        u = _solve_local_fraction(local, length, d0, d1)
        x0, y0 = points[seg_i]
        x1, y1 = points[seg_i + 1]
        out.append((x0 + (x1 - x0) * u, y0 + (y1 - y0) * u))

    out.append(points[-1])
    return _refine_high_curvature(out, segments)

def laplacian_smooth(points: List[Point], iters: int) -> List[Point]:
    pts = [list(p) for p in points]
    n = len(pts)
    if n < 3 or iters <= 0:
        return [(p[0], p[1]) for p in pts]
    for _ in range(iters):
        new = [p[:] for p in pts]
        for i in range(1, n - 1):
            new[i][0] = 0.5 * (pts[i - 1][0] + pts[i + 1][0])
            new[i][1] = 0.5 * (pts[i - 1][1] + pts[i + 1][1])
        pts = new
    return [(p[0], p[1]) for p in pts]

@dataclass
class SmoothState:
    base_points: List[Point]
    last_result: Optional[List[Point]] = None
    segments: int = 200
    iterations: int = 5

class SmoothingController:
    def __init__(self) -> None:
        self.state = SmoothState(base_points=[])

    def set_base_points(self, pts: List[Point]) -> None:
        self.state.base_points = list(pts)
        self.state.last_result = None

    def set_params(self, segments: int, iterations: int) -> None:
        self.state.segments = int(segments)
        self.state.iterations = int(iterations)

    def run(self) -> List[Point]:
        base = list(self.state.base_points)
        seg = max(self.state.segments, 1)
        it = max(self.state.iterations, 0)
        pts = resample_by_segments(base, seg)
        pts = laplacian_smooth(pts, it)
        self.state.last_result = pts
        return pts

    def revert(self) -> None:
        self.state.last_result = None

    def get_saved_payload(self) -> dict:
        return {
            "base_points": list(self.state.base_points),
            "segments": int(self.state.segments),
            "iterations": int(self.state.iterations),
        }
