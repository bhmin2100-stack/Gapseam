from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional
from gapsim.domain.units import LengthUnit

Point = Tuple[float, float]
SCHEMA_VERSION = 1

@dataclass
class GeometrySpec:
    points: List[Point]
    unit: LengthUnit = LengthUnit.ANGSTROM
    bottom_closed: bool = True
    top_open: bool = True
    side_walls_infinite: bool = True

@dataclass
class SmoothingSpec:
    segment_n: int = 200
    iterations: int = 5

@dataclass
class Recipe:
    schema_version: int
    geometry: GeometrySpec
    smoothing: SmoothingSpec
    steps: List[Dict[str, Any]]       # engine steps (future)
    addons: List[Dict[str, Any]]      # analysis addons (future)
    meta: Optional[Dict[str, Any]] = None
