from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from gapsim.emulation.addon_manager import AddonManifest, AddonRecord, sanitize_addon_id


@dataclass(frozen=True)
class AddonLoadResult:
    addon_id: str
    name: str
    loaded: bool
    message: str


class AddonContext:
    def __init__(
        self,
        *,
        manifest: AddonManifest,
        window: Any,
        log: Callable[[str], None],
    ) -> None:
        self.manifest = manifest
        self.window = window
        self.addon_id = manifest.addon_id
        self.addon_path = manifest.path
        self._log = log

    def log(self, message: str) -> None:
        self._log(f"[{self.addon_id}] {message}")

    def add_progress_widget(self, widget: Any, *, title: str = "") -> None:
        callback = getattr(self.window, "_add_addon_progress_widget", None)
        if callback is None:
            raise RuntimeError("Host window does not support progress addon widgets.")
        callback(widget, title=title or self.manifest.name)

    def add_result_widget(self, widget: Any, *, title: str = "") -> None:
        callback = getattr(self.window, "_add_addon_result_widget", None)
        if callback is None:
            raise RuntimeError("Host window does not support result addon widgets.")
        callback(widget, title=title or self.manifest.name)

    @property
    def result_applied(self) -> Any:
        return getattr(self.window, "addonResultApplied", None)

    @property
    def frame_shown(self) -> Any:
        return getattr(self.window, "addonFrameShown", None)


def _entrypoint_path(manifest: AddonManifest) -> Optional[Path]:
    entrypoint = str(manifest.entrypoint or "").strip()
    if not entrypoint:
        return None
    candidate = (manifest.path / entrypoint).resolve()
    addon_root = manifest.path.resolve()
    if candidate != addon_root and addon_root not in candidate.parents:
        raise RuntimeError(f"Addon entrypoint escapes addon folder: {entrypoint}")
    if not candidate.is_file():
        raise RuntimeError(f"Addon entrypoint not found: {entrypoint}")
    return candidate


def load_enabled_addons(
    records: Sequence[AddonRecord],
    *,
    window: Any,
    log: Callable[[str], None],
) -> tuple[List[Any], List[AddonLoadResult]]:
    handles: List[Any] = []
    results: List[AddonLoadResult] = []
    for record in records:
        manifest = record.manifest
        if not record.enabled:
            continue
        try:
            entrypoint = _entrypoint_path(manifest)
            if entrypoint is None:
                results.append(
                    AddonLoadResult(
                        addon_id=manifest.addon_id,
                        name=manifest.name,
                        loaded=True,
                        message="manifest only",
                    )
                )
                continue
            module_name = f"gapsim_user_addon_{sanitize_addon_id(manifest.addon_id)}"
            spec = importlib.util.spec_from_file_location(module_name, entrypoint)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Cannot load addon entrypoint: {entrypoint}")
            module = importlib.util.module_from_spec(spec)
            old_path = list(sys.path)
            sys.path.insert(0, str(manifest.path))
            try:
                spec.loader.exec_module(module)
            finally:
                sys.path[:] = old_path
            register = getattr(module, "register", None)
            if not callable(register):
                raise RuntimeError("Addon entrypoint must define register(context).")
            context = AddonContext(manifest=manifest, window=window, log=log)
            handle = register(context)
            handles.append(handle if handle is not None else module)
            results.append(
                AddonLoadResult(
                    addon_id=manifest.addon_id,
                    name=manifest.name,
                    loaded=True,
                    message=f"loaded {entrypoint.name}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            log(f"[{manifest.addon_id}] load failed: {exc}\n{traceback.format_exc()}")
            results.append(
                AddonLoadResult(
                    addon_id=manifest.addon_id,
                    name=manifest.name,
                    loaded=False,
                    message=str(exc),
                )
            )
    return handles, results
