from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from gapsim.emulation.research_registry import DEFAULT_RESEARCH_ROOT


ADDON_MANIFEST_FILENAME = "addon.json"
ADDON_LIBRARY_VERSION = 1
DEFAULT_ADDON_ROOT = DEFAULT_RESEARCH_ROOT / "addons"
DEFAULT_ADDON_STATE_PATH = DEFAULT_RESEARCH_ROOT / "addons_state.json"
_INVALID_ID_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


class AddonError(ValueError):
    pass


@dataclass(frozen=True)
class AddonManifest:
    addon_id: str
    name: str
    version: str
    description: str
    path: Path
    extension_points: tuple[str, ...] = ()


@dataclass(frozen=True)
class AddonRecord:
    manifest: AddonManifest
    enabled: bool


def sanitize_addon_id(raw: str) -> str:
    cleaned = _INVALID_ID_CHARS.sub("_", str(raw or "").strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = "addon"
    return cleaned[:80]


def _manifest_path(path: Path) -> Path:
    p = Path(path)
    if p.is_dir():
        return p / ADDON_MANIFEST_FILENAME
    return p


def read_addon_manifest(path: Path | str) -> AddonManifest:
    manifest_path = _manifest_path(Path(path))
    if not manifest_path.exists():
        raise AddonError(f"Addon manifest not found: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AddonError(f"Addon manifest is not valid JSON: {manifest_path}") from exc
    if not isinstance(payload, dict):
        raise AddonError(f"Addon manifest root must be an object: {manifest_path}")
    raw_id = payload.get("id") or manifest_path.parent.name
    addon_id = sanitize_addon_id(str(raw_id))
    name = str(payload.get("name") or addon_id).strip() or addon_id
    version = str(payload.get("version") or "0.0.0").strip() or "0.0.0"
    description = str(payload.get("description") or "").strip()
    raw_points = payload.get("extension_points", [])
    extension_points: tuple[str, ...]
    if isinstance(raw_points, Sequence) and not isinstance(raw_points, (str, bytes)):
        extension_points = tuple(str(point).strip() for point in raw_points if str(point).strip())
    else:
        extension_points = ()
    return AddonManifest(
        addon_id=addon_id,
        name=name,
        version=version,
        description=description,
        path=manifest_path.parent.resolve(),
        extension_points=extension_points,
    )


def _empty_state() -> Dict[str, Any]:
    return {"version": ADDON_LIBRARY_VERSION, "enabled": {}, "installed": {}}


class AddonManager:
    def __init__(
        self,
        *,
        addons_dir: Path | str = DEFAULT_ADDON_ROOT,
        state_path: Path | str = DEFAULT_ADDON_STATE_PATH,
    ) -> None:
        self.addons_dir = Path(addons_dir)
        self.state_path = Path(state_path)

    def _read_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return _empty_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AddonError(f"Addon state file is not valid JSON: {self.state_path}") from exc
        if not isinstance(raw, dict):
            raise AddonError(f"Addon state root must be an object: {self.state_path}")
        enabled = raw.get("enabled", {})
        installed = raw.get("installed", {})
        if not isinstance(enabled, dict):
            enabled = {}
        if not isinstance(installed, dict):
            installed = {}
        return {
            "version": int(raw.get("version", ADDON_LIBRARY_VERSION)),
            "enabled": dict(enabled),
            "installed": dict(installed),
        }

    def _write_state(self, state: Mapping[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _iter_manifest_paths(self) -> List[Path]:
        if not self.addons_dir.exists():
            return []
        paths: List[Path] = []
        for child in sorted(self.addons_dir.iterdir(), key=lambda p: p.name.lower()):
            manifest = child / ADDON_MANIFEST_FILENAME if child.is_dir() else child
            if manifest.is_file() and manifest.name == ADDON_MANIFEST_FILENAME:
                paths.append(manifest)
        return paths

    def scan(self) -> List[AddonRecord]:
        state = self._read_state()
        enabled_map = state.get("enabled", {})
        records: List[AddonRecord] = []
        for manifest_path in self._iter_manifest_paths():
            manifest = read_addon_manifest(manifest_path)
            records.append(AddonRecord(manifest=manifest, enabled=bool(enabled_map.get(manifest.addon_id, False))))
        return records

    def enabled_ids(self) -> List[str]:
        return [record.manifest.addon_id for record in self.scan() if record.enabled]

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        safe_id = sanitize_addon_id(addon_id)
        state = self._read_state()
        state.setdefault("enabled", {})[safe_id] = bool(enabled)
        self._write_state(state)

    def install_from_path(self, source: Path | str, *, enable: bool = True) -> AddonManifest:
        source_path = Path(source).resolve()
        manifest = read_addon_manifest(source_path)
        target_dir = (self.addons_dir / manifest.addon_id).resolve()
        source_manifest = _manifest_path(source_path).resolve()
        already_installed = source_manifest.parent == target_dir
        self.addons_dir.mkdir(parents=True, exist_ok=True)
        if already_installed:
            pass
        elif source_path.is_dir():
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_path, target_dir)
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_manifest, target_dir / ADDON_MANIFEST_FILENAME)
        installed_manifest = read_addon_manifest(target_dir)
        state = self._read_state()
        now = datetime.now().isoformat(timespec="seconds")
        state.setdefault("installed", {})[installed_manifest.addon_id] = {
            "id": installed_manifest.addon_id,
            "source": str(source_path),
            "installed_at": now,
        }
        state.setdefault("enabled", {})[installed_manifest.addon_id] = bool(enable)
        self._write_state(state)
        return installed_manifest

    def ensure_builtin_manifest(
        self,
        payload: Mapping[str, Any],
        *,
        enable_by_default: bool = True,
    ) -> AddonManifest:
        raw_id = str(payload.get("id", "")).strip()
        if not raw_id:
            raise AddonError("Builtin addon payload must include an id.")
        addon_id = sanitize_addon_id(raw_id)
        target_dir = (self.addons_dir / addon_id).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = target_dir / ADDON_MANIFEST_FILENAME
        manifest_payload = dict(payload)
        manifest_payload["id"] = addon_id
        encoded = json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True)
        if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != encoded:
            manifest_path.write_text(encoded, encoding="utf-8")
        manifest = read_addon_manifest(target_dir)
        state = self._read_state()
        state.setdefault("installed", {}).setdefault(
            manifest.addon_id,
            {
                "id": manifest.addon_id,
                "source": "builtin",
                "installed_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        enabled_map = state.setdefault("enabled", {})
        if manifest.addon_id not in enabled_map:
            enabled_map[manifest.addon_id] = bool(enable_by_default)
        self._write_state(state)
        return manifest
