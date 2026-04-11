from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

Point = Tuple[float, float]  # (x, y_user)

def load_recipe(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def _coerce_points(raw: Any) -> List[Point]:
    if raw is None:
        return []
    out: List[Point] = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("Invalid point format in recipe")
        x, y = p
        out.append((float(x), float(y)))
    return out

def extract_geometry_raw(recipe: Dict[str, Any]) -> List[Point]:
    pts = recipe.get("structure_points") or recipe.get("geometry_raw")
    if not pts:
        geom = recipe.get("geometry")
        if isinstance(geom, dict):
            pts = geom.get("points")
    return _coerce_points(pts)

def extract_geometry_final(recipe: Dict[str, Any]) -> List[Point]:
    pts = recipe.get("geometry_final")
    if pts:
        return _coerce_points(pts)
    return extract_geometry_raw(recipe)

def extract_case_name(recipe: Dict[str, Any]) -> str:
    run = recipe.get("run") or {}
    if run.get("case_name"):
        return str(run.get("case_name"))
    meta = recipe.get("meta") or {}
    return str(meta.get("case_name") or "gfs")
