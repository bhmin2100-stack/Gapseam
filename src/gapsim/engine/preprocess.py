from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

Point = Tuple[float, float]  # (x, y_user)

@dataclass(frozen=True)
class EngineGeometry:
    points: List[Point]
    segments: List[Tuple[int, int]]
    wall_x_left: float
    wall_x_right: float
    unit: str = "Å"

def compute_walls(points: List[Point]) -> tuple[float, float, str]:
    xs = [p[0] for p in points] if points else [0.0]
    x_min, x_max = min(xs), max(xs)
    span = max(x_max - x_min, 1.0)
    margin = max(span * 0.02, 10.0)  # display/guard margin
    return (x_min - margin, x_max + margin, "Å")

def build_engine_geometry(points: List[Point]) -> EngineGeometry:
    wl, wr, unit = compute_walls(points)
    segs = [(i, i + 1) for i in range(max(0, len(points) - 1))]
    return EngineGeometry(points=list(points), segments=segs, wall_x_left=wl, wall_x_right=wr, unit=unit)
