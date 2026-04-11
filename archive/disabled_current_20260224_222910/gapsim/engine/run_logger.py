from __future__ import annotations
import json
import platform
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

def create_run_dir(runs_root: Path, case_name: str) -> Path:
    runs_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (case_name or "case"))
    base_name = f"{ts}_{safe}"
    for i in range(0, 1000):
        suffix = "" if i == 0 else f"_{i:03d}"
        run_dir = runs_root / f"{base_name}{suffix}"
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_dir
        except FileExistsError:
            continue
    raise RuntimeError("Failed to allocate unique run directory name")

def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def make_meta(engine_version: str, recipe_meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "engine_version": engine_version,
        "created_at_local": datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "recipe_meta": recipe_meta,
    }
