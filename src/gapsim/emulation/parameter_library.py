from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping

from gapsim.emulation.research_registry import DEFAULT_RESEARCH_ROOT
from gapsim.emulation.trench_depo import TrenchDepoConfig

DEFAULT_PARAMETER_LIBRARY_PATH = DEFAULT_RESEARCH_ROOT / "parameter_presets.json"
PARAMETER_LIBRARY_VERSION = 1
_INVALID_NAME_CHARS = re.compile(r"[\\/\:\*\?\"<>\|]")
_CONFIG_FIELD_NAMES = set(TrenchDepoConfig.__dataclass_fields__.keys())


class ParameterLibraryError(ValueError):
    pass


def sanitize_parameter_preset_name(name: str) -> str:
    cleaned = _INVALID_NAME_CHARS.sub("_", str(name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "parameter_preset"
    return cleaned[:80]


def _empty_library() -> Dict[str, Any]:
    return {"version": PARAMETER_LIBRARY_VERSION, "presets": {}}


def _read_library(path: Path) -> Dict[str, Any]:
    library_path = Path(path)
    if not library_path.exists():
        return _empty_library()
    try:
        raw = json.loads(library_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParameterLibraryError(f"Parameter preset file is not valid JSON: {library_path}") from exc
    if not isinstance(raw, dict):
        raise ParameterLibraryError(f"Parameter preset file root must be an object: {library_path}")
    presets = raw.get("presets", {})
    if not isinstance(presets, dict):
        raise ParameterLibraryError(f"Parameter preset file 'presets' must be an object: {library_path}")
    return {"version": int(raw.get("version", PARAMETER_LIBRARY_VERSION)), "presets": presets}


def _write_library(path: Path, payload: Mapping[str, Any]) -> None:
    library_path = Path(path)
    library_path.parent.mkdir(parents=True, exist_ok=True)
    library_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _config_payload(config: TrenchDepoConfig) -> Dict[str, Any]:
    payload = asdict(config)
    payload.pop("points", None)
    return {key: value for key, value in payload.items() if key in _CONFIG_FIELD_NAMES}


def list_parameter_presets(path: Path = DEFAULT_PARAMETER_LIBRARY_PATH) -> List[str]:
    library = _read_library(Path(path))
    return sorted(str(name) for name in library["presets"].keys())


def read_parameter_preset(path: Path, name: str) -> Dict[str, Any]:
    safe_name = sanitize_parameter_preset_name(name)
    library = _read_library(Path(path))
    presets = library["presets"]
    if safe_name not in presets:
        raise ParameterLibraryError(f"Parameter preset not found: {safe_name}")
    record = presets[safe_name]
    if not isinstance(record, dict):
        raise ParameterLibraryError(f"Parameter preset record is invalid: {safe_name}")
    config = record.get("config", {})
    if not isinstance(config, dict):
        raise ParameterLibraryError(f"Parameter preset config is invalid: {safe_name}")
    return dict(record)


def save_parameter_preset(
    path: Path,
    name: str,
    config: TrenchDepoConfig,
    *,
    emulator_number: int,
) -> str:
    safe_name = sanitize_parameter_preset_name(name)
    library_path = Path(path)
    library = _read_library(library_path)
    presets = library["presets"]
    now = datetime.now().isoformat(timespec="seconds")
    previous = presets.get(safe_name, {})
    created_at = previous.get("created_at", now) if isinstance(previous, dict) else now
    presets[safe_name] = {
        "name": safe_name,
        "emulator_number": int(emulator_number),
        "created_at": created_at,
        "updated_at": now,
        "config": _config_payload(config),
    }
    _write_library(library_path, library)
    return safe_name


def delete_parameter_preset(path: Path, name: str) -> str:
    safe_name = sanitize_parameter_preset_name(name)
    library_path = Path(path)
    library = _read_library(library_path)
    presets = library["presets"]
    if safe_name not in presets:
        raise ParameterLibraryError(f"Parameter preset not found: {safe_name}")
    del presets[safe_name]
    _write_library(library_path, library)
    return safe_name
