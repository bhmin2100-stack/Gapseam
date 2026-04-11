from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict
from gapsim.domain.recipe import Recipe, GeometrySpec, SmoothingSpec, SCHEMA_VERSION
from gapsim.domain.units import LengthUnit

def save_recipe(path: str | Path, recipe: Recipe) -> None:
    p = Path(path)
    data: Dict[str, Any] = {
        "schema_version": recipe.schema_version,
        "geometry": {
            "points": recipe.geometry.points,
            "unit": recipe.geometry.unit.value,
            "bottom_closed": recipe.geometry.bottom_closed,
            "top_open": recipe.geometry.top_open,
            "side_walls_infinite": recipe.geometry.side_walls_infinite,
        },
        "smoothing": {
            "segment_n": recipe.smoothing.segment_n,
            "iterations": recipe.smoothing.iterations,
        },
        "steps": recipe.steps,
        "addons": recipe.addons,
        "meta": recipe.meta or {},
    }
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def load_recipe(path: str | Path) -> Recipe:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))

    if int(data.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError("Unsupported schema_version")

    g = data["geometry"]
    s = data.get("smoothing", {}) or {}

    geom = GeometrySpec(
        points=[tuple(x) for x in g["points"]],
        unit=LengthUnit(g.get("unit", "A")),
        bottom_closed=bool(g.get("bottom_closed", True)),
        top_open=bool(g.get("top_open", True)),
        side_walls_infinite=bool(g.get("side_walls_infinite", True)),
    )
    sm = SmoothingSpec(
        segment_n=int(s.get("segment_n", 200)),
        iterations=int(s.get("iterations", 5)),
    )

    return Recipe(
        schema_version=SCHEMA_VERSION,
        geometry=geom,
        smoothing=sm,
        steps=list(data.get("steps", [])),
        addons=list(data.get("addons", [])),
        meta=dict(data.get("meta", {})),
    )
