from __future__ import annotations
import math
from typing import List, Tuple
from gapsim.engine.steps.base import Step
from gapsim.engine.types import EngineState, RunContext, Point

def _unit(vx: float, vy: float) -> Tuple[float, float]:
    n = math.hypot(vx, vy)
    if n <= 1e-12:
        return 0.0, 0.0
    return vx / n, vy / n

def _point_in_poly(x: float, y: float, poly: List[Point]) -> bool:
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersect = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) if abs(yj - yi) > 1e-12 else 1e-12) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside

def _compute_air_normals(points: List[Point]) -> List[Tuple[float, float]]:
    if len(points) < 2:
        return [(0.0, 0.0) for _ in points]

    ys = [p[1] for p in points]
    y_floor = min(ys) - max((max(ys) - min(ys)) * 0.5, 200.0)

    # Si polygon = boundary + floor closure
    poly = list(points) + [(points[-1][0], y_floor), (points[0][0], y_floor)]

    normals: List[Tuple[float, float]] = []
    eps = 1e-2

    n = len(points)
    for i in range(n):
        if i == 0:
            x0, y0 = points[i]
            x1, y1 = points[i + 1]
            tx, ty = _unit(x1 - x0, y1 - y0)
        elif i == n - 1:
            x0, y0 = points[i - 1]
            x1, y1 = points[i]
            tx, ty = _unit(x1 - x0, y1 - y0)
        else:
            xa, ya = points[i - 1]
            xb, yb = points[i]
            xc, yc = points[i + 1]
            t1x, t1y = _unit(xb - xa, yb - ya)
            t2x, t2y = _unit(xc - xb, yc - yb)
            tx, ty = _unit(t1x + t2x, t1y + t2y)

        # candidate normals
        n1x, n1y = -ty, tx
        n2x, n2y = ty, -tx

        px, py = points[i]
        p1_in = _point_in_poly(px + eps * n1x, py + eps * n1y, poly)
        p2_in = _point_in_poly(px + eps * n2x, py + eps * n2y, poly)

        if p1_in and not p2_in:
            nx, ny = n2x, n2y
        elif p2_in and not p1_in:
            nx, ny = n1x, n1y
        else:
            nx, ny = (n1x, n1y) if n1y >= n2y else (n2x, n2y)

        normals.append(_unit(nx, ny))

    return normals

class ConformalGrowthStep(Step):
    step_id = "conformal_growth"

    def apply(self, state: EngineState, ctx: RunContext, params: dict) -> EngineState:
        pts = list(state.points)
        if len(pts) < 3:
            return state

        dt = max(0.0, float(params.get("dt", 1.0)))
        base_rate = max(0.0, float(params.get("base_rate", 1.0)))
        epsilon = max(0.0, float(params.get("epsilon", 0.0)))

        sealed = params.get("sealed_mode", {})
        if not isinstance(sealed, dict):
            sealed = {}
        sealed_opt = str(sealed.get("option", "A"))
        decay_k = max(0.0, float(sealed.get("decay_k", 0.0)))

        xs = [p[0] for p in pts]
        opening = float(max(xs) - min(xs)) if xs else 0.0

        rate = base_rate
        if opening <= epsilon:
            if sealed_opt == "A":
                rate = 0.0
            elif sealed_opt == "B":
                rate = base_rate * math.exp(-decay_k * max(epsilon - opening, 0.0))

        dr = rate * dt

        if dr <= 0.0:
            return state

        normals = _compute_air_normals(pts)

        new_pts: List[Point] = []
        for i, (p, (nx, ny)) in enumerate(zip(pts, normals)):
            x, y = p
            if i == 0 or i == len(pts) - 1:
                new_pts.append((x, y))
            else:
                new_pts.append((x + dr * nx, y + dr * ny))

        return EngineState(points=new_pts)
