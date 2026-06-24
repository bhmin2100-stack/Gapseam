from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DATA_ROOT_ENV = "GAPSIM_DATA_ROOT"
DATA_CONFIG_ENV = "GAPSIM_DATA_CONFIG"
DATA_SETTINGS_FILENAME = "data_root.json"


@dataclass(frozen=True)
class GapsimDataPaths:
    root: Path
    runs_root: Path
    results_root: Path
    research_root: Path
    structure_library_path: Path
    parameter_library_path: Path
    addons_root: Path
    addon_state_path: Path


def _config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Gapseam"
        return Path.home() / "AppData" / "Roaming" / "Gapseam"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Gapseam"
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "gapseam"
    return Path.home() / ".config" / "gapseam"


def data_root_config_path(*, config_path: Optional[Path | str] = None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser()
    override = os.environ.get(DATA_CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return _config_dir() / DATA_SETTINGS_FILENAME


def default_data_root_candidate() -> Path:
    documents = Path.home() / "Documents"
    base = documents if documents.exists() else Path.home()
    return base / "GapseamData"


def paths_for_data_root(root: Path | str) -> GapsimDataPaths:
    data_root = Path(root).expanduser().resolve()
    research_root = data_root / "emulator_research"
    addons_root = data_root / "addons"
    return GapsimDataPaths(
        root=data_root,
        runs_root=data_root / "runs" / "trench_depo_emulation",
        results_root=data_root / "results" / "trench_depo_emulation",
        research_root=research_root,
        structure_library_path=research_root / "structures.xlsx",
        parameter_library_path=research_root / "parameter_presets.json",
        addons_root=addons_root,
        addon_state_path=addons_root / "addons_state.json",
    )


def _read_data_root_from_config(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("data_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def configured_data_root(*, config_path: Optional[Path | str] = None) -> Optional[Path]:
    env_root = os.environ.get(DATA_ROOT_ENV)
    if env_root and env_root.strip():
        return Path(env_root).expanduser()
    return _read_data_root_from_config(data_root_config_path(config_path=config_path))


def configured_data_paths(*, config_path: Optional[Path | str] = None) -> Optional[GapsimDataPaths]:
    root = configured_data_root(config_path=config_path)
    if root is None:
        return None
    return paths_for_data_root(root)


def ensure_data_paths(paths: GapsimDataPaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.runs_root.mkdir(parents=True, exist_ok=True)
    paths.results_root.mkdir(parents=True, exist_ok=True)
    paths.research_root.mkdir(parents=True, exist_ok=True)
    paths.addons_root.mkdir(parents=True, exist_ok=True)


def save_configured_data_root(
    root: Path | str,
    *,
    config_path: Optional[Path | str] = None,
) -> Path:
    paths = paths_for_data_root(root)
    ensure_data_paths(paths)
    settings_path = data_root_config_path(config_path=config_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "version": 1,
                "data_root": str(paths.root),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.environ[DATA_ROOT_ENV] = str(paths.root)
    return paths.root


def configure_data_root(
    root: Path | str,
    *,
    config_path: Optional[Path | str] = None,
) -> GapsimDataPaths:
    saved_root = save_configured_data_root(root, config_path=config_path)
    return paths_for_data_root(saved_root)
