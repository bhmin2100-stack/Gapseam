from __future__ import annotations

import copy
import math
import json
import os
import re
import sys
import tempfile
import time
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QObject, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QImage, QKeySequence, QPainter, QUndoStack
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QToolBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from gapsim.prediction import auto_anchor_spec, sanitize_anchor_spec
from gapsim.ui_qt.calibrate_dialog import CalibrateDialog
from gapsim.ui_qt.controllers.smoothing_ctrl import SmoothingController
from gapsim.ui_qt.engine_worker import EngineWorker
from gapsim.ui_qt.models.points_table import Point, PointsTableModel
from gapsim.ui_qt.models.points_table_view import PointsTableView
from gapsim.ui_qt.prediction_dialogs import (
    PredictionAnchorDialog,
    PredictionPostEditorDialog,
    PredictionPostSmoothingDialog,
)
from gapsim.ui_qt.prediction_worker import ParameterPredictionWorker
from gapsim.ui_qt.models.structure_document import (
    DeletePointCommand,
    InsertPointCommand,
    MovePointCommand,
    SetPointsCommand,
    StructureDocument,
)
from gapsim.ui_qt.switch_schema import PHASE1_SWITCH_SCHEMA, default_switch_state
from gapsim.ui_qt.ui_text import tr
from gapsim.ui_qt.views.result_vector_view import ResultVectorView
from gapsim.ui_qt.views.structure_view import StructureView

DEFAULT_POINTS: List[Point] = [
    (500.0, 0.0),
    (250.0, 0.0),
    (125.0, -4000.0),
    (-125.0, -4000.0),
    (-250.0, 0.0),
    (-500.0, 0.0),
]

REPARAM_PRESET_TARGET_POINTS: Dict[str, float] = {
    "fast": 600.0,
    "normal": 1200.0,
    "detail": 2400.0,
}

REPARAM_PRESET_LIMITS_A: Dict[str, Tuple[float, float]] = {
    "fast": (5.0, 200.0),
    "normal": (2.5, 100.0),
    "detail": (2.5, 50.0),
}


def _profiles_same_points(a: List[Point], b: List[Point], tol: float = 1e-6) -> bool:
    if len(a) != len(b):
        return False
    for (ax, ay), (bx, by) in zip(a, b):
        if abs(float(ax) - float(bx)) > tol or abs(float(ay) - float(by)) > tol:
            return False
    return True


def _load_result_payload_single(run_dir: Path) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    profiles_path = run_dir / "profiles.json"
    recipe_path = run_dir / "recipe.json"
    meta_path = run_dir / "meta.json"

    frames: List[List[Point]] = []
    voids: List[List[List[Point]]] = []
    steps: List[int] = []
    stage_ids: List[int] = []
    x_window: Optional[Tuple[float, float]] = None
    stage_info: Dict[str, Any] = {"index": 1}
    void_mode = "legacy_cumulative"
    recipe: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    history_self_contained = False

    if profiles_path.exists():
        data = json.loads(profiles_path.read_text(encoding="utf-8"))
        history_self_contained = bool(data.get("history_self_contained", False))
        raw_frames = data.get("frame_profiles") or []
        raw_voids = data.get("frame_voids") or []
        raw_steps = data.get("frame_steps") or []
        raw_stage_ids = data.get("frame_stage_ids") or []
        raw_window = data.get("x_window")
        raw_stage = data.get("stage")
        raw_void_mode = data.get("frame_voids_mode")
        if isinstance(raw_stage, dict):
            stage_info = dict(raw_stage)
        if isinstance(raw_void_mode, str) and raw_void_mode.lower() == "current":
            void_mode = "current"

        for frm in raw_frames:
            if not isinstance(frm, list) or len(frm) < 2:
                continue
            pts: List[Point] = []
            ok = True
            for p in frm:
                if not isinstance(p, (list, tuple)) or len(p) != 2:
                    ok = False
                    break
                pts.append((float(p[0]), float(p[1])))
            if ok:
                frames.append(pts)

        if isinstance(raw_voids, list):
            for vf in raw_voids[: len(frames)]:
                frame_voids: List[List[Point]] = []
                if isinstance(vf, list):
                    for poly in vf:
                        if not isinstance(poly, list) or len(poly) < 3:
                            continue
                        vpts: List[Point] = []
                        ok_poly = True
                        for p in poly:
                            if not isinstance(p, (list, tuple)) or len(p) != 2:
                                ok_poly = False
                                break
                            vpts.append((float(p[0]), float(p[1])))
                        if ok_poly:
                            frame_voids.append(vpts)
                voids.append(frame_voids)

        if isinstance(raw_steps, list):
            for s in raw_steps[: len(frames)]:
                steps.append(int(s))

        if isinstance(raw_stage_ids, list):
            for sid in raw_stage_ids[: len(frames)]:
                stage_ids.append(max(1, int(sid)))

        if isinstance(raw_window, (list, tuple)) and len(raw_window) == 2:
            x_window = (float(raw_window[0]), float(raw_window[1]))

    stage_idx = 1
    try:
        stage_idx = max(1, int(stage_info.get("index", 1)))
    except Exception:
        stage_idx = 1
    if len(voids) != len(frames):
        voids = [[] for _ in frames]
    if len(steps) != len(frames):
        steps = list(range(len(frames)))
    if len(stage_ids) != len(frames):
        stage_ids = [stage_idx for _ in frames]

    if recipe_path.exists():
        try:
            loaded_recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            if isinstance(loaded_recipe, dict):
                recipe = loaded_recipe
        except Exception:
            recipe = {}
    if meta_path.exists():
        try:
            loaded_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded_meta, dict):
                meta = loaded_meta
        except Exception:
            meta = {}

    return {
        "frames": frames,
        "voids": voids,
        "steps": steps,
        "stage_ids": stage_ids,
        "x_window": x_window,
        "stage_info": stage_info,
        "void_mode": void_mode,
        "recipe": recipe,
        "meta": meta,
        "run_dir": str(run_dir.resolve()),
        "history_self_contained": history_self_contained,
        "history_complete": False,
    }


def _payload_stage_index(payload: Dict[str, Any]) -> int:
    stage_info = payload.get("stage_info")
    if not isinstance(stage_info, dict):
        return 1
    try:
        return max(1, int(stage_info.get("index", 1)))
    except Exception:
        return 1


def _payload_has_prior_stage_history(payload: Dict[str, Any]) -> bool:
    stage_idx = _payload_stage_index(payload)
    if stage_idx <= 1:
        return True
    if bool(payload.get("history_self_contained", False)):
        return True
    stage_ids = payload.get("stage_ids")
    present: set[int] = set()
    if isinstance(stage_ids, list):
        for sid in stage_ids:
            try:
                present.add(max(1, int(sid)))
            except Exception:
                continue
    return all(sid in present for sid in range(1, stage_idx))


