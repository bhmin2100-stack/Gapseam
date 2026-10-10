"""Frozen fixed-repeat recipe and prescribed input, never a target contour.

The old recipe is retained in incident_presets for historical research replay.
Registration is explicit and backs up libraries before replacing SFO3.1.
"""
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import json
import shutil

from .trench_depo import TrenchDepoConfig

STRUCTURE_NAME = "SFO3.1 CD242 R42 H702"
VERSION = "fixed-repeat-20261008"


def verified_sfo31_config():
    payload = json.loads(Path(__file__).with_name("sfo31_verified.json").read_text(encoding="utf-8"))
    cfg = payload["config"]
    cfg["points"] = tuple(tuple(p) for p in cfg["points"])
    cfg["initial_voids"] = tuple(tuple(tuple(p) for p in poly) for poly in cfg.get("initial_voids", []))
    return TrenchDepoConfig(**cfg)


def backup_library(path):
    path = Path(path)
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.stem}.before-sfo31-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    return str(backup)


def register_verified_sfo31(parameter_path, structure_path, *, replace_existing=False):
    from .parameter_library import list_parameter_presets, save_parameter_preset
    from .structure_library import list_structure_names, save_structure_points
    cfg = verified_sfo31_config()
    backups = []
    if replace_existing or "SFO3.1" not in list_parameter_presets(parameter_path):
        backup = backup_library(parameter_path)
        if backup:
            backups.append(backup)
        save_parameter_preset(parameter_path, "SFO3.1", cfg, emulator_number=0)
    if replace_existing or STRUCTURE_NAME not in list_structure_names(structure_path):
        backup = backup_library(structure_path)
        if backup:
            backups.append(backup)
        save_structure_points(structure_path, STRUCTURE_NAME, cfg.points)
    return backups


def structure_metadata(name, points):
    """Only recognize the unmodified named input; do not alter user structures."""
    if name != STRUCTURE_NAME:
        return None
    cfg = verified_sfo31_config()
    if len(points) != len(cfg.points) or any(abs(a-b)>1e-8 for p,q in zip(points,cfg.points) for a,b in zip(p,q)):
        return None
    return {key:getattr(cfg,key) for key in ("deposition_feature_type", "deposition_feature_width_a", "deposition_feature_depth_a", "deposition_feature_length_a")}
