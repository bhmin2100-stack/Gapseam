from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping

from gapsim.emulation.research_registry import DEFAULT_RESEARCH_ROOT
from gapsim.emulation.trench_depo import TrenchDepoConfig

DEFAULT_PARAMETER_LIBRARY_PATH = DEFAULT_RESEARCH_ROOT / "parameter_presets.json"
PARAMETER_LIBRARY_VERSION = 2
_INVALID_NAME_CHARS = re.compile(r"[\\/\:\*\?\"<>\|]")
_CONFIG_FIELD_NAMES = set(TrenchDepoConfig.__dataclass_fields__.keys())

# A process preset must be portable between structures. These fields describe
# the run being performed, rather than the deposited material/process recipe.
GEOMETRY_PARAMETER_FIELDS = frozenset({
    "points", "initial_voids", "deposition_feature_type", "deposition_feature_width_a",
    "deposition_feature_depth_a", "deposition_feature_length_a",
})
RUN_PARAMETER_FIELDS = frozenset({"cycles", "cvd_duration_s"})
CALCULATION_PARAMETER_FIELDS = frozenset({
    "reparam_ds_a", "redepo_incident_ray_count", "redepo_ray_count",
    "redepo_neighbor_exclusion", "redepo_soft_los_radius_points",
    "redepo_footprint_radius_sigma", "deposition_max_depo_per_cell_a",
    "transport_ray_count", "numerical_step_a",
})
_NON_PROCESS_FIELDS = (
    GEOMETRY_PARAMETER_FIELDS | RUN_PARAMETER_FIELDS | CALCULATION_PARAMETER_FIELDS
)
# Legacy smoothing/footprint widths remain recipe calibration coefficients.
# Removing them on load changes SFO3.1's accepted profile. They are not claimed
# to be measured material constants; pure discretization controls live above.
_LEGACY_RECIPE_DEFAULTS = {
    "recipe_model": "legacy_calibrated_v1", "process_type": "ald",
    "growth_basis": "gross",
    "symmetry_mode": "off",  # Older fitted recipes must not acquire a new boundary.
}


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
    try:
        version = int(raw.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise ParameterLibraryError("Parameter preset file version is invalid") from exc
    if version < 1 or version > PARAMETER_LIBRARY_VERSION:
        raise ParameterLibraryError(f"Unsupported parameter preset file version: {version}")
    # Preserve unrelated library metadata and every other preset on updates.
    return {**raw, "version": version, "presets": presets}


def _write_library(path: Path, payload: Mapping[str, Any]) -> None:
    library_path = Path(path)
    library_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=library_path.parent,
            prefix=f".{library_path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, library_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _config_payload(config: TrenchDepoConfig) -> Dict[str, Any]:
    return {
        key: value for key, value in asdict(config).items()
        if key in _CONFIG_FIELD_NAMES and key not in _NON_PROCESS_FIELDS
    }


def _record_group(record: Mapping[str, Any], name: str) -> Dict[str, Any]:
    values = record.get(name, {})
    if not isinstance(values, dict):
        raise ParameterLibraryError(f"Parameter preset {name} must be an object")
    return dict(values)


def parameter_preset_application_values(
    record: Mapping[str, Any],
    current_config: TrenchDepoConfig,
    *,
    include_run_defaults: bool = False,
    include_calculation_settings: bool = False,
) -> Dict[str, Any]:
    """Merge a v1/v2 process recipe onto the current structure and execution.

    Loading does not rewrite/migrate the library. Old flat records are split in
    memory; a subsequent explicit save writes the v2 representation. Missing
    recipe fields use compatible defaults, never stale controls from the last
    selected recipe. The caller may explicitly request saved run/solver values;
    geometry is always retained. Replay JSON loading uses its full config and
    must not call this helper.
    """
    source = _record_group(record, "config")
    current = asdict(current_config)
    result = dict(current)
    defaults = asdict(TrenchDepoConfig())
    for key, value in _LEGACY_RECIPE_DEFAULTS.items():
        if key in _CONFIG_FIELD_NAMES:
            defaults[key] = value
    for key in _CONFIG_FIELD_NAMES - _NON_PROCESS_FIELDS:
        result[key] = source.get(key, defaults[key])
    # v1 keeps everything in config; v2 stores optional defaults separately.
    for group, fields, enabled in (
        ("run_defaults", RUN_PARAMETER_FIELDS, include_run_defaults),
        ("calculation_settings", CALCULATION_PARAMETER_FIELDS, include_calculation_settings),
    ):
        values = {key: value for key, value in source.items() if key in fields}
        values.update(_record_group(record, group))
        if enabled:
            for key in fields & _CONFIG_FIELD_NAMES:
                if key in values:
                    result[key] = values[key]
    if "emulator_number" in record:
        result["emulator_number"] = int(record["emulator_number"])
    return result


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
    for group in ("run_defaults", "calculation_settings", "source_structure"):
        _record_group(record, group)
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
    payload = asdict(config)
    presets[safe_name] = {
        **(previous if isinstance(previous, dict) else {}),
        "name": safe_name,
        "schema_version": PARAMETER_LIBRARY_VERSION,
        "emulator_number": int(emulator_number),
        "created_at": created_at,
        "updated_at": now,
        "config": {**_config_payload(config), "emulator_number": int(emulator_number)},
        "run_defaults": {key: value for key, value in payload.items() if key in RUN_PARAMETER_FIELDS},
        "calculation_settings": {
            key: value for key, value in payload.items() if key in CALCULATION_PARAMETER_FIELDS
        },
        "source_structure": {
            key: value for key, value in payload.items() if key in GEOMETRY_PARAMETER_FIELDS
        },
    }
    library["version"] = PARAMETER_LIBRARY_VERSION
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