def _resolve_continuation_run_dir(continued_from: Any, current_run_dir: Path) -> Optional[Path]:
    text = str(continued_from or "").strip()
    if not text:
        return None
    raw = Path(text).expanduser()
    current_run_dir = Path(current_run_dir)
    candidates: List[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
        if raw.name:
            candidates.append(current_run_dir.parent / raw.name)
    else:
        candidates.extend(
            [
                current_run_dir / raw,
                current_run_dir.parent / raw,
                current_run_dir.parent.parent / raw,
            ]
        )
        if raw.name:
            candidates.append(current_run_dir.parent / raw.name)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if (resolved / "profiles.json").exists():
            return resolved
    return None


def _merged_x_window(
    base_payload: Dict[str, Any],
    current_payload: Dict[str, Any],
    merged_frames: List[List[Point]],
) -> Optional[Tuple[float, float]]:
    windows: List[Tuple[float, float]] = []
    for payload in (base_payload, current_payload):
        raw = payload.get("x_window")
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            try:
                windows.append((float(raw[0]), float(raw[1])))
            except Exception:
                pass
    if windows:
        return (min(w[0] for w in windows), max(w[1] for w in windows))

    xs = [float(x) for frame in merged_frames for x, _y in frame]
    if not xs:
        return None
    return (min(xs), max(xs))


def _merge_result_payload_history(
    base_payload: Dict[str, Any],
    current_payload: Dict[str, Any],
) -> Dict[str, Any]:
    base_frames = base_payload.get("frames") if isinstance(base_payload.get("frames"), list) else []
    current_frames = current_payload.get("frames") if isinstance(current_payload.get("frames"), list) else []
    if not base_frames or not current_frames:
        out = dict(current_payload)
        out["history_complete"] = bool(current_payload.get("history_complete", False))
        return out

    base_voids = base_payload.get("voids") if isinstance(base_payload.get("voids"), list) else []
    current_voids = current_payload.get("voids") if isinstance(current_payload.get("voids"), list) else []
    base_steps = base_payload.get("steps") if isinstance(base_payload.get("steps"), list) else []
    current_steps = current_payload.get("steps") if isinstance(current_payload.get("steps"), list) else []
    base_stage_ids = base_payload.get("stage_ids") if isinstance(base_payload.get("stage_ids"), list) else []
    current_stage_ids = current_payload.get("stage_ids") if isinstance(current_payload.get("stage_ids"), list) else []
    stage_index = _payload_stage_index(current_payload)

    drop_head = 0
    if _profiles_same_points(base_frames[-1], current_frames[0]):
        drop_head = 1

    used_frames = list(current_frames[drop_head:])
    if len(current_voids) == len(current_frames):
        used_voids = list(current_voids[drop_head:])
    else:
        used_voids = [[] for _ in used_frames]
    if len(current_stage_ids) == len(current_frames):
        used_stage_ids = [max(1, int(sid)) for sid in current_stage_ids[drop_head:]]
    else:
        used_stage_ids = [stage_index for _ in used_frames]

    merged_frames = list(base_frames) + used_frames
    merged_voids = list(base_voids if len(base_voids) == len(base_frames) else [[] for _ in base_frames]) + used_voids

    merged_steps = [int(s) for s in base_steps] if len(base_steps) == len(base_frames) else list(range(len(base_frames)))
    step_counter = (merged_steps[-1] + 1) if merged_steps else 0
    for _ in (current_steps[drop_head:] if len(current_steps) == len(current_frames) else used_frames):
        merged_steps.append(step_counter)
        step_counter += 1

    merged_stage_ids = (
        [max(1, int(sid)) for sid in base_stage_ids]
        if len(base_stage_ids) == len(base_frames)
        else [1 for _ in base_frames]
    )
    merged_stage_ids.extend(used_stage_ids)

    base_void_mode = "current" if str(base_payload.get("void_mode", "")).lower() == "current" else "legacy_cumulative"
    current_void_mode = "current" if str(current_payload.get("void_mode", "")).lower() == "current" else "legacy_cumulative"
    merged_void_mode = "current" if base_void_mode == "current" and current_void_mode == "current" else "legacy_cumulative"

    out = dict(current_payload)
    out.update(
        {
            "frames": merged_frames,
            "voids": merged_voids if len(merged_voids) == len(merged_frames) else [[] for _ in merged_frames],
            "steps": merged_steps if len(merged_steps) == len(merged_frames) else list(range(len(merged_frames))),
            "stage_ids": (
                merged_stage_ids
                if len(merged_stage_ids) == len(merged_frames)
                else [stage_index for _ in merged_frames]
            ),
            "x_window": _merged_x_window(base_payload, current_payload, merged_frames),
            "void_mode": merged_void_mode,
            "history_self_contained": True,
            "history_complete": True,
        }
    )
    return out


def load_result_payload_from_run_dir(
    run_dir: Path,
    *,
    include_history: bool = True,
    _seen: Optional[set[str]] = None,
) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    payload = _load_result_payload_single(run_dir)
    if not include_history:
        return payload

    seen = set(_seen or set())
    try:
        run_key = str(run_dir.resolve())
    except Exception:
        run_key = str(run_dir)
    if run_key in seen:
        payload["history_complete"] = False
        return payload
    seen.add(run_key)

    stage_info = payload.get("stage_info")
    continued_from = stage_info.get("continued_from") if isinstance(stage_info, dict) else None
    if not continued_from or _payload_has_prior_stage_history(payload):
        payload["history_complete"] = True
        return payload

    base_dir = _resolve_continuation_run_dir(continued_from, run_dir)
    if base_dir is None:
        payload["history_complete"] = False
        return payload

    base_payload = load_result_payload_from_run_dir(base_dir, include_history=True, _seen=seen)
    if not base_payload.get("frames"):
        payload["history_complete"] = bool(base_payload.get("history_complete", False))
        return payload
    return _merge_result_payload_history(base_payload, payload)


class _NoWheelEventFilter(QObject):
    def eventFilter(self, _obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            return True
        return False


class ResultLoadWorker(QObject):
    loaded = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, *, seq: int, run_dir: Path, include_history: bool = True) -> None:
        super().__init__()
        self.seq = int(seq)
        self.run_dir = Path(run_dir)
        self.include_history = bool(include_history)

    @Slot()
    def run(self) -> None:
        try:
            payload = load_result_payload_from_run_dir(self.run_dir, include_history=self.include_history)
        except Exception as exc:
            self.error.emit(self.seq, str(exc))
            return
        self.loaded.emit(self.seq, payload)


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        workflow_stage: Optional[str] = None,
        initial_data: Optional[Dict[str, Any]] = None,
        source_path: Optional[Path] = None,
        initial_run_dir: Optional[Path] = None,
        workflow_spawn: Optional[
            Callable[[str, Optional[Dict[str, Any]], Optional[Path], Optional[Path], str], None]
        ] = None,
    ) -> None:
        super().__init__()
        self.lang = "ko"
        self._workflow_stage = workflow_stage
        self._workflow_windows: List["MainWindow"] = []
        self._workflow_initial_data = initial_data
        self._workflow_source_path = Path(source_path) if source_path is not None else None
        self._workflow_initial_run_dir = Path(initial_run_dir) if initial_run_dir is not None else None
        self._workflow_spawn = workflow_spawn

        self._current_path: Optional[Path] = None
        self._last_run_dir: Optional[Path] = None
        self._structure_origin: List[Point] = list(DEFAULT_POINTS)
        self._drag_start: Optional[Tuple[int, Point]] = None
        self._model_change_from_view = False

        self.smoothing = SmoothingController()
        self.undo_stack = QUndoStack(self)

        self._engine_thread: Optional[QThread] = None
        self._engine_worker: Optional[EngineWorker] = None
        self._result_frames: List[List[Point]] = []
        self._result_voids: List[List[List[Point]]] = []
        self._result_steps: List[int] = []
        self._result_stage_ids: List[int] = []
        self._result_stage_info: Dict[str, Any] = {"index": 1}
        self._result_recipe: Dict[str, Any] = {}
        self._result_meta: Dict[str, Any] = {}
        self._result_display_indices: List[int] = []
        self._result_display_steps: List[int] = []
        self._result_display_stage_ids: List[int] = []
        self._result_x_window: Optional[Tuple[float, float]] = None
        self._result_void_mode = "legacy_cumulative"
        self._result_show_every_n = 1
        self._frame_index = -1
        self._result_loading = False
        self._result_load_seq = 0
        self._result_loader_thread: Optional[QThread] = None
        self._result_loader_worker: Optional[ResultLoadWorker] = None
        self._continuation_seed_points: Optional[List[Point]] = None
        self._continuation_base_frames: Optional[List[List[Point]]] = None
        self._continuation_base_voids: Optional[List[List[List[Point]]]] = None
        self._continuation_base_steps: Optional[List[int]] = None
        self._continuation_base_stage_ids: Optional[List[int]] = None
        self._continuation_base_void_mode: Optional[str] = None
        self._continuation_base_run_dir: Optional[Path] = None
        self._continuation_stage_index = 1
        self._continuation_merge_pending = False

        self._run_status_kind = "idle"
        self._run_status_step = 0
        self._run_status_total = 0
        self._run_status_substep = 0
        self._run_status_substeps = 0
        self._run_status_detail: dict[str, Any] | None = None
        self._run_started_at_mono: float | None = None
        self._run_eta_seconds: float | None = None
        self._run_eta_finish_text: str = ""
        self._run_progress_marks: List[Tuple[int, float]] = []
        self._run_presets: Dict[str, Dict[str, Any]] = {}
        self._overlay_opacity = 0.35
        self._overlay_path: Optional[str] = None
        self._overlay_scale_a_per_px = 1.0
        self._cached_geometry_final: Optional[List[Point]] = None
        self._cached_geometry_base: Optional[List[Point]] = None

        self._switch_state = default_switch_state()
        self._switch_widgets: Dict[str, Dict[str, Any]] = {}
        self._panel_scroll_widgets: Dict[str, QScrollArea] = {}
        self._no_wheel_filter = _NoWheelEventFilter(self)
        self._prediction_post_points_raw: List[Point] = []
        self._prediction_post_points_smooth: List[Point] = []
        self._prediction_anchor_spec: Dict[str, Any] = {}
        self._prediction_result: Dict[str, Any] = {}
        self._prediction_thread: Optional[QThread] = None
        self._prediction_worker: Optional[ParameterPredictionWorker] = None

        self._build_ui()
        self.document = StructureDocument(self.points_model)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(250)

        self._wire()
        self._on_fps_changed(int(self.slider_fps.value()))

        self._set_structure_points(DEFAULT_POINTS, mark_origin=True, clear_undo=True)
        self.view.set_points_xy(self.points_model.get_points())
        self._update_smoothing_limits()
        self._goto("structure")
        self._apply_texts()

        if self._workflow_source_path is not None:
            self._current_path = self._workflow_source_path
        if self._workflow_initial_data is not None:
            self._apply_loaded(self._workflow_initial_data)
        if self._workflow_initial_run_dir is not None:
            self._last_run_dir = self._workflow_initial_run_dir
            self._update_run_dir_label()
            self.btn_open_dir.setEnabled(True)
            self._load_result_frames(self._workflow_initial_run_dir)

        self._apply_workflow_stage()

    # ---------------- i18n helpers ----------------
    def _tr(self, key: str) -> str:
        return tr(key, self.lang)

    def _tf(self, key: str, **kwargs) -> str:
        return self._tr(key).format(**kwargs)

    def _prediction_text(self, key: str, **kwargs) -> str:
        ko = {
            "button": "기존 결과 기반 PARAMETER 예측",
            "busy_title": "파라미터 예측",
            "busy_body": "파라미터 예측이 이미 실행 중입니다.",
            "pre_invalid": "PRE 구조는 최소 2개 점이 필요합니다.",
            "post_invalid": "POST 구조는 최소 2개 점이 필요합니다.",
            "post_smooth_invalid": "POST smoothing 결과는 최소 2개 점이 필요합니다.",
            "running": "기존 결과 기반 파라미터 예측을 준비 중입니다.",
            "progress": "기존 결과 기반 파라미터 예측 중 ({step}/{total})",
            "cancel_requested": "파라미터 예측 취소를 요청했습니다.",
            "complete": "파라미터 예측 완료",
            "complete_loss": "파라미터 예측 완료 (loss={loss:.4f})",
            "canceled": "파라미터 예측이 취소되었습니다.",
            "failed": "파라미터 예측 실패",
            "confirm_title": "예측 파라미터 확인",
            "confirm_body": "아래 예측 파라미터를 현재 Run 설정에 적용할까요?",
            "confirm_apply": "적용",
            "confirm_keep": "현재 값 유지",
            "not_applied": "예측값은 계산되었지만 적용하지 않았습니다.",
            "preview_header": "예측 loss={loss:.4f}, 후보 {count}개 평가",
            "preview_none": "현재 값과 달라지는 파라미터가 없습니다.",
            "preview_group": "[{group}]",
            "preview_enabled": "enabled: {old} -> {new}",
        }
        en = {
            "button": "Predict Parameters From Existing Result",
            "busy_title": "Parameter Prediction",
            "busy_body": "Parameter prediction is already running.",
            "pre_invalid": "The PRE profile must contain at least 2 points.",
            "post_invalid": "The POST profile must contain at least 2 points.",
            "post_smooth_invalid": "The smoothed POST profile must contain at least 2 points.",
            "running": "Preparing parameter prediction from the existing result.",
            "progress": "Running parameter prediction ({step}/{total})",
            "cancel_requested": "Parameter prediction cancel requested.",
            "complete": "Parameter prediction complete",
            "complete_loss": "Parameter prediction complete (loss={loss:.4f})",
            "canceled": "Parameter prediction canceled.",
            "failed": "Parameter prediction failed",
            "confirm_title": "Review Predicted Parameters",
            "confirm_body": "Apply the predicted parameters below to the current Run settings?",
            "confirm_apply": "Apply",
            "confirm_keep": "Keep Current",
            "not_applied": "Prediction finished, but the values were not applied.",
            "preview_header": "Prediction loss={loss:.4f}, evaluated {count} candidates",
            "preview_none": "No parameters differ from the current settings.",
            "preview_group": "[{group}]",
            "preview_enabled": "enabled: {old} -> {new}",
        }
        table = ko if self.lang == "ko" else en
        return table.get(key, key).format(**kwargs)

    # ---------------- UI build ----------------
    def _build_ui(self) -> None:
        self.setWindowTitle(self._tr("app.title"))
        self.resize(1280, 820)

        # actions
        self.act_open = QAction(self)
        self.act_save = QAction(self)
        self.act_save_as = QAction(self)
        self.act_exit = QAction(self)

        self.act_structure = QAction(self)
        self.act_smoothing = QAction(self)
        self.act_run = QAction(self)
        self.act_results = QAction(self)

        self.act_undo = QAction(self)
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_redo = QAction(self)
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])

        self.act_lang_ko = QAction(self)
        self.act_lang_ko.setCheckable(True)
        self.act_lang_en = QAction(self)
        self.act_lang_en.setCheckable(True)
        self._lang_group = QActionGroup(self)
        self._lang_group.addAction(self.act_lang_ko)
        self._lang_group.addAction(self.act_lang_en)

        # menubar
        self.menu_file = self.menuBar().addMenu("")
        self.menu_edit = self.menuBar().addMenu("")
        self.menu_view = self.menuBar().addMenu("")
        self.menu_language = self.menu_view.addMenu("")

        self.menu_file.addAction(self.act_open)
        self.menu_file.addAction(self.act_save)
        self.menu_file.addAction(self.act_save_as)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.act_exit)

        self.menu_edit.addAction(self.act_undo)
        self.menu_edit.addAction(self.act_redo)

        self.menu_view.addAction(self.act_structure)
        self.menu_view.addAction(self.act_smoothing)
        self.menu_view.addAction(self.act_run)
        self.menu_view.addAction(self.act_results)
        self.menu_view.addSeparator()
        self.menu_language.addAction(self.act_lang_ko)
        self.menu_language.addAction(self.act_lang_en)

        # toolbar
        self.tb_top = QToolBar(self)
        self.addToolBar(self.tb_top)
        self.tb_top.setVisible(True)
        self.tb_top.setMovable(False)
        self.tb_top.setFloatable(False)
        self.tb_top.addAction(self.act_structure)
        self.tb_top.addAction(self.act_smoothing)
        self.tb_top.addAction(self.act_run)
        self.tb_top.addAction(self.act_results)

        # shared split
        self.splitter = QSplitter(Qt.Horizontal)
        self.view = StructureView()
        self.splitter.addWidget(self.view)

        self.right_stack = QStackedWidget()
        self.splitter.addWidget(self.right_stack)
        self.right_stack.setMinimumWidth(360)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)

        # -------- Structure panel --------
        self.panel_structure = QWidget()
        s_layout = QVBoxLayout(self.panel_structure)
        self.lbl_structure_help = QLabel()
        s_layout.addWidget(self.lbl_structure_help)

        edit_row = QHBoxLayout()
        self.btn_struct_undo = QPushButton()
        self.btn_struct_redo = QPushButton()
        self.btn_revert_structure = QPushButton()
        edit_row.addWidget(self.btn_struct_undo)
        edit_row.addWidget(self.btn_struct_redo)
        edit_row.addWidget(self.btn_revert_structure)
        edit_row.addStretch(1)
        s_layout.addLayout(edit_row)

        self.points_model = PointsTableModel()
        self.points_table = PointsTableView()
        self.points_table.setModel(self.points_model)
        self.points_table.setMinimumHeight(120)
        self.points_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        s_layout.addWidget(self.points_table, 1)

        overlay_row = QHBoxLayout()
        overlay_btn_col = QVBoxLayout()
        self.btn_load_overlay = QPushButton()
        self.btn_clear_overlay = QPushButton()
        self.btn_move_overlay = QPushButton()
        self.btn_move_overlay.setCheckable(True)
        self.btn_move_overlay.setEnabled(False)
        self.btn_load_overlay.setMinimumWidth(120)
        self.btn_clear_overlay.setMinimumWidth(120)
        self.btn_move_overlay.setMinimumWidth(120)
        overlay_btn_col.addWidget(self.btn_load_overlay)
        overlay_btn_col.addWidget(self.btn_clear_overlay)
        overlay_btn_col.addWidget(self.btn_move_overlay)
        overlay_btn_col.addStretch(1)
        overlay_row.addLayout(overlay_btn_col)
        self.lbl_overlay_opacity_struct = QLabel()
        self.slider_overlay_opacity_struct = QSlider(Qt.Horizontal)
        self.slider_overlay_opacity_struct.setRange(0, 100)
        self.slider_overlay_opacity_struct.setValue(int(round(self._overlay_opacity * 100.0)))
        self.slider_overlay_opacity_struct.setFixedWidth(160)
        overlay_row.addSpacing(8)
        overlay_row.addWidget(self.lbl_overlay_opacity_struct)
        overlay_row.addWidget(self.slider_overlay_opacity_struct)
        overlay_row.addStretch(1)
        s_layout.addLayout(overlay_row)

        struct_next_row = QHBoxLayout()
        self.btn_structure_done = QPushButton()
        self.btn_structure_done.setVisible(False)
        struct_next_row.addStretch(1)
        struct_next_row.addWidget(self.btn_structure_done)
        s_layout.addLayout(struct_next_row)

        # -------- Smoothing panel --------
        self.panel_smoothing = QWidget()
        sm_layout = QVBoxLayout(self.panel_smoothing)
        self.lbl_smoothing_title = QLabel()
        sm_layout.addWidget(self.lbl_smoothing_title)

        sm_controls = QHBoxLayout()
        sm_form = QFormLayout()
        self.lbl_segments = QLabel()
        self.spin_segments = QSpinBox()
        self.spin_segments.setRange(1, 5_000)
        self.spin_segments.setValue(200)
        self._setup_int_editor(self.spin_segments)
        sm_form.addRow(self.lbl_segments, self.spin_segments)

        self.lbl_iters = QLabel()
        self.spin_iters = QSpinBox()
        self.spin_iters.setRange(0, 200)
        self.spin_iters.setValue(5)
        self._setup_int_editor(self.spin_iters)
        sm_form.addRow(self.lbl_iters, self.spin_iters)
        sm_controls.addLayout(sm_form, 1)

        sm_btn_col = QVBoxLayout()
        self.btn_smooth_apply = QPushButton()
        self.btn_smooth_revert = QPushButton()
        self.btn_smoothing_next = QPushButton()
        sm_btn_col.addWidget(self.btn_smooth_apply)
        sm_btn_col.addWidget(self.btn_smooth_revert)
        sm_btn_col.addStretch(1)
        sm_controls.addLayout(sm_btn_col)
        sm_layout.addLayout(sm_controls)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        sm_layout.addWidget(line)

        self.lbl_smoothing_result = QLabel()
        sm_layout.addWidget(self.lbl_smoothing_result)
        self.smooth_model = PointsTableModel()
        self.smooth_table = PointsTableView()
        self.smooth_table.setModel(self.smooth_model)
        self.smooth_table.setEditTriggers(PointsTableView.NoEditTriggers)
        self.smooth_table.setMinimumHeight(120)
        self.smooth_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sm_layout.addWidget(self.smooth_table, 1)

        smoothing_next_row = QHBoxLayout()
        smoothing_next_row.addStretch(1)
        smoothing_next_row.addWidget(self.btn_smoothing_next)
        sm_layout.addLayout(smoothing_next_row)

        # -------- Run panel --------
        self.panel_run = QWidget()
        run_layout = QVBoxLayout(self.panel_run)
        self.lbl_run_title = QLabel()
        run_layout.addWidget(self.lbl_run_title)

        run_meta_widget = QWidget()
        run_meta_form = QFormLayout(run_meta_widget)

        self.lbl_case = QLabel()
        self.edit_case = QLineEdit(self._tr("run.case_default"))
        run_meta_form.addRow(self.lbl_case, self.edit_case)
        self.lbl_run_preset = QLabel()
        preset_row_widget = QWidget()
        preset_row = QVBoxLayout(preset_row_widget)
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(4)
        self.combo_run_preset = QComboBox()
        self.combo_run_preset.setMinimumWidth(200)
        self.combo_run_preset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._setup_enum_editor(self.combo_run_preset)
        self.btn_save_run_preset = QPushButton()
        self.btn_delete_run_preset = QPushButton()
        self.btn_delete_run_preset.setEnabled(False)
        self.btn_save_run_preset.setMinimumWidth(110)
        self.btn_delete_run_preset.setMinimumWidth(90)
        preset_btn_row = QHBoxLayout()
        preset_btn_row.setContentsMargins(0, 0, 0, 0)
        preset_btn_row.addWidget(self.btn_save_run_preset)
        preset_btn_row.addWidget(self.btn_delete_run_preset)
        preset_btn_row.addStretch(1)
        preset_row.addWidget(self.combo_run_preset)
        preset_row.addLayout(preset_btn_row)
        run_meta_form.addRow(self.lbl_run_preset, preset_row_widget)
        self.lbl_run_geometry_source = QLabel()
        run_meta_form.addRow(self.lbl_run_geometry_source)
        run_layout.addWidget(run_meta_widget)

        prediction_row = QHBoxLayout()
        self.btn_parameter_prediction = QPushButton()
        self.btn_parameter_prediction.setMinimumWidth(240)
        prediction_row.addWidget(self.btn_parameter_prediction)
        prediction_row.addStretch(1)
        run_layout.addLayout(prediction_row)

        self.lbl_cycles = QLabel()
        self.spin_cycles = QSpinBox()
        self.spin_cycles.setRange(1, 10_000_000)
        self.spin_cycles.setValue(200)
        self._setup_int_editor(self.spin_cycles)

        self.lbl_dt = QLabel()
        self.spin_dt = QDoubleSpinBox()
        self.spin_dt.setDecimals(3)
        self.spin_dt.setRange(1e-9, 1e9)
        self.spin_dt.setValue(1.0)
        self._setup_float_editor(self.spin_dt)

        self.group_run_advanced = QGroupBox()
        self.group_run_advanced.setCheckable(True)
        self.group_run_advanced.setChecked(False)
        self.group_run_advanced.setVisible(False)
        adv_layout = QVBoxLayout(self.group_run_advanced)

        self.run_advanced_body = QWidget()
        adv_form = QFormLayout(self.run_advanced_body)

        self.lbl_base_rate = QLabel()
        self.spin_rate = QDoubleSpinBox()
        self.spin_rate.setDecimals(3)
        self.spin_rate.setRange(0.0, 1e12)
        self.spin_rate.setValue(1.0)
        self._setup_float_editor(self.spin_rate)
        adv_form.addRow(self.lbl_base_rate, self.spin_rate)

        self.lbl_epsilon = QLabel()
        self.spin_eps = QDoubleSpinBox()
        self.spin_eps.setDecimals(3)
        self.spin_eps.setRange(0.0, 1e12)
        self.spin_eps.setValue(10.0)
        self._setup_float_editor(self.spin_eps)
        adv_form.addRow(self.lbl_epsilon, self.spin_eps)

        self.lbl_sealed_model = QLabel()
        self.combo_sealed_model = QComboBox()
        self.combo_sealed_model.addItem("", "a")
        self.combo_sealed_model.addItem("", "b")
        self._setup_enum_editor(self.combo_sealed_model)
        adv_form.addRow(self.lbl_sealed_model, self.combo_sealed_model)

        self.lbl_decay_k = QLabel()
        self.spin_decay_k = QDoubleSpinBox()
        self.spin_decay_k.setDecimals(3)
        self.spin_decay_k.setRange(0.0, 1e12)
        self.spin_decay_k.setValue(1.0)
        self._setup_float_editor(self.spin_decay_k)
        adv_form.addRow(self.lbl_decay_k, self.spin_decay_k)

        adv_layout.addWidget(self.run_advanced_body)

        overlay_run_row = QHBoxLayout()
        self.lbl_overlay_opacity_run = QLabel()
        self.slider_overlay_opacity_run = QSlider(Qt.Horizontal)
        self.slider_overlay_opacity_run.setRange(0, 100)
        self.slider_overlay_opacity_run.setValue(int(round(self._overlay_opacity * 100.0)))
        self.slider_overlay_opacity_run.setFixedWidth(120)
        overlay_run_row.addWidget(self.lbl_overlay_opacity_run)
        overlay_run_row.addWidget(self.slider_overlay_opacity_run)
        overlay_run_row.addStretch(1)
        run_layout.addLayout(overlay_run_row)

        self.group_switches = QGroupBox()
        switch_layout = QVBoxLayout(self.group_switches)
        switch_layout.setContentsMargins(10, 10, 10, 10)
        switch_layout.setSpacing(10)
        self.switch_toolbox = QToolBox()
        self.switch_toolbox.setStyleSheet("QToolBox::tab { padding: 8px 12px; font-weight: 600; }")
        switch_layout.addWidget(self.switch_toolbox)
        run_layout.addWidget(self.group_switches)

        run_layout.addWidget(self.group_run_advanced)

        self.btn_run = QPushButton()
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_run.setMinimumWidth(170)
        self.btn_stop.setMinimumWidth(90)
        self.lbl_status = QLabel()
        self.lbl_status.setMinimumWidth(0)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_status.setWordWrap(True)
        run_layout.addWidget(self.lbl_status)
        self.progress_run = QProgressBar()
        self.progress_run.setRange(0, 1000)
        self.progress_run.setValue(0)
        self.progress_run.setTextVisible(True)
        self.progress_run.setMinimumHeight(18)
        run_layout.addWidget(self.progress_run)
        run_btn_row = QHBoxLayout()
        run_btn_row.addStretch(1)
        run_btn_row.addWidget(self.btn_run)
        run_btn_row.addWidget(self.btn_stop)
        run_layout.addLayout(run_btn_row)

        self._build_switch_accordion()

        # -------- Results panel --------
        self.panel_results = QWidget()
        res_layout = QVBoxLayout(self.panel_results)
        self.lbl_results_title = QLabel()
        res_layout.addWidget(self.lbl_results_title)

        run_dir_row = QHBoxLayout()
        self.lbl_run_dir = QLabel()
        self.btn_open_dir = QPushButton()
        self.btn_open_dir.setEnabled(False)
        run_dir_row.addWidget(self.lbl_run_dir)
        run_dir_row.addStretch(1)
        run_dir_row.addWidget(self.btn_open_dir)
        res_layout.addLayout(run_dir_row)

        controls_top = QHBoxLayout()
        controls_bottom = QHBoxLayout()
        self.btn_anim_play = QPushButton()
        self.btn_anim_fit = QPushButton()
        self.lbl_next_depo_from = QLabel()
        self.combo_next_depo_from = QComboBox()
        self.combo_next_depo_from.setMinimumWidth(150)
        self.btn_second_depo = QPushButton()
        self.btn_second_depo.setEnabled(False)
        self.btn_export_gif = QPushButton()
        self.chk_show_initial_points = QCheckBox()
        self.chk_show_initial_points.setChecked(True)
        controls_top.addWidget(self.btn_anim_play)
        controls_top.addWidget(self.btn_anim_fit)
        controls_top.addWidget(self.lbl_next_depo_from)
        controls_top.addWidget(self.combo_next_depo_from)
        controls_top.addWidget(self.btn_second_depo)
        controls_top.addWidget(self.btn_export_gif)
        controls_top.addWidget(self.chk_show_initial_points)
        controls_top.addStretch(1)

        self.lbl_fps_title = QLabel()
        controls_bottom.addWidget(self.lbl_fps_title)
        self.slider_fps = QSlider(Qt.Horizontal)
        self.slider_fps.setRange(1, 30)
        self.slider_fps.setValue(5)
        self.slider_fps.setFixedWidth(120)
        self.lbl_fps = QLabel("5")
        controls_bottom.addWidget(self.slider_fps)
        controls_bottom.addWidget(self.lbl_fps)
        controls_bottom.addSpacing(8)
        self.lbl_show_every_title = QLabel()
        controls_bottom.addWidget(self.lbl_show_every_title)
        self.spin_show_every = QSpinBox()
        self.spin_show_every.setRange(1, 10_000)
        self.spin_show_every.setValue(1)
        self.spin_show_every.setFixedWidth(80)
        self._setup_int_editor(self.spin_show_every)
        controls_bottom.addWidget(self.spin_show_every)
        controls_bottom.addSpacing(8)
        self.lbl_decimation_title = QLabel()
        controls_bottom.addWidget(self.lbl_decimation_title)
        self.combo_decimation = QComboBox()
        for stride in (1, 2, 4, 8):
            self.combo_decimation.addItem(f"{stride}x", stride)
        self.combo_decimation.setCurrentIndex(0)
        self.combo_decimation.setFixedWidth(80)
        self._setup_enum_editor(self.combo_decimation)
        controls_bottom.addWidget(self.combo_decimation)
        controls_bottom.addStretch(1)
        res_layout.addLayout(controls_top)
        res_layout.addLayout(controls_bottom)

        self.result_content_splitter = QSplitter(Qt.Horizontal)
        self.result_view = ResultVectorView()
        self.result_view.setMinimumHeight(340)
        self.result_view.setStyleSheet("border: 1px solid #999;")
        self.result_view.set_show_initial_points(self.chk_show_initial_points.isChecked())
        self.result_content_splitter.addWidget(self.result_view)

        self.group_result_params = QGroupBox()
        self.group_result_params.setMinimumWidth(250)
        self.group_result_params.setMaximumWidth(360)
        result_params_layout = QVBoxLayout(self.group_result_params)
        self.edit_result_params = QPlainTextEdit()
        self.edit_result_params.setReadOnly(True)
        self.edit_result_params.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        result_params_layout.addWidget(self.edit_result_params)
        self.result_content_splitter.addWidget(self.group_result_params)
        self.result_content_splitter.setStretchFactor(0, 1)
        self.result_content_splitter.setStretchFactor(1, 0)
        self.result_content_splitter.setSizes([760, 280])
        res_layout.addWidget(self.result_content_splitter, 1)

        frame_row = QHBoxLayout()
        self.lbl_frame_title = QLabel()
        frame_row.addWidget(self.lbl_frame_title)
        self.slider_frame = QSlider(Qt.Horizontal)
        self.slider_frame.setRange(0, 0)
        self.slider_frame.setEnabled(False)
        frame_row.addWidget(self.slider_frame)
        self.lbl_frame = QLabel()
        frame_row.addWidget(self.lbl_frame)
        res_layout.addLayout(frame_row)

        frame_step_row = QHBoxLayout()
        frame_step_row.addStretch(1)
        self.btn_frame_prev = QPushButton()
        self.btn_frame_prev.setFixedWidth(44)
        self.btn_frame_prev.setEnabled(False)
        self.btn_frame_next = QPushButton()
        self.btn_frame_next.setFixedWidth(44)
        self.btn_frame_next.setEnabled(False)
        frame_step_row.addWidget(self.btn_frame_prev)
        frame_step_row.addWidget(self.btn_frame_next)
        frame_step_row.addStretch(1)
        res_layout.addLayout(frame_step_row)

        self.right_stack.addWidget(self._make_right_panel_scroll("structure", self.panel_structure))
        self.right_stack.addWidget(self._make_right_panel_scroll("smoothing", self.panel_smoothing))
        self.right_stack.addWidget(self._make_right_panel_scroll("run", self.panel_run))
        self.right_stack.addWidget(self._make_right_panel_scroll("results", self.panel_results))
        self.right_stack.setCurrentWidget(self._panel_scroll_widgets["structure"])

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.addWidget(self.splitter)
        self.setCentralWidget(root)
        self.splitter.setSizes([920, 320])

    def _setup_int_editor(self, widget: QSpinBox) -> None:
        widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        widget.setKeyboardTracking(False)
        widget.installEventFilter(self._no_wheel_filter)

    def _setup_float_editor(self, widget: QDoubleSpinBox) -> None:
        widget.setDecimals(3)
        widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        widget.setKeyboardTracking(False)
        widget.installEventFilter(self._no_wheel_filter)

    def _setup_enum_editor(self, widget: QComboBox) -> None:
        widget.installEventFilter(self._no_wheel_filter)

    def _make_right_panel_scroll(self, key: str, panel: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        scroll.setWidget(panel)
        self._panel_scroll_widgets[key] = scroll
        return scroll

    def _build_switch_accordion(self) -> None:
        while self.switch_toolbox.count() > 0:
            self.switch_toolbox.removeItem(0)
        self._switch_widgets = {}

        defaults = default_switch_state()
        for sw in PHASE1_SWITCH_SCHEMA:
            sid = str(sw.get("id", ""))
            if not sid:
                continue
            state = self._switch_state.get(sid, defaults.get(sid, {"enabled": False, "params": {}}))
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(14, 14, 14, 14)
            page_layout.setSpacing(12)

            chk_enabled = QCheckBox(self._tr("switch.enabled"))
            chk_enabled.setChecked(bool(state.get("enabled", sw.get("default_enabled", False))))
            page_layout.addWidget(chk_enabled)

            form_host = QWidget()
            form = QFormLayout(form_host)
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(10)
            form.setHorizontalSpacing(14)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            controls: Dict[str, Any] = {}
            param_defs: Dict[str, Dict[str, Any]] = {}
            param_labels: Dict[str, QLabel] = {}
            extras: Dict[str, Any] = {}

            for pdef in sw.get("params", []):
                pid = str(pdef.get("id", ""))
                if not pid:
                    continue
                ptype = str(pdef.get("type", "float"))
                label = QLabel(self._tr(str(pdef.get("label_key", pid))))
                label.setWordWrap(True)
                label.setMinimumWidth(150)
                label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
                tip_key = pdef.get("tooltip_key")
                if isinstance(tip_key, str):
                    tooltip = self._tr(tip_key)
                    label.setToolTip(tooltip)
                else:
                    tooltip = ""

                if ptype == "int":
                    w = QSpinBox()
                    w.setRange(int(pdef.get("min", -1_000_000_000)), int(pdef.get("max", 1_000_000_000)))
                    w.setValue(int(state.get("params", {}).get(pid, pdef.get("default", 0))))
                    self._setup_int_editor(w)
                elif ptype == "bool":
                    w = QCheckBox()
                    w.setChecked(bool(state.get("params", {}).get(pid, pdef.get("default", False))))
                elif ptype == "enum":
                    w = QComboBox()
                    opts = list(pdef.get("options", []))
                    if not opts:
                        opts = [str(pdef.get("default", ""))]
                    for opt in opts:
                        key = f"switch.enum.{opt}"
                        label_txt = self._tr(key)
                        if label_txt == key:
                            label_txt = str(opt)
                        w.addItem(label_txt, str(opt))
                    current = str(state.get("params", {}).get(pid, pdef.get("default", opts[0])))
                    idx = max(0, w.findData(current))
                    w.setCurrentIndex(idx)
                    self._setup_enum_editor(w)
                else:
                    w = QDoubleSpinBox()
                    w.setDecimals(3)
                    w.setRange(float(pdef.get("min", -1e12)), float(pdef.get("max", 1e12)))
                    w.setSingleStep(float(pdef.get("step", 0.1)))
                    w.setValue(float(state.get("params", {}).get(pid, pdef.get("default", 0.0))))
                    self._setup_float_editor(w)

                if ptype != "bool":
                    w.setMinimumWidth(170)
                    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                if tooltip:
                    w.setToolTip(tooltip)
                form.addRow(label, w)
                controls[pid] = w
                param_defs[pid] = dict(pdef)
                param_labels[pid] = label

            if not controls:
                empty = QLabel(self._tr("switch.placeholder"))
                form.addRow(empty)

            if sid == "conformal":
                info_title = QLabel()
                info_value = QLabel()
                info_value.setWordWrap(True)
                info_value.setStyleSheet("color: #555;")
                form.addRow(info_title, info_value)
                extras["reparam_info_title"] = info_title
                extras["reparam_info_value"] = info_value

            page_layout.addWidget(form_host)
            form_host.setEnabled(chk_enabled.isChecked())
            chk_enabled.toggled.connect(form_host.setEnabled)

            self.switch_toolbox.addItem(page, self._tr(str(sw.get("title_key", sid))))
            self._switch_widgets[sid] = {
                "enabled": chk_enabled,
                "form_host": form_host,
                "controls": controls,
                "param_defs": param_defs,
                "param_labels": param_labels,
                "extras": extras,
                "title_key": str(sw.get("title_key", sid)),
            }

        self._sync_switches_from_legacy_run_controls()
        self._sync_legacy_run_controls_from_switches()
        self._refresh_switch_dependency_ui()
        self._update_reparam_preset_ui()
        self.group_switches.setMinimumHeight(self.group_switches.sizeHint().height())

    def _sputter_only_checked(self) -> bool:
        sputter = self._switch_widgets.get("sputter")
        if not sputter:
            return False
        ctrl = sputter.get("controls", {}).get("sputter_only")
        return bool(ctrl.isChecked()) if isinstance(ctrl, QCheckBox) else False

    def _refresh_switch_dependency_ui(self) -> None:
        conformal = self._switch_widgets.get("conformal")
        if not conformal:
            return
        keep_reference_editable = self._sputter_only_checked()
        if keep_reference_editable and conformal["enabled"].isChecked():
            try:
                conformal["enabled"].blockSignals(True)
                conformal["enabled"].setChecked(False)
            finally:
                conformal["enabled"].blockSignals(False)
        conformal["form_host"].setEnabled(bool(conformal["enabled"].isChecked()) or keep_reference_editable)

    def _on_sputter_only_toggled(self, checked: bool) -> None:
        conformal = self._switch_widgets.get("conformal")
        if checked and conformal and conformal["enabled"].isChecked():
            try:
                conformal["enabled"].blockSignals(True)
                conformal["enabled"].setChecked(False)
            finally:
                conformal["enabled"].blockSignals(False)
        self._refresh_switch_dependency_ui()
        self._on_switch_controls_changed()

    def _on_conformal_switch_toggled(self, checked: bool) -> None:
        if checked:
            sputter = self._switch_widgets.get("sputter")
            ctrl = sputter.get("controls", {}).get("sputter_only") if sputter else None
            if isinstance(ctrl, QCheckBox) and ctrl.isChecked():
                try:
                    ctrl.blockSignals(True)
                    ctrl.setChecked(False)
                finally:
                    ctrl.blockSignals(False)
        self._refresh_switch_dependency_ui()
        self._on_switch_controls_changed()

    def _switch_widget_value(self, widget: Any, pdef: Dict[str, Any]) -> Any:
        ptype = str(pdef.get("type", "float"))
        if ptype == "int":
            return int(widget.value())
        if ptype == "bool":
            return bool(widget.isChecked())
        if ptype == "enum":
            data = widget.currentData()
            return str(data) if data is not None else str(widget.currentText())
        return float(widget.value())

    def _set_switch_widget_value(self, widget: Any, pdef: Dict[str, Any], value: Any) -> None:
        ptype = str(pdef.get("type", "float"))
        try:
            widget.blockSignals(True)
            if ptype == "int":
                widget.setValue(int(value))
            elif ptype == "bool":
                widget.setChecked(bool(value))
            elif ptype == "enum":
                idx = widget.findData(str(value))
                widget.setCurrentIndex(max(0, idx))
            else:
                widget.setValue(float(value))
        finally:
            widget.blockSignals(False)

    @staticmethod
    def _polyline_arc_length(points: List[Point]) -> float:
        if len(points) < 2:
            return 0.0
        total = 0.0
        for i in range(len(points) - 1):
            ax, ay = points[i]
            bx, by = points[i + 1]
            total += math.hypot(float(bx) - float(ax), float(by) - float(ay))
        return float(total)

    def _compute_reparam_ds_from_preset(self, preset: str, points: List[Point]) -> float:
        preset_id = str(preset or "manual")
        if preset_id not in REPARAM_PRESET_TARGET_POINTS:
            return 2.5
        arc_len = max(0.0, self._polyline_arc_length(points))
        target_points = REPARAM_PRESET_TARGET_POINTS[preset_id]
        min_a, max_a = REPARAM_PRESET_LIMITS_A[preset_id]
        if arc_len <= 1e-9:
            return float(min_a)
        ds = arc_len / max(1.0, float(target_points))
        return max(float(min_a), min(float(max_a), float(ds)))

    def _update_reparam_preset_ui(self) -> None:
        conformal = self._switch_widgets.get("conformal")
        if not conformal:
            return
        controls = conformal.get("controls", {})
        extras = conformal.get("extras", {})
        preset_ctrl = controls.get("reparam_preset")
        ds_ctrl = controls.get("reparam_ds_a")
        ds_def = conformal.get("param_defs", {}).get("reparam_ds_a", {})
        info_title = extras.get("reparam_info_title")
        info_value = extras.get("reparam_info_value")
        if preset_ctrl is None or ds_ctrl is None:
            return

        preset = str(preset_ctrl.currentData() or "manual")
        manual = preset == "manual"
        form_enabled = bool(conformal["form_host"].isEnabled())
        ds_ctrl.setEnabled(form_enabled and manual)

        if info_title is not None:
            info_title.setText(self._tr("switch.param.reparam_preset"))

        if manual:
            if info_value is not None:
                info_value.setText(self._tr("switch.reparam_manual_info"))
            return

        pts = self._active_profile_points()
        ds_value = self._compute_reparam_ds_from_preset(preset, pts)
        self._set_switch_widget_value(ds_ctrl, ds_def, ds_value)

        if info_value is not None:
            label_key = f"switch.enum.{preset}"
            label_text = self._tr(label_key)
            if label_text == label_key:
                label_text = preset
            info_value.setText(
                self._tf(
                    "switch.reparam_info",
                    arc=self._polyline_arc_length(pts),
                    label=label_text,
                    ds=ds_value,
                )
            )

    def _collect_switch_state(self) -> Dict[str, Dict[str, Any]]:
        self._update_reparam_preset_ui()
        out = default_switch_state()
        for sid, wd in self._switch_widgets.items():
            entry = out.setdefault(sid, {"enabled": False, "params": {}})
            entry["enabled"] = bool(wd["enabled"].isChecked())
            params: Dict[str, Any] = {}
            for pid, ctrl in wd["controls"].items():
                pdef = wd["param_defs"].get(pid, {})
                params[pid] = self._switch_widget_value(ctrl, pdef)
            entry["params"] = params
        return out

    def _apply_switch_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        defaults = default_switch_state()
        merged = defaults
        for sid, val in state.items():
            if not isinstance(val, dict):
                continue
            entry = merged.setdefault(sid, {"enabled": False, "params": {}})
            if "enabled" in val:
                entry["enabled"] = bool(val.get("enabled"))
            params_in = val.get("params")
            if isinstance(params_in, dict):
                for k, v in params_in.items():
                    entry.setdefault("params", {})[str(k)] = v
        self._switch_state = merged

        for sid, wd in self._switch_widgets.items():
            src = merged.get(sid, {"enabled": False, "params": {}})
            wd["enabled"].setChecked(bool(src.get("enabled", False)))
            src_params = src.get("params") or {}
            for pid, ctrl in wd["controls"].items():
                pdef = wd["param_defs"].get(pid, {})
                val = src_params.get(pid, pdef.get("default"))
                self._set_switch_widget_value(ctrl, pdef, val)

        self._refresh_switch_dependency_ui()
        self._update_reparam_preset_ui()
        self._sync_legacy_run_controls_from_switches()

    def _sync_switches_from_legacy_run_controls(self) -> None:
        conformal = self._switch_widgets.get("conformal")
        if not conformal:
            return
        controls = conformal["controls"]
        defs = conformal["param_defs"]
        if "base_rate" in controls:
            self._set_switch_widget_value(controls["base_rate"], defs["base_rate"], self.spin_rate.value())
        if "n_steps" in controls:
            self._set_switch_widget_value(controls["n_steps"], defs["n_steps"], self.spin_cycles.value())

    def _sync_legacy_run_controls_from_switches(self) -> None:
        conformal = self._switch_widgets.get("conformal")
        if not conformal:
            return
        controls = conformal["controls"]
        if "base_rate" in controls:
            self.spin_rate.setValue(float(controls["base_rate"].value()))
        if "n_steps" in controls:
            self.spin_cycles.setValue(int(controls["n_steps"].value()))

    def _on_switch_controls_changed(self, *_args) -> None:
        self._refresh_switch_dependency_ui()
        self._update_reparam_preset_ui()
        self._switch_state = self._collect_switch_state()
        self._sync_legacy_run_controls_from_switches()

    @staticmethod
    def _app_root_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[3]

    @staticmethod
    def _runs_root_dir() -> Path:
        if getattr(sys, "frozen", False):
            return MainWindow._app_root_dir() / "runs"
        return Path("runs")

    def _run_preset_store_path(self) -> Path:
        return self._app_root_dir() / "presets" / "run_presets.json"

    def _load_run_presets(self) -> Dict[str, Dict[str, Any]]:
        path = self._run_preset_store_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        raw = payload.get("presets") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(value, dict):
                continue
            out[key.strip()] = dict(value)
        return dict(sorted(out.items(), key=lambda item: item[0].lower()))

    def _write_run_presets(self, presets: Dict[str, Dict[str, Any]]) -> None:
        path = self._run_preset_store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "presets": presets,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _build_run_preset_payload(self) -> Dict[str, Any]:
        self._switch_state = self._collect_switch_state()
        cycles = int(self.spin_cycles.value())
        return {
            "simulation_name": self.edit_case.text().strip() or self._tr("run.case_default"),
            "cycles": cycles,
            "phase1_switches": self._switch_state,
        }

    def _refresh_run_preset_combo(self, *, select_name: Optional[str] = None) -> None:
        self._run_presets = self._load_run_presets()
        current_name = select_name
        if current_name is None:
            current_name = self.edit_case.text().strip()
        try:
            self.combo_run_preset.blockSignals(True)
            self.combo_run_preset.clear()
            self.combo_run_preset.addItem(self._tr("run.preset_placeholder"), "")
            for name in self._run_presets.keys():
                self.combo_run_preset.addItem(name, name)
            idx = self.combo_run_preset.findData(current_name)
            self.combo_run_preset.setCurrentIndex(max(0, idx))
        finally:
            self.combo_run_preset.blockSignals(False)
        has_selected = bool(self.combo_run_preset.currentData())
        self.btn_delete_run_preset.setEnabled(has_selected)

    def _apply_run_preset_by_name(self, name: str) -> None:
        preset = self._run_presets.get(name)
        if not isinstance(preset, dict):
            return
        self.edit_case.setText(str(preset.get("simulation_name") or name))
        try:
            self.spin_cycles.setValue(max(1, int(preset.get("cycles", self.spin_cycles.value()))))
        except Exception:
            pass
        switches = preset.get("phase1_switches")
        if isinstance(switches, dict):
            self._apply_switch_state(switches)
        self._refresh_run_preset_combo(select_name=name)

    def _on_run_preset_activated(self, index: int) -> None:
        name = str(self.combo_run_preset.itemData(index) or "").strip()
        if not name:
            self.btn_delete_run_preset.setEnabled(False)
            return
        self._apply_run_preset_by_name(name)

    def _save_current_run_preset(self) -> None:
        name = self.edit_case.text().strip()
        if not name:
            QMessageBox.warning(self, self._tr("dialog.preset_invalid.title"), self._tr("dialog.preset_invalid.body"))
            return
        presets = self._load_run_presets()
        if name in presets:
            reply = QMessageBox.question(
                self,
                self._tr("dialog.preset_overwrite.title"),
                self._tf("dialog.preset_overwrite.body", name=name),
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        presets[name] = self._build_run_preset_payload()
        self._write_run_presets(presets)
        self._refresh_run_preset_combo(select_name=name)
        self.statusBar().showMessage(self._tf("status.preset_saved", name=name), 2500)

    def _delete_selected_run_preset(self) -> None:
        name = str(self.combo_run_preset.currentData() or "").strip()
        if not name:
            return
        reply = QMessageBox.question(
            self,
            self._tr("dialog.preset_delete.title"),
            self._tf("dialog.preset_delete.body", name=name),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        presets = self._load_run_presets()
        if name in presets:
            presets.pop(name, None)
            self._write_run_presets(presets)
        self._refresh_run_preset_combo(select_name=self.edit_case.text().strip())
        self.statusBar().showMessage(self._tf("status.preset_deleted", name=name), 2500)

    # ---------------- wiring ----------------
    def _wire(self) -> None:
        self.act_open.triggered.connect(self._open)
        self.act_save.triggered.connect(self._save)
        self.act_save_as.triggered.connect(self._save_as)
        self.act_exit.triggered.connect(self.close)

        self.act_structure.triggered.connect(lambda: self._goto("structure"))
        self.act_smoothing.triggered.connect(lambda: self._goto("smoothing"))
        self.act_run.triggered.connect(lambda: self._goto("run"))
        self.act_results.triggered.connect(lambda: self._goto("results"))

        self.act_undo.triggered.connect(self._undo)
        self.act_redo.triggered.connect(self._redo)
        self.btn_struct_undo.clicked.connect(self._undo)
        self.btn_struct_redo.clicked.connect(self._redo)
        self.btn_revert_structure.clicked.connect(self._revert_structure_to_origin)
        self.btn_structure_done.clicked.connect(self._open_smoothing_window)
        self.btn_load_overlay.clicked.connect(self._load_overlay_image)
        self.btn_clear_overlay.clicked.connect(self._clear_overlay_image)
        self.btn_move_overlay.toggled.connect(self._on_overlay_move_toggled)
        self.slider_overlay_opacity_struct.valueChanged.connect(self._on_overlay_opacity_changed_from_structure)

        self.act_lang_ko.triggered.connect(lambda: self._set_language("ko"))
        self.act_lang_en.triggered.connect(lambda: self._set_language("en"))

        self.group_run_advanced.toggled.connect(self._on_run_advanced_toggled)
        self._on_run_advanced_toggled(self.group_run_advanced.isChecked())
        self.spin_rate.valueChanged.connect(self._sync_switches_from_legacy_run_controls)
        self.spin_cycles.valueChanged.connect(self._sync_switches_from_legacy_run_controls)
        self.edit_case.textChanged.connect(lambda _text: self._refresh_run_preset_combo())
        self.combo_run_preset.activated.connect(self._on_run_preset_activated)
        self.btn_save_run_preset.clicked.connect(self._save_current_run_preset)
        self.btn_delete_run_preset.clicked.connect(self._delete_selected_run_preset)

        # model -> view sync
        self.points_model.dataChanged.connect(self._sync_view_from_model)
        self.points_model.modelReset.connect(self._sync_view_from_model)
        self.points_model.rowsRemoved.connect(self._sync_view_from_model)
        self.points_model.rowsInserted.connect(self._sync_view_from_model)

        # table edit requests
        self.points_model.pointEditRequested.connect(self._on_table_point_edit_requested)
        self.points_table.deleteRowsRequested.connect(self._on_table_delete_rows_requested)
        self.points_table.replacePointsRequested.connect(self._on_table_replace_points_requested)

        # view -> model live updates
        self.view.pointDragStarted.connect(self._on_view_drag_started)
        self.view.pointMoved.connect(self._on_view_point_moved)
        self.view.pointDragFinished.connect(self._on_view_drag_finished)
        self.view.pointInserted.connect(self._on_view_point_inserted)
        self.view.pointDeleted.connect(self._on_view_point_deleted)

        self.undo_stack.canUndoChanged.connect(lambda _v: self._update_structure_edit_actions())
        self.undo_stack.canRedoChanged.connect(lambda _v: self._update_structure_edit_actions())
        self.document.pointsChanged.connect(self._on_document_points_changed)

        # smoothing
        self.btn_smooth_apply.clicked.connect(self._do_smoothing)
        self.btn_smooth_revert.clicked.connect(self._revert_smoothing)
        self.btn_smoothing_next.clicked.connect(self._open_run_window)

        # run / result
        self.btn_parameter_prediction.clicked.connect(self._open_parameter_prediction_flow)
        self.btn_run.clicked.connect(self._engine_run)
        self.btn_stop.clicked.connect(self._engine_stop)
        self.btn_open_dir.clicked.connect(self._open_run_dir)
        self.btn_anim_play.clicked.connect(self._toggle_animation)
        self.btn_anim_fit.clicked.connect(self._fit_snapshot)
        self.btn_second_depo.clicked.connect(self._start_second_depo)
        self.btn_export_gif.clicked.connect(self._export_animation_gif)
        self.chk_show_initial_points.toggled.connect(self._on_show_initial_points_toggled)
        self.slider_frame.valueChanged.connect(self._on_frame_changed)
        self.btn_frame_prev.clicked.connect(lambda: self._step_frame_by(-1))
        self.btn_frame_next.clicked.connect(lambda: self._step_frame_by(1))
        self.slider_fps.valueChanged.connect(self._on_fps_changed)
        self.spin_show_every.valueChanged.connect(self._on_show_every_changed)
        self.combo_decimation.currentIndexChanged.connect(self._on_decimation_changed)
        self.slider_overlay_opacity_run.valueChanged.connect(self._on_overlay_opacity_changed_from_run)
        self._anim_timer.timeout.connect(self._advance_frame)

        for sid, wd in self._switch_widgets.items():
            wd["enabled"].toggled.connect(self._on_switch_controls_changed)
            for ctrl in wd["controls"].values():
                if isinstance(ctrl, QSpinBox):
                    ctrl.valueChanged.connect(self._on_switch_controls_changed)
                elif isinstance(ctrl, QDoubleSpinBox):
                    ctrl.valueChanged.connect(self._on_switch_controls_changed)
                elif isinstance(ctrl, QComboBox):
                    ctrl.currentIndexChanged.connect(self._on_switch_controls_changed)
                elif isinstance(ctrl, QCheckBox):
                    ctrl.toggled.connect(self._on_switch_controls_changed)

        conformal_wd = self._switch_widgets.get("conformal")
        if conformal_wd:
            conformal_wd["enabled"].toggled.connect(self._on_conformal_switch_toggled)
        sputter_wd = self._switch_widgets.get("sputter")
        if sputter_wd:
            sputter_only_ctrl = sputter_wd.get("controls", {}).get("sputter_only")
            if isinstance(sputter_only_ctrl, QCheckBox):
                sputter_only_ctrl.toggled.connect(self._on_sputter_only_toggled)

        self._on_switch_controls_changed()
        self._refresh_run_preset_combo()

    # ---------------- text refresh ----------------
    def _apply_texts(self) -> None:
        self.setWindowTitle(self._tr("app.title"))
        self.tb_top.setWindowTitle(self._tr("toolbar.top"))

        self.menu_file.setTitle(self._tr("menu.file"))
        self.menu_edit.setTitle(self._tr("menu.edit"))
        self.menu_view.setTitle(self._tr("menu.view"))
        self.menu_language.setTitle(self._tr("menu.language"))

        self.act_open.setText(self._tr("menu.open"))
        self.act_save.setText(self._tr("menu.save"))
        self.act_save_as.setText(self._tr("menu.save_as"))
        self.act_exit.setText(self._tr("menu.exit"))
        self.act_structure.setText(self._tr("tab.structure"))
        self.act_smoothing.setText(self._tr("tab.smoothing"))
        self.act_run.setText(self._tr("tab.run"))
        self.act_results.setText(self._tr("tab.results"))
        self.act_undo.setText(self._tr("btn.undo"))
        self.act_redo.setText(self._tr("btn.redo"))

        self.act_lang_ko.setText(self._tr("menu.lang_ko"))
        self.act_lang_en.setText(self._tr("menu.lang_en"))
        self.act_lang_ko.setChecked(self.lang == "ko")
        self.act_lang_en.setChecked(self.lang == "en")

        self.lbl_structure_help.setText(self._tr("structure.title"))
        self.btn_struct_undo.setText(self._tr("btn.undo"))
        self.btn_struct_redo.setText(self._tr("btn.redo"))
        self.btn_revert_structure.setText(self._tr("btn.revert_structure"))
        self.btn_structure_done.setText(self._tr("workflow.structure_done"))
        self.btn_load_overlay.setText(self._tr("overlay.load_image"))
        self.btn_clear_overlay.setText(self._tr("overlay.clear_image"))
        self.btn_move_overlay.setText(self._tr("overlay.move_toggle"))
        self.lbl_overlay_opacity_struct.setText(self._tr("overlay.opacity"))

        self.lbl_smoothing_title.setText(self._tr("smoothing.title"))
        self.lbl_segments.setText(self._tr("smoothing.segments"))
        self.lbl_iters.setText(self._tr("smoothing.iterations"))
        self.btn_smooth_apply.setText(self._tr("smoothing.apply"))
        self.btn_smooth_revert.setText(self._tr("smoothing.revert"))
        self.btn_smoothing_next.setText(self._tr("workflow.smoothing_next"))
        self.lbl_smoothing_result.setText(self._tr("smoothing.result"))

        self.lbl_run_title.setText(self._tr("run.title"))
        self.group_switches.setTitle(self._tr("run.switches"))
        self.group_run_advanced.setTitle(self._tr("run.advanced"))
        self.btn_parameter_prediction.setText(self._prediction_text("button"))
        self.lbl_case.setText(self._tr("run.case_name"))
        self.lbl_run_preset.setText(self._tr("run.preset"))
        self.btn_save_run_preset.setText(self._tr("run.preset_save"))
        self.btn_delete_run_preset.setText(self._tr("run.preset_delete"))
        self.lbl_cycles.setText(self._tr("run.cycles"))
        self.lbl_dt.setText(self._tr("run.dt"))
        self.lbl_base_rate.setText(self._tr("run.base_rate"))
        self.lbl_epsilon.setText(self._tr("run.epsilon"))
        self.lbl_sealed_model.setText(self._tr("run.sealed_model"))
        self.lbl_decay_k.setText(self._tr("run.decay_k"))
        self.combo_sealed_model.setItemText(0, self._tr("run.sealed_model_a"))
        self.combo_sealed_model.setItemText(1, self._tr("run.sealed_model_b"))
        self.btn_run.setText(self._tr("run.start"))
        self.btn_stop.setText(self._tr("run.stop"))
        self.lbl_overlay_opacity_run.setText(self._tr("overlay.opacity"))
        self._refresh_run_preset_combo()

        self.lbl_results_title.setText(self._tr("results.title"))
        self.group_result_params.setTitle(self._tr("results.parameters"))
        self.btn_open_dir.setText(self._tr("results.open_folder"))
        self.btn_anim_fit.setText(self._tr("results.fit"))
        self.lbl_next_depo_from.setText(self._tr("results.next_depo_from"))
        self.btn_export_gif.setText(self._tr("results.export_gif"))
        self.chk_show_initial_points.setText(self._tr("results.show_initial_points"))
        self.lbl_fps_title.setText(self._tr("results.fps"))
        self.lbl_show_every_title.setText(self._tr("results.show_every_n"))
        self.lbl_decimation_title.setText(self._tr("results.decimation"))
        for i in range(self.combo_decimation.count()):
            stride = int(self.combo_decimation.itemData(i) or 1)
            self.combo_decimation.setItemText(i, self._tf("results.decimation_item", n=stride))
        self.lbl_frame_title.setText(self._tr("results.frame"))
        self.btn_frame_prev.setText("<")
        self.btn_frame_next.setText(">")
        self._update_run_dir_label()
        self._update_result_parameter_view()

        for page_idx, sw in enumerate(PHASE1_SWITCH_SCHEMA):
            sid = str(sw.get("id", ""))
            wd = self._switch_widgets.get(sid)
            if wd is None:
                continue
            self.switch_toolbox.setItemText(page_idx, self._tr(str(wd.get("title_key", sid))))
            wd["enabled"].setText(self._tr("switch.enabled"))
            for pid, lbl in wd["param_labels"].items():
                pdef = wd["param_defs"].get(pid, {})
                lbl.setText(self._tr(str(pdef.get("label_key", pid))))
                tip_key = pdef.get("tooltip_key")
                if isinstance(tip_key, str):
                    tip_text = self._tr(tip_key)
                    lbl.setToolTip(tip_text)
                    wd["controls"][pid].setToolTip(tip_text)
                if str(pdef.get("type", "")) == "enum":
                    ctrl = wd["controls"][pid]
                    opts = list(pdef.get("options", []))
                    for oi, opt in enumerate(opts):
                        key = f"switch.enum.{opt}"
                        label_txt = self._tr(key)
                        if label_txt == key:
                            label_txt = str(opt)
                        ctrl.setItemText(oi, label_txt)

        self._update_reparam_preset_ui()
        self._update_run_dir_label()
        self._update_run_geometry_source_label()
        self._render_run_status()
        self._refresh_anim_button_text()
        if not self._result_frames:
            if self._result_loading:
                self.lbl_frame.setText(self._tr("results.loading"))
            elif self._last_run_dir is not None:
                self.lbl_frame.setText(self._tr("results.no_vector"))
            else:
                self.lbl_frame.setText(self._tr("results.frame_empty"))
        elif self._frame_index >= 0:
            self._show_frame(self._frame_index, fit=False)

        self._apply_tooltips()
        self._update_overlay_move_button_state()
        self._update_structure_edit_actions()
        self._update_stage_visibility_controls()
        if self._is_workflow_mode():
            self._apply_workflow_stage()

    def _apply_tooltips(self) -> None:
        self.lbl_dt.setToolTip(self._tr("tip.dt"))
        self.spin_dt.setToolTip(self._tr("tip.dt"))

        self.lbl_base_rate.setToolTip(self._tr("tip.base_rate"))
        self.spin_rate.setToolTip(self._tr("tip.base_rate"))
        self.lbl_epsilon.setToolTip(self._tr("tip.epsilon"))
        self.spin_eps.setToolTip(self._tr("tip.epsilon"))
        self.lbl_sealed_model.setToolTip(self._tr("tip.sealed_model"))
        self.combo_sealed_model.setToolTip(
            f"{self._tr('tip.sealed_model_a')}\n{self._tr('tip.sealed_model_b')}"
        )
        self.lbl_decay_k.setToolTip(self._tr("tip.decay_k"))
        self.spin_decay_k.setToolTip(self._tr("tip.decay_k"))

    def _set_language(self, lang: str) -> None:
        if lang not in ("ko", "en"):
            return
        if self.lang == lang:
            return
        self.lang = lang
        self._apply_texts()

    def _is_workflow_mode(self) -> bool:
        return self._workflow_stage in {"structure", "smoothing", "run", "results"}

    def _spawn_workflow_window(
        self,
        stage: str,
        *,
        initial_data: Optional[Dict[str, Any]] = None,
        source_path: Optional[Path] = None,
        initial_run_dir: Optional[Path] = None,
    ) -> None:
        if self._workflow_spawn is not None:
            self._workflow_spawn(
                stage,
                initial_data,
                source_path,
                initial_run_dir,
                self.lang,
            )
            return
        child = MainWindow(
            workflow_stage=stage,
            initial_data=initial_data,
            source_path=source_path,
            initial_run_dir=initial_run_dir,
            workflow_spawn=self._workflow_spawn,
        )
        if self.lang != "ko":
            child._set_language(self.lang)
        child.show()
        self._workflow_windows.append(child)

    def _open_smoothing_window(self) -> None:
        self._goto("smoothing")

    def _open_run_window(self) -> None:
        self._goto("run")

    def _apply_workflow_stage(self) -> None:
        self.menuBar().setVisible(True)
        self.tb_top.setVisible(True)
        self.act_structure.setEnabled(True)
        self.act_smoothing.setEnabled(True)
        self.act_run.setEnabled(True)
        self.act_results.setEnabled(True)

        if not self._is_workflow_mode():
            return
        stage = str(self._workflow_stage)
        if stage in {"structure", "smoothing", "run", "results"}:
            self._goto(stage)
        self._workflow_stage = None
        self.setWindowTitle(self._tr("app.title"))

    # ---------------- navigation ----------------
    def _goto(self, where: str) -> None:
        self.btn_structure_done.setVisible(False)
        self.btn_smoothing_next.setVisible(False)
        if where == "structure":
            self._clear_continuation_context(clear_base=True)
            self.view.setVisible(True)
            self.view.set_point_radius_px(4)
            self.view.set_reference_profiles_xy([])
            self.view.set_points_xy(self.points_model.get_points())
            self.view.fit_points()
            self.btn_structure_done.setVisible(True)
            self.right_stack.setCurrentWidget(self._panel_scroll_widgets["structure"])
        elif where == "smoothing":
            self._clear_continuation_context(clear_base=True)
            self.view.setVisible(True)
            self.view.set_point_radius_px(1)
            self.view.set_reference_profiles_xy([])
            base = self.points_model.get_points()
            self.smoothing.set_base_points(base)
            self.view.set_points_xy(base)
            self.view.fit_points()
            self._update_smoothing_limits()
            self.smooth_model.set_points([])
            self.btn_smoothing_next.setVisible(True)
            self.right_stack.setCurrentWidget(self._panel_scroll_widgets["smoothing"])
        elif where == "run":
            self.view.setVisible(True)
            self.view.set_reference_profiles_xy(self._continuation_reference_profiles())
            pts = self._active_profile_points()
            self.view.set_points_xy(pts)
            self.view.set_point_radius_px(1 if len(pts) > 200 else 4)
            self._update_run_geometry_source_label()
            self.right_stack.setCurrentWidget(self._panel_scroll_widgets["run"])
            self.view.fit_points()
            QTimer.singleShot(0, self._fit_current_non_result_view)
        elif where == "results":
            self.view.setVisible(False)
            self.right_stack.setCurrentWidget(self._panel_scroll_widgets["results"])
            self._refresh_result_view()

        self._update_structure_edit_actions()

    def _fit_current_non_result_view(self) -> None:
        if self.right_stack.currentWidget() in (
            self._panel_scroll_widgets.get("structure"),
            self._panel_scroll_widgets.get("smoothing"),
            self._panel_scroll_widgets.get("run"),
        ):
            self.view.fit_points()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not hasattr(self, "_did_initial_fit_after_show"):
            self._did_initial_fit_after_show = True
            QTimer.singleShot(0, self._fit_current_non_result_view)

    # ---------------- structure edit + undo ----------------
    def _is_structure_panel_active(self) -> bool:
        return self.right_stack.currentWidget() is self._panel_scroll_widgets.get("structure")

    def _set_structure_points(self, pts: List[Point], *, mark_origin: bool, clear_undo: bool) -> None:
        self.document.set_points([(float(x), float(y)) for x, y in pts])
        self._clear_cached_geometry_final()
        if mark_origin:
            self._structure_origin = [(float(x), float(y)) for x, y in pts]
        if clear_undo:
            self.undo_stack.clear()
        self._drag_start = None
        self._update_run_geometry_source_label()
        self._update_structure_edit_actions()

    def _sync_view_from_model(self) -> None:
        if self._model_change_from_view:
            return
        self.view.set_points_xy(self.points_model.get_points())
        self._update_smoothing_limits()
        self._update_structure_edit_actions()

    def _on_document_points_changed(self) -> None:
        self._invalidate_cached_geometry_if_needed()
        self._update_run_geometry_source_label()
        self._update_structure_edit_actions()

    def _on_view_drag_started(self, idx: int, x: float, y: float) -> None:
        pts = self.points_model.get_points()
        if 0 <= idx < len(pts):
            self._drag_start = (idx, pts[idx])
        else:
            self._drag_start = None

    def _on_view_point_moved(self, idx: int, x: float, y: float) -> None:
        pts = self.points_model.get_points()
        if not (0 <= idx < len(pts)):
            return
        self._model_change_from_view = True
        try:
            self.points_model.set_point(idx, (x, y))
        finally:
            self._model_change_from_view = False

    def _on_view_drag_finished(self, idx: int, x: float, y: float) -> None:
        pts = self.points_model.get_points()
        if not (0 <= idx < len(pts)):
            self._drag_start = None
            return
        old = None
        if self._drag_start is not None and self._drag_start[0] == idx:
            old = self._drag_start[1]
        self._drag_start = None
        if old is None:
            old = (float(x), float(y))
        new = pts[idx]
        self.view.set_points_xy(pts)
        if abs(old[0] - new[0]) <= 1e-12 and abs(old[1] - new[1]) <= 1e-12:
            return
        self.undo_stack.push(MovePointCommand(self.document, idx, old, new, applied=True))
        self._update_structure_edit_actions()

    def _on_view_point_inserted(self, idx: int, x: float, y: float) -> None:
        pts = self.points_model.get_points()
        if not (0 <= idx <= len(pts)):
            return

        self._model_change_from_view = True
        try:
            ok = self.points_model.insert_point(idx, (x, y))
        finally:
            self._model_change_from_view = False
        if not ok:
            return

        self.view.set_points_xy(self.points_model.get_points())
        self.undo_stack.push(InsertPointCommand(self.document, idx, (x, y), applied=True))
        self._update_smoothing_limits()
        self._update_structure_edit_actions()

    def _on_view_point_deleted(self, idx: int) -> None:
        pts = self.points_model.get_points()
        if not (0 <= idx < len(pts)):
            return
        point = pts[idx]

        self._model_change_from_view = True
        try:
            removed = self.points_model.delete_point(idx)
        finally:
            self._model_change_from_view = False
        if removed is None:
            return

        self.view.set_points_xy(self.points_model.get_points())
        self.undo_stack.push(DeletePointCommand(self.document, idx, point, applied=True))
        self._update_smoothing_limits()
        self._update_structure_edit_actions()

    def _on_table_point_edit_requested(self, row: int, x: float, y: float) -> None:
        pts = self.points_model.get_points()
        if not (0 <= row < len(pts)):
            return
        old = pts[row]
        new = (float(x), float(y))
        if abs(old[0] - new[0]) <= 1e-12 and abs(old[1] - new[1]) <= 1e-12:
            return
        self.undo_stack.push(MovePointCommand(self.document, row, old, new, applied=False))
        self._update_structure_edit_actions()

    def _on_table_delete_rows_requested(self, rows: List[int]) -> None:
        pts = self.points_model.get_points()
        if not pts:
            return
        targets = [r for r in sorted(set(rows), reverse=True) if 0 < r < (len(pts) - 1)]
        if not targets:
            return

        self.undo_stack.beginMacro("Delete points")
        try:
            for r in targets:
                current = self.points_model.get_points()
                if not (0 < r < (len(current) - 1)):
                    continue
                self.undo_stack.push(DeletePointCommand(self.document, r, current[r], applied=False))
        finally:
            self.undo_stack.endMacro()
        self._update_structure_edit_actions()

    def _on_table_replace_points_requested(self, new_points: List[Point]) -> None:
        if len(new_points) < 2:
            return
        old = self.points_model.get_points()
        new = [(float(x), float(y)) for x, y in new_points]
        if old == new:
            return
        self.undo_stack.push(SetPointsCommand(self.document, old, new, applied=False))
        self._update_structure_edit_actions()

    def _undo(self) -> None:
        if not self._is_structure_panel_active():
            return
        if self.undo_stack.canUndo():
            self.undo_stack.undo()

    def _redo(self) -> None:
        if not self._is_structure_panel_active():
            return
        if self.undo_stack.canRedo():
            self.undo_stack.redo()

    def _revert_structure_to_origin(self) -> None:
        self._set_structure_points(list(self._structure_origin), mark_origin=False, clear_undo=True)

    def _update_structure_edit_actions(self) -> None:
        in_structure = self._is_structure_panel_active()
        can_undo = in_structure and self.undo_stack.canUndo()
        can_redo = in_structure and self.undo_stack.canRedo()
        can_revert = in_structure and (self.points_model.get_points() != self._structure_origin)

        self.act_undo.setEnabled(can_undo)
        self.act_redo.setEnabled(can_redo)
        self.btn_struct_undo.setEnabled(can_undo)
        self.btn_struct_redo.setEnabled(can_redo)
        self.btn_revert_structure.setEnabled(can_revert)

    def _set_overlay_opacity(self, opacity: float) -> None:
        clamped = max(0.0, min(1.0, float(opacity)))
        self._overlay_opacity = clamped
        v = int(round(clamped * 100.0))
        for slider in (self.slider_overlay_opacity_struct, self.slider_overlay_opacity_run):
            try:
                slider.blockSignals(True)
                slider.setValue(v)
            finally:
                slider.blockSignals(False)
        self.view.set_overlay_opacity(clamped)

    def _on_overlay_opacity_changed_from_structure(self, value: int) -> None:
        self._set_overlay_opacity(float(value) / 100.0)

    def _on_overlay_opacity_changed_from_run(self, value: int) -> None:
        self._set_overlay_opacity(float(value) / 100.0)

    def _update_overlay_move_button_state(self) -> None:
        has_overlay = self.view.get_overlay_state() is not None
        self.btn_move_overlay.setEnabled(has_overlay)
        if not has_overlay and self.btn_move_overlay.isChecked():
            try:
                self.btn_move_overlay.blockSignals(True)
                self.btn_move_overlay.setChecked(False)
            finally:
                self.btn_move_overlay.blockSignals(False)
        self.view.set_overlay_drag_enabled(has_overlay and self.btn_move_overlay.isChecked())

    def _on_overlay_move_toggled(self, checked: bool) -> None:
        has_overlay = self.view.get_overlay_state() is not None
        if not has_overlay and checked:
            try:
                self.btn_move_overlay.blockSignals(True)
                self.btn_move_overlay.setChecked(False)
            finally:
                self.btn_move_overlay.blockSignals(False)
            return
        self.view.set_overlay_drag_enabled(has_overlay and bool(checked))
        if has_overlay:
            self.statusBar().showMessage(
                self._tr("status.overlay_move_on") if checked else self._tr("status.overlay_move_off"),
                1500,
            )

    def _apply_overlay_payload(self, payload: Optional[Dict[str, Any]]) -> None:
        if not isinstance(payload, dict):
            return
        image_path = payload.get("image_path")
        if not image_path:
            return
        p = Path(str(image_path))
        if not p.exists():
            self.statusBar().showMessage(
                self._tf("status.overlay_missing", path=str(p)),
                4000,
            )
            return
        scale = float(payload.get("scale_a_per_px", 1.0))
        opacity = float(payload.get("opacity", self._overlay_opacity))
        align_to_axes = bool(payload.get("align_to_axes", True))
        ox = payload.get("origin_x")
        oy = payload.get("origin_y")
        ok = self.view.set_overlay_image(
            str(p),
            scale_a_per_px=scale,
            opacity=opacity,
            origin_x=float(ox) if ox is not None else None,
            origin_y=float(oy) if oy is not None else None,
            align_to_axes=align_to_axes,
        )
        if not ok:
            self.statusBar().showMessage(self._tr("status.overlay_load_failed"), 4000)
            return
        self._overlay_path = str(p)
        self._overlay_scale_a_per_px = scale
        self._set_overlay_opacity(opacity)
        self._update_overlay_move_button_state()
        self.statusBar().showMessage(self._tr("status.overlay_loaded"), 2000)

    def _load_overlay_image(self, _checked: bool = False) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("overlay.load_image"),
            "",
            self._tr("dialog.image_filter"),
        )
        if not path:
            return
        p = Path(path)
        dlg = CalibrateDialog(p, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        scale = dlg.scale_a_per_px
        if scale is None or scale <= 0.0:
            QMessageBox.warning(self, self._tr("dialog.overlay.title"), self._tr("dialog.overlay.invalid_scale"))
            return
        ok = self.view.set_overlay_image(
            str(p),
            scale_a_per_px=scale,
            opacity=self._overlay_opacity,
            align_to_axes=True,
        )
        if not ok:
            QMessageBox.warning(self, self._tr("dialog.overlay.title"), self._tr("dialog.overlay.load_failed"))
            return
        self._overlay_path = str(p)
        self._overlay_scale_a_per_px = float(scale)
        self._update_overlay_move_button_state()
        self.statusBar().showMessage(self._tr("status.overlay_loaded"), 2000)

    def _clear_overlay_image(self, silent: bool = False) -> None:
        self.view.clear_overlay_image()
        self._overlay_path = None
        self._update_overlay_move_button_state()
        if not silent:
            self.statusBar().showMessage(self._tr("status.overlay_cleared"), 1500)

    def _set_cached_geometry_final(self, pts: List[Point], base_pts: List[Point]) -> None:
        if len(pts) < 2:
            self._cached_geometry_final = None
            self._cached_geometry_base = None
            return
        self._cached_geometry_final = [(float(x), float(y)) for x, y in pts]
        self._cached_geometry_base = [(float(x), float(y)) for x, y in base_pts]

    def _clear_cached_geometry_final(self) -> None:
        self._cached_geometry_final = None
        self._cached_geometry_base = None

    def _invalidate_cached_geometry_if_needed(self) -> None:
        if self._cached_geometry_final is None or self._cached_geometry_base is None:
            return
        if list(self.points_model.get_points()) != list(self._cached_geometry_base):
            self._clear_cached_geometry_final()

    def _active_profile_with_source(self) -> Tuple[List[Point], str]:
        if self._continuation_seed_points and len(self._continuation_seed_points) >= 2:
            return list(self._continuation_seed_points), "continued"

        structure_pts = list(self.points_model.get_points())
        last = self.smoothing.state.last_result
        base = self.smoothing.state.base_points
        if last and len(last) >= 2 and base and list(base) == structure_pts:
            return list(last), "smoothing"
        if (
            self._cached_geometry_final
            and len(self._cached_geometry_final) >= 2
            and self._cached_geometry_base
            and list(self._cached_geometry_base) == structure_pts
        ):
            return list(self._cached_geometry_final), "saved"
        return structure_pts, "structure"

    def _update_run_geometry_source_label(self) -> None:
        pts, src = self._active_profile_with_source()
        src_txt = self._tr(f"run.geometry_source.{src}")
        self.lbl_run_geometry_source.setText(
            self._tf("run.geometry_source", source=src_txt, n=len(pts))
        )
        self._update_reparam_preset_ui()

    # ---------------- smoothing ----------------
    def _smoothing_caps(self) -> Tuple[int, int]:
        n = max(len(self.points_model.get_points()), 2)
        seg_cap = max(200, min(5000, n * 300))
        iter_cap = max(10, min(200, 6000 // n))
        return int(seg_cap), int(iter_cap)

    def _update_smoothing_limits(self) -> Tuple[int, int, bool]:
        seg_cap, iter_cap = self._smoothing_caps()
        prev_seg = int(self.spin_segments.value())
        prev_it = int(self.spin_iters.value())
        self.spin_segments.setRange(1, seg_cap)
        self.spin_iters.setRange(0, iter_cap)
        clamped = (int(self.spin_segments.value()) != prev_seg) or (int(self.spin_iters.value()) != prev_it)
        return seg_cap, iter_cap, clamped

    def _do_smoothing(self) -> None:
        seg_cap, iter_cap, clamped = self._update_smoothing_limits()
        if clamped:
            QMessageBox.warning(
                self,
                self._tr("dialog.smoothing_limit.title"),
                self._tf("dialog.smoothing_limit.body", seg_cap=seg_cap, iter_cap=iter_cap),
            )

        base = self.points_model.get_points()
        self.smoothing.set_base_points(base)
        self.smoothing.set_params(self.spin_segments.value(), self.spin_iters.value())
        out = self.smoothing.run()
        self.smooth_model.set_points(out)
        self.view.set_points_xy(out)
        self.view.set_point_radius_px(1)
        self._set_cached_geometry_final(out, self.points_model.get_points())
        self._update_run_geometry_source_label()

    def _revert_smoothing(self) -> None:
        self.smoothing.revert()
        self.smooth_model.set_points([])
        self.view.set_points_xy(self.points_model.get_points())
        self.view.set_point_radius_px(4)
        self._clear_cached_geometry_final()
        self._update_run_geometry_source_label()

    def _active_profile_points(self) -> List[Point]:
        pts, _source = self._active_profile_with_source()
        return pts

    def _prediction_running(self) -> bool:
        return self._prediction_thread is not None and self._prediction_thread.isRunning()

    @staticmethod
    def _prediction_points_payload(points: List[Point]) -> List[List[float]]:
        return [[float(x), float(y)] for x, y in points]

    @staticmethod
    def _prediction_points_from_payload(payload: Any) -> List[Point]:
        if not isinstance(payload, list):
            return []
        out: List[Point] = []
        for item in payload:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            try:
                out.append((float(item[0]), float(item[1])))
            except Exception:
                continue
        return out if len(out) >= 2 else []

    def _build_parameter_prediction_payload(self) -> Optional[Dict[str, Any]]:
        if not (
            self._prediction_post_points_raw
            or self._prediction_post_points_smooth
            or self._prediction_anchor_spec
            or self._prediction_result
        ):
            return None
        payload: Dict[str, Any] = {
            "post_points_raw": self._prediction_points_payload(self._prediction_post_points_raw),
            "post_points_smooth": self._prediction_points_payload(self._prediction_post_points_smooth),
            "anchor_spec": copy.deepcopy(self._prediction_anchor_spec),
            "fit_result": copy.deepcopy(self._prediction_result),
        }
        return payload

    def _apply_parameter_prediction_payload(self, payload: Any) -> None:
        self._prediction_post_points_raw = []
        self._prediction_post_points_smooth = []
        self._prediction_anchor_spec = {}
        self._prediction_result = {}
        if not isinstance(payload, dict):
            return

        raw_points = self._prediction_points_from_payload(payload.get("post_points_raw"))
        smooth_points = self._prediction_points_from_payload(payload.get("post_points_smooth"))
        self._prediction_post_points_raw = raw_points
        self._prediction_post_points_smooth = smooth_points

        pre_points = self._active_profile_points()
        anchor_post_points = smooth_points if len(smooth_points) >= 2 else raw_points
        anchor_spec = payload.get("anchor_spec")
        if len(pre_points) >= 2 and len(anchor_post_points) >= 2 and isinstance(anchor_spec, dict):
            self._prediction_anchor_spec = sanitize_anchor_spec(pre_points, anchor_post_points, anchor_spec)
        elif isinstance(anchor_spec, dict):
            self._prediction_anchor_spec = copy.deepcopy(anchor_spec)

        fit_result = payload.get("fit_result")
        if isinstance(fit_result, dict):
            self._prediction_result = copy.deepcopy(fit_result)

    def _prediction_initial_post_points(self) -> List[Point]:
        if len(self._prediction_post_points_raw) >= 2:
            return [(float(x), float(y)) for x, y in self._prediction_post_points_raw]
        structure_points = list(self.points_model.get_points())
        if len(structure_points) >= 2:
            return [(float(x), float(y)) for x, y in structure_points]
        active_points = self._active_profile_points()
        return [(float(x), float(y)) for x, y in active_points]

    def _prediction_result_preview_text(self, result: Dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return self._prediction_text("preview_none")

        current_state = self._collect_switch_state()
        predicted_state = result.get("predicted_switch_state")
        if not isinstance(predicted_state, dict):
            return self._prediction_text("preview_none")

        lines: List[str] = []
        if "loss" in result:
            try:
                lines.append(
                    self._prediction_text(
                        "preview_header",
                        loss=float(result.get("loss", 0.0)),
                        count=max(0, int(result.get("evaluated_candidates", 0))),
                    )
                )
            except Exception:
                pass

        changed = False
        for sid, wd in self._switch_widgets.items():
            predicted_group = predicted_state.get(sid)
            if not isinstance(predicted_group, dict):
                continue
            current_group = current_state.get(sid, {})
            current_params = current_group.get("params") if isinstance(current_group, dict) else {}
            predicted_params = predicted_group.get("params") if isinstance(predicted_group, dict) else {}
            current_params = current_params if isinstance(current_params, dict) else {}
            predicted_params = predicted_params if isinstance(predicted_params, dict) else {}

            group_lines: List[str] = []
            current_enabled = bool(current_group.get("enabled", False)) if isinstance(current_group, dict) else False
            predicted_enabled = bool(predicted_group.get("enabled", False))
            if current_enabled != predicted_enabled:
                group_lines.append(
                    self._prediction_text(
                        "preview_enabled",
                        old=self._tr("common.on") if current_enabled else self._tr("common.off"),
                        new=self._tr("common.on") if predicted_enabled else self._tr("common.off"),
                    )
                )

            param_defs = wd.get("param_defs", {})
            if isinstance(param_defs, dict):
                for pid, pdef in param_defs.items():
                    if not isinstance(pdef, dict):
                        continue
                    old_value = current_params.get(pid, pdef.get("default"))
                    new_value = predicted_params.get(pid, pdef.get("default"))
                    old_text = self._format_result_param_value(pdef, old_value)
                    new_text = self._format_result_param_value(pdef, new_value)
                    if old_text == new_text:
                        continue
                    label = self._tr(str(pdef.get("label_key", pid)))
                    group_lines.append(f"{label}: {old_text} -> {new_text}")

            if not group_lines:
                continue

            changed = True
            if lines:
                lines.append("")
            lines.append(self._prediction_text("preview_group", group=self._tr(str(wd.get("title_key", sid)))))
            for line in group_lines:
                lines.append(f"  {line}")

        if not changed:
            if lines:
                lines.append("")
            lines.append(self._prediction_text("preview_none"))
        return "\n".join(lines)

    def _confirm_prediction_result(self, result: Dict[str, Any]) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle(self._prediction_text("confirm_title"))
        dialog.setModal(True)
        dialog.resize(560, 420)

        layout = QVBoxLayout(dialog)
        body = QLabel(self._prediction_text("confirm_body"))
        body.setWordWrap(True)
        layout.addWidget(body)

        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        preview.setPlainText(self._prediction_result_preview_text(result))
        layout.addWidget(preview, 1)

        buttons = QDialogButtonBox()
        btn_apply = buttons.addButton(self._prediction_text("confirm_apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self._prediction_text("confirm_keep"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if btn_apply is not None:
            btn_apply.setDefault(True)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _apply_prediction_result(self, result: Dict[str, Any], *, announce: bool) -> None:
        self._prediction_result = copy.deepcopy(result) if isinstance(result, dict) else {}
        switch_state = self._prediction_result.get("predicted_switch_state")
        if isinstance(switch_state, dict):
            self._apply_switch_state(switch_state)
            conformal = switch_state.get("conformal")
            conformal_params = conformal.get("params") if isinstance(conformal, dict) else {}
            if isinstance(conformal_params, dict):
                if "base_rate" in conformal_params:
                    self.spin_rate.setValue(float(conformal_params["base_rate"]))
                if "n_steps" in conformal_params:
                    self.spin_cycles.setValue(int(conformal_params["n_steps"]))
                self._sync_switches_from_legacy_run_controls()
                self._switch_state = self._collect_switch_state()
        if not announce:
            return
        if "loss" in self._prediction_result:
            text = self._prediction_text("complete_loss", loss=float(self._prediction_result.get("loss", 0.0)))
        else:
            text = self._prediction_text("complete")
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)
        self.progress_run.setRange(0, 1)
        self.progress_run.setValue(1)
        self.progress_run.setFormat("")
        self.statusBar().showMessage(self._prediction_text("complete"), 3000)

    def _set_prediction_running_ui(self) -> None:
        text = self._prediction_text("running")
        self.btn_parameter_prediction.setEnabled(False)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)
        self.progress_run.setRange(0, 0)
        self.progress_run.setFormat("")

    def _reset_prediction_running_ui(self) -> None:
        self.btn_parameter_prediction.setEnabled(True)
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_run.setRange(0, 1000)
        self.progress_run.setValue(0)
        self.progress_run.setFormat("")

    def _open_parameter_prediction_flow(self) -> None:
        if self._prediction_running():
            QMessageBox.warning(
                self,
                self._prediction_text("busy_title"),
                self._prediction_text("busy_body"),
            )
            return
        if self._engine_thread is not None and self._engine_thread.isRunning():
            QMessageBox.warning(
                self,
                self._tr("dialog.engine_running.title"),
                self._tr("dialog.engine_running.body"),
            )
            return

        pre_points = self._active_profile_points()
        if len(pre_points) < 2:
            QMessageBox.warning(self, self._prediction_text("busy_title"), self._prediction_text("pre_invalid"))
            return

        initial_post_raw = self._prediction_initial_post_points()
        editor = PredictionPostEditorDialog(
            pre_points=pre_points,
            initial_post_points=initial_post_raw,
            reset_points=self.points_model.get_points(),
            lang=self.lang,
            parent=self,
        )
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        post_points_raw = [(float(x), float(y)) for x, y in editor.post_points]
        if len(post_points_raw) < 2:
            QMessageBox.warning(self, self._prediction_text("busy_title"), self._prediction_text("post_invalid"))
            return

        initial_post_smooth = (
            self._prediction_post_points_smooth if len(self._prediction_post_points_smooth) >= 2 else post_points_raw
        )
        smoothing_dialog = PredictionPostSmoothingDialog(
            pre_points=pre_points,
            post_points_raw=post_points_raw,
            initial_post_points_smooth=initial_post_smooth,
            segments=self.spin_segments.value(),
            iterations=self.spin_iters.value(),
            lang=self.lang,
            parent=self,
        )
        if smoothing_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        post_points_smooth = [(float(x), float(y)) for x, y in smoothing_dialog.post_points_smooth]
        if len(post_points_smooth) < 2:
            QMessageBox.warning(self, self._prediction_text("busy_title"), self._prediction_text("post_smooth_invalid"))
            return

        initial_anchor_spec = (
            self._prediction_anchor_spec
            if isinstance(self._prediction_anchor_spec, dict) and self._prediction_anchor_spec
            else auto_anchor_spec(pre_points, post_points_smooth)
        )
        anchor_dialog = PredictionAnchorDialog(
            pre_points=pre_points,
            post_points=post_points_smooth,
            initial_anchor_spec=initial_anchor_spec,
            lang=self.lang,
            parent=self,
        )
        if anchor_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._prediction_post_points_raw = post_points_raw
        self._prediction_post_points_smooth = post_points_smooth
        self._prediction_anchor_spec = sanitize_anchor_spec(pre_points, post_points_smooth, anchor_dialog.anchor_spec)
        self._start_parameter_prediction(pre_points)

    def _start_parameter_prediction(self, pre_points: List[Point]) -> None:
        if self._prediction_running():
            return
        base_switch_state = self._collect_switch_state()
        base_recipe = self._build_recipe()

        th = QThread()
        worker = ParameterPredictionWorker(
            pre_points=pre_points,
            post_points=self._prediction_post_points_smooth,
            anchor_spec=self._prediction_anchor_spec,
            base_recipe=base_recipe,
            base_switch_state=base_switch_state,
        )
        worker.moveToThread(th)
        th.started.connect(worker.run)

        worker.progress.connect(self._on_prediction_progress)
        worker.message.connect(self._on_prediction_message)
        worker.finished.connect(self._on_prediction_finished)
        worker.error.connect(self._on_prediction_error)
        worker.canceled.connect(self._on_prediction_canceled)

        worker.finished.connect(th.quit)
        worker.error.connect(th.quit)
        worker.canceled.connect(th.quit)
        th.finished.connect(worker.deleteLater)
        th.finished.connect(th.deleteLater)
        th.finished.connect(self._on_prediction_thread_finished)

        self._prediction_thread = th
        self._prediction_worker = worker
        self._set_prediction_running_ui()
        th.start()

    def _on_prediction_progress(self, step: int, total: int) -> None:
        text = self._prediction_text("progress", step=step, total=total)
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)
        self.progress_run.setRange(0, max(1, int(total)))
        self.progress_run.setValue(max(0, min(int(total), int(step))))
        self.progress_run.setFormat(f"{int(step)}/{int(total)}")

    def _on_prediction_message(self, msg: str) -> None:
        self.statusBar().showMessage(str(msg), 2000)

    def _on_prediction_finished(self, result_obj: object) -> None:
        self._reset_prediction_running_ui()
        result = copy.deepcopy(result_obj) if isinstance(result_obj, dict) else {}
        if not isinstance(result.get("predicted_switch_state"), dict):
            self._apply_prediction_result(result, announce=True)
            return
        if self._confirm_prediction_result(result):
            result["applied"] = True
            self._apply_prediction_result(result, announce=True)
            return
        result["applied"] = False
        self._prediction_result = copy.deepcopy(result)
        text = self._prediction_text("not_applied")
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)
        self.progress_run.setRange(0, 1)
        self.progress_run.setValue(1)
        self.progress_run.setFormat("")
        self.statusBar().showMessage(text, 3000)

    def _on_prediction_canceled(self) -> None:
        self._reset_prediction_running_ui()
        text = self._prediction_text("canceled")
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)
        self.statusBar().showMessage(text, 2500)

    def _on_prediction_error(self, message: str) -> None:
        self._reset_prediction_running_ui()
        text = self._prediction_text("failed")
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)
        QMessageBox.critical(self, self._prediction_text("busy_title"), message)

    def _on_prediction_thread_finished(self) -> None:
        self._prediction_thread = None
        self._prediction_worker = None

    # ---------------- recipe IO ----------------
    def _sealed_model_code(self) -> str:
        code = self.combo_sealed_model.currentData()
        if isinstance(code, str) and code.lower() in ("a", "b"):
            return code.lower()
        return "a"

    def _set_sealed_model_code(self, code: str) -> None:
        code_l = str(code or "a").lower()
        idx = 0 if code_l.startswith("a") else 1
        self.combo_sealed_model.setCurrentIndex(idx)

    def _build_recipe(self) -> dict:
        structure_pts = list(self.points_model.get_points())
        self.smoothing.set_params(self.spin_segments.value(), self.spin_iters.value())
        self._switch_state = self._collect_switch_state()
        self._sync_legacy_run_controls_from_switches()

        conformal = self._switch_state.get("conformal", {"enabled": True, "params": {}})
        conf_enabled = bool(conformal.get("enabled", True))
        conf_params = conformal.get("params") or {}
        cycles = int(conf_params.get("n_steps", self.spin_cycles.value()))
        base_rate = float(conf_params.get("base_rate", self.spin_rate.value()))
        reparam_ds_a = float(conf_params.get("reparam_ds_a", 2.5))

        attenuation = self._switch_state.get("attenuation", {"enabled": False, "params": {}})
        att_enabled = bool(attenuation.get("enabled", False))
        att_params = attenuation.get("params") or {}
        source_onset_width_a = float(att_params.get("source_onset_width_a", 0.0))
        source_decay_pct = float(att_params.get("source_decay_pct", 0.0))
        source_distance_decay_pct = float(att_params.get("source_distance_decay_pct", 0.0))

        sputter = self._switch_state.get("sputter", {"enabled": False, "params": {}})
        sp_enabled = bool(sputter.get("enabled", False))
        sp_params = sputter.get("params") or {}
        sputter_only = bool(sp_params.get("sputter_only", False))
        sputter_strength_pct = float(sp_params.get("strength_pct", 0.0))
        sputter_peak_angle_deg = float(sp_params.get("peak_angle_deg", 55.0))
        sputter_angle_sigma_deg = float(sp_params.get("angle_sigma_deg", 15.0))
        sputter_depth_decay_length_a = float(sp_params.get("depth_decay_length_a", 1000.0))
        sputter_vis_exponent = float(sp_params.get("vis_exponent", 1.0))

        inhibition = self._switch_state.get("inhibition", {"enabled": False, "params": {}})
        inhib_enabled = bool(inhibition.get("enabled", False))
        inhib_params = inhibition.get("params") or {}
        inhibition_i_max = float(inhib_params.get("i_max", 0.5))
        inhibition_lambda_a = float(inhib_params.get("lambda_a", 500.0))

        redepo = self._switch_state.get("redepo", {"enabled": False, "params": {}})
        rd_enabled = bool(redepo.get("enabled", False))
        rd_params = redepo.get("params") or {}
        redepo_efficiency_pct = float(rd_params.get("efficiency_pct", 50.0))
        redepo_lobe_sigma_deg = float(rd_params.get("lobe_sigma_deg", 20.0))

        if not att_enabled:
            source_onset_width_a = 0.0
            source_decay_pct = 0.0
            source_distance_decay_pct = 0.0
        if not sp_enabled:
            sputter_only = False
            sputter_strength_pct = 0.0
        if sputter_only:
            conf_enabled = False
        if not inhib_enabled:
            inhibition_i_max = 0.0
            inhibition_lambda_a = 0.0
        if not rd_enabled:
            redepo_efficiency_pct = 0.0

        geom_final = self._active_profile_points()
        sm_payload = self.smoothing.get_saved_payload()
        if not sm_payload.get("base_points"):
            sm_payload["base_points"] = list(structure_pts)
        stage_index = self._continuation_stage_index if (self._continuation_seed_points and len(self._continuation_seed_points) >= 2) else 1

        return {
            "version": 1,
            "units": {"length": "A", "y_down_is_negative": True},
            "structure_points": structure_pts,
            "smoothing": sm_payload,
            "geometry_final": geom_final,
            "run": {
                "case_name": self.edit_case.text().strip() or self._tr("run.case_default"),
                "cycles": cycles,
            },
            "model_base": {
                "base_rate": base_rate,
                "conformal_enabled": conf_enabled,
                "reparam_ds_a": reparam_ds_a,
                # Keep sealing keys as fixed neutral defaults for compatibility with old readers.
                "epsilon": 0.0,
                "sealed_model": "b",
                "decay_k": 0.0,
                "source_kind": "none",
                "source_onset_width_a": source_onset_width_a,
                "source_decay_pct": source_decay_pct,
                "source_distance_decay_pct": source_distance_decay_pct,
                "sputter_enabled": sp_enabled,
                "sputter_only": sputter_only,
                "sputter_strength_pct": sputter_strength_pct,
                "sputter_peak_angle_deg": sputter_peak_angle_deg,
                "sputter_angle_sigma_deg": sputter_angle_sigma_deg,
                "sputter_depth_decay_length_a": sputter_depth_decay_length_a,
                "sputter_sky_vis_exponent": sputter_vis_exponent,
                "inhibition_enabled": inhib_enabled,
                "inhibition_i_max": inhibition_i_max,
                "inhibition_lambda_a": inhibition_lambda_a,
                "redepo_enabled": rd_enabled,
                "redepo_efficiency_pct": redepo_efficiency_pct,
                "redepo_lobe_sigma_deg": redepo_lobe_sigma_deg,
            },
            "phase1_switches": self._switch_state,
            "overlay": self.view.get_overlay_state(),
            "run_stage": {
                "index": stage_index,
                "continued_from": str(self._continuation_base_run_dir) if stage_index > 1 and self._continuation_base_run_dir else None,
            },
        }

    def _current_panel_key(self) -> str:
        cur = self.right_stack.currentWidget()
        if cur is self._panel_scroll_widgets.get("structure"):
            return "structure"
        if cur is self._panel_scroll_widgets.get("smoothing"):
            return "smoothing"
        if cur is self._panel_scroll_widgets.get("run"):
            return "run"
        if cur is self._panel_scroll_widgets.get("results"):
            return "results"
        return "structure"

    @staticmethod
    def _project_panel_key_from_data(data: Dict[str, Any]) -> str:
        view_state = data.get("view_state") if isinstance(data.get("view_state"), dict) else {}
        panel = str(view_state.get("panel") or "").strip().lower()
        if panel in {"structure", "smoothing", "run", "results"}:
            return panel
        return "structure"

    @staticmethod
    def _resolve_project_run_dir_value(value: Any, *, source_path: Optional[Path] = None) -> Optional[Path]:
        raw = str(value or "").strip()
        if not raw:
            return None
        run_dir = Path(raw)
        candidates: List[Path] = []
        if run_dir.is_absolute():
            candidates.append(run_dir)
        else:
            if source_path is not None:
                candidates.append(Path(source_path).parent / run_dir)
            candidates.append(Path.cwd() / run_dir)
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            if resolved.exists():
                return resolved
        return None

    @classmethod
    def resolve_project_run_dir_from_data(
        cls,
        data: Dict[str, Any],
        *,
        source_path: Optional[Path] = None,
    ) -> Optional[Path]:
        return cls._resolve_project_run_dir_value(data.get("last_run_dir"), source_path=source_path)

    @classmethod
    def project_open_stage_from_data(
        cls,
        data: Dict[str, Any],
        *,
        source_path: Optional[Path] = None,
    ) -> str:
        panel = cls._project_panel_key_from_data(data)
        if panel != "results":
            return panel
        if isinstance(data.get("saved_results"), dict):
            return "results"
        return "results" if cls.resolve_project_run_dir_from_data(data, source_path=source_path) is not None else "structure"

    def _serialize_project_run_dir(self, run_dir: Path) -> str:
        try:
            resolved_run_dir = Path(run_dir).resolve()
        except Exception:
            resolved_run_dir = Path(run_dir)
        if self._current_path is not None:
            try:
                base_dir = self._current_path.parent.resolve()
                return os.path.relpath(str(resolved_run_dir), str(base_dir))
            except ValueError:
                pass
        return str(resolved_run_dir)

    def _build_saved_results_payload(self) -> Optional[Dict[str, Any]]:
        if not self._result_frames:
            return None
        return {
            "frames": [[(float(x), float(y)) for x, y in frame] for frame in self._result_frames],
            "voids": [
                [[(float(x), float(y)) for x, y in poly] for poly in frame_voids]
                for frame_voids in self._result_voids
            ],
            "steps": [int(s) for s in self._result_steps],
            "stage_ids": [max(1, int(sid)) for sid in self._result_stage_ids],
            "stage_info": dict(self._result_stage_info) if isinstance(self._result_stage_info, dict) else {"index": 1},
            "void_mode": self._result_void_mode,
            "recipe": dict(self._result_recipe) if isinstance(self._result_recipe, dict) else {},
            "meta": dict(self._result_meta) if isinstance(self._result_meta, dict) else {},
            "x_window": list(self._result_x_window) if isinstance(self._result_x_window, tuple) and len(self._result_x_window) == 2 else None,
        }

    def _build_project_payload(self) -> Dict[str, Any]:
        data = self._build_recipe()
        if self._last_run_dir is not None and self._last_run_dir.exists():
            data["last_run_dir"] = self._serialize_project_run_dir(self._last_run_dir)
        else:
            results_payload = self._build_saved_results_payload()
            if results_payload:
                data["saved_results"] = results_payload
        prediction_payload = self._build_parameter_prediction_payload()
        if prediction_payload is not None:
            data["parameter_prediction"] = prediction_payload
        data["view_state"] = {"panel": self._current_panel_key()}
        return data

    def _apply_result_payload(self, payload: Dict[str, Any], *, fit: bool = True) -> bool:
        frames_obj = payload.get("frames", [])
        voids_obj = payload.get("voids", [])
        steps_obj = payload.get("steps", [])
        stage_ids_obj = payload.get("stage_ids", [])
        x_window_obj = payload.get("x_window")
        stage_info_obj = payload.get("stage_info", {})
        void_mode_obj = payload.get("void_mode", "legacy_cumulative")
        recipe_obj = payload.get("recipe", {})
        meta_obj = payload.get("meta", {})

        self._result_frames = [list(frame) for frame in frames_obj if isinstance(frame, list)]
        self._result_voids = [list(vf) for vf in voids_obj] if isinstance(voids_obj, list) else []
        self._result_steps = [int(s) for s in steps_obj] if isinstance(steps_obj, list) else []
        self._result_stage_ids = [max(1, int(sid)) for sid in stage_ids_obj] if isinstance(stage_ids_obj, list) else []
        self._result_stage_info = dict(stage_info_obj) if isinstance(stage_info_obj, dict) else {"index": 1}
        self._result_recipe = dict(recipe_obj) if isinstance(recipe_obj, dict) else {}
        self._result_meta = dict(meta_obj) if isinstance(meta_obj, dict) else {}
        self._result_void_mode = "current" if str(void_mode_obj).lower() == "current" else "legacy_cumulative"
        self._update_result_parameter_view()
        if isinstance(x_window_obj, (list, tuple)) and len(x_window_obj) == 2:
            self._result_x_window = (float(x_window_obj[0]), float(x_window_obj[1]))
        else:
            self._result_x_window = None

        if len(self._result_voids) != len(self._result_frames):
            self._result_voids = [[] for _ in self._result_frames]
        if len(self._result_steps) != len(self._result_frames):
            self._result_steps = list(range(len(self._result_frames)))
        if len(self._result_stage_ids) != len(self._result_frames):
            stage_idx = 1
            try:
                stage_idx = max(1, int(self._result_stage_info.get("index", 1)))
            except Exception:
                stage_idx = 1
            self._result_stage_ids = [stage_idx for _ in self._result_frames]

        if not self._result_frames:
            self._clear_result_view_state(message_key="results.no_vector")
            return False

        self._apply_default_show_every_n()
        self._rebuild_result_display(fit=fit)
        return True

    def _apply_loaded(self, data: dict) -> None:
        self._clear_continuation_context(clear_base=True)
        pts = data.get("structure_points") or []
        if not pts:
            geom = data.get("geometry")
            if isinstance(geom, dict):
                pts = geom.get("points") or []
        if not isinstance(pts, list) or len(pts) < 2:
            raise ValueError(self._tr("error.invalid_structure_points"))

        clean_pts = [(float(x), float(y)) for x, y in pts]
        self._set_structure_points(clean_pts, mark_origin=True, clear_undo=True)

        sm = data.get("smoothing") or {}
        self.spin_segments.setValue(int(sm.get("segments", self.spin_segments.value())))
        self.spin_iters.setValue(int(sm.get("iterations", self.spin_iters.value())))
        self._update_smoothing_limits()
        self.smoothing.set_base_points(sm.get("base_points", pts))
        self.smoothing.set_params(self.spin_segments.value(), self.spin_iters.value())
        self.smoothing.revert()
        self.smooth_model.set_points([])

        gf = data.get("geometry_final")
        if isinstance(gf, list) and len(gf) >= 2:
            try:
                gf_pts = [(float(x), float(y)) for x, y in gf]
                self._set_cached_geometry_final(gf_pts, clean_pts)
            except Exception:
                self._clear_cached_geometry_final()

        run = data.get("run") or {}
        if not isinstance(run, dict):
            run = {}
        mb = data.get("model_base") or {}
        if not isinstance(mb, dict):
            mb = {}

        if (not run) or (not mb):
            steps = data.get("steps") or []
            first_params = {}
            if isinstance(steps, list) and steps:
                step0 = steps[0]
                if isinstance(step0, dict):
                    maybe_params = step0.get("params") or {}
                    if isinstance(maybe_params, dict):
                        first_params = maybe_params

            if not run:
                meta = data.get("meta") or {}
                if not isinstance(meta, dict):
                    meta = {}
                run = {
                    "case_name": meta.get("case_name", self._tr("run.case_default")),
                    "cycles": first_params.get("cycles", self.spin_cycles.value()),
                }

            if not mb:
                mb = {
                    "base_rate": first_params.get("base_rate", self.spin_rate.value()),
                    "epsilon": 0.0,
                    "sealed_model": "b",
                    "decay_k": 0.0,
                }

        self.edit_case.setText(str(run.get("case_name") or self._tr("run.case_default")))
        if "cycles" in run:
            self.spin_cycles.setValue(int(run["cycles"]))

        if "base_rate" in mb:
            self.spin_rate.setValue(float(mb["base_rate"]))
        self.spin_eps.setValue(float(mb.get("epsilon", 0.0)))
        self._set_sealed_model_code(str(mb.get("sealed_model", "b")))
        self.spin_decay_k.setValue(float(mb.get("decay_k", 0.0)))

        switches = data.get("phase1_switches")
        if isinstance(switches, dict):
            self._apply_switch_state(switches)
        else:
            self._sync_switches_from_legacy_run_controls()
            conformal_wd = self._switch_widgets.get("conformal")
            if conformal_wd and ("conformal_enabled" in mb):
                conf_enabled = bool(mb.get("conformal_enabled", True))
                conformal_wd["enabled"].setChecked(conf_enabled)
                self._refresh_switch_dependency_ui()
            self._switch_state = self._collect_switch_state()

        if "reparam_ds_a" in mb:
            conformal_wd = self._switch_widgets.get("conformal")
            if conformal_wd:
                ctrl = conformal_wd["controls"].get("reparam_ds_a")
                pdef = conformal_wd["param_defs"].get("reparam_ds_a", {})
                if ctrl is not None:
                    self._set_switch_widget_value(ctrl, pdef, float(mb.get("reparam_ds_a", 2.5)))

        def _distance_len_to_pct(length_a: Any) -> float:
            try:
                length_val = float(length_a)
            except Exception:
                return 0.0
            if length_val <= 0.0:
                return 0.0
            remain_100 = math.exp(-100.0 / max(length_val, 1e-9))
            return max(0.0, min(100.0, (1.0 - remain_100) * 100.0))

        raw_onset = mb.get("source_onset_width_a")
        if raw_onset is None:
            raw_onset = mb.get("source_block_width_a")

        raw_decay = mb.get("source_decay_pct")
        if raw_decay is None and ("source_gamma" in mb):
            try:
                raw_decay = max(0.0, min(100.0, float(mb.get("source_gamma", 0.0)) * 70.0))
            except Exception:
                raw_decay = 0.0

        raw_dist_pct = mb.get("source_distance_decay_pct")
        if raw_dist_pct is None:
            raw_dist_len = mb.get("source_distance_decay_len_a")
            if raw_dist_len is None:
                raw_dist_len = mb.get("source_distance_len_a")
            if raw_dist_len is None:
                raw_dist_len = mb.get("source_distance_decay_a")
            raw_dist_pct = _distance_len_to_pct(raw_dist_len)

        conf_params_legacy = {}
        if isinstance(switches, dict):
            conf_sw = switches.get("conformal")
            if isinstance(conf_sw, dict):
                maybe_params = conf_sw.get("params")
                if isinstance(maybe_params, dict):
                    conf_params_legacy = maybe_params
        if raw_onset is None:
            raw_onset = conf_params_legacy.get("source_onset_width_a")
        if raw_decay is None:
            raw_decay = conf_params_legacy.get("source_decay_pct")
        if raw_dist_pct is None:
            raw_dist_pct = conf_params_legacy.get("source_distance_decay_pct")
        if raw_dist_pct is None:
            raw_dist_pct = _distance_len_to_pct(conf_params_legacy.get("source_distance_decay_len_a"))

        explicit_att = False
        if isinstance(switches, dict):
            att_sw = switches.get("attenuation")
            if isinstance(att_sw, dict):
                if "enabled" in att_sw:
                    explicit_att = True
                maybe_params = att_sw.get("params")
                if isinstance(maybe_params, dict):
                    explicit_att = explicit_att or any(
                        key in maybe_params
                        for key in ("source_onset_width_a", "source_decay_pct", "source_distance_decay_pct")
                    )

        attenuation_wd = self._switch_widgets.get("attenuation")
        if attenuation_wd and (not explicit_att):
            controls = attenuation_wd.get("controls", {})
            pdefs = attenuation_wd.get("param_defs", {})
            onset = float(raw_onset or 0.0)
            decay = float(raw_decay or 0.0)
            dist_pct = float(raw_dist_pct or 0.0)

            if "source_onset_width_a" in controls:
                self._set_switch_widget_value(
                    controls["source_onset_width_a"],
                    pdefs.get("source_onset_width_a", {}),
                    onset,
                )
            if "source_decay_pct" in controls:
                self._set_switch_widget_value(
                    controls["source_decay_pct"],
                    pdefs.get("source_decay_pct", {}),
                    decay,
                )
            if "source_distance_decay_pct" in controls:
                self._set_switch_widget_value(
                    controls["source_distance_decay_pct"],
                    pdefs.get("source_distance_decay_pct", {}),
                    dist_pct,
                )
            att_enable = (onset > 0.0 and decay > 0.0) or (dist_pct > 0.0)
            attenuation_wd["enabled"].setChecked(att_enable)
            attenuation_wd["form_host"].setEnabled(att_enable)
            self._switch_state = self._collect_switch_state()

        explicit_sputter = False
        if isinstance(switches, dict):
            sp_sw = switches.get("sputter")
            if isinstance(sp_sw, dict):
                if "enabled" in sp_sw:
                    explicit_sputter = True
                maybe_params = sp_sw.get("params")
                if isinstance(maybe_params, dict):
                    explicit_sputter = explicit_sputter or any(
                        key in maybe_params
                        for key in (
                            "sputter_only",
                            "strength_pct",
                            "peak_angle_deg",
                            "angle_sigma_deg",
                            "depth_decay_length_a",
                            "vis_exponent",
                        )
                    )

        sputter_wd = self._switch_widgets.get("sputter")
        if sputter_wd and (not explicit_sputter):
            controls = sputter_wd.get("controls", {})
            pdefs = sputter_wd.get("param_defs", {})
            sputter_only = bool(mb.get("sputter_only", False))
            strength_pct = float(mb.get("sputter_strength_pct", 0.0) or 0.0)
            peak_angle_deg = float(mb.get("sputter_peak_angle_deg", 55.0) or 55.0)
            angle_sigma_deg = float(mb.get("sputter_angle_sigma_deg", mb.get("sputter_peak_width_deg", 15.0)) or 15.0)
            depth_decay_length_a = mb.get("sputter_depth_decay_length_a")
            if depth_decay_length_a is None:
                legacy_pct = float(mb.get("sputter_ion_depth_decay_pct", 70.0) or 70.0)
                y_top = max((float(p[1]) for p in clean_pts), default=0.0)
                max_depth = max((max(0.0, y_top - float(p[1])) for p in clean_pts), default=0.0)
                if legacy_pct <= 0.0 or max_depth <= 1e-9:
                    depth_decay_length_a = 0.0
                else:
                    legacy_floor = max(1e-6, 1.0 - (legacy_pct / 100.0))
                    depth_decay_length_a = max_depth / max(1e-9, -math.log(legacy_floor))
            depth_decay_length_a = float(depth_decay_length_a or 0.0)
            vis_exponent = float(mb.get("sputter_sky_vis_exponent", mb.get("sputter_vis_exponent", 1.0)) or 1.0)

            if "sputter_only" in controls:
                self._set_switch_widget_value(
                    controls["sputter_only"],
                    pdefs.get("sputter_only", {}),
                    sputter_only,
                )
            if "strength_pct" in controls:
                self._set_switch_widget_value(controls["strength_pct"], pdefs.get("strength_pct", {}), strength_pct)
            if "peak_angle_deg" in controls:
                self._set_switch_widget_value(controls["peak_angle_deg"], pdefs.get("peak_angle_deg", {}), peak_angle_deg)
            if "angle_sigma_deg" in controls:
                self._set_switch_widget_value(
                    controls["angle_sigma_deg"],
                    pdefs.get("angle_sigma_deg", {}),
                    angle_sigma_deg,
                )
            if "depth_decay_length_a" in controls:
                self._set_switch_widget_value(
                    controls["depth_decay_length_a"],
                    pdefs.get("depth_decay_length_a", {}),
                    depth_decay_length_a,
                )
            if "vis_exponent" in controls:
                self._set_switch_widget_value(
                    controls["vis_exponent"],
                    pdefs.get("vis_exponent", {}),
                    vis_exponent,
                )
            sp_enable = bool(mb.get("sputter_enabled", False)) or sputter_only or strength_pct > 0.0
            sputter_wd["enabled"].setChecked(sp_enable)
            self._switch_state = self._collect_switch_state()

        explicit_redepo = False
        if isinstance(switches, dict):
            rd_sw = switches.get("redepo")
            if isinstance(rd_sw, dict):
                if "enabled" in rd_sw:
                    explicit_redepo = True
                maybe_params = rd_sw.get("params")
                if isinstance(maybe_params, dict):
                    explicit_redepo = explicit_redepo or any(
                        key in maybe_params
                        for key in (
                            "efficiency_pct",
                            "lobe_sigma_deg",
                        )
                    )

        redepo_wd = self._switch_widgets.get("redepo")
        if redepo_wd and (not explicit_redepo):
            controls = redepo_wd.get("controls", {})
            pdefs = redepo_wd.get("param_defs", {})
            efficiency_pct = float(mb.get("redepo_efficiency_pct", 50.0) or 50.0)
            lobe_sigma_deg = float(mb.get("redepo_lobe_sigma_deg", 0.0) or 0.0)
            if lobe_sigma_deg <= 0.0:
                legacy_spread_pct = float(mb.get("redepo_specular_spread_pct", 30.0) or 30.0)
                lobe_sigma_deg = max(1.0, min(60.0, 5.0 + (0.35 * legacy_spread_pct)))

            if "efficiency_pct" in controls:
                self._set_switch_widget_value(controls["efficiency_pct"], pdefs.get("efficiency_pct", {}), efficiency_pct)
            if "lobe_sigma_deg" in controls:
                self._set_switch_widget_value(
                    controls["lobe_sigma_deg"],
                    pdefs.get("lobe_sigma_deg", {}),
                    lobe_sigma_deg,
                )
            rd_enable = bool(mb.get("redepo_enabled", False)) or efficiency_pct > 0.0
            redepo_wd["enabled"].setChecked(rd_enable)
            redepo_wd["form_host"].setEnabled(rd_enable)
            self._switch_state = self._collect_switch_state()

        self._apply_parameter_prediction_payload(data.get("parameter_prediction"))
        if isinstance(self._prediction_result.get("predicted_switch_state"), dict) and bool(
            self._prediction_result.get("applied", True)
        ):
            self._apply_prediction_result(self._prediction_result, announce=False)

        overlay_payload = data.get("overlay")
        if isinstance(overlay_payload, dict):
            self._apply_overlay_payload(overlay_payload)
        else:
            self._clear_overlay_image(silent=True)
        self._last_run_dir = self.resolve_project_run_dir_from_data(data, source_path=self._current_path)
        self._update_run_dir_label()
        self.btn_open_dir.setEnabled(self._last_run_dir is not None)
        saved_results = data.get("saved_results")
        if isinstance(saved_results, dict):
            self._result_loading = False
            self._anim_timer.stop()
            self._refresh_anim_button_text()
            self._apply_result_payload(saved_results, fit=True)
        else:
            self._result_frames = []
            self._result_voids = []
            self._result_steps = []
            self._result_stage_ids = []
            self._result_stage_info = {"index": 1}
            self._result_recipe = {}
            self._result_meta = {}
            self._result_x_window = None
            self._result_void_mode = "legacy_cumulative"
            self._update_result_parameter_view()
        self._update_run_geometry_source_label()
        panel = self._project_panel_key_from_data(data)
        if panel in {"structure", "smoothing", "run", "results"}:
            if panel != "results" or self._result_frames or self._last_run_dir is not None:
                self._goto(panel)

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("dialog.open.title"),
            "",
            self._tr("dialog.file_filter"),
        )
        if not path:
            return

        p = Path(path)
        prev_path = self._current_path
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self._current_path = p
            self._apply_loaded(data)
        except Exception as e:
            self._current_path = prev_path
            self.statusBar().showMessage(self._tf("status.open_failed", error=e), 6000)
            QMessageBox.critical(self, self._tr("dialog.open_error.title"), str(e))
            return

        self.statusBar().showMessage(self._tr("status.loaded"), 2000)

    def _save(self) -> None:
        if self._current_path is None:
            self._save_as()
            return
        data = self._build_project_payload()
        self._current_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.statusBar().showMessage(self._tf("status.saved", name=self._current_path.name), 2000)

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("dialog.save.title"),
            "",
            self._tr("dialog.file_filter"),
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != ".json":
            p = p.with_suffix(".json")
        self._current_path = p
        self._save()

    # ---------------- engine run ----------------
    def _write_temp_recipe(self, recipe: dict) -> Path:
        fd, tmp_path = tempfile.mkstemp(prefix="gapsim_recipe_", suffix=".json")
        Path(tmp_path).write_text(json.dumps(recipe, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            import os

            os.close(fd)
        except Exception:
            pass
        return Path(tmp_path)

    def _set_run_status(self, kind: str, *, step: int = 0, total: int = 0) -> None:
        self._run_status_kind = kind
        self._run_status_step = int(step)
        self._run_status_total = int(total)
        if kind == "running":
            self._run_status_substep = 0
            self._run_status_substeps = 0
            self._run_started_at_mono = time.monotonic()
            self._run_eta_seconds = None
            self._run_eta_finish_text = ""
            self._run_progress_marks = []
        elif kind == "idle":
            self._run_status_substep = 0
            self._run_status_substeps = 0
            self._run_eta_seconds = None
            self._run_eta_finish_text = ""
            self._run_progress_marks = []
        elif kind == "cancel_requested":
            self._run_eta_seconds = None
            self._run_eta_finish_text = ""
        elif kind == "progress" and self._run_started_at_mono is not None:
            self._run_status_substep = 0
            self._run_status_substeps = 0
            now = time.monotonic()
            step_i = int(step)
            if (not self._run_progress_marks) or (self._run_progress_marks[-1][0] != step_i):
                self._run_progress_marks.append((step_i, now))
                if len(self._run_progress_marks) > 12:
                    self._run_progress_marks = self._run_progress_marks[-12:]
        self._render_run_status()

    def _set_run_detail(self, payload: dict[str, Any] | None) -> None:
        self._run_status_detail = dict(payload) if isinstance(payload, dict) else None
        detail = self._run_status_detail or {}
        if str(detail.get("kind", "")) == "ion_substep":
            self._run_status_substep = max(0, int(detail.get("substep", 0)))
            self._run_status_substeps = max(0, int(detail.get("substeps", 0)))
        elif str(detail.get("kind", "")) == "cycle":
            self._run_status_substep = 0
            self._run_status_substeps = 0
        self._render_run_status()

    def _update_run_progress_bar(self) -> None:
        total = max(0, int(self._run_status_total))
        step = max(0, int(self._run_status_step))
        substep = max(0, int(self._run_status_substep))
        substeps = max(0, int(self._run_status_substeps))
        scale = 1000

        if self._run_status_kind == "running":
            self.progress_run.setRange(0, 0)
            self.progress_run.setFormat("")
            return

        self.progress_run.setRange(0, max(1, total * scale))

        if total <= 0:
            self.progress_run.setValue(0)
            self.progress_run.setFormat("")
            return

        progress_units = step * scale
        if (
            self._run_status_kind in {"progress", "cancel_requested"}
            and 0 <= step < total
            and substeps > 0
            and substep > 0
        ):
            frac = min(1.0, max(0.0, float(substep) / float(substeps)))
            progress_units += int(round(frac * scale))

        max_value = total * scale
        self.progress_run.setValue(max(0, min(max_value, progress_units)))

        if self._run_status_kind in {"progress", "cancel_requested"} and substeps > 0 and 0 <= step < total:
            self.progress_run.setFormat(f"{step}/{total} | {substep}/{substeps}")
        elif self._run_status_kind in {"progress", "cancel_requested"}:
            self.progress_run.setFormat(f"{step}/{total}")
        else:
            self.progress_run.setFormat("")

    @staticmethod
    def _format_eta_duration(seconds: float) -> str:
        total = max(0, int(round(float(seconds))))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        if minutes > 0:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _update_run_eta(self) -> None:
        self._run_eta_seconds = None
        self._run_eta_finish_text = ""
        if self._run_started_at_mono is None:
            return
        step = max(0, int(self._run_status_step))
        total = max(0, int(self._run_status_total))
        if step <= 0 or total <= step:
            return
        elapsed = max(0.0, time.monotonic() - self._run_started_at_mono)
        if step < 5 or elapsed < 8.0 or len(self._run_progress_marks) < 6:
            return
        marks = self._run_progress_marks[-6:]
        step_delta = max(0, int(marks[-1][0]) - int(marks[0][0]))
        time_delta = max(0.0, float(marks[-1][1]) - float(marks[0][1]))
        if step_delta <= 0 or time_delta <= 0.0:
            return
        avg_per_step = time_delta / float(step_delta)
        remain = max(0.0, avg_per_step * float(total - step))
        self._run_eta_seconds = remain
        self._run_eta_finish_text = datetime.fromtimestamp(time.time() + remain).strftime("%H:%M:%S")

    def _format_run_status_tooltip(self) -> str:
        self._update_run_eta()
        detail = self._run_status_detail or {}
        kind = str(detail.get("kind", ""))
        if kind == "ion_substep":
            base = self._tf(
                "run.status.tooltip_ion_substep",
                step=int(detail.get("step", self._run_status_step)),
                total=int(detail.get("total", self._run_status_total)),
                substep=int(detail.get("substep", 0)),
                substeps=int(detail.get("substeps", 0)),
                points=int(detail.get("points", 0)),
                etch_candidates=int(detail.get("etch_candidates", 0)),
                redepo_sources=int(detail.get("redepo_sources", 0)),
            )
            if self._run_eta_seconds is not None and self._run_eta_finish_text:
                return base + "\n" + self._tf(
                    "run.status.tooltip_eta",
                    remain=self._format_eta_duration(self._run_eta_seconds),
                    finish=self._run_eta_finish_text,
                )
            return base
        if kind == "cycle":
            base = self._tf(
                "run.status.tooltip_cycle",
                step=int(detail.get("step", self._run_status_step)),
                total=int(detail.get("total", self._run_status_total)),
                points=int(detail.get("points", 0)),
            )
            if self._run_eta_seconds is not None and self._run_eta_finish_text:
                return base + "\n" + self._tf(
                    "run.status.tooltip_eta",
                    remain=self._format_eta_duration(self._run_eta_seconds),
                    finish=self._run_eta_finish_text,
                )
            return base
        if self._run_status_kind == "progress":
            base = self._tf(
                "run.status.tooltip_cycle",
                step=self._run_status_step,
                total=self._run_status_total,
                points=0,
            )
            if self._run_eta_seconds is not None and self._run_eta_finish_text:
                return base + "\n" + self._tf(
                    "run.status.tooltip_eta",
                    remain=self._format_eta_duration(self._run_eta_seconds),
                    finish=self._run_eta_finish_text,
                )
            return base
        return self.lbl_status.text()

    def _render_run_status(self) -> None:
        self._update_run_eta()
        if self._run_status_kind == "running":
            self.lbl_status.setText(self._tr("run.status.running"))
        elif self._run_status_kind == "cancel_requested":
            self.lbl_status.setText(self._tr("run.status.cancel_requested"))
        elif self._run_status_kind == "progress":
            if self._run_eta_seconds is not None:
                self.lbl_status.setText(
                    self._tf(
                        "run.status.progress_eta",
                        step=self._run_status_step,
                        total=self._run_status_total,
                        remain=self._format_eta_duration(self._run_eta_seconds),
                    )
                )
            else:
                self.lbl_status.setText(
                    self._tf(
                        "run.status.progress",
                        step=self._run_status_step,
                        total=self._run_status_total,
                    )
                )
        else:
            self.lbl_status.setText(self._tr("run.status.idle"))
        self.lbl_status.setToolTip(self._format_run_status_tooltip())
        self._update_run_progress_bar()

    def _refresh_anim_button_text(self) -> None:
        if self._anim_timer.isActive():
            self.btn_anim_play.setText(self._tr("results.pause"))
        else:
            self.btn_anim_play.setText(self._tr("results.play"))

    def _engine_run(self) -> None:
        if self._engine_thread is not None and self._engine_thread.isRunning():
            QMessageBox.warning(
                self,
                self._tr("dialog.engine_running.title"),
                self._tr("dialog.engine_running.body"),
            )
            return

        continuation_used = bool(self._continuation_seed_points and self._continuation_base_frames)
        self._continuation_merge_pending = continuation_used
        recipe = self._build_recipe()
        recipe_path = self._write_temp_recipe(recipe)

        th = QThread()
        worker = EngineWorker(recipe_path=recipe_path, runs_root=self._runs_root_dir())
        worker.moveToThread(th)
        th.started.connect(worker.run)

        worker.progress.connect(self._on_engine_progress)
        worker.detail.connect(self._on_engine_detail)
        worker.message.connect(self._on_engine_message)
        worker.finished.connect(self._on_engine_finished)
        worker.error.connect(self._on_engine_error)

        worker.finished.connect(th.quit)
        worker.error.connect(th.quit)
        th.finished.connect(worker.deleteLater)
        th.finished.connect(th.deleteLater)
        th.finished.connect(self._on_engine_thread_finished)

        self._engine_thread = th
        self._engine_worker = worker

        self._anim_timer.stop()
        self._refresh_anim_button_text()
        self._result_frames = []
        self._result_voids = []
        self._result_steps = []
        self._result_stage_ids = []
        self._result_stage_info = {"index": 1}
        self._result_recipe = {}
        self._result_meta = {}
        self._result_display_indices = []
        self._result_display_steps = []
        self._result_display_stage_ids = []
        self._result_x_window = None
        self._result_void_mode = "legacy_cumulative"
        self._result_loading = False
        self._result_load_seq += 1
        self._frame_index = -1
        self._update_result_parameter_view()
        self.slider_frame.blockSignals(True)
        self.slider_frame.setRange(0, 0)
        self.slider_frame.setValue(0)
        self.slider_frame.setEnabled(False)
        self.slider_frame.blockSignals(False)
        self.lbl_frame.setText(self._tr("results.frame_empty"))
        self.result_view.clear_data()
        self._update_stage_visibility_controls()
        self._update_frame_step_buttons()

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_run_detail(None)
        self._set_run_status("running")

        th.start()

    def _engine_stop(self) -> None:
        if self._prediction_worker is not None:
            self._prediction_worker.request_cancel()
            self.btn_stop.setEnabled(False)
            text = self._prediction_text("cancel_requested")
            self.lbl_status.setText(text)
            self.lbl_status.setToolTip(text)
            return
        if self._engine_worker is not None:
            self._engine_worker.request_cancel()
            self.btn_stop.setEnabled(False)
            self._set_run_status("cancel_requested")

    def _on_engine_progress(self, step: int, total: int) -> None:
        self._set_run_status("progress", step=step, total=total)

    def _on_engine_detail(self, payload: object) -> None:
        self._set_run_detail(payload if isinstance(payload, dict) else None)

    def _on_engine_message(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 2000)

    def _on_engine_finished(self, run_dir_str: str) -> None:
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_run_detail(None)
        self._set_run_status("idle")

        self._last_run_dir = Path(run_dir_str)
        self._update_run_dir_label()
        self.btn_open_dir.setEnabled(True)

        self._load_result_frames(self._last_run_dir)
        self._goto("results")
        self.statusBar().showMessage(self._tr("status.run_complete"), 3000)

    def _on_engine_error(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_run_detail(None)
        self._set_run_status("idle")
        QMessageBox.critical(self, self._tr("dialog.engine_error.title"), msg)

    def _on_engine_thread_finished(self) -> None:
        self._engine_thread = None
        self._engine_worker = None

    def _profiles_same(self, a: List[Point], b: List[Point], tol: float = 1e-6) -> bool:
        if len(a) != len(b):
            return False
        for (ax, ay), (bx, by) in zip(a, b):
            if abs(float(ax) - float(bx)) > tol or abs(float(ay) - float(by)) > tol:
                return False
        return True

    def _read_profiles_payload(self, run_dir: Path) -> Optional[Dict[str, Any]]:
        try:
            return load_result_payload_from_run_dir(run_dir)
        except Exception:
            return None

    def _clear_continuation_context(self, *, clear_base: bool = True) -> None:
        self._continuation_seed_points = None
        self._continuation_stage_index = 1
        self._continuation_merge_pending = False
        if clear_base:
            self._continuation_base_frames = None
            self._continuation_base_voids = None
            self._continuation_base_steps = None
            self._continuation_base_stage_ids = None
            self._continuation_base_void_mode = None
            self._continuation_base_run_dir = None
        self._update_run_geometry_source_label()

    def _next_continuation_stage_index(self) -> int:
        max_stage = 1
        if self._result_stage_ids:
            try:
                max_stage = max(max(1, int(sid)) for sid in self._result_stage_ids)
            except Exception:
                max_stage = 1
        else:
            try:
                max_stage = max(1, int(self._result_stage_info.get("index", 1)))
            except Exception:
                max_stage = 1
        return max_stage + 1

    def _continuation_reference_profiles(self) -> List[List[Point]]:
        if not (self._continuation_seed_points and self._continuation_base_frames):
            return []
        frames = self._continuation_base_frames or []
        stage_ids = self._continuation_base_stage_ids or [1 for _ in frames]
        if len(stage_ids) != len(frames):
            stage_ids = [1 for _ in frames]

        last_by_stage: Dict[int, List[Point]] = {}
        stage_order: List[int] = []
        for frame, sid in zip(frames, stage_ids):
            if not frame or len(frame) < 2:
                continue
            sid_i = max(1, int(sid))
            if sid_i not in last_by_stage:
                stage_order.append(sid_i)
            last_by_stage[sid_i] = [(float(x), float(y)) for x, y in frame]

        return [last_by_stage[sid] for sid in stage_order if sid in last_by_stage]

    def _stage_completion_indices(self) -> List[Tuple[int, int]]:
        if not self._result_frames or not self._result_stage_ids:
            return []
        last_index_by_stage: Dict[int, int] = {}
        stage_order: List[int] = []
        for idx, sid in enumerate(self._result_stage_ids[: len(self._result_frames)]):
            sid_i = max(1, int(sid))
            if sid_i not in last_index_by_stage:
                stage_order.append(sid_i)
            last_index_by_stage[sid_i] = idx
        return [(sid, last_index_by_stage[sid]) for sid in stage_order if sid in last_index_by_stage]

    def _selected_stage_completion_actual_index(self) -> int:
        data = self.combo_next_depo_from.currentData()
        try:
            idx = int(data)
        except Exception:
            idx = -1
        if 0 <= idx < len(self._result_frames):
            return idx
        completions = self._stage_completion_indices()
        if completions:
            return completions[-1][1]
        return self._selected_result_actual_index()

    def _selected_result_actual_index(self) -> int:
        if not self._result_frames:
            return -1
        if self._result_display_indices and 0 <= self._frame_index < len(self._result_display_indices):
            actual_idx = int(self._result_display_indices[self._frame_index])
            return max(0, min(actual_idx, len(self._result_frames) - 1))
        return len(self._result_frames) - 1

    def _start_second_depo(self) -> None:
        if not self._result_frames:
            QMessageBox.warning(self, self._tr("dialog.export.title"), self._tr("dialog.export.no_frames"))
            return

        selected_idx = self._selected_stage_completion_actual_index()
        if selected_idx < 0:
            QMessageBox.warning(self, self._tr("dialog.export.title"), self._tr("dialog.export.no_frames"))
            return

        seed = list(self._result_frames[selected_idx])
        if len(seed) < 2:
            QMessageBox.warning(self, self._tr("dialog.export.title"), self._tr("dialog.export.no_frames"))
            return

        self._continuation_seed_points = [(float(x), float(y)) for x, y in seed]
        self._continuation_base_frames = [
            [(float(x), float(y)) for x, y in frame]
            for frame in self._result_frames[: selected_idx + 1]
        ]
        self._continuation_base_voids = [
            [[(float(x), float(y)) for x, y in poly] for poly in frame_voids]
            for frame_voids in self._result_voids[: selected_idx + 1]
        ]
        self._continuation_base_steps = [int(s) for s in self._result_steps[: selected_idx + 1]]
        self._continuation_base_stage_ids = [max(1, int(s)) for s in self._result_stage_ids[: selected_idx + 1]]
        self._continuation_base_void_mode = self._result_void_mode
        self._continuation_base_run_dir = self._last_run_dir
        self._continuation_stage_index = self._next_continuation_stage_index()
        self._continuation_merge_pending = False

        case = self.edit_case.text().strip() or self._tr("run.case_default")
        case = re.sub(r"_p\d+$", "", case, flags=re.IGNORECASE)
        self.edit_case.setText(f"{case}_p{self._continuation_stage_index}")
        self._update_run_geometry_source_label()
        step_value = 0
        if 0 <= selected_idx < len(self._result_steps):
            step_value = int(self._result_steps[selected_idx])
        self.statusBar().showMessage(
            self._tf("status.next_depo_ready", stage=self._continuation_stage_index) + f" (step {step_value})",
            2500,
        )
        self._goto("run")

    def _update_stage_visibility_controls(self) -> None:
        has_frames = bool(self._result_frames)
        completions = self._stage_completion_indices()
        self.combo_next_depo_from.blockSignals(True)
        current_data = self.combo_next_depo_from.currentData()
        self.combo_next_depo_from.clear()
        for sid, idx in completions:
            step_value = int(self._result_steps[idx]) if 0 <= idx < len(self._result_steps) else idx
            label = self._tf("results.stage_completion_item", stage=sid, step=step_value)
            self.combo_next_depo_from.addItem(label, idx)
        restore_idx = self.combo_next_depo_from.findData(current_data)
        if restore_idx >= 0:
            self.combo_next_depo_from.setCurrentIndex(restore_idx)
        elif self.combo_next_depo_from.count() > 0:
            self.combo_next_depo_from.setCurrentIndex(self.combo_next_depo_from.count() - 1)
        self.combo_next_depo_from.setEnabled(has_frames and self.combo_next_depo_from.count() > 0)
        self.lbl_next_depo_from.setEnabled(has_frames and self.combo_next_depo_from.count() > 0)
        self.combo_next_depo_from.blockSignals(False)
        self.btn_second_depo.setEnabled(has_frames)
        next_stage = self._next_continuation_stage_index() if has_frames else 2
        self.btn_second_depo.setText(self._tf("results.next_depo", stage=next_stage))

    # ---------------- results ----------------
    def _update_run_dir_label(self) -> None:
        if self._last_run_dir is None:
            self.lbl_run_dir.setText(self._tr("results.run_dir_empty"))
            return
        self.lbl_run_dir.setText(self._tf("results.run_dir", path=str(self._last_run_dir)))

    def _format_result_param_value(self, pdef: Dict[str, Any], value: Any) -> str:
        ptype = str(pdef.get("type", ""))
        if ptype == "enum":
            option = str(value)
            text = self._tr(f"switch.enum.{option}")
            return option if text == f"switch.enum.{option}" else text
        if ptype == "bool":
            return self._tr("common.on") if bool(value) else self._tr("common.off")
        if ptype == "float":
            try:
                decimals = int(pdef.get("decimals", 3))
                txt = f"{float(value):.{max(0, decimals)}f}"
                if "." in txt:
                    txt = txt.rstrip("0").rstrip(".")
                return txt
            except Exception:
                return str(value)
        if ptype == "int":
            try:
                return str(int(value))
            except Exception:
                return str(value)
        return str(value)

    def _recipe_switch_state_for_results(self, recipe: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        raw = recipe.get("phase1_switches")
        if isinstance(raw, dict) and raw:
            out: Dict[str, Dict[str, Any]] = {}
            for sid, state in raw.items():
                if not isinstance(state, dict):
                    continue
                params = state.get("params")
                out[str(sid)] = {
                    "enabled": bool(state.get("enabled", False)),
                    "params": dict(params) if isinstance(params, dict) else {},
                }
            if out:
                return out

        out = default_switch_state()
        run = recipe.get("run") if isinstance(recipe.get("run"), dict) else {}
        model = recipe.get("model_base") if isinstance(recipe.get("model_base"), dict) else {}

        conf = out.get("conformal", {"enabled": True, "params": {}})
        conf["enabled"] = bool(model.get("conformal_enabled", True))
        conf["params"]["base_rate"] = float(model.get("base_rate", conf["params"].get("base_rate", 1.0)))
        conf["params"]["n_steps"] = int(run.get("cycles", conf["params"].get("n_steps", 200)))
        conf["params"]["reparam_ds_a"] = float(model.get("reparam_ds_a", conf["params"].get("reparam_ds_a", 2.5)))
        out["conformal"] = conf

        att = out.get("attenuation", {"enabled": False, "params": {}})
        att["params"]["source_onset_width_a"] = float(model.get("source_onset_width_a", 0.0))
        att["params"]["source_decay_pct"] = float(model.get("source_decay_pct", 0.0))
        att["params"]["source_distance_decay_pct"] = float(model.get("source_distance_decay_pct", 0.0))
        att["enabled"] = any(float(att["params"].get(key, 0.0)) > 0.0 for key in att["params"])
        out["attenuation"] = att

        sp = out.get("sputter", {"enabled": False, "params": {}})
        sp["enabled"] = (
            bool(model.get("sputter_enabled", False))
            or bool(model.get("sputter_only", False))
            or float(model.get("sputter_strength_pct", 0.0)) > 0.0
        )
        sp["params"]["sputter_only"] = bool(model.get("sputter_only", False))
        sp["params"]["strength_pct"] = float(model.get("sputter_strength_pct", 0.0))
        sp["params"]["peak_angle_deg"] = float(model.get("sputter_peak_angle_deg", 55.0))
        sp["params"]["angle_sigma_deg"] = float(model.get("sputter_angle_sigma_deg", 15.0))
        sp["params"]["depth_decay_length_a"] = float(model.get("sputter_depth_decay_length_a", 1000.0))
        sp["params"]["vis_exponent"] = float(
            model.get("sputter_sky_vis_exponent", model.get("sputter_vis_exponent", 1.0))
        )
        out["sputter"] = sp

        inhib = out.get("inhibition", {"enabled": False, "params": {}})
        inhib["enabled"] = bool(model.get("inhibition_enabled", False)) or float(model.get("inhibition_i_max", 0.0)) > 0.0
        inhib["params"]["i_max"] = float(model.get("inhibition_i_max", 0.5))
        inhib["params"]["lambda_a"] = float(model.get("inhibition_lambda_a", 500.0))
        out["inhibition"] = inhib

        rd = out.get("redepo", {"enabled": False, "params": {}})
        rd["enabled"] = bool(model.get("redepo_enabled", False)) or float(model.get("redepo_efficiency_pct", 0.0)) > 0.0
        rd["params"]["efficiency_pct"] = float(model.get("redepo_efficiency_pct", 0.0))
        rd["params"]["lobe_sigma_deg"] = float(model.get("redepo_lobe_sigma_deg", 20.0))
        out["redepo"] = rd
        return out

    def _format_result_parameters(self) -> str:
        recipe = self._result_recipe if isinstance(self._result_recipe, dict) else {}
        if not recipe:
            return self._tr("results.parameters_empty")

        lines: List[str] = []
        run = recipe.get("run") if isinstance(recipe.get("run"), dict) else {}
        stage = recipe.get("run_stage") if isinstance(recipe.get("run_stage"), dict) else {}
        smoothing = recipe.get("smoothing") if isinstance(recipe.get("smoothing"), dict) else {}
        switch_state = self._recipe_switch_state_for_results(recipe)

        case_name = str(run.get("case_name", "")).strip()
        if case_name:
            lines.append(f"{self._tr('run.case_name')}: {case_name}")
        if "cycles" in run:
            lines.append(f"{self._tr('run.cycles')}: {int(run.get('cycles', 0))}")

        stage_idx = 1
        try:
            stage_idx = max(1, int(stage.get("index", self._result_stage_info.get("index", 1))))
        except Exception:
            stage_idx = 1
        lines.append(f"{self._tr('results.param.stage')}: {stage_idx}")

        continued_from = str(stage.get("continued_from") or "").strip()
        if continued_from:
            lines.append(f"{self._tr('results.param.continued_from')}: {continued_from}")

        if smoothing:
            seg = int(smoothing.get("segments", 0))
            itr = int(smoothing.get("iterations", 0))
            lines.append(self._tf("results.param.smoothing_value", segments=seg, iterations=itr))

        lines.append("")
        lines.append(self._tr("results.param.active_switches"))
        appended = False
        for sw in PHASE1_SWITCH_SCHEMA:
            sid = str(sw.get("id", ""))
            state = switch_state.get(sid)
            if not isinstance(state, dict) or not bool(state.get("enabled", False)):
                continue
            title = self._tr(str(sw.get("title_key", sid)))
            lines.append(f"[{title}]")
            params = state.get("params")
            params_dict = params if isinstance(params, dict) else {}
            for pdef in sw.get("params", []):
                pid = str(pdef.get("id", ""))
                if not pid:
                    continue
                value = params_dict.get(pid, pdef.get("default"))
                label = self._tr(str(pdef.get("label_key", pid)))
                lines.append(f"  {label}: {self._format_result_param_value(pdef, value)}")
            appended = True
        if not appended:
            lines.append(self._tr("results.param.none"))
        return "\n".join(lines)

    def _update_result_parameter_view(self) -> None:
        self.edit_result_params.setPlainText(self._format_result_parameters())

    def _format_export_parameters(self) -> str:
        recipe = self._result_recipe if isinstance(self._result_recipe, dict) else {}
        if not recipe:
            return ""

        lines: List[str] = []
        run = recipe.get("run") if isinstance(recipe.get("run"), dict) else {}
        stage = recipe.get("run_stage") if isinstance(recipe.get("run_stage"), dict) else {}
        smoothing = recipe.get("smoothing") if isinstance(recipe.get("smoothing"), dict) else {}
        switch_state = self._recipe_switch_state_for_results(recipe)

        top_parts: List[str] = []
        case_name = str(run.get("case_name", "")).strip()
        if case_name:
            top_parts.append(f"{self._tr('run.case_name')}: {case_name}")
        if "cycles" in run:
            top_parts.append(f"{self._tr('run.cycles')}: {int(run.get('cycles', 0))}")
        try:
            stage_idx = max(1, int(stage.get("index", self._result_stage_info.get("index", 1))))
        except Exception:
            stage_idx = 1
        top_parts.append(f"{self._tr('results.param.stage')}: {stage_idx}")
        if top_parts:
            lines.append(" | ".join(top_parts))

        if smoothing:
            seg = int(smoothing.get("segments", 0))
            itr = int(smoothing.get("iterations", 0))
            lines.append(self._tf("results.param.smoothing_value", segments=seg, iterations=itr))

        for sw in PHASE1_SWITCH_SCHEMA:
            sid = str(sw.get("id", ""))
            state = switch_state.get(sid)
            if not isinstance(state, dict) or not bool(state.get("enabled", False)):
                continue
            params = state.get("params")
            params_dict = params if isinstance(params, dict) else {}
            parts: List[str] = []
            for pdef in sw.get("params", []):
                pid = str(pdef.get("id", ""))
                if not pid:
                    continue
                label = self._tr(str(pdef.get("label_key", pid)))
                value = params_dict.get(pid, pdef.get("default"))
                parts.append(f"{label}={self._format_result_param_value(pdef, value)}")
            title = self._tr(str(sw.get("title_key", sid)))
            lines.append(f"[{title}] " + ", ".join(parts))
        return "\n".join(lines)

    def _clear_result_view_state(self, *, message_key: str) -> None:
        self._frame_index = -1
        self._result_display_indices = []
        self._result_display_steps = []
        self._result_display_stage_ids = []
        self.slider_frame.blockSignals(True)
        self.slider_frame.setRange(0, 0)
        self.slider_frame.setValue(0)
        self.slider_frame.setEnabled(False)
        self.slider_frame.blockSignals(False)
        self.lbl_frame.setText(self._tr(message_key))
        self.result_view.clear_data()
        self._anim_timer.stop()
        self._refresh_anim_button_text()
        self._update_stage_visibility_controls()
        self._update_frame_step_buttons()

    def _load_result_frames(self, run_dir: Path) -> None:
        self._result_load_seq += 1
        seq = self._result_load_seq
        self._result_loading = True
        self._anim_timer.stop()
        self._refresh_anim_button_text()
        self._result_frames = []
        self._result_voids = []
        self._result_steps = []
        self._result_stage_ids = []
        self._result_stage_info = {"index": 1}
        self._result_recipe = {}
        self._result_meta = {}
        self._result_x_window = None
        self._result_void_mode = "legacy_cumulative"
        self._update_result_parameter_view()
        self._clear_result_view_state(message_key="results.loading")

        include_history = not (self._continuation_merge_pending and self._continuation_base_frames)
        th = QThread()
        worker = ResultLoadWorker(seq=seq, run_dir=run_dir, include_history=include_history)
        worker.moveToThread(th)
        th.started.connect(worker.run)
        worker.loaded.connect(self._on_result_load_loaded)
        worker.error.connect(self._on_result_load_error)
        worker.loaded.connect(th.quit)
        worker.error.connect(th.quit)
        th.finished.connect(worker.deleteLater)
        th.finished.connect(th.deleteLater)
        th.finished.connect(self._on_result_loader_thread_finished)

        self._result_loader_thread = th
        self._result_loader_worker = worker
        th.start()

    def _on_result_load_loaded(self, seq: int, payload_obj: object) -> None:
        if int(seq) != self._result_load_seq:
            return
        self._result_loading = False
        payload = payload_obj if isinstance(payload_obj, dict) else {}
        if not self._apply_result_payload(payload, fit=False):
            return

        if self._continuation_merge_pending and self._continuation_base_frames:
            self._merge_stages_with_continuation_base()
        elif not bool(payload.get("history_complete", False)):
            stage_idx = 1
            try:
                stage_idx = max(1, int(self._result_stage_info.get("index", 1)))
            except Exception:
                stage_idx = 1
            continued_from = self._result_stage_info.get("continued_from")
            if stage_idx > 1 and continued_from:
                base_dir = Path(str(continued_from))
                if (not base_dir.exists()) and (self._last_run_dir is not None):
                    alt = (self._last_run_dir.parent.parent / base_dir).resolve()
                    if alt.exists():
                        base_dir = alt
                base_payload = self._read_profiles_payload(base_dir)
                if base_payload and base_payload.get("frames"):
                    self._continuation_base_frames = [list(frame) for frame in base_payload.get("frames", [])]
                    self._continuation_base_voids = [list(vf) for vf in base_payload.get("voids", [])]
                    self._continuation_base_steps = [int(s) for s in base_payload.get("steps", [])]
                    self._continuation_base_stage_ids = [
                        max(1, int(s)) for s in base_payload.get("stage_ids", [])
                    ]
                    self._continuation_base_void_mode = (
                        "current"
                        if str(base_payload.get("void_mode", "legacy_cumulative")).lower() == "current"
                        else "legacy_cumulative"
                    )
                    self._continuation_base_run_dir = base_dir
                    self._continuation_stage_index = stage_idx
                    self._continuation_merge_pending = True
                    self._merge_stages_with_continuation_base()
        self._apply_default_show_every_n()
        self._rebuild_result_display(fit=True)

    def _merge_stages_with_continuation_base(self) -> None:
        base_frames = self._continuation_base_frames or []
        base_voids = self._continuation_base_voids or [[] for _ in base_frames]
        base_steps = self._continuation_base_steps or list(range(len(base_frames)))
        base_stage_ids = self._continuation_base_stage_ids or [1 for _ in base_frames]
        if len(base_stage_ids) != len(base_frames):
            base_stage_ids = [1 for _ in base_frames]
        stage_index = max(1, int(self._continuation_stage_index))

        new_frames = self._result_frames
        new_voids = self._result_voids
        new_steps = self._result_steps
        if not base_frames or not new_frames:
            self._clear_continuation_context(clear_base=True)
            return

        drop_head = 0
        if self._profiles_same(base_frames[-1], new_frames[0]):
            drop_head = 1

        used_new_frames = new_frames[drop_head:]
        used_new_voids = new_voids[drop_head:] if len(new_voids) >= len(new_frames) else [[] for _ in used_new_frames]
        used_new_steps = new_steps[drop_head:] if len(new_steps) >= len(new_frames) else list(range(len(used_new_frames)))

        merged_frames = list(base_frames) + list(used_new_frames)
        merged_voids = list(base_voids) + list(used_new_voids)

        step_counter = (base_steps[-1] + 1) if base_steps else 0
        merged_steps = list(base_steps)
        for _ in used_new_steps:
            merged_steps.append(step_counter)
            step_counter += 1

        merged_stage_ids = list(base_stage_ids) + [stage_index for _ in used_new_frames]
        base_void_mode = (
            "current"
            if str(self._continuation_base_void_mode or "legacy_cumulative").lower() == "current"
            else "legacy_cumulative"
        )
        new_void_mode = "current" if str(self._result_void_mode).lower() == "current" else "legacy_cumulative"
        merged_void_mode = "current" if (base_void_mode == "current" and new_void_mode == "current") else "legacy_cumulative"

        self._result_frames = merged_frames
        self._result_voids = merged_voids if len(merged_voids) == len(merged_frames) else [[] for _ in merged_frames]
        self._result_steps = merged_steps if len(merged_steps) == len(merged_frames) else list(range(len(merged_frames)))
        self._result_stage_ids = merged_stage_ids if len(merged_stage_ids) == len(merged_frames) else [1 for _ in merged_frames]
        self._result_void_mode = merged_void_mode
        self._result_stage_info = {
            "index": stage_index,
            "continued_from": str(self._continuation_base_run_dir) if self._continuation_base_run_dir else None,
        }
        inferred_window = self._infer_result_x_window_from_frames(self._result_frames)
        if self._result_x_window is None:
            self._result_x_window = inferred_window
        elif inferred_window is not None:
            self._result_x_window = (
                min(float(self._result_x_window[0]), float(inferred_window[0])),
                max(float(self._result_x_window[1]), float(inferred_window[1])),
            )

        self._persist_current_result_history_to_run_dir(self._last_run_dir)
        self._clear_continuation_context(clear_base=True)

    def _infer_result_x_window_from_frames(self, frames: List[List[Point]]) -> Optional[Tuple[float, float]]:
        xs = [float(x) for frame in frames for x, _y in frame]
        if not xs:
            return None
        return (min(xs), max(xs))

    def _persist_current_result_history_to_run_dir(self, run_dir: Optional[Path]) -> None:
        if run_dir is None or not self._result_frames:
            return
        run_dir = Path(run_dir)
        profiles_path = run_dir / "profiles.json"
        existing: Dict[str, Any] = {}
        try:
            if profiles_path.exists():
                loaded = json.loads(profiles_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
        except Exception:
            existing = {}

        x_window = self._result_x_window or self._infer_result_x_window_from_frames(self._result_frames)
        payload = dict(existing)
        payload.update(
            {
                "version": int(existing.get("version", 1) or 1),
                "stage": dict(self._result_stage_info or {"index": 1}),
                "frame_steps": [int(v) for v in self._result_steps],
                "frame_profiles": [
                    [[float(x), float(y)] for x, y in frame]
                    for frame in self._result_frames
                ],
                "frame_voids": [
                    [
                        [[float(x), float(y)] for x, y in poly]
                        for poly in frame_voids
                    ]
                    for frame_voids in self._result_voids
                ],
                "frame_voids_mode": (
                    "current" if str(self._result_void_mode).lower() == "current" else "legacy_cumulative"
                ),
                "frame_stage_ids": [max(1, int(v)) for v in self._result_stage_ids],
                "x_window": list(x_window) if x_window is not None else None,
                "history_self_contained": True,
                "history_saved_at_local": datetime.now().isoformat(timespec="seconds"),
            }
        )
        try:
            profiles_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.statusBar().showMessage(f"History save skipped: {exc}", 3000)

    def _on_result_load_error(self, seq: int, message: str) -> None:
        if int(seq) != self._result_load_seq:
            return
        self._result_loading = False
        self._result_frames = []
        self._result_voids = []
        self._result_steps = []
        self._result_stage_ids = []
        self._result_stage_info = {"index": 1}
        self._result_recipe = {}
        self._result_meta = {}
        self._result_x_window = None
        self._result_void_mode = "legacy_cumulative"
        self._update_result_parameter_view()
        self._clear_continuation_context(clear_base=True)
        self.statusBar().showMessage(self._tf("status.profile_parse_failed", error=message), 5000)
        self._clear_result_view_state(message_key="results.no_vector")

    def _on_result_loader_thread_finished(self) -> None:
        sender = self.sender()
        if sender is self._result_loader_thread:
            self._result_loading = False
            self._result_loader_thread = None
            self._result_loader_worker = None

    def _display_indices(self, total: int, every_n: int) -> List[int]:
        if total <= 0:
            return []
        step = max(1, int(every_n))
        indices = list(range(0, total, step))
        last = total - 1
        if not indices or indices[-1] != last:
            indices.append(last)
        return indices

    def _stabilize_void_series(self, void_series: List[List[List[Point]]]) -> List[List[List[Point]]]:
        # Once a trapped void appears, keep it visible and prevent artificial shrink due sampling/noise.
        if not void_series:
            return []

        def poly_area(poly: List[Point]) -> float:
            if len(poly) < 3:
                return 0.0
            s = 0.0
            n = len(poly)
            for i in range(n):
                x1, y1 = poly[i]
                x2, y2 = poly[(i + 1) % n]
                s += float(x1) * float(y2) - float(x2) * float(y1)
            return abs(s) * 0.5

        def total_area(polys: List[List[Point]]) -> float:
            return sum(poly_area(p) for p in polys)

        out: List[List[List[Point]]] = []
        prev: List[List[Point]] = []
        for frame_voids in void_series:
            current = [
                [(float(x), float(y)) for x, y in poly]
                for poly in (frame_voids or [])
                if len(poly) >= 3
            ]
            if not current:
                current = [
                    [(float(x), float(y)) for x, y in poly]
                    for poly in prev
                ]
            elif prev:
                prev_area = total_area(prev)
                cur_area = total_area(current)
                # Keep previous voids only when area regresses spuriously.
                # Polygon count can legitimately shrink (e.g. two pockets merge into one),
                # so count-based fallback causes large real voids to disappear.
                if cur_area + 1e-9 < prev_area * 0.995:
                    current = [
                        [(float(x), float(y)) for x, y in poly]
                        for poly in prev
                    ]
            out.append(current)
            prev = [
                [(float(x), float(y)) for x, y in poly]
                for poly in current
            ]
        return out

    def _recommended_show_every_n(self, total_frames: int) -> int:
        if total_frames <= 1:
            return 1
        total_cycles = total_frames - 1
        if len(self._result_steps) >= 2:
            try:
                total_cycles = max(1, int(self._result_steps[-1]) - int(self._result_steps[0]))
            except Exception:
                total_cycles = total_frames - 1
        return max(1, min(10_000, int(round(total_cycles / 20.0))))

    def _apply_default_show_every_n(self) -> None:
        recommended = self._recommended_show_every_n(len(self._result_frames))
        self._result_show_every_n = recommended
        self.spin_show_every.blockSignals(True)
        self.spin_show_every.setValue(recommended)
        self.spin_show_every.blockSignals(False)

    def _result_solid_fill_flags(self, stage_ids: List[int]) -> List[bool]:
        if not stage_ids:
            return []
        recipe = self._result_recipe if isinstance(self._result_recipe, dict) else {}
        if not recipe:
            return [False for _ in stage_ids]
        switch_state = self._recipe_switch_state_for_results(recipe)
        conformal_enabled = bool(switch_state.get("conformal", {}).get("enabled", True))
        sputter_state = switch_state.get("sputter", {})
        sputter_params = sputter_state.get("params") if isinstance(sputter_state, dict) else {}
        sputter_only = bool(sputter_params.get("sputter_only", False)) if isinstance(sputter_params, dict) else False
        if conformal_enabled and not sputter_only:
            return [False for _ in stage_ids]
        stage_cfg = recipe.get("run_stage") if isinstance(recipe.get("run_stage"), dict) else {}
        latest_stage = max(1, int(stage_cfg.get("index", self._result_stage_info.get("index", 1)) or 1))
        return [max(1, int(sid)) == latest_stage for sid in stage_ids]

    def _rebuild_result_display(self, *, fit: bool) -> None:
        if not self._result_frames:
            self._clear_result_view_state(message_key="results.no_vector")
            return

        self._result_show_every_n = max(1, int(self.spin_show_every.value()))
        next_indices = self._display_indices(len(self._result_frames), self._result_show_every_n)
        extra_stage_starts: List[int] = []
        seen_stages = set()
        for i, sid in enumerate(self._result_stage_ids):
            sid_int = max(1, int(sid))
            if sid_int <= 1:
                continue
            if sid_int not in seen_stages:
                seen_stages.add(sid_int)
                extra_stage_starts.append(i)
        if extra_stage_starts:
            next_indices.extend(extra_stage_starts)
            next_indices = sorted(set(next_indices))
        if not next_indices:
            self._clear_result_view_state(message_key="results.no_vector")
            return

        current_actual: Optional[int] = None
        if 0 <= self._frame_index < len(self._result_display_indices):
            current_actual = self._result_display_indices[self._frame_index]

        # Keep trapped-void rendering stable regardless of legacy/current metadata.
        effective_voids = self._stabilize_void_series(self._result_voids)

        display_frames = [self._result_frames[i] for i in next_indices]
        display_voids = [effective_voids[i] if i < len(effective_voids) else [] for i in next_indices]
        display_steps = [self._result_steps[i] if i < len(self._result_steps) else i for i in next_indices]
        display_stage_ids = [self._result_stage_ids[i] if i < len(self._result_stage_ids) else 1 for i in next_indices]
        solid_fill_flags = self._result_solid_fill_flags(display_stage_ids)

        self._result_display_indices = next_indices
        self._result_display_steps = display_steps
        self._result_display_stage_ids = display_stage_ids
        self.result_view.set_frames(
            display_frames,
            x_window=self._result_x_window,
            voids=display_voids,
            stage_ids=display_stage_ids,
            void_mode="legacy_cumulative",
            dynamic_substrate_fill=any(solid_fill_flags),
            solid_fill_flags=solid_fill_flags,
        )
        self._update_stage_visibility_controls()

        self.slider_frame.blockSignals(True)
        self.slider_frame.setRange(0, len(display_frames) - 1)
        self.slider_frame.setEnabled(True)

        target_idx = len(display_frames) - 1
        if current_actual is not None:
            target_idx = min(
                range(len(next_indices)),
                key=lambda i: abs(next_indices[i] - current_actual),
            )
        self.slider_frame.setValue(target_idx)
        self.slider_frame.blockSignals(False)
        self._show_frame(target_idx, fit=fit)
        self._update_frame_step_buttons()

    def _show_frame(self, idx: int, *, fit: bool = False) -> None:
        if not self._result_display_indices:
            return
        idx = max(0, min(idx, len(self._result_display_indices) - 1))
        ok = self.result_view.show_frame(idx, fit=fit)
        self._frame_index = idx

        step_txt = ""
        if 0 <= idx < len(self._result_display_steps):
            step_txt = self._tf("results.frame_step", step=self._result_display_steps[idx])
        stage_txt = ""
        if 0 <= idx < len(self._result_display_stage_ids):
            stage_txt = self._tf("results.frame_stage", stage=self._result_display_stage_ids[idx])
        if ok:
            self.lbl_frame.setText(f"{idx + 1}/{len(self._result_display_indices)}{step_txt}{stage_txt}")
        else:
            self.lbl_frame.setText(
                self._tf(
                    "results.frame_draw_failed",
                    idx=idx + 1,
                    total=len(self._result_display_indices),
                )
            )
        self._update_frame_step_buttons()

    def _refresh_result_view(self) -> None:
        if not self._last_run_dir:
            return
        if self._result_loading:
            return
        if not self._result_frames:
            self._load_result_frames(self._last_run_dir)
            return
        if not self._result_display_indices:
            self._rebuild_result_display(fit=True)
            return
        if self._frame_index < 0 or self._frame_index >= len(self._result_display_indices):
            self._show_frame(len(self._result_display_indices) - 1, fit=True)
            return
        self._show_frame(self._frame_index, fit=False)

    def _on_frame_changed(self, idx: int) -> None:
        self._show_frame(idx, fit=False)

    def _step_frame_by(self, delta: int) -> None:
        if not self._result_display_indices:
            return
        cur = int(self.slider_frame.value())
        max_idx = len(self._result_display_indices) - 1
        nxt = max(0, min(max_idx, cur + int(delta)))
        if nxt != cur:
            self.slider_frame.setValue(nxt)
        else:
            self._update_frame_step_buttons()

    def _update_frame_step_buttons(self) -> None:
        has = bool(self._result_display_indices)
        if not has:
            self.btn_frame_prev.setEnabled(False)
            self.btn_frame_next.setEnabled(False)
            return
        cur = int(self.slider_frame.value())
        max_idx = len(self._result_display_indices) - 1
        self.btn_frame_prev.setEnabled(cur > 0)
        self.btn_frame_next.setEnabled(cur < max_idx)

    def _on_show_every_changed(self, every_n: int) -> None:
        self._result_show_every_n = max(1, int(every_n))
        if self._result_frames:
            self._rebuild_result_display(fit=False)

    def _on_decimation_changed(self, _index: int) -> None:
        stride = int(self.combo_decimation.currentData() or 1)
        self.result_view.set_decimation_stride(stride)
        if self._result_display_indices:
            idx = self._frame_index if self._frame_index >= 0 else (len(self._result_display_indices) - 1)
            self._show_frame(idx, fit=False)

    def _toggle_animation(self) -> None:
        if not self._result_display_indices:
            return
        if self._anim_timer.isActive():
            self._anim_timer.stop()
        else:
            self._anim_timer.start()
        self._refresh_anim_button_text()

    def _advance_frame(self) -> None:
        if not self._result_display_indices:
            self._anim_timer.stop()
            self._refresh_anim_button_text()
            return
        nxt = (self.slider_frame.value() + 1) % len(self._result_display_indices)
        self.slider_frame.setValue(nxt)

    def _on_fps_changed(self, fps: int) -> None:
        fps = max(1, int(fps))
        self.lbl_fps.setText(str(fps))
        self._anim_timer.setInterval(max(20, int(round(1000.0 / fps))))

    def _on_show_initial_points_toggled(self, checked: bool) -> None:
        self.result_view.set_show_initial_points(bool(checked))
        if self._result_display_indices:
            idx = self._frame_index if self._frame_index >= 0 else (len(self._result_display_indices) - 1)
            self._show_frame(idx, fit=False)

    def _fit_snapshot(self) -> None:
        self.result_view.fit_content()

    def _open_run_dir(self) -> None:
        if self._last_run_dir and self._last_run_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_run_dir)))

    def _render_export_frames_png(self, out_dir: Path) -> List[Path]:
        if not self._result_frames or not self._result_display_indices:
            return []

        out_dir.mkdir(parents=True, exist_ok=True)
        outputs: List[Path] = []
        was_animating = self._anim_timer.isActive()
        if was_animating:
            self._anim_timer.stop()
            self._refresh_anim_button_text()

        prev_idx = self._frame_index if self._frame_index >= 0 else 0
        try:
            self.result_view.fit_content()
            QApplication.processEvents()
            target = self.result_content_splitter
            width = max(1, target.width())
            height = max(1, target.height())
            for idx in range(len(self._result_display_indices)):
                self._show_frame(idx, fit=False)
                QApplication.processEvents()
                out_png = out_dir / f"frame_{idx:05d}.png"
                image = QImage(width, height, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.white)
                painter = QPainter(image)
                target.render(painter)
                painter.end()
                image.save(str(out_png))
                outputs.append(out_png)
        finally:
            if self._result_display_indices:
                self._show_frame(prev_idx, fit=False)
            if was_animating:
                self._anim_timer.start()
                self._refresh_anim_button_text()
        return outputs

    def _render_export_frames_pil(self) -> List[Any]:
        if not self._result_frames or not self._result_display_indices:
            return []
        try:
            from PIL import Image
        except Exception as exc:
            raise RuntimeError(self._tr("dialog.export.pillow_missing")) from exc

        images: List[Any] = []
        was_animating = self._anim_timer.isActive()
        if was_animating:
            self._anim_timer.stop()
            self._refresh_anim_button_text()

        prev_idx = self._frame_index if self._frame_index >= 0 else 0
        try:
            self.result_view.fit_content()
            QApplication.processEvents()
            target = self.result_content_splitter
            width = max(1, target.width())
            height = max(1, target.height())
            for idx in range(len(self._result_display_indices)):
                self._show_frame(idx, fit=False)
                QApplication.processEvents()
                image = QImage(width, height, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.white)
                painter = QPainter(image)
                target.render(painter)
                painter.end()

                png_bytes = QByteArray()
                buffer = QBuffer(png_bytes)
                if not buffer.open(QBuffer.OpenModeFlag.WriteOnly):
                    raise RuntimeError("Failed to open in-memory buffer for GIF export.")
                try:
                    ok = image.save(buffer, b"PNG")
                finally:
                    buffer.close()
                if not ok:
                    raise RuntimeError("Failed to render an export frame image.")
                frame = Image.open(BytesIO(bytes(png_bytes)))
                frame.load()
                images.append(frame.convert("RGB"))
                frame.close()
        finally:
            if self._result_display_indices:
                self._show_frame(prev_idx, fit=False)
            if was_animating:
                self._anim_timer.start()
                self._refresh_anim_button_text()
        return images

    def _export_animation_gif(self, _checked: bool = False) -> None:
        if not self._result_frames:
            QMessageBox.warning(self, self._tr("dialog.export.title"), self._tr("dialog.export.no_frames"))
            return
        try:
            from PIL import Image
        except Exception:
            QMessageBox.warning(
                self,
                self._tr("dialog.export.title"),
                self._tr("dialog.export.pillow_missing"),
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("dialog.export.gif_title"),
            "",
            "GIF (*.gif);;All Files (*)",
        )
        if not path:
            return
        out_path = Path(path)
        if out_path.suffix.lower() != ".gif":
            out_path = out_path.with_suffix(".gif")

        fps = max(1, int(self.slider_fps.value()))
        frame_ms = max(1, int(round(1000.0 / fps)))
        try:
            images = self._render_export_frames_pil()
            if not images:
                raise RuntimeError(self._tr("dialog.export.no_frames"))
            try:
                images[0].save(
                    str(out_path),
                    save_all=True,
                    append_images=images[1:],
                    duration=frame_ms,
                    loop=0,
                )
            finally:
                for img in images:
                    img.close()
            self.statusBar().showMessage(self._tf("status.export_done", path=str(out_path)), 3000)
        except Exception as exc:
            QMessageBox.critical(self, self._tr("dialog.export.title"), str(exc))

    # ---------------- misc ----------------
    def _on_run_advanced_toggled(self, checked: bool) -> None:
        self.run_advanced_body.setVisible(bool(checked))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.right_stack.currentWidget() is self._panel_scroll_widgets.get("results"):
            self._refresh_result_view()

    def closeEvent(self, event):
        self._anim_timer.stop()
        self._result_load_seq += 1
        self._result_loading = False
        if self._result_loader_thread is not None and self._result_loader_thread.isRunning():
            try:
                self._result_loader_thread.quit()
                self._result_loader_thread.wait(2000)
            except Exception:
                pass
        if self._engine_thread is not None and self._engine_thread.isRunning():
            try:
                if self._engine_worker is not None:
                    self._engine_worker.request_cancel()
                self._engine_thread.quit()
                self._engine_thread.wait(2000)
            except Exception:
                pass
        if self._prediction_thread is not None and self._prediction_thread.isRunning():
            try:
                if self._prediction_worker is not None:
                    self._prediction_worker.request_cancel()
                self._prediction_thread.quit()
                self._prediction_thread.wait(2000)
            except Exception:
                pass
        super().closeEvent(event)


def main() -> int:
    from gapsim.ui_qt.launcher_window import LauncherWindow

    app = QApplication(sys.argv)
    w = LauncherWindow()
    w.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
