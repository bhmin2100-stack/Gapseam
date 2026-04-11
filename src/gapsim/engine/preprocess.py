from __future__ import annotations

from typing import List, Tuple

Point = Tuple[float, float]  # (x, y_user)

def compute_walls(points: List[Point]) -> tuple[float, float, str]:
    xs = [p[0] for p in points] if points else [0.0]
    x_min, x_max = min(xs), max(xs)
    span = max(x_max - x_min, 1.0)
    margin = max(span * 0.02, 10.0)  # display/guard margin
    return (x_min - margin, x_max + margin, "Å")
