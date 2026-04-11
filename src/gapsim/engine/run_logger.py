from __future__ import annotations

import json
import platform
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

def create_run_dir(runs_root: Path, case_name: str) -> Path:
    runs_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (case_name or "gfs"))
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

@lru_cache(maxsize=1)
def _runtime_info() -> Dict[str, str]:
    system = (platform.system() or "").strip()
    release = (platform.release() or "").strip()
    machine = (platform.machine() or "").strip()
    parts = [part for part in (system, release, machine) if part]
    platform_summary = " ".join(parts) if parts else "unknown"
    python_version = (platform.python_version() or "").strip() or "unknown"
    return {
        "python": python_version,
        "platform": platform_summary,
    }

def make_meta(recipe: Dict[str, Any], engine_version: str = "0.0.0") -> Dict[str, Any]:
    runtime = _runtime_info()
    return {
        "app_name": "GFS",
        "engine_version": engine_version,
        "created_at_local": datetime.now().isoformat(timespec="seconds"),
        "python": runtime["python"],
        "platform": runtime["platform"],
        "units": recipe.get("units", {"length": "Å", "y_down_is_negative": True}),
    }
