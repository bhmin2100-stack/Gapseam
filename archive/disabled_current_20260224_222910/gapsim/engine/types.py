from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

Point = Tuple[float, float]  # (x, y_user) depth is negative

@dataclass(frozen=True)
class EngineState:
    points: List[Point]       # current boundary polyline

@dataclass(frozen=True)
class RunContext:
    run_dir: str
