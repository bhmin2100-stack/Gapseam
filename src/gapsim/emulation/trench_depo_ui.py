from __future__ import annotations

from dataclasses import replace
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, QEvent, QMimeData, QPointF, QRectF, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QBrush, QDesktopServices, QDrag, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStatusBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gapsim.emulation.research_registry import (
    MAX_EMULATOR_NUMBER,
    ensure_emulator_research_slot,
    load_created_emulator_numbers,
    next_emulator_number,
    save_created_emulator_numbers,
)
from gapsim.emulation.parameter_library import (
    DEFAULT_PARAMETER_LIBRARY_PATH,
    delete_parameter_preset,
    list_parameter_presets,
    read_parameter_preset,
    sanitize_parameter_preset_name,
    save_parameter_preset,
)
from gapsim.emulation.structure_library import (
    DEFAULT_EMULATOR_STRUCTURE_SHEETS,
    DEFAULT_STRUCTURE_LIBRARY_PATH,
    StructureLibraryError,
    delete_structure_sheet,
    ensure_default_structures,
    list_structure_names,
    read_structure_points,
    sanitize_structure_name,
    save_structure_points,
)
from gapsim.emulation.trench_depo import (
    BOWED_JAR_TRENCH_POINTS,
    ION_TRANSMISSION_STEPPED_TRENCH_POINTS,
    TrenchDepoConfig,
    TrenchDepoResult,
    TrenchSweepResult,
    compute_depth_deposition_ratio,
    compute_effective_aspect_ratio,
    run_trench_depo,
    run_trench_depo_legacy_redeposition,
    run_trench_depo_legacy_sputter,
    run_trench_depo_sweep,
)
from gapsim.emulation.trench_depo_export import (
    DEFAULT_RESULTS_ROOT,
    DEFAULT_RUNS_ROOT,
    export_trench_depo_run,
    export_trench_depo_sweep_runs,
    load_trench_depo_run,
    load_trench_depo_split_group,
    save_trench_depo_result_json,
)
from gapsim.ui_qt.calibrate_dialog import CalibrateDialog
from gapsim.ui_qt.controllers.smoothing_ctrl import SmoothingController
from gapsim.ui_qt.models.points_table import PointsTableModel
from gapsim.ui_qt.models.points_table_view import PointsTableView
from gapsim.ui_qt.views.result_vector_view import ResultVectorView
from gapsim.ui_qt.views.structure_view import StructureView


OVERLAY_AUTO_DECIMATION_TARGET_POINTS = 2200
DEFAULT_UI_REPARAM_DS_A = 10.0
QUALITY_MODE_PRESETS: Tuple[Tuple[str, Optional[float]], ...] = (
    ("빠름 (20 A)", 20.0),
    ("보통 (10 A)", DEFAULT_UI_REPARAM_DS_A),
    ("정밀 (5 A)", 5.0),
    ("최정밀 (2.5 A)", 2.5),
    ("사용자", None),
)
MODEL_SECTION_MIME = "application/x-gapsim-emulation-model-section"
DEFAULT_MODEL_PARAMETER_SECTION_ORDER: Tuple[str, ...] = (
    "direct",
    "ion",
    "reflected",
    "redepo",
    "depth",
    "inhibition",
    "lf",
    "closure",
)


def _display_decimation_stride(profiles: Sequence[Sequence[Tuple[float, float]]]) -> int:
    max_points = max((len(profile) for profile in profiles), default=0)
    if max_points <= OVERLAY_AUTO_DECIMATION_TARGET_POINTS:
        return 1
    return max(1, int(math.ceil(max_points / float(OVERLAY_AUTO_DECIMATION_TARGET_POINTS))))


def _decimate_profile_for_display(
    profile: Sequence[Tuple[float, float]],
    stride: int,
) -> List[Tuple[float, float]]:
    if stride <= 1 or len(profile) <= 2:
        return [(float(x), float(y)) for x, y in profile]
    out: List[Tuple[float, float]] = [(float(profile[0][0]), float(profile[0][1]))]
    for idx in range(1, len(profile) - 1):
        if idx % stride == 0:
            out.append((float(profile[idx][0]), float(profile[idx][1])))
    out.append((float(profile[-1][0]), float(profile[-1][1])))
    return out


def _use_solid_playback(result: TrenchDepoResult) -> bool:
    if not bool(result.meta.get("sputter_active")):
        return False
    try:
        depo_a = float(result.meta.get("angstrom_per_cycle", 0.0))
        etch_a = float(result.meta.get("sputter_strength_a_per_cycle", 0.0))
    except (TypeError, ValueError):
        return True
    return etch_a > depo_a + 1e-9


def _elide_middle(text: str, max_chars: int) -> str:
    raw = str(text)
    limit = max(3, int(max_chars))
    if len(raw) <= limit:
        return raw
    keep = max(1, limit - 3)
    left = (keep + 1) // 2
    right = keep // 2
    return f"{raw[:left]}...{raw[-right:]}"


def _depth_deposition_display_mode(value: object) -> str:
    raw = str(value or "depo_rate").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"attenuation", "depletion", "decay", "loss", "drop"}:
        return "attenuation"
    return "depo_rate"


def _depth_deposition_depth_transform_text(
    *,
    feature_type: object,
    feature_width_a: float,
    feature_length_a: Optional[float],
) -> str:
    width = max(1e-9, float(feature_width_a))
    type_key = str(feature_type or "hole").strip().lower()
    if type_key in {"line", "trench"}:
        length = None if feature_length_a is None else float(feature_length_a)
        if length is None or not math.isfinite(length) or length <= 0.0 or length >= width * 1000.0:
            return f"g(z)=z/(2*W), W={width:.1f} A"
        return f"g(z)=z*(W+L)/(2*W*L), W={width:.1f} A, L={length:.1f} A"
    return f"g(z)=z/W, W={width:.1f} A"


def _depth_deposition_ratio_expression(attenuation_model: str, variable: str = "g(z)") -> str:
    model = str(attenuation_model or "exponential").strip().lower()
    if model == "power":
        raw = f"1/(1+K*{variable}^P)"
    elif model == "logistic":
        raw = f"1/(1+({variable}/(1/K))^P)"
    else:
        raw = f"exp(-K*{variable}^P)"
    return f"R(z)=m+(1-m)*{raw}"


def _depth_deposition_formula_text(
    *,
    display_mode: object,
    base_rate_a_per_cycle: float,
    attenuation_model: str,
    depth_decay_k: float,
    depth_decay_power: float,
    min_ratio_pct: float,
    feature_type: object = "hole",
    feature_width_a: float = 240.0,
    feature_length_a: Optional[float] = None,
) -> str:
    mode = _depth_deposition_display_mode(display_mode)
    ratio_expr = _depth_deposition_ratio_expression(attenuation_model, "g(z)")
    depth_transform = _depth_deposition_depth_transform_text(
        feature_type=feature_type,
        feature_width_a=feature_width_a,
        feature_length_a=feature_length_a,
    )
    base = max(0.0, float(base_rate_a_per_cycle))
    k = max(0.0, float(depth_decay_k))
    power = max(0.05, float(depth_decay_power))
    min_pct = max(0.0, min(100.0, float(min_ratio_pct)))
    if mode == "attenuation":
        return (
            f"감쇄식: depletion(z)=1-R(z), {ratio_expr}, {depth_transform}; "
            f"K={k:.3f}, P={power:.2f}, m={min_pct:.1f}%"
        )
    return (
        f"Dep rate식: dep_rate(z)=D0*R(z), {ratio_expr}, {depth_transform}; "
        f"D0={base:.3f} A/CYC, K={k:.3f}, P={power:.2f}, m={min_pct:.1f}%"
    )


def _profiles_same_points(
    a: Sequence[Tuple[float, float]],
    b: Sequence[Tuple[float, float]],
    *,
    tol: float = 1e-6,
) -> bool:
    if len(a) != len(b):
        return False
    for (ax, ay), (bx, by) in zip(a, b):
        if abs(float(ax) - float(bx)) > tol or abs(float(ay) - float(by)) > tol:
            return False
    return True


def _result_frame_series(
    result: TrenchDepoResult,
    key: str,
) -> List[Any]:
    raw = result.meta.get(key)
    if isinstance(raw, list) and len(raw) == len(result.frame_profiles):
        return list(raw)
    return [[] for _ in result.frame_profiles]


def merge_continued_trench_result(
    base_result: TrenchDepoResult,
    next_result: TrenchDepoResult,
    *,
    stage_index: int,
    continued_from_run: Optional[Path],
) -> TrenchDepoResult:
    """Return a self-contained result that includes all previous Depo stages."""

    if not base_result.frame_profiles or not next_result.frame_profiles:
        return next_result

    stage_i = max(2, int(stage_index))
    drop_head = 1 if _profiles_same_points(base_result.frame_profiles[-1], next_result.frame_profiles[0]) else 0
    used_frames = list(next_result.frame_profiles[drop_head:])
    used_voids = (
        list(next_result.frame_voids[drop_head:])
        if len(next_result.frame_voids) == len(next_result.frame_profiles)
        else [[] for _ in used_frames]
    )

    base_steps = (
        [int(v) for v in base_result.frame_steps]
        if len(base_result.frame_steps) == len(base_result.frame_profiles)
        else list(range(len(base_result.frame_profiles)))
    )
    merged_steps = list(base_steps)
    step_counter = (merged_steps[-1] + 1) if merged_steps else 0
    for _ in used_frames:
        merged_steps.append(step_counter)
        step_counter += 1

    base_voids = (
        list(base_result.frame_voids)
        if len(base_result.frame_voids) == len(base_result.frame_profiles)
        else [[] for _ in base_result.frame_profiles]
    )
    merged_frames = list(base_result.frame_profiles) + used_frames
    merged_voids = base_voids + used_voids

    meta = dict(next_result.meta)
    base_meta = dict(base_result.meta)
    for key in ("frame_redepo_overlays", "frame_etch_overlays", "frame_transport_lines"):
        meta[key] = _result_frame_series(base_result, key) + _result_frame_series(next_result, key)[drop_head:]

    previous_history = base_meta.get("stage_history")
    if isinstance(previous_history, list) and previous_history:
        stage_history = [dict(item) for item in previous_history if isinstance(item, Mapping)]
    else:
        base_stage = int(base_meta.get("stage_index", base_meta.get("stage_count", 1)) or 1)
        stage_history = [
            {
                "stage": max(1, base_stage),
                "start_step": int(base_steps[0]) if base_steps else 0,
                "end_step": int(base_steps[-1]) if base_steps else 0,
                "frames": len(base_result.frame_profiles),
            }
        ]

    if used_frames:
        stage_history.append(
            {
                "stage": stage_i,
                "start_step": int(merged_steps[len(base_result.frame_profiles)]),
                "end_step": int(merged_steps[-1]),
                "frames": len(used_frames),
                "continued_from_run": "" if continued_from_run is None else str(Path(continued_from_run)),
            }
        )

    meta.update(
        {
            "cycles": int(merged_steps[-1]) if merged_steps else int(meta.get("cycles", 0) or 0),
            "stage_cycles": int(next_result.meta.get("cycles", max(0, len(next_result.frame_profiles) - 1)) or 0),
            "stage_index": stage_i,
            "stage_count": max(stage_i, int(base_meta.get("stage_count", 1) or 1)),
            "continued_from_run": "" if continued_from_run is None else str(Path(continued_from_run)),
            "history_self_contained": True,
            "stage_history": stage_history,
            "initial_points": len(merged_frames[0]) if merged_frames else int(meta.get("initial_points", 0) or 0),
            "final_points": len(next_result.final_profile),
        }
    )

    return TrenchDepoResult(
        frame_steps=merged_steps,
        frame_profiles=merged_frames,
        frame_voids=merged_voids if len(merged_voids) == len(merged_frames) else [[] for _ in merged_frames],
        final_profile=list(next_result.final_profile),
        meta=meta,
    )


_DEFAULT_STRUCTURE_PRESET_NAMES = {
    "em00_integrated_depo_etch_depth": "통합 트렌치",
    "em01_conformal": "기본 트렌치",
    "em02_direct_sputter": "기본 트렌치",
    "em03_ion_transmission_etch": "계단형 트렌치",
    "em04_depth_depletion": "Bowed Jar 트렌치",
    "em05_inhibition": "Bowed Jar 트렌치",
    "em06_reflection_redepo": "반사 리데포 트렌치",
}

_DEFAULT_STRUCTURE_PRESET_CANONICAL = {
    "em00_integrated_depo_etch_depth": "em05_inhibition",
    "em01_conformal": "em01_conformal",
    "em02_direct_sputter": "em01_conformal",
    "em03_ion_transmission_etch": "em03_ion_transmission_etch",
    "em04_depth_depletion": "em04_depth_depletion",
    "em05_inhibition": "em05_inhibition",
    "em06_reflection_redepo": "em01_conformal",
}


def _structure_preset_display_name(sheet_name: str) -> str:
    raw = str(sheet_name or "").strip()
    if raw in _DEFAULT_STRUCTURE_PRESET_NAMES:
        return _DEFAULT_STRUCTURE_PRESET_NAMES[raw]
    cleaned = raw.replace("_", " ").strip()
    return cleaned or "사용자 구조"


def _structure_preset_items(sheet_names: Sequence[str]) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for sheet_name in sheet_names:
        sheet = str(sheet_name or "").strip()
        if not sheet:
            continue
        canonical = _DEFAULT_STRUCTURE_PRESET_CANONICAL.get(sheet, sheet)
        if canonical in seen:
            continue
        seen.add(canonical)
        items.append((_structure_preset_display_name(sheet), sheet))
    return items


EMULATOR_MODE_TITLES = {
    0: "Integrated depo/etch/depletion/inhibition",
    1: "Conformal depo baseline",
    2: "Direct angle sputter etch",
    3: "Ion transmission etch",
    4: "Depth depletion depo fill",
    5: "Inhibition deposition fill",
    6: "Normal/specular lobe redepo",
}


def _emulator_mode_title(number: int) -> str:
    number_i = int(number)
    if number_i in EMULATOR_MODE_TITLES:
        return EMULATOR_MODE_TITLES[number_i]
    return "Unassigned conformal baseline"


def _emulator_mode_label(number: int) -> str:
    return _emulator_mode_title(int(number))


EMULATOR_PROCESS_PRESETS: dict[int, list[tuple[str, dict[str, object]]]] = {
    0: [
        ("Integrated default", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "redepo": True, "depth": True, "etch": 4.0, "peak": 55.0, "width": 14.0, "redepo_eff": 30.0, "redepo_emit": 22.0, "redepo_dist": 25.0, "depth_k": 0.55, "depth_power": 1.2, "depth_min": 8.0}),
        ("Soft integrated", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "redepo": True, "depth": True, "etch": 2.5, "peak": 55.0, "width": 18.0, "redepo_eff": 22.0, "redepo_emit": 28.0, "redepo_dist": 15.0, "depth_k": 0.35, "depth_power": 1.0, "depth_min": 12.0}),
        ("Strong etch/depletion", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "redepo": True, "depth": True, "etch": 6.0, "peak": 58.0, "width": 12.0, "redepo_eff": 35.0, "redepo_emit": 18.0, "redepo_dist": 35.0, "depth_k": 0.9, "depth_power": 1.4, "depth_min": 5.0}),
    ],
    1: [
        ("Baseline conformal", {"cycles": 20, "depo": 10.0}),
        ("Quick conformal", {"cycles": 8, "depo": 10.0}),
    ],
    2: [
        ("Direct sputter default", {"cycles": 20, "depo": 10.0, "sputter": True, "etch": 4.0, "peak": 55.0, "width": 14.0}),
        ("Soft direct etch", {"cycles": 20, "depo": 10.0, "sputter": True, "etch": 2.0, "peak": 55.0, "width": 18.0}),
        ("Strong direct etch", {"cycles": 20, "depo": 10.0, "sputter": True, "etch": 7.0, "peak": 58.0, "width": 12.0}),
    ],
    3: [
        ("Ion depth default", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "ion_start": 0.0, "ion_end": 100.0, "ion_drop": 100.0, "ion_floor": 0.0, "ion_curve": 1.0}),
        ("Top-open ion", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "ion_start": 20.0, "ion_end": 100.0, "ion_drop": 80.0, "ion_floor": 10.0, "ion_curve": 1.2}),
        ("Deep-select ion", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "ion_start": 45.0, "ion_end": 100.0, "ion_drop": 100.0, "ion_floor": 0.0, "ion_curve": 1.8}),
    ],
    4: [
        ("Depth fill default", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.8, "depth_power": 1.2, "depth_min": 3.0}),
        ("Gentle depth fill", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.45, "depth_power": 1.0, "depth_min": 8.0}),
        ("Strong top loss", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 1.35, "depth_power": 1.4, "depth_min": 2.0}),
    ],
    5: [
        ("Inhibition default", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.8, "depth_power": 1.2, "depth_min": 8.0}),
        ("Soft inhibition", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.45, "depth_power": 1.0, "depth_min": 12.0}),
        ("Strong inhibition", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 1.25, "depth_power": 1.5, "depth_min": 5.0}),
    ],
    6: [
        ("Reflection lobe default", {"cycles": 20, "depo": 10.0, "sputter": True, "redepo": True, "etch": 4.0, "peak": 55.0, "width": 14.0, "redepo_eff": 30.0, "redepo_emit": 22.0, "redepo_dist": 25.0}),
        ("Narrow normal lobe", {"cycles": 20, "depo": 10.0, "sputter": True, "redepo": True, "etch": 5.0, "peak": 58.0, "width": 12.0, "redepo_eff": 35.0, "redepo_emit": 12.0, "redepo_dist": 15.0}),
        ("Wide specular-biased lobe", {"cycles": 20, "depo": 10.0, "sputter": True, "redepo": True, "etch": 3.5, "peak": 55.0, "width": 18.0, "redepo_eff": 25.0, "redepo_emit": 34.0, "redepo_dist": 45.0}),
    ],
}


def _map_structure_points_to_rect(
    points: Sequence[Tuple[float, float]],
    rect: QRectF,
) -> List[QPointF]:
    if len(points) < 2:
        return []
    xs = [float(x) for x, _y in points]
    ys = [float(y) for _x, y in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = max(x_max - x_min, 1e-9)
    y_span = max(y_max - y_min, 1e-9)
    return [
        QPointF(
            rect.left() + (rect.width() * ((float(x) - x_min) / x_span)),
            rect.top() + (rect.height() * ((y_max - float(y)) / y_span)),
        )
        for x, y in points
    ]


def _draw_structure_background(
    painter: QPainter,
    points: Sequence[Tuple[float, float]],
    rect: QRectF,
    *,
    fill_color: Optional[QColor] = None,
    line_color: Optional[QColor] = None,
    line_width: float = 1.7,
) -> None:
    mapped_points = _map_structure_points_to_rect(points, rect)
    if len(mapped_points) < 2:
        return

    profile = QPainterPath()
    for idx, point in enumerate(mapped_points):
        if idx == 0:
            profile.moveTo(point)
        else:
            profile.lineTo(point)

    solid = QPainterPath()
    solid.moveTo(mapped_points[0])
    for point in mapped_points[1:]:
        solid.lineTo(point)
    solid.lineTo(QPointF(mapped_points[-1].x(), rect.bottom()))
    solid.lineTo(QPointF(mapped_points[0].x(), rect.bottom()))
    solid.closeSubpath()

    painter.save()
    painter.setClipRect(rect)
    painter.fillPath(solid, fill_color or QColor(226, 232, 240, 92))
    painter.setPen(QPen(line_color or QColor(51, 65, 85, 170), line_width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(profile)
    painter.restore()


class SputterGaussianEditor(QWidget):
    parametersChanged = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._peak_pct = 100.0
        self._peak_deg = 55.0
        self._width_deg = 14.0
        self._etch_cap_a = 4.0
        self._drag_handle: Optional[str] = None
        self._percent_range = (0.0, 100.0)
        self._peak_range = (0.0, 89.9)
        self._width_range = (1.0, 60.0)
        self.setMinimumHeight(132)
        self.setMaximumHeight(156)
        self.setMouseTracking(True)
        self.setToolTip("Drag peak to set peak angle and peak percent. Drag side handles to set width.")

    def parameters(self) -> Tuple[float, float, float]:
        return (float(self._peak_pct), float(self._peak_deg), float(self._width_deg))

    def set_parameters(self, peak_pct: float, peak_deg: float, width_deg: float) -> None:
        pct_f = self._clamp(float(peak_pct), *self._percent_range)
        peak_f = self._clamp(float(peak_deg), *self._peak_range)
        width_f = self._clamp(float(width_deg), *self._width_range)
        changed = (
            abs(pct_f - self._peak_pct) > 1e-9
            or abs(peak_f - self._peak_deg) > 1e-9
            or abs(width_f - self._width_deg) > 1e-9
        )
        self._peak_pct = pct_f
        self._peak_deg = peak_f
        self._width_deg = width_f
        if changed:
            self.update()

    def set_etch_cap_a(self, etch_cap_a: float) -> None:
        cap_f = max(0.0, float(etch_cap_a))
        if abs(cap_f - self._etch_cap_a) <= 1e-9:
            return
        self._etch_cap_a = cap_f
        self.update()

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(float(low), min(float(high), float(value)))

    def _plot_rect(self) -> QRectF:
        return QRectF(46.0, 24.0, max(80.0, float(self.width()) - 66.0), max(36.0, float(self.height()) - 58.0))

    def _x_for_angle(self, angle_deg: float) -> float:
        rect = self._plot_rect()
        t = self._clamp(float(angle_deg) / 90.0, 0.0, 1.0)
        return rect.left() + (rect.width() * t)

    def _angle_for_x(self, x: float) -> float:
        rect = self._plot_rect()
        if rect.width() <= 1e-9:
            return 0.0
        t = self._clamp((float(x) - rect.left()) / rect.width(), 0.0, 1.0)
        return 90.0 * t

    def _y_for_percent(self, percent: float) -> float:
        rect = self._plot_rect()
        t = self._clamp(float(percent) / self._percent_range[1], 0.0, 1.0)
        return rect.bottom() - (rect.height() * t)

    def _percent_for_y(self, y: float) -> float:
        rect = self._plot_rect()
        if rect.height() <= 1e-9:
            return 0.0
        t = self._clamp((rect.bottom() - float(y)) / rect.height(), 0.0, 1.0)
        return self._percent_range[1] * t

    def _response_percent_at(self, angle_deg: float) -> float:
        width = max(1e-9, float(self._width_deg))
        z = (float(angle_deg) - float(self._peak_deg)) / width
        return float(self._peak_pct) * math.exp(-0.5 * z * z)

    def _handle_points(self) -> dict[str, QPointF]:
        side_pct = float(self._peak_pct) * math.exp(-0.5)
        return {
            "peak": QPointF(self._x_for_angle(self._peak_deg), self._y_for_percent(self._peak_pct)),
            "left_width": QPointF(
                self._x_for_angle(max(0.0, self._peak_deg - self._width_deg)),
                self._y_for_percent(side_pct),
            ),
            "right_width": QPointF(
                self._x_for_angle(min(90.0, self._peak_deg + self._width_deg)),
                self._y_for_percent(side_pct),
            ),
        }

    def _hit_handle(self, pos: QPointF) -> Optional[str]:
        best_name: Optional[str] = None
        best_dist_sq = 12.0 * 12.0
        for name, hp in self._handle_points().items():
            dx = float(pos.x() - hp.x())
            dy = float(pos.y() - hp.y())
            dist_sq = (dx * dx) + (dy * dy)
            if dist_sq <= best_dist_sq:
                best_name = name
                best_dist_sq = dist_sq
        return best_name

    def _emit_parameters_changed(self) -> None:
        self.parametersChanged.emit(float(self._peak_pct), float(self._peak_deg), float(self._width_deg))

    def _apply_drag(self, handle: str, pos: QPointF) -> None:
        if handle == "peak":
            self._peak_deg = self._clamp(self._angle_for_x(pos.x()), *self._peak_range)
            self._peak_pct = self._clamp(self._percent_for_y(pos.y()), *self._percent_range)
        elif handle in {"left_width", "right_width"}:
            angle = self._angle_for_x(pos.x())
            self._width_deg = self._clamp(abs(angle - float(self._peak_deg)), *self._width_range)
        else:
            return
        self.update()
        self._emit_parameters_changed()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        handle = self._hit_handle(pos)
        if handle is None and self._plot_rect().contains(pos):
            handle = "peak"
        if handle is None:
            super().mousePressEvent(event)
            return
        self._drag_handle = handle
        self._apply_drag(handle, pos)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag_handle is not None:
            self._apply_drag(self._drag_handle, pos)
            event.accept()
            return
        handle = self._hit_handle(pos)
        if handle == "peak":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif handle in {"left_width", "right_width"}:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_handle is not None:
            self._drag_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_handle is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._plot_rect()
        painter.fillRect(self.rect(), QColor(248, 250, 252))
        painter.setPen(QPen(QColor(203, 213, 225), 1.0))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(rect, 5.0, 5.0)

        painter.setPen(QPen(QColor(226, 232, 240), 1.0))
        for angle in (0.0, 30.0, 60.0, 90.0):
            x = self._x_for_angle(angle)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for percent in (0.0, 50.0, 100.0):
            y = self._y_for_percent(percent)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        painter.setPen(QPen(QColor(100, 116, 139), 1.0))
        for angle in (0.0, 30.0, 60.0, 90.0):
            painter.drawText(QPointF(self._x_for_angle(angle) - 10.0, rect.bottom() + 18.0), f"{angle:.0f}")
        painter.drawText(QPointF(rect.left() - 36.0, rect.top() + 4.0), "100")
        painter.drawText(QPointF(rect.left() - 24.0, rect.bottom() + 4.0), "0")

        curve = QPainterPath()
        samples = 180
        for idx in range(samples + 1):
            angle = 90.0 * idx / float(samples)
            point = QPointF(self._x_for_angle(angle), self._y_for_percent(self._response_percent_at(angle)))
            if idx == 0:
                curve.moveTo(point)
            else:
                curve.lineTo(point)
        painter.setPen(QPen(QColor(37, 99, 235), 2.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve)

        handles = self._handle_points()
        painter.setPen(QPen(QColor(202, 138, 4), 1.6))
        painter.setBrush(QColor(253, 224, 71))
        for name in ("left_width", "right_width"):
            hp = handles[name]
            painter.drawEllipse(hp, 5.2, 5.2)
            painter.drawLine(QPointF(hp.x(), hp.y() + 7.0), QPointF(hp.x(), rect.bottom()))

        peak = handles["peak"]
        painter.setPen(QPen(QColor(29, 78, 216), 1.8))
        painter.setBrush(QColor(96, 165, 250))
        painter.drawEllipse(peak, 6.5, 6.5)
        painter.drawLine(QPointF(peak.x(), peak.y() + 8.0), QPointF(peak.x(), rect.bottom()))

        painter.setPen(QPen(QColor(15, 23, 42), 1.0))
        effective_peak_a = float(self._etch_cap_a) * float(self._peak_pct) / 100.0
        painter.drawText(
            QPointF(rect.left(), 16.0),
            (
                f"P {self._peak_pct:.1f}% ({effective_peak_a:.2f} A)    "
                f"Ang {self._peak_deg:.1f}    W {self._width_deg:.1f}"
            ),
        )
        painter.drawText(QPointF(rect.right() - 76.0, rect.bottom() + 18.0), "angle deg")


class IonTransmissionEditor(QWidget):
    parametersChanged = Signal(float, float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._start_depth_pct = 0.0
        self._end_depth_pct = 100.0
        self._decay_strength_pct = 100.0
        self._floor_pct = 0.0
        self._curve_power = 1.0
        self._drag_handle: Optional[str] = None
        self._points = tuple(ION_TRANSMISSION_STEPPED_TRENCH_POINTS)
        self.setMinimumHeight(196)
        self.setMaximumHeight(246)
        self.setMouseTracking(True)
        self.setToolTip("Drag the line or dots to tune the depth fade.")

    def parameters(self) -> Tuple[float, float, float, float, float]:
        return (
            float(self._start_depth_pct),
            float(self._end_depth_pct),
            float(self._decay_strength_pct),
            float(self._floor_pct),
            float(self._curve_power),
        )

    def set_structure_points(self, points: Sequence[Tuple[float, float]]) -> None:
        pts = tuple((float(x), float(y)) for x, y in points)
        if len(pts) < 2 or pts == self._points:
            return
        self._points = pts
        self.update()

    def set_parameters(
        self,
        start_depth_pct: float,
        end_depth_pct: float,
        decay_strength_pct: float,
        floor_pct: float,
        curve_power: float,
    ) -> None:
        start_f = self._clamp(float(start_depth_pct), 0.0, 100.0)
        end_f = self._clamp(float(end_depth_pct), 0.0, 100.0)
        strength_f = self._clamp(float(decay_strength_pct), 0.0, 100.0)
        floor_f = self._clamp(float(floor_pct), 0.0, 100.0)
        curve_f = self._clamp(float(curve_power), 0.2, 6.0)
        changed = (
            abs(start_f - self._start_depth_pct) > 1e-9
            or abs(end_f - self._end_depth_pct) > 1e-9
            or abs(strength_f - self._decay_strength_pct) > 1e-9
            or abs(floor_f - self._floor_pct) > 1e-9
            or abs(curve_f - self._curve_power) > 1e-9
        )
        self._start_depth_pct = start_f
        self._end_depth_pct = end_f
        self._decay_strength_pct = strength_f
        self._floor_pct = floor_f
        self._curve_power = curve_f
        if changed:
            self.update()

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(float(low), min(float(high), float(value)))

    def _map_rect(self) -> QRectF:
        return QRectF(32.0, 28.0, max(120.0, float(self.width()) - 64.0), max(72.0, float(self.height()) - 62.0))

    def _y_for_depth_pct(self, depth_pct: float) -> float:
        rect = self._map_rect()
        t = self._clamp(float(depth_pct) / 100.0, 0.0, 1.0)
        return rect.top() + rect.height() * t

    def _depth_pct_for_y(self, y: float) -> float:
        rect = self._map_rect()
        if rect.height() <= 1e-9:
            return 0.0
        t = self._clamp((float(y) - rect.top()) / rect.height(), 0.0, 1.0)
        return 100.0 * t

    def _x_for_factor(self, factor: float) -> float:
        rect = self._map_rect()
        t = self._clamp(float(factor), 0.0, 1.0)
        return rect.left() + rect.width() * t

    def _factor_for_x(self, x: float) -> float:
        rect = self._map_rect()
        if rect.width() <= 1e-9:
            return 1.0
        return self._clamp((float(x) - rect.left()) / rect.width(), 0.0, 1.0)

    def _depth_curve_factor(self, depth_pct: float) -> float:
        depth_f = self._clamp(float(depth_pct), 0.0, 100.0)
        if depth_f <= self._start_depth_pct:
            return 1.0
        end_f = max(float(self._start_depth_pct) + 1e-9, float(self._end_depth_pct))
        span = max(1e-9, end_f - float(self._start_depth_pct))
        t = self._clamp((depth_f - float(self._start_depth_pct)) / span, 0.0, 1.0)
        factor = 1.0 - ((float(self._decay_strength_pct) / 100.0) * (t ** float(self._curve_power)))
        return self._clamp(max(float(self._floor_pct) / 100.0, factor), 0.0, 1.0)

    def _factor_curve_points(self) -> List[Tuple[float, float]]:
        return [
            (100.0 * idx / 100.0, self._depth_curve_factor(100.0 * idx / 100.0))
            for idx in range(101)
        ]

    def _handle_points(self) -> dict[str, QPointF]:
        end_depth = max(float(self._start_depth_pct), min(100.0, float(self._end_depth_pct)))
        end_factor = self._depth_curve_factor(end_depth)
        mid_depth = float(self._start_depth_pct) + ((end_depth - float(self._start_depth_pct)) * 0.5)
        return {
            "start": QPointF(self._map_rect().right() - 10.0, self._y_for_depth_pct(self._start_depth_pct)),
            "strength": QPointF(self._x_for_factor(end_factor), self._y_for_depth_pct(end_depth)),
            "curve": QPointF(self._x_for_factor(self._depth_curve_factor(mid_depth)), self._y_for_depth_pct(mid_depth)),
        }

    def _hit_handle(self, pos: QPointF) -> Optional[str]:
        best_name: Optional[str] = None
        best_dist_sq = 13.0 * 13.0
        for name, hp in self._handle_points().items():
            dx = float(pos.x() - hp.x())
            dy = float(pos.y() - hp.y())
            dist_sq = (dx * dx) + (dy * dy)
            if dist_sq <= best_dist_sq:
                best_name = name
                best_dist_sq = dist_sq
        start_y = self._y_for_depth_pct(self._start_depth_pct)
        if best_name is None and abs(float(pos.y()) - start_y) <= 6.0 and self._map_rect().contains(pos):
            return "start"
        return best_name

    def _emit_parameters_changed(self) -> None:
        self.parametersChanged.emit(
            float(self._start_depth_pct),
            float(self._end_depth_pct),
            float(self._decay_strength_pct),
            float(self._floor_pct),
            float(self._curve_power),
        )

    def _apply_drag(self, handle: str, pos: QPointF) -> None:
        if handle == "start":
            self._start_depth_pct = self._clamp(self._depth_pct_for_y(pos.y()), 0.0, 100.0)
        elif handle == "strength":
            self._end_depth_pct = self._clamp(
                self._depth_pct_for_y(pos.y()),
                float(self._start_depth_pct),
                100.0,
            )
            target_factor = self._factor_for_x(pos.x())
            self._decay_strength_pct = self._clamp(100.0 * (1.0 - target_factor), 0.0, 100.0)
        elif handle == "curve":
            drop = float(self._decay_strength_pct) / 100.0
            if drop <= 1e-9:
                return
            target_factor = self._clamp(
                self._factor_for_x(pos.x()),
                float(self._floor_pct) / 100.0,
                0.999999,
            )
            normalized_drop = self._clamp((1.0 - target_factor) / drop, 1e-6, 0.999999)
            self._curve_power = self._clamp(math.log(normalized_drop) / math.log(0.5), 0.2, 6.0)
        else:
            return
        self.update()
        self._emit_parameters_changed()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        handle = self._hit_handle(pos)
        if handle is None and self._map_rect().contains(pos):
            handle = "start"
        if handle is None:
            super().mousePressEvent(event)
            return
        self._drag_handle = handle
        self._apply_drag(handle, pos)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag_handle is not None:
            self._apply_drag(self._drag_handle, pos)
            event.accept()
            return
        handle = self._hit_handle(pos)
        if handle == "start":
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif handle == "strength":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif handle == "curve":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_handle is not None:
            self._drag_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_handle is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._map_rect()
        painter.fillRect(self.rect(), QColor(248, 250, 252))
        painter.setPen(QPen(QColor(203, 213, 225), 1.0))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(rect, 5.0, 5.0)
        _draw_structure_background(
            painter,
            self._points,
            rect,
            fill_color=QColor(226, 232, 240, 82),
            line_color=QColor(51, 65, 85, 185),
            line_width=2.0,
        )

        painter.setPen(QPen(QColor(226, 232, 240), 1.0))
        for depth_pct in (0.0, 25.0, 50.0, 75.0, 100.0):
            y = self._y_for_depth_pct(depth_pct)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for factor in (0.0, 0.5, 1.0):
            x = self._x_for_factor(factor)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        _draw_structure_background(
            painter,
            self._points,
            rect,
            fill_color=QColor(0, 0, 0, 0),
            line_color=QColor(51, 65, 85, 185),
            line_width=2.0,
        )

        start_y = self._y_for_depth_pct(self._start_depth_pct)
        painter.setPen(QPen(QColor(245, 158, 11), 1.6, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(rect.left(), start_y), QPointF(rect.right(), start_y))

        curve = QPainterPath()
        for idx, (depth_pct, factor) in enumerate(self._factor_curve_points()):
            point = QPointF(self._x_for_factor(factor), self._y_for_depth_pct(depth_pct))
            if idx == 0:
                curve.moveTo(point)
            else:
                curve.lineTo(point)
        painter.setPen(QPen(QColor(14, 116, 144), 2.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve)

        handles = self._handle_points()
        painter.setPen(QPen(QColor(180, 83, 9), 1.8))
        painter.setBrush(QColor(251, 191, 36))
        painter.drawEllipse(handles["start"], 6.0, 6.0)
        painter.setPen(QPen(QColor(15, 118, 110), 1.8))
        painter.setBrush(QColor(45, 212, 191))
        painter.drawEllipse(handles["strength"], 6.5, 6.5)
        painter.setPen(QPen(QColor(79, 70, 229), 1.8))
        painter.setBrush(QColor(129, 140, 248))
        painter.drawEllipse(handles["curve"], 5.8, 5.8)

        painter.setPen(QPen(QColor(15, 23, 42), 1.0))
        painter.drawText(
            QPointF(rect.left(), 18.0),
            (
                f"Start {self._start_depth_pct:.1f}%    "
                f"End {self._end_depth_pct:.1f}%    "
                f"Drop {self._decay_strength_pct:.1f}%    "
                f"Curve {self._curve_power:.2f}    "
                f"Floor {self._floor_pct:.1f}%"
            ),
        )
        painter.setPen(QPen(QColor(100, 116, 139), 1.0))
        painter.drawText(QPointF(rect.left() - 26.0, rect.top() + 4.0), "0")
        painter.drawText(QPointF(rect.left() - 34.0, rect.bottom() + 4.0), "100")
        painter.drawText(QPointF(rect.right() - 42.0, rect.bottom() + 18.0), "factor")


class DepthDepositionProfileEditor(QWidget):
    parametersChanged = Signal(float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._feature_type = "hole"
        self._feature_width_a = 240.0
        self._feature_depth_a = 4700.0
        self._feature_length_a: Optional[float] = None
        self._decay_k = 0.8
        self._decay_power = 1.2
        self._min_ratio_pct = 3.0
        self._closure_threshold_a = 8.0
        self._base_depo_a_per_cycle = 10.0
        self._display_mode = "depo_rate"
        self._drag_handle: Optional[str] = None
        self._structure_points: Tuple[Tuple[float, float], ...] = tuple(BOWED_JAR_TRENCH_POINTS)
        self.setMinimumHeight(220)
        self.setMaximumHeight(280)
        self.setMouseTracking(True)
        self.setToolTip("Drag the dots to tune the depth map.")

    def parameters(self) -> Tuple[float, float, float, float]:
        return (
            float(self._decay_k),
            float(self._decay_power),
            float(self._min_ratio_pct),
            float(self._closure_threshold_a),
        )

    def set_structure_points(self, points: Sequence[Tuple[float, float]]) -> None:
        pts = tuple((float(x), float(y)) for x, y in points)
        if len(pts) < 2 or pts == self._structure_points:
            return
        self._structure_points = pts
        self.update()

    def set_feature_geometry(
        self,
        feature_type: str,
        feature_width_a: float,
        feature_depth_a: float,
        feature_length_a: Optional[float],
    ) -> None:
        type_f = "line" if str(feature_type or "hole").strip().lower() in {"line", "trench"} else "hole"
        width_f = self._clamp(float(feature_width_a), 1.0, 100000.0)
        depth_f = self._clamp(float(feature_depth_a), 1.0, 200000.0)
        length_f = None if feature_length_a is None else self._clamp(float(feature_length_a), 0.0, 1000000.0)
        changed = (
            type_f != self._feature_type
            or abs(width_f - self._feature_width_a) > 1e-9
            or abs(depth_f - self._feature_depth_a) > 1e-9
            or (length_f is None) != (self._feature_length_a is None)
            or (length_f is not None and abs(length_f - float(self._feature_length_a or 0.0)) > 1e-9)
        )
        self._feature_type = type_f
        self._feature_width_a = width_f
        self._feature_depth_a = depth_f
        self._feature_length_a = None if length_f is None or length_f <= 0.0 else length_f
        if changed:
            self.update()

    def display_mode(self) -> str:
        return str(self._display_mode)

    def set_display_mode(self, mode: object) -> None:
        mode_key = _depth_deposition_display_mode(mode)
        if mode_key == self._display_mode:
            return
        self._display_mode = mode_key
        self.update()

    def set_depo_rate_a_per_cycle(self, value: float) -> None:
        rate = self._clamp(float(value), 0.0, 10000.0)
        if abs(rate - self._base_depo_a_per_cycle) <= 1e-9:
            return
        self._base_depo_a_per_cycle = rate
        self.update()

    def set_parameters(
        self,
        decay_k: float,
        decay_power: float,
        min_ratio_pct: float,
        closure_threshold_a: float,
    ) -> None:
        k_f = self._clamp(float(decay_k), 0.0, 20.0)
        power_f = self._clamp(float(decay_power), 0.05, 8.0)
        min_f = self._clamp(float(min_ratio_pct), 0.0, 100.0)
        close_f = self._clamp(float(closure_threshold_a), 0.0, 10000.0)
        changed = (
            abs(k_f - self._decay_k) > 1e-9
            or abs(power_f - self._decay_power) > 1e-9
            or abs(min_f - self._min_ratio_pct) > 1e-9
            or abs(close_f - self._closure_threshold_a) > 1e-9
        )
        self._decay_k = k_f
        self._decay_power = power_f
        self._min_ratio_pct = min_f
        self._closure_threshold_a = close_f
        if changed:
            self.update()

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(float(low), min(float(high), float(value)))

    def _plot_rect(self) -> QRectF:
        return QRectF(44.0, 30.0, max(120.0, float(self.width()) - 78.0), max(72.0, float(self.height()) - 64.0))

    def _x_for_ratio(self, ratio: float) -> float:
        rect = self._plot_rect()
        t = self._clamp(float(ratio), 0.0, 1.0)
        return rect.left() + rect.width() * t

    def _ratio_for_x(self, x: float) -> float:
        rect = self._plot_rect()
        if rect.width() <= 1e-9:
            return 1.0
        return self._clamp((float(x) - rect.left()) / rect.width(), 0.0, 1.0)

    def _y_for_depth_ratio(self, depth_ratio: float) -> float:
        rect = self._plot_rect()
        t = self._clamp(float(depth_ratio), 0.0, 1.0)
        return rect.top() + rect.height() * t

    def _depth_ratio_for_y(self, y: float) -> float:
        rect = self._plot_rect()
        if rect.height() <= 1e-9:
            return 0.0
        return self._clamp((float(y) - rect.top()) / rect.height(), 0.0, 1.0)

    def _closure_display_max_a(self) -> float:
        return max(80.0, float(self._closure_threshold_a) * 1.2)

    def _x_for_closure_threshold(self, threshold_a: float) -> float:
        rect = self._plot_rect()
        t = self._clamp(float(threshold_a) / self._closure_display_max_a(), 0.0, 1.0)
        return rect.left() + rect.width() * t

    def _closure_threshold_for_x(self, x: float) -> float:
        return self._closure_display_max_a() * self._ratio_for_x(x)

    def _effective_ar_at_depth_ratio(self, depth_ratio: float) -> float:
        return compute_effective_aspect_ratio(
            float(self._feature_depth_a) * self._clamp(float(depth_ratio), 0.0, 1.0),
            self._feature_type,
            self._feature_width_a,
            self._feature_length_a,
            use_equivalent_aspect_ratio=True,
        )

    def _ratio_at_depth_ratio(self, depth_ratio: float) -> float:
        return compute_depth_deposition_ratio(
            self._effective_ar_at_depth_ratio(depth_ratio),
            attenuation_model="exponential",
            depth_decay_k=self._decay_k,
            depth_decay_power=self._decay_power,
            min_depo_ratio=float(self._min_ratio_pct) / 100.0,
        )

    def _decay_k_for_bottom_ratio(self, target_ratio: float) -> float:
        min_ratio = self._clamp(float(self._min_ratio_pct) / 100.0, 0.0, 0.999999)
        target = self._clamp(float(target_ratio), min_ratio + 1e-6, 0.999999)
        raw = self._clamp((target - min_ratio) / max(1e-9, 1.0 - min_ratio), 1e-9, 0.999999)
        ear = max(1e-9, self._effective_ar_at_depth_ratio(1.0))
        return self._clamp(-math.log(raw) / max(1e-9, ear ** float(self._decay_power)), 0.0, 20.0)

    def _decay_power_for_mid_ratio(self, target_ratio: float) -> float:
        if self._decay_k <= 1e-9:
            return 0.05
        min_ratio = self._clamp(float(self._min_ratio_pct) / 100.0, 0.0, 0.999999)
        target = self._clamp(float(target_ratio), min_ratio + 1e-6, 0.999999)
        raw = self._clamp((target - min_ratio) / max(1e-9, 1.0 - min_ratio), 1e-9, 0.999999)
        ear = max(1e-9, self._effective_ar_at_depth_ratio(0.5))
        if abs(math.log(ear)) <= 1e-9:
            return self._clamp(8.05 - (8.0 * target), 0.05, 8.0)
        power = math.log(max(1e-9, -math.log(raw) / max(1e-9, self._decay_k))) / math.log(ear)
        return self._clamp(power, 0.05, 8.0)

    def _curve_points(self) -> List[Tuple[float, float]]:
        return [(idx / 100.0, self._ratio_at_depth_ratio(idx / 100.0)) for idx in range(101)]

    def _display_value_for_ratio(self, ratio: float) -> float:
        ratio_f = self._clamp(float(ratio), 0.0, 1.0)
        if self._display_mode == "attenuation":
            return 1.0 - ratio_f
        return ratio_f

    def _ratio_for_display_value(self, value: float) -> float:
        value_f = self._clamp(float(value), 0.0, 1.0)
        if self._display_mode == "attenuation":
            return 1.0 - value_f
        return value_f

    def _x_for_deposition_ratio(self, ratio: float) -> float:
        return self._x_for_ratio(self._display_value_for_ratio(ratio))

    def _deposition_ratio_for_x(self, x: float) -> float:
        return self._ratio_for_display_value(self._ratio_for_x(x))

    def _handle_points(self) -> dict[str, QPointF]:
        rect = self._plot_rect()
        return {
            "floor": QPointF(self._x_for_deposition_ratio(float(self._min_ratio_pct) / 100.0), rect.bottom() - 11.0),
            "attenuation": QPointF(self._x_for_deposition_ratio(self._ratio_at_depth_ratio(1.0)), rect.bottom()),
            "power": QPointF(
                self._x_for_deposition_ratio(self._ratio_at_depth_ratio(0.5)),
                self._y_for_depth_ratio(0.5),
            ),
            "closure": QPointF(self._x_for_closure_threshold(self._closure_threshold_a), rect.top() + 8.0),
        }

    def _hit_handle(self, pos: QPointF) -> Optional[str]:
        best_name: Optional[str] = None
        best_dist_sq = 13.0 * 13.0
        for name, hp in self._handle_points().items():
            dx = float(pos.x() - hp.x())
            dy = float(pos.y() - hp.y())
            dist_sq = (dx * dx) + (dy * dy)
            if dist_sq <= best_dist_sq:
                best_name = name
                best_dist_sq = dist_sq
        rect = self._plot_rect()
        if best_name is None and abs(float(pos.y()) - (rect.top() + 8.0)) <= 7.0 and rect.contains(pos):
            return "closure"
        return best_name

    def _emit_parameters_changed(self) -> None:
        self.parametersChanged.emit(
            float(self._decay_k),
            float(self._decay_power),
            float(self._min_ratio_pct),
            float(self._closure_threshold_a),
        )

    def _apply_drag(self, handle: str, pos: QPointF) -> None:
        if handle == "attenuation":
            self._decay_k = self._decay_k_for_bottom_ratio(self._deposition_ratio_for_x(pos.x()))
        elif handle == "power":
            self._decay_power = self._decay_power_for_mid_ratio(self._deposition_ratio_for_x(pos.x()))
        elif handle == "floor":
            self._min_ratio_pct = self._clamp(self._deposition_ratio_for_x(pos.x()) * 100.0, 0.0, 100.0)
        elif handle == "closure":
            self._closure_threshold_a = self._clamp(self._closure_threshold_for_x(pos.x()), 0.0, 10000.0)
        else:
            return
        self.update()
        self._emit_parameters_changed()

    @staticmethod
    def _draw_arrow(
        painter: QPainter,
        start: QPointF,
        end: QPointF,
        color: QColor,
        *,
        width: float = 1.4,
    ) -> None:
        dx = float(end.x() - start.x())
        dy = float(end.y() - start.y())
        dist = math.hypot(dx, dy)
        if dist <= 7.0:
            return
        ux = dx / dist
        uy = dy / dist
        head = 7.0
        side = 3.6
        left = QPointF(end.x() - (ux * head) - (uy * side), end.y() - (uy * head) + (ux * side))
        right = QPointF(end.x() - (ux * head) + (uy * side), end.y() - (uy * head) - (ux * side))

        painter.setPen(QPen(color, width))
        painter.drawLine(start, end)
        arrow_head = QPainterPath()
        arrow_head.moveTo(end)
        arrow_head.lineTo(left)
        arrow_head.moveTo(end)
        arrow_head.lineTo(right)
        painter.drawPath(arrow_head)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        handle = self._hit_handle(pos)
        rect = self._plot_rect()
        if handle is None and rect.contains(pos):
            handle = "attenuation" if self._depth_ratio_for_y(pos.y()) > 0.72 else "power"
        if handle is None:
            super().mousePressEvent(event)
            return
        self._drag_handle = handle
        self._apply_drag(handle, pos)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag_handle is not None:
            self._apply_drag(self._drag_handle, pos)
            event.accept()
            return
        handle = self._hit_handle(pos)
        if handle == "closure":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif handle in {"attenuation", "power", "floor"}:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_handle is not None:
            self._drag_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_handle is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._plot_rect()
        painter.fillRect(self.rect(), QColor(248, 250, 252))
        painter.setPen(QPen(QColor(203, 213, 225), 1.0))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(rect, 5.0, 5.0)
        _draw_structure_background(
            painter,
            self._structure_points,
            rect,
            fill_color=QColor(220, 252, 231, 58),
            line_color=QColor(51, 65, 85, 165),
            line_width=1.8,
        )

        painter.setPen(QPen(QColor(226, 232, 240), 1.0))
        for depth_ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = self._y_for_depth_ratio(depth_ratio)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for ratio in (0.0, 0.5, 1.0):
            x = self._x_for_ratio(ratio)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        field_x = self._x_for_deposition_ratio(1.0)
        curve_points = self._curve_points()
        field_area = QPainterPath()
        field_area.moveTo(QPointF(rect.left(), rect.top()))
        for idx, (depth_ratio, ratio) in enumerate(curve_points):
            point = QPointF(self._x_for_deposition_ratio(ratio), self._y_for_depth_ratio(depth_ratio))
            if idx == 0:
                field_area.lineTo(point)
            else:
                field_area.lineTo(point)
        field_area.lineTo(QPointF(rect.left(), rect.bottom()))
        field_area.closeSubpath()
        if self._display_mode == "attenuation":
            area_color = QColor(219, 234, 254, 86)
            curve_color = QColor(37, 99, 235)
            arrow_color = QColor(37, 99, 235, 150)
        else:
            area_color = QColor(187, 247, 208, 82)
            curve_color = QColor(21, 128, 61)
            arrow_color = QColor(22, 163, 74, 150)
        painter.fillPath(field_area, area_color)
        _draw_structure_background(
            painter,
            self._structure_points,
            rect,
            fill_color=QColor(0, 0, 0, 0),
            line_color=QColor(51, 65, 85, 165),
            line_width=1.8,
        )

        painter.setPen(QPen(QColor(37, 99, 235, 165), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(field_x, rect.top()), QPointF(field_x, rect.bottom()))
        painter.setPen(QPen(QColor(30, 64, 175), 1.0))
        field_label = "Field max" if self._display_mode == "depo_rate" else "Field loss 0%"
        label_x = max(rect.left(), min(rect.right() - 92.0, field_x - 44.0))
        painter.drawText(QPointF(label_x, rect.top() - 8.0), field_label)
        painter.setPen(QPen(QColor(15, 23, 42), 1.0))
        painter.drawText(QPointF(rect.left() + 8.0, rect.bottom() - 8.0), f"Depth {self._feature_depth_a:.0f} A")

        for depth_ratio in (0.18, 0.36, 0.54, 0.72, 0.90):
            y = self._y_for_depth_ratio(depth_ratio)
            ratio = self._ratio_at_depth_ratio(depth_ratio)
            curve_x = self._x_for_deposition_ratio(ratio)
            if self._display_mode == "attenuation":
                start = QPointF(rect.left() + 4.0, y)
                end = QPointF(curve_x - 4.0, y)
            else:
                start = QPointF(field_x - 4.0, y)
                end = QPointF(curve_x + 4.0, y)
            self._draw_arrow(
                painter,
                start,
                end,
                arrow_color,
            )

        floor_x = self._x_for_deposition_ratio(float(self._min_ratio_pct) / 100.0)
        painter.setPen(QPen(QColor(22, 163, 74), 1.4, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(floor_x, rect.top()), QPointF(floor_x, rect.bottom()))

        curve = QPainterPath()
        for idx, (depth_ratio, ratio) in enumerate(curve_points):
            point = QPointF(self._x_for_deposition_ratio(ratio), self._y_for_depth_ratio(depth_ratio))
            if idx == 0:
                curve.moveTo(point)
            else:
                curve.lineTo(point)
        painter.setPen(QPen(curve_color, 2.7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve)

        closure_y = rect.top() + 8.0
        painter.setPen(QPen(QColor(132, 204, 22), 1.6))
        painter.drawLine(QPointF(rect.left(), closure_y), QPointF(rect.right(), closure_y))

        handles = self._handle_points()
        painter.setPen(QPen(QColor(22, 101, 52), 1.8))
        painter.setBrush(QColor(74, 222, 128))
        painter.drawEllipse(handles["attenuation"], 6.5, 6.5)
        painter.setPen(QPen(QColor(20, 83, 45), 1.7))
        painter.setBrush(QColor(134, 239, 172))
        painter.drawEllipse(handles["power"], 5.9, 5.9)
        painter.setPen(QPen(QColor(63, 98, 18), 1.7))
        painter.setBrush(QColor(190, 242, 100))
        painter.drawEllipse(handles["floor"], 5.8, 5.8)
        painter.setPen(QPen(QColor(77, 124, 15), 1.7))
        painter.setBrush(QColor(217, 249, 157))
        painter.drawEllipse(handles["closure"], 5.8, 5.8)

        painter.setPen(QPen(QColor(15, 23, 42), 1.0))
        painter.drawText(
            QPointF(rect.left(), 18.0),
            (
                ("Dep rate    " if self._display_mode == "depo_rate" else "Attenuation    ")
                + (
                f"K {self._decay_k:.2f}    "
                f"P {self._decay_power:.2f}    "
                f"Min {self._min_ratio_pct:.1f}%    "
                f"Close {self._closure_threshold_a:.1f} A"
                )
            ),
        )
        painter.setPen(QPen(QColor(100, 116, 139), 1.0))
        painter.drawText(QPointF(rect.left() - 28.0, rect.top() + 4.0), "0")
        painter.drawText(QPointF(rect.left() - 34.0, rect.bottom() + 4.0), "100")
        axis_label = "depletion %" if self._display_mode == "attenuation" else "dep rate A/CYC"
        painter.drawText(QPointF(rect.right() - 82.0, rect.bottom() + 18.0), axis_label)


class InhibitionProfileEditor(QWidget):
    parametersChanged = Signal(float, float, float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._strength_pct = 85.0
        self._penetration_depth_a = 1100.0
        self._decay_power = 1.2
        self._min_growth_pct = 8.0
        self._bottom_boost_pct = 20.0
        self._recombination_pct = 35.0
        self._feature_depth_a = 4700.0
        self._drag_handle: Optional[str] = None
        self._structure_points: Tuple[Tuple[float, float], ...] = tuple(BOWED_JAR_TRENCH_POINTS)
        self.setMinimumHeight(230)
        self.setMaximumHeight(292)
        self.setMouseTracking(True)
        self.setToolTip(
            "깊이별 growth ratio 곡선입니다. 점을 드래그해서 inhibition 강도, 침투 깊이, "
            "바닥 회복, PEALD recombination을 조절합니다."
        )

    def parameters(self) -> Tuple[float, float, float, float, float, float]:
        return (
            float(self._strength_pct),
            float(self._penetration_depth_a),
            float(self._decay_power),
            float(self._min_growth_pct),
            float(self._bottom_boost_pct),
            float(self._recombination_pct),
        )

    def set_structure_points(self, points: Sequence[Tuple[float, float]]) -> None:
        pts = tuple((float(x), float(y)) for x, y in points)
        if len(pts) < 2 or pts == self._structure_points:
            return
        self._structure_points = pts
        self.update()

    def set_feature_depth(self, feature_depth_a: float) -> None:
        depth_f = self._clamp(float(feature_depth_a), 1.0, 200000.0)
        if abs(depth_f - self._feature_depth_a) <= 1e-9:
            return
        self._feature_depth_a = depth_f
        self.update()

    def set_parameters(
        self,
        strength_pct: float,
        penetration_depth_a: float,
        decay_power: float,
        min_growth_pct: float,
        bottom_boost_pct: float,
        recombination_pct: float,
    ) -> None:
        strength_f = self._clamp(float(strength_pct), 0.0, 100.0)
        penetration_f = self._clamp(float(penetration_depth_a), 1.0, 200000.0)
        power_f = self._clamp(float(decay_power), 0.05, 8.0)
        min_f = self._clamp(float(min_growth_pct), 0.0, 100.0)
        boost_f = self._clamp(float(bottom_boost_pct), 0.0, 100.0)
        recomb_f = self._clamp(float(recombination_pct), 0.0, 100.0)
        changed = (
            abs(strength_f - self._strength_pct) > 1e-9
            or abs(penetration_f - self._penetration_depth_a) > 1e-9
            or abs(power_f - self._decay_power) > 1e-9
            or abs(min_f - self._min_growth_pct) > 1e-9
            or abs(boost_f - self._bottom_boost_pct) > 1e-9
            or abs(recomb_f - self._recombination_pct) > 1e-9
        )
        self._strength_pct = strength_f
        self._penetration_depth_a = penetration_f
        self._decay_power = power_f
        self._min_growth_pct = min_f
        self._bottom_boost_pct = boost_f
        self._recombination_pct = recomb_f
        if changed:
            self.update()

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(float(low), min(float(high), float(value)))

    def _plot_rect(self) -> QRectF:
        return QRectF(44.0, 31.0, max(130.0, float(self.width()) - 80.0), max(82.0, float(self.height()) - 66.0))

    def _ratio_max(self) -> float:
        return max(1.15, min(2.0, 1.0 + (float(self._bottom_boost_pct) / 100.0) + 0.10))

    def _x_for_ratio(self, ratio: float) -> float:
        rect = self._plot_rect()
        t = self._clamp(float(ratio) / self._ratio_max(), 0.0, 1.0)
        return rect.left() + rect.width() * t

    def _ratio_for_x(self, x: float) -> float:
        rect = self._plot_rect()
        if rect.width() <= 1e-9:
            return 1.0
        t = self._clamp((float(x) - rect.left()) / rect.width(), 0.0, 1.0)
        return t * self._ratio_max()

    def _y_for_depth_ratio(self, depth_ratio: float) -> float:
        rect = self._plot_rect()
        return rect.top() + rect.height() * self._clamp(float(depth_ratio), 0.0, 1.0)

    def _depth_ratio_for_y(self, y: float) -> float:
        rect = self._plot_rect()
        if rect.height() <= 1e-9:
            return 0.0
        return self._clamp((float(y) - rect.top()) / rect.height(), 0.0, 1.0)

    def _coverage_at_depth_ratio(self, depth_ratio: float, *, power: Optional[float] = None, recomb_pct: Optional[float] = None) -> float:
        depth_t = self._clamp(float(depth_ratio), 0.0, 1.0)
        depth_a = depth_t * max(1.0, float(self._feature_depth_a))
        penetration = max(1e-9, float(self._penetration_depth_a))
        power_f = float(self._decay_power if power is None else power)
        exponent = self._clamp((depth_a / penetration) ** power_f, 0.0, 80.0)
        depth_decay = math.exp(-exponent)
        recomb_f = float(self._recombination_pct if recomb_pct is None else recomb_pct) / 100.0
        recomb_loss = recomb_f * (depth_t ** 1.25) * 0.55
        return self._clamp(depth_decay - recomb_loss, 0.0, 1.0)

    def _growth_ratio_at_depth_ratio(
        self,
        depth_ratio: float,
        *,
        strength_pct: Optional[float] = None,
        power: Optional[float] = None,
        min_growth_pct: Optional[float] = None,
        bottom_boost_pct: Optional[float] = None,
        recomb_pct: Optional[float] = None,
    ) -> float:
        depth_t = self._clamp(float(depth_ratio), 0.0, 1.0)
        strength_f = float(self._strength_pct if strength_pct is None else strength_pct) / 100.0
        min_f = float(self._min_growth_pct if min_growth_pct is None else min_growth_pct) / 100.0
        boost_f = float(self._bottom_boost_pct if bottom_boost_pct is None else bottom_boost_pct) / 100.0
        coverage = self._coverage_at_depth_ratio(depth_t, power=power, recomb_pct=recomb_pct)
        bottom_relief = boost_f * (depth_t ** 1.35)
        ratio = 1.0 - (strength_f * coverage) + bottom_relief
        return self._clamp(ratio, min_f, 1.0 + boost_f)

    def _curve_points(self) -> List[Tuple[float, float]]:
        return [(idx / 100.0, self._growth_ratio_at_depth_ratio(idx / 100.0)) for idx in range(101)]

    def _decay_power_for_mid_ratio(self, target_ratio: float) -> float:
        target = self._clamp(float(target_ratio), 0.0, self._ratio_max())
        best_power = float(self._decay_power)
        best_error = float("inf")
        for idx in range(200):
            power = 0.05 + (7.95 * idx / 199.0)
            ratio = self._growth_ratio_at_depth_ratio(0.5, power=power)
            error = abs(ratio - target)
            if error < best_error:
                best_power = power
                best_error = error
        return self._clamp(best_power, 0.05, 8.0)

    def _bottom_boost_for_bottom_ratio(self, target_ratio: float) -> float:
        base = self._growth_ratio_at_depth_ratio(1.0, bottom_boost_pct=0.0)
        return self._clamp((float(target_ratio) - base) * 100.0, 0.0, 100.0)

    def _recombination_for_deep_ratio(self, target_ratio: float) -> float:
        target = self._clamp(float(target_ratio), 0.0, self._ratio_max())
        best_recomb = float(self._recombination_pct)
        best_error = float("inf")
        for idx in range(201):
            recomb = float(idx) * 0.5
            ratio = self._growth_ratio_at_depth_ratio(0.72, recomb_pct=recomb)
            error = abs(ratio - target)
            if error < best_error:
                best_recomb = recomb
                best_error = error
        return self._clamp(best_recomb, 0.0, 100.0)

    def _handle_points(self) -> dict[str, QPointF]:
        penetration_ratio = self._clamp(float(self._penetration_depth_a) / max(1.0, float(self._feature_depth_a)), 0.0, 1.0)
        return {
            "strength": QPointF(self._x_for_ratio(self._growth_ratio_at_depth_ratio(0.0)), self._y_for_depth_ratio(0.0)),
            "penetration": QPointF(
                self._x_for_ratio(self._growth_ratio_at_depth_ratio(penetration_ratio)),
                self._y_for_depth_ratio(penetration_ratio),
            ),
            "power": QPointF(self._x_for_ratio(self._growth_ratio_at_depth_ratio(0.5)), self._y_for_depth_ratio(0.5)),
            "floor": QPointF(self._x_for_ratio(float(self._min_growth_pct) / 100.0), self._y_for_depth_ratio(1.0) - 11.0),
            "boost": QPointF(self._x_for_ratio(self._growth_ratio_at_depth_ratio(1.0)), self._y_for_depth_ratio(1.0)),
            "recombination": QPointF(self._x_for_ratio(self._growth_ratio_at_depth_ratio(0.72)), self._y_for_depth_ratio(0.72)),
        }

    def _hit_handle(self, pos: QPointF) -> Optional[str]:
        best_name: Optional[str] = None
        best_dist_sq = 13.5 * 13.5
        for name, hp in self._handle_points().items():
            dx = float(pos.x() - hp.x())
            dy = float(pos.y() - hp.y())
            dist_sq = (dx * dx) + (dy * dy)
            if dist_sq <= best_dist_sq:
                best_name = name
                best_dist_sq = dist_sq
        return best_name

    def _emit_parameters_changed(self) -> None:
        self.parametersChanged.emit(
            float(self._strength_pct),
            float(self._penetration_depth_a),
            float(self._decay_power),
            float(self._min_growth_pct),
            float(self._bottom_boost_pct),
            float(self._recombination_pct),
        )

    def _apply_drag(self, handle: str, pos: QPointF) -> None:
        target_ratio = self._ratio_for_x(pos.x())
        if handle == "strength":
            self._strength_pct = self._clamp((1.0 - target_ratio) * 100.0, 0.0, 100.0)
        elif handle == "penetration":
            self._penetration_depth_a = self._clamp(
                self._depth_ratio_for_y(pos.y()) * max(1.0, float(self._feature_depth_a)),
                1.0,
                200000.0,
            )
        elif handle == "power":
            self._decay_power = self._decay_power_for_mid_ratio(target_ratio)
        elif handle == "floor":
            self._min_growth_pct = self._clamp(target_ratio * 100.0, 0.0, 100.0)
        elif handle == "boost":
            self._bottom_boost_pct = self._bottom_boost_for_bottom_ratio(target_ratio)
        elif handle == "recombination":
            self._recombination_pct = self._recombination_for_deep_ratio(target_ratio)
        else:
            return
        self.update()
        self._emit_parameters_changed()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        handle = self._hit_handle(pos)
        if handle is None and self._plot_rect().contains(pos):
            depth_t = self._depth_ratio_for_y(pos.y())
            if depth_t <= 0.18:
                handle = "strength"
            elif depth_t >= 0.86:
                handle = "boost" if self._ratio_for_x(pos.x()) >= 0.75 else "floor"
            elif depth_t >= 0.63:
                handle = "recombination"
            elif depth_t <= 0.38:
                handle = "penetration"
            else:
                handle = "power"
        if handle is None:
            super().mousePressEvent(event)
            return
        self._drag_handle = handle
        self._apply_drag(handle, pos)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag_handle is not None:
            self._apply_drag(self._drag_handle, pos)
            event.accept()
            return
        handle = self._hit_handle(pos)
        if handle == "penetration":
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif handle in {"strength", "power", "floor", "boost", "recombination"}:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_handle is not None:
            self._drag_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_handle is None:
            self.unsetCursor()
        super().leaveEvent(event)

    @staticmethod
    def _draw_handle(painter: QPainter, point: QPointF, color: QColor, edge: QColor, radius: float = 6.0) -> None:
        painter.setPen(QPen(edge, 1.7))
        painter.setBrush(color)
        painter.drawEllipse(point, radius, radius)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._plot_rect()
        painter.fillRect(self.rect(), QColor(255, 251, 235))
        painter.setPen(QPen(QColor(253, 230, 138), 1.0))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(rect, 5.0, 5.0)
        _draw_structure_background(
            painter,
            self._structure_points,
            rect,
            fill_color=QColor(254, 243, 199, 70),
            line_color=QColor(120, 53, 15, 150),
            line_width=1.8,
        )

        painter.setPen(QPen(QColor(254, 243, 199), 1.0))
        for depth_ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = self._y_for_depth_ratio(depth_ratio)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for ratio in (0.0, 0.5, 1.0):
            x = self._x_for_ratio(ratio)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        conformal_x = self._x_for_ratio(1.0)
        curve_points = self._curve_points()
        suppressed = QPainterPath()
        boosted = QPainterPath()
        for idx, (depth_ratio, ratio) in enumerate(curve_points):
            y = self._y_for_depth_ratio(depth_ratio)
            x = self._x_for_ratio(ratio)
            if ratio <= 1.0:
                if idx == 0:
                    suppressed.moveTo(QPointF(conformal_x, y))
                suppressed.lineTo(QPointF(conformal_x, y))
                suppressed.lineTo(QPointF(x, y))
            else:
                if idx == 0:
                    boosted.moveTo(QPointF(conformal_x, y))
                boosted.lineTo(QPointF(conformal_x, y))
                boosted.lineTo(QPointF(x, y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(suppressed, QColor(251, 146, 60, 58))
        painter.fillPath(boosted, QColor(45, 212, 191, 54))

        _draw_structure_background(
            painter,
            self._structure_points,
            rect,
            fill_color=QColor(0, 0, 0, 0),
            line_color=QColor(120, 53, 15, 150),
            line_width=1.8,
        )

        painter.setPen(QPen(QColor(37, 99, 235, 155), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(conformal_x, rect.top()), QPointF(conformal_x, rect.bottom()))
        painter.setPen(QPen(QColor(30, 64, 175), 1.0))
        painter.drawText(QPointF(max(rect.left(), conformal_x - 72.0), rect.top() - 8.0), "100%")

        floor_x = self._x_for_ratio(float(self._min_growth_pct) / 100.0)
        painter.setPen(QPen(QColor(22, 163, 74), 1.4, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(floor_x, rect.top()), QPointF(floor_x, rect.bottom()))

        pen_ratio = self._clamp(float(self._penetration_depth_a) / max(1.0, float(self._feature_depth_a)), 0.0, 1.0)
        pen_y = self._y_for_depth_ratio(pen_ratio)
        painter.setPen(QPen(QColor(59, 130, 246), 1.4, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(rect.left(), pen_y), QPointF(rect.right(), pen_y))

        for depth_ratio in (0.14, 0.32, 0.50, 0.68, 0.86):
            y = self._y_for_depth_ratio(depth_ratio)
            ratio = self._growth_ratio_at_depth_ratio(depth_ratio)
            color = QColor(234, 88, 12, 145) if ratio <= 1.0 else QColor(13, 148, 136, 145)
            DepthDepositionProfileEditor._draw_arrow(
                painter,
                QPointF(conformal_x, y),
                QPointF(self._x_for_ratio(ratio), y),
                color,
                width=1.25,
            )

        curve = QPainterPath()
        for idx, (depth_ratio, ratio) in enumerate(curve_points):
            point = QPointF(self._x_for_ratio(ratio), self._y_for_depth_ratio(depth_ratio))
            if idx == 0:
                curve.moveTo(point)
            else:
                curve.lineTo(point)
        painter.setPen(QPen(QColor(180, 83, 9), 2.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve)

        handles = self._handle_points()
        self._draw_handle(painter, handles["strength"], QColor(251, 146, 60), QColor(154, 52, 18), 6.4)
        self._draw_handle(painter, handles["penetration"], QColor(96, 165, 250), QColor(30, 64, 175), 5.9)
        self._draw_handle(painter, handles["power"], QColor(196, 181, 253), QColor(91, 33, 182), 5.7)
        self._draw_handle(painter, handles["floor"], QColor(134, 239, 172), QColor(22, 101, 52), 5.7)
        self._draw_handle(painter, handles["boost"], QColor(45, 212, 191), QColor(15, 118, 110), 6.0)
        self._draw_handle(painter, handles["recombination"], QColor(253, 164, 175), QColor(159, 18, 57), 5.7)

        painter.setPen(QPen(QColor(15, 23, 42), 1.0))
        painter.drawText(
            QPointF(rect.left(), 18.0),
            (
                f"Inhibit {self._strength_pct:.1f}%    "
                f"Pen {self._penetration_depth_a:.0f} A    "
                f"P {self._decay_power:.2f}    "
                f"Floor {self._min_growth_pct:.1f}%    "
                f"Boost {self._bottom_boost_pct:.1f}%    "
                f"Recomb {self._recombination_pct:.1f}%"
            ),
        )
        painter.setPen(QPen(QColor(120, 113, 108), 1.0))
        painter.drawText(QPointF(rect.left() - 28.0, rect.top() + 4.0), "0")
        painter.drawText(QPointF(rect.left() - 34.0, rect.bottom() + 4.0), "100")
        painter.drawText(QPointF(rect.right() - 76.0, rect.bottom() + 18.0), "growth ratio")


class RedepositionLobeEditor(QWidget):
    parametersChanged = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._efficiency_pct = 25.0
        self._emit_power = 1.0
        self._distance_power = 1.0
        self._mode = "transport"
        self._drag_handle: Optional[str] = None
        self.setMinimumHeight(172)
        self.setMaximumHeight(210)
        self.setMouseTracking(True)
        self._update_tooltip()

    def parameters(self) -> Tuple[float, float, float]:
        return (float(self._efficiency_pct), float(self._emit_power), float(self._distance_power))

    def set_mode(self, mode: str) -> None:
        normalized = "reflection" if str(mode).lower() == "reflection" else "transport"
        if normalized == self._mode:
            return
        self._mode = normalized
        self._update_tooltip()
        self.set_parameters(self._efficiency_pct, self._emit_power, self._distance_power)
        self.update()

    def _update_tooltip(self) -> None:
        if self._mode == "reflection":
            self.setToolTip(
                "리데포 양은 왼쪽 바, 각도 spread는 cone edge, specular bias는 중심축 핸들을 드래그해서 조절합니다."
            )
        else:
            self.setToolTip(
                "Drag the density handle for redeposition amount, cone edge handles for emit, and axis handle for distance fade."
            )

    def set_parameters(self, efficiency_pct: float, emit_power: float, distance_power: float) -> None:
        eff_f = self._clamp(float(efficiency_pct), 0.0, 100.0)
        if self._mode == "reflection":
            emit_f = self._clamp(float(emit_power), 1.0, 80.0)
            dist_f = self._clamp(float(distance_power), -100.0, 100.0)
        else:
            emit_f = self._clamp(float(emit_power), 0.0, 8.0)
            dist_f = self._clamp(float(distance_power), 0.0, 4.0)
        changed = (
            abs(eff_f - self._efficiency_pct) > 1e-9
            or abs(emit_f - self._emit_power) > 1e-9
            or abs(dist_f - self._distance_power) > 1e-9
        )
        self._efficiency_pct = eff_f
        self._emit_power = emit_f
        self._distance_power = dist_f
        if changed:
            self.update()

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(float(low), min(float(high), float(value)))

    def _canvas_rect(self) -> QRectF:
        return QRectF(18.0, 24.0, max(120.0, float(self.width()) - 36.0), max(70.0, float(self.height()) - 52.0))

    def _amount_bar_rect(self) -> QRectF:
        rect = self._canvas_rect()
        return QRectF(rect.left() + 8.0, rect.top() + 10.0, 12.0, max(30.0, rect.height() - 20.0))

    def _source_point(self) -> QPointF:
        rect = self._canvas_rect()
        return QPointF(rect.left() + 48.0, rect.center().y() + 10.0)

    def _normal_axis_angle_deg(self) -> float:
        return 12.0

    def _specular_axis_angle_deg(self) -> float:
        return 44.0

    def _axis_angle_deg(self) -> float:
        if self._mode == "reflection":
            span = self._specular_axis_angle_deg() - self._normal_axis_angle_deg()
            bias = self._clamp(float(self._distance_power), -100.0, 100.0) / 100.0
            return self._normal_axis_angle_deg() + (span * bias)
        return 17.0

    def _axis_vec(self) -> Tuple[float, float]:
        angle = math.radians(self._axis_angle_deg())
        return (math.cos(angle), math.sin(angle))

    def _emit_to_half_angle(self, emit_power: float) -> float:
        if self._mode == "reflection":
            return self._clamp(float(emit_power), 1.0, 80.0)
        return 10.0 + (52.0 / (1.0 + (0.9 * self._clamp(float(emit_power), 0.0, 8.0))))

    def _half_angle_to_emit(self, half_angle_deg: float) -> float:
        if self._mode == "reflection":
            return self._clamp(float(half_angle_deg), 1.0, 80.0)
        half = self._clamp(float(half_angle_deg), 12.0, 62.0)
        return self._clamp(((52.0 / max(0.1, half - 10.0)) - 1.0) / 0.9, 0.0, 8.0)

    def _distance_handle_t(self) -> float:
        return 0.90 - (0.68 * self._clamp(self._distance_power, 0.0, 4.0) / 4.0)

    def _distance_from_t(self, t: float) -> float:
        return self._clamp((0.90 - self._clamp(float(t), 0.22, 0.90)) * 4.0 / 0.68, 0.0, 4.0)

    def _bias_from_axis_angle(self, angle_deg: float) -> float:
        span = self._specular_axis_angle_deg() - self._normal_axis_angle_deg()
        if abs(span) <= 1e-9:
            return 0.0
        delta = self._angle_delta_deg(float(angle_deg), self._normal_axis_angle_deg())
        return self._clamp(100.0 * delta / span, -100.0, 100.0)

    def _radius_limit_for_angle(self, angle_deg: float) -> float:
        rect = self._canvas_rect()
        source = self._source_point()
        dx = math.cos(math.radians(angle_deg))
        dy = math.sin(math.radians(angle_deg))
        limits: List[float] = []
        pad = 8.0
        if dx > 1e-9:
            limits.append((rect.right() - pad - source.x()) / dx)
        elif dx < -1e-9:
            limits.append((rect.left() + pad - source.x()) / dx)
        if dy > 1e-9:
            limits.append((rect.bottom() - pad - source.y()) / dy)
        elif dy < -1e-9:
            limits.append((rect.top() + pad - source.y()) / dy)
        positive = [value for value in limits if value > 1.0]
        return min(positive) if positive else max(70.0, rect.width() * 0.6)

    def _max_radius(self, half_angle_deg: Optional[float] = None) -> float:
        half = self._emit_to_half_angle(self._emit_power) if half_angle_deg is None else float(half_angle_deg)
        axis = self._axis_angle_deg()
        return max(
            72.0,
            min(
                self._radius_limit_for_angle(axis),
                self._radius_limit_for_angle(axis - half),
                self._radius_limit_for_angle(axis + half),
            ),
        )

    def _point_from_polar(self, angle_deg: float, radius: float) -> QPointF:
        source = self._source_point()
        angle = math.radians(float(angle_deg))
        return QPointF(source.x() + (math.cos(angle) * float(radius)), source.y() + (math.sin(angle) * float(radius)))

    def _y_for_efficiency_pct(self, efficiency_pct: float) -> float:
        bar = self._amount_bar_rect()
        t = self._clamp(float(efficiency_pct) / 100.0, 0.0, 1.0)
        return bar.bottom() - (bar.height() * t)

    def _efficiency_pct_for_y(self, y: float) -> float:
        bar = self._amount_bar_rect()
        if bar.height() <= 1e-9:
            return 0.0
        t = self._clamp((bar.bottom() - float(y)) / bar.height(), 0.0, 1.0)
        return 100.0 * t

    @staticmethod
    def _angle_delta_deg(angle_deg: float, reference_deg: float) -> float:
        delta = float(angle_deg) - float(reference_deg)
        while delta > 180.0:
            delta -= 360.0
        while delta < -180.0:
            delta += 360.0
        return delta

    def _handle_points(self) -> dict[str, QPointF]:
        half = self._emit_to_half_angle(self._emit_power)
        radius = self._max_radius(half) * 0.92
        axis = self._axis_angle_deg()
        axis_dx, axis_dy = self._axis_vec()
        source = self._source_point()
        distance_radius = self._max_radius(half) * self._distance_handle_t()
        if self._mode == "reflection":
            distance_radius = self._max_radius(half) * 0.58
        return {
            "efficiency": QPointF(self._amount_bar_rect().center().x(), self._y_for_efficiency_pct(self._efficiency_pct)),
            "emit_left": self._point_from_polar(axis - half, radius),
            "emit_right": self._point_from_polar(axis + half, radius),
            "distance": QPointF(source.x() + (axis_dx * distance_radius), source.y() + (axis_dy * distance_radius)),
        }

    def _hit_handle(self, pos: QPointF) -> Optional[str]:
        best_name: Optional[str] = None
        best_dist_sq = 12.0 * 12.0
        for name, hp in self._handle_points().items():
            dx = float(pos.x() - hp.x())
            dy = float(pos.y() - hp.y())
            dist_sq = (dx * dx) + (dy * dy)
            if dist_sq <= best_dist_sq:
                best_name = name
                best_dist_sq = dist_sq
        return best_name

    def _emit_parameters_changed(self) -> None:
        self.parametersChanged.emit(float(self._efficiency_pct), float(self._emit_power), float(self._distance_power))

    def _apply_drag(self, handle: str, pos: QPointF) -> None:
        if handle == "efficiency":
            self._efficiency_pct = self._efficiency_pct_for_y(pos.y())
        elif handle in {"emit_left", "emit_right"}:
            source = self._source_point()
            angle = math.degrees(math.atan2(float(pos.y() - source.y()), float(pos.x() - source.x())))
            half = abs(self._angle_delta_deg(angle, self._axis_angle_deg()))
            self._emit_power = self._half_angle_to_emit(half)
        elif handle == "distance":
            source = self._source_point()
            if self._mode == "reflection":
                angle = math.degrees(math.atan2(float(pos.y() - source.y()), float(pos.x() - source.x())))
                self._distance_power = self._bias_from_axis_angle(angle)
            else:
                axis_dx, axis_dy = self._axis_vec()
                projection = ((float(pos.x() - source.x()) * axis_dx) + (float(pos.y() - source.y()) * axis_dy))
                t = projection / max(1.0, self._max_radius())
                self._distance_power = self._distance_from_t(t)
        else:
            return
        self.update()
        self._emit_parameters_changed()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        handle = self._hit_handle(pos)
        if handle is None and self._amount_bar_rect().adjusted(-8.0, -4.0, 8.0, 4.0).contains(pos):
            handle = "efficiency"
        if handle is None and self._canvas_rect().contains(pos):
            handle = "distance"
        if handle is None:
            super().mousePressEvent(event)
            return
        self._drag_handle = handle
        self._apply_drag(handle, pos)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag_handle is not None:
            self._apply_drag(self._drag_handle, pos)
            event.accept()
            return
        handle = self._hit_handle(pos)
        if handle == "efficiency":
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif handle in {"emit_left", "emit_right"}:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif handle == "distance":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_handle is not None:
            self._drag_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_handle is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._canvas_rect()
        painter.fillRect(self.rect(), QColor(248, 250, 252))
        painter.setPen(QPen(QColor(203, 213, 225), 1.0))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(rect, 5.0, 5.0)

        bar = self._amount_bar_rect()
        for idx in range(22):
            t0 = idx / 22.0
            t1 = (idx + 1) / 22.0
            alpha = int(18 + (190 * t1))
            y0 = bar.bottom() - (bar.height() * t1)
            y1 = bar.bottom() - (bar.height() * t0)
            painter.fillRect(QRectF(bar.left(), y0, bar.width(), max(1.0, y1 - y0)), QColor(249, 115, 22, alpha))
        painter.setPen(QPen(QColor(124, 45, 18), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bar, 3.0, 3.0)

        half = self._emit_to_half_angle(self._emit_power)
        axis = self._axis_angle_deg()
        radius = self._max_radius(half)
        source = self._source_point()
        base_alpha = int(18 + (self._clamp(self._efficiency_pct, 0.0, 100.0) * 1.95))
        segments = 18
        painter.setPen(Qt.PenStyle.NoPen)
        for idx in range(segments, 0, -1):
            r0 = radius * (idx - 1) / float(segments)
            r1 = radius * idx / float(segments)
            t = (idx - 0.5) / float(segments)
            if self._mode == "reflection":
                fade = max(0.045, (1.0 - t) ** 0.72)
            else:
                fade = max(0.035, (1.0 - t) ** (0.45 + (self._distance_power * 1.1)))
            alpha = max(4, min(230, int(base_alpha * fade)))
            p0 = self._point_from_polar(axis - half, r0)
            p1 = self._point_from_polar(axis - half, r1)
            p2 = self._point_from_polar(axis + half, r1)
            p3 = self._point_from_polar(axis + half, r0)
            cone = QPainterPath()
            cone.moveTo(p0)
            cone.lineTo(p1)
            cone.lineTo(p2)
            cone.lineTo(p3)
            cone.closeSubpath()
            painter.fillPath(cone, QColor(249, 115, 22, alpha))

        painter.setPen(QPen(QColor(100, 116, 139), 2.0))
        trench = QPainterPath()
        trench.moveTo(QPointF(source.x() - 22.0, source.y() - 58.0))
        trench.lineTo(source)
        trench.lineTo(QPointF(source.x() + 28.0, source.y() + 56.0))
        trench.lineTo(QPointF(rect.right() - 12.0, source.y() + 56.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(trench)

        painter.setPen(QPen(QColor(124, 45, 18, 95), 1.2, Qt.PenStyle.DashLine))
        painter.drawLine(source, self._point_from_polar(axis, radius))
        if self._mode == "reflection":
            painter.setPen(QPen(QColor(37, 99, 235, 120), 1.1, Qt.PenStyle.DashLine))
            painter.drawLine(source, self._point_from_polar(self._normal_axis_angle_deg(), radius * 0.82))
            painter.setPen(QPen(QColor(190, 24, 93, 125), 1.1, Qt.PenStyle.DashLine))
            painter.drawLine(source, self._point_from_polar(self._specular_axis_angle_deg(), radius * 0.82))
        painter.setPen(QPen(QColor(124, 45, 18, 130), 1.4))
        painter.drawLine(source, self._point_from_polar(axis - half, radius * 0.92))
        painter.drawLine(source, self._point_from_polar(axis + half, radius * 0.92))

        handles = self._handle_points()
        painter.setPen(QPen(QColor(124, 45, 18), 1.4))
        painter.setBrush(QColor(254, 215, 170))
        for name in ("emit_left", "emit_right", "distance"):
            painter.drawEllipse(handles[name], 5.8, 5.8)
        painter.setBrush(QColor(249, 115, 22, max(70, min(230, base_alpha))))
        painter.drawEllipse(source, 7.0, 7.0)
        painter.setPen(QPen(QColor(124, 45, 18), 1.4))
        painter.setBrush(QColor(255, 237, 213))
        painter.drawEllipse(handles["efficiency"], 5.8, 5.8)

        painter.setPen(QPen(QColor(15, 23, 42), 1.0))
        if self._mode == "reflection":
            label = (
                f"Redepo {self._efficiency_pct:.1f}%    "
                f"Spread {self._emit_power:.1f} deg    "
                f"Specular bias {self._distance_power:.1f}%"
            )
        else:
            label = (
                f"Redepo {self._efficiency_pct:.1f}%    "
                f"Cone {2.0 * half:.0f} deg    "
                f"Dist {self._distance_power:.2f}"
            )
        painter.drawText(
            QPointF(rect.left(), 17.0),
            label,
        )


class CompareOverlayView(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._cases: List[TrenchSweepResult] = []
        self._opacity = 0.55
        self._content_rect: Optional[QRectF] = None
        self._current_index = 0
        self._display_decimation_stride = 1
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def set_cases(self, cases: Sequence[TrenchSweepResult]) -> None:
        self._cases = list(cases[:2])
        self._display_decimation_stride = _display_decimation_stride(
            [profile for case in self._cases for profile in case.result.frame_profiles]
        )
        self._update_content_rect()
        self.show_frame(0, fit=True)

    def set_opacity_pct(self, opacity_pct: int) -> None:
        self._opacity = max(0.05, min(1.0, float(opacity_pct) / 100.0))
        self.show_frame(self._current_index, fit=False)

    def _scene_points(self, profile: Sequence[Tuple[float, float]]) -> List[QPointF]:
        decimated = _decimate_profile_for_display(profile, self._display_decimation_stride)
        return [QPointF(float(x), -float(y)) for x, y in decimated]

    @staticmethod
    def _line_path(points: Sequence[QPointF]) -> QPainterPath:
        path = QPainterPath()
        if not points:
            return path
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        return path

    @staticmethod
    def _fill_path(points: Sequence[QPointF], floor_y: float) -> QPainterPath:
        path = CompareOverlayView._line_path(points)
        if len(points) < 2:
            return path
        path.lineTo(QPointF(points[-1].x(), floor_y))
        path.lineTo(QPointF(points[0].x(), floor_y))
        path.closeSubpath()
        return path

    @staticmethod
    def _profile_key(profile: Sequence[Tuple[float, float]]) -> Tuple[Tuple[float, float], ...]:
        return tuple((round(float(x), 6), round(float(y), 6)) for x, y in profile)

    def _add_legend(
        self,
        anchor: QPointF,
        entries: Sequence[Tuple[str, QColor, Qt.PenStyle]],
    ) -> None:
        if not entries:
            return
        row_h = 28.0
        width = 430.0
        height = 18.0 + row_h * float(len(entries))
        bg = QGraphicsRectItem(0.0, 0.0, width, height)
        bg.setPos(anchor)
        bg.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        bg.setBrush(QBrush(QColor(255, 255, 255, 238)))
        bg.setPen(QPen(QColor(148, 163, 184, 190), 1.1))
        bg.setZValue(500.0)
        self._scene.addItem(bg)

        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        for idx, (label, color, style) in enumerate(entries):
            y = 16.0 + row_h * float(idx)
            line_path = QPainterPath()
            line_path.moveTo(14.0, y + 7.0)
            line_path.lineTo(56.0, y + 7.0)
            sample = QGraphicsPathItem(line_path)
            sample.setPos(anchor)
            sample.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            pen_color = QColor(color)
            pen_color.setAlpha(240)
            pen = QPen(pen_color, 4.0)
            pen.setCosmetic(True)
            pen.setStyle(style)
            sample.setPen(pen)
            sample.setZValue(501.0)
            self._scene.addItem(sample)

            text = self._scene.addText(_elide_middle(str(label), 44), font)
            text.setDefaultTextColor(QColor(15, 23, 42, 245))
            text.setPos(QPointF(anchor.x() + 66.0, anchor.y() + y - 8.0))
            text.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            text.setZValue(502.0)

    def _update_content_rect(self) -> None:
        points: List[QPointF] = []
        for case in self._cases:
            for profile in case.result.frame_profiles:
                points.extend(self._scene_points(profile))
        if not points:
            self._content_rect = QRectF(-1000.0, -1000.0, 2000.0, 2000.0)
            self._scene.setSceneRect(self._content_rect)
            return
        xs = [float(p.x()) for p in points]
        ys = [float(p.y()) for p in points]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(min(ys), 0.0), max(max(ys), 0.0)
        if abs(x1 - x0) < 1e-9:
            x1 = x0 + 1.0
        if abs(y1 - y0) < 1e-9:
            y1 = y0 + 1.0
        pad = max(x1 - x0, y1 - y0, 100.0) * 0.08
        self._content_rect = QRectF(x0 - pad, y0 - pad, (x1 - x0) + 2.0 * pad, (y1 - y0) + 2.0 * pad)
        self._scene.setSceneRect(self._content_rect)

    def show_frame(self, index: int, *, fit: bool = False) -> None:
        self._current_index = max(0, int(index))
        self._scene.clear()
        if not self._cases:
            return
        colors = [QColor(37, 99, 235), QColor(249, 115, 22)]
        labels = ["A", "B"]
        rect = self._content_rect or QRectF(-1000.0, -1000.0, 2000.0, 2000.0)
        floor_y = rect.bottom()
        line_alpha = max(25, min(255, int(round(255.0 * self._opacity))))
        fill_alpha = max(8, min(150, int(round(95.0 * self._opacity))))
        legend_entries: List[Tuple[str, QColor, Qt.PenStyle]] = []
        base_profiles: List[Sequence[Tuple[float, float]]] = []
        seen_base_profiles: set[Tuple[Tuple[float, float], ...]] = set()
        for case in self._cases:
            frames = case.result.frame_profiles
            if not frames:
                continue
            key = self._profile_key(frames[0])
            if key in seen_base_profiles:
                continue
            seen_base_profiles.add(key)
            base_profiles.append(frames[0])
        for base_idx, profile in enumerate(base_profiles):
            pts = self._scene_points(profile)
            if len(pts) < 2:
                continue
            base_line = QGraphicsPathItem(self._line_path(pts))
            base_pen = QPen(QColor(51, 65, 85, 165 if base_idx == 0 else 105), 2.0)
            base_pen.setCosmetic(True)
            base_pen.setStyle(Qt.PenStyle.DashLine if base_idx == 0 else Qt.PenStyle.DotLine)
            base_line.setPen(base_pen)
            base_line.setZValue(25.0 + float(base_idx))
            self._scene.addItem(base_line)
            legend_entries.append(
                (
                    "기본 구조" if base_idx == 0 else f"기본 구조 {base_idx + 1}",
                    QColor(51, 65, 85),
                    Qt.PenStyle.DashLine if base_idx == 0 else Qt.PenStyle.DotLine,
                )
            )

        for case_idx, case in enumerate(self._cases):
            frames = case.result.frame_profiles
            if not frames:
                continue
            local_idx = max(0, min(self._current_index, len(frames) - 1))
            pts = self._scene_points(frames[local_idx])
            if len(pts) < 2:
                continue
            color = QColor(colors[case_idx % len(colors)])
            fill_color = QColor(color)
            fill_color.setAlpha(fill_alpha)
            line_color = QColor(color)
            line_color.setAlpha(line_alpha)
            fill_item = QGraphicsPathItem(self._fill_path(pts, floor_y))
            fill_item.setPen(QPen(Qt.PenStyle.NoPen))
            fill_item.setBrush(QBrush(fill_color))
            fill_item.setZValue(float(case_idx))
            self._scene.addItem(fill_item)
            line_item = QGraphicsPathItem(self._line_path(pts))
            pen = QPen(line_color, 2.4)
            pen.setCosmetic(True)
            line_item.setPen(pen)
            line_item.setZValue(10.0 + float(case_idx))
            self._scene.addItem(line_item)
            legend_entries.append((f"{labels[case_idx]}: {case.label}", color, Qt.PenStyle.SolidLine))
        self._add_legend(QPointF(rect.left() + 16.0, rect.top() + 16.0), legend_entries)
        if fit:
            self.fit_content()

    def fit_content(self) -> None:
        if self._content_rect is None:
            return
        self.resetTransform()
        self.fitInView(self._content_rect, Qt.AspectRatioMode.KeepAspectRatio)


class SplitTestWindow(QMainWindow):
    def __init__(self, cases: Sequence[TrenchSweepResult]) -> None:
        super().__init__()
        self._cases = list(cases)
        self._views: List[ResultVectorView] = []
        self._case_status_labels: List[QLabel] = []
        self._syncing_viewports = False
        self._compare_overlay_enabled = bool(len(self._cases) >= 2 and self._is_compare_parameter(self._cases[0].parameter))

        title = "Split Test"
        if self._cases:
            if self._is_compare_parameter(self._cases[0].parameter):
                title = "모델 비교"
            else:
                title = f"Split Test - {self._cases[0].label}"
        self.setWindowTitle(title)
        self.resize(1320, 860)

        self._timer = QTimer(self)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._advance_frame)

        self.slider_frame = QSlider(Qt.Orientation.Horizontal)
        max_idx = max((len(case.result.frame_profiles) - 1 for case in self._cases), default=0)
        self.slider_frame.setRange(0, max(0, max_idx))
        self.slider_frame.setValue(0)
        self.slider_frame.setEnabled(max_idx > 0)
        self.slider_frame.valueChanged.connect(self.show_frame)

        self.btn_play = QPushButton("일시정지" if max_idx > 0 else "재생")
        self.btn_play.setEnabled(max_idx > 0)
        self.btn_play.clicked.connect(self.toggle_playback)
        self.lbl_frame = QLabel("Frame 0/0")
        self.btn_overlay_compare = QPushButton("한 그래프 보기")
        self.btn_overlay_compare.setCheckable(True)
        self.btn_overlay_compare.setVisible(self._compare_overlay_enabled)
        self.btn_overlay_compare.toggled.connect(self._on_overlay_compare_toggled)
        self.lbl_overlay_opacity = QLabel("투명도 55%")
        self.lbl_overlay_opacity.setVisible(self._compare_overlay_enabled)
        self.slider_overlay_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_overlay_opacity.setRange(10, 100)
        self.slider_overlay_opacity.setValue(55)
        self.slider_overlay_opacity.setFixedWidth(150)
        self.slider_overlay_opacity.setVisible(self._compare_overlay_enabled)
        self.slider_overlay_opacity.valueChanged.connect(self._on_overlay_opacity_changed)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Frame"))
        controls.addWidget(self.slider_frame, 1)
        controls.addWidget(self.lbl_frame)
        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_overlay_compare)
        controls.addWidget(self.lbl_overlay_opacity)
        controls.addWidget(self.slider_overlay_opacity)

        grid_host = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        case_count = max(1, len(self._cases))
        columns = 1 if case_count <= 1 else (2 if case_count <= 4 else 3)
        for idx, case in enumerate(self._cases):
            cell = QWidget()
            cell_layout = QVBoxLayout()
            cell_layout.setContentsMargins(6, 6, 6, 6)
            header = QLabel(self._case_label(case))
            status = QLabel("Cycle 0/0 | 점 0")
            view = ResultVectorView()
            view.setMinimumSize(360, 260)
            solid_playback = _use_solid_playback(case.result)
            view.set_frames(
                case.result.frame_profiles,
                voids=case.result.frame_voids,
                redepo_overlays=case.result.meta.get("frame_redepo_overlays"),
                etch_overlays=case.result.meta.get("frame_etch_overlays"),
                transport_lines=case.result.meta.get("frame_transport_lines"),
                void_mode="current",
                dynamic_substrate_fill=solid_playback,
                history_mode="mixed_etch" if solid_playback else "film",
            )
            view.show_frame(0, fit=True)
            view.viewportChanged.connect(lambda state, source=view: self._sync_viewports(source, state))
            cell_layout.addWidget(header)
            cell_layout.addWidget(view, 1)
            cell_layout.addWidget(status)
            cell.setLayout(cell_layout)
            row = idx // columns
            col = idx % columns
            grid.addWidget(cell, row, col)
            self._views.append(view)
            self._case_status_labels.append(status)

        grid_host.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(grid_host)
        self._grid_scroll = scroll
        self._overlay_view = CompareOverlayView()
        self._overlay_view.setMinimumSize(760, 520)
        self._overlay_view.setVisible(False)
        if self._compare_overlay_enabled:
            self._overlay_view.set_cases(self._cases[:2])
            self._overlay_view.set_opacity_pct(self.slider_overlay_opacity.value())

        root = QVBoxLayout()
        root.addLayout(controls)
        root.addWidget(scroll, 1)
        root.addWidget(self._overlay_view, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._install_slider_wheel_guards()

        self.show_frame(0)
        QTimer.singleShot(0, self.fit_all_views)
        if max_idx > 0:
            self._timer.start()

    def _install_slider_wheel_guards(self) -> None:
        for slider in self.findChildren(QSlider):
            slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            slider.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802, ANN001
        if isinstance(watched, QSlider) and event.type() == QEvent.Type.Wheel:
            focus_widget = QApplication.focusWidget()
            slider_has_focus = focus_widget is watched or (
                focus_widget is not None and watched.isAncestorOf(focus_widget)
            )
            if not slider_has_focus:
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def _case_label(self, case: TrenchSweepResult) -> str:
        if self._is_compare_parameter(case.parameter):
            return case.label
        if case.parameter == "cycles":
            value_text = str(int(case.value))
        else:
            value_text = f"{case.value:g}"
        return f"{case.label}: {value_text}"

    @staticmethod
    def _is_compare_parameter(parameter: str) -> bool:
        return "compare" in str(parameter or "").lower()

    def toggle_playback(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.btn_play.setText("재생")
            return
        if self.slider_frame.value() >= self.slider_frame.maximum():
            self.slider_frame.setValue(0)
        self._timer.start()
        self.btn_play.setText("일시정지")

    def _advance_frame(self) -> None:
        current = self.slider_frame.value()
        if current >= self.slider_frame.maximum():
            self._timer.stop()
            self.btn_play.setText("다시 재생")
            return
        self.slider_frame.setValue(current + 1)

    def show_frame(self, index: int) -> None:
        max_idx = self.slider_frame.maximum()
        idx = max(0, min(int(index), max_idx))
        self.lbl_frame.setText(f"Frame {idx}/{max_idx}")
        for case_idx, case in enumerate(self._cases):
            frames = case.result.frame_profiles
            if not frames:
                continue
            local_idx = max(0, min(idx, len(frames) - 1))
            self._views[case_idx].show_frame(local_idx, fit=False)
            cycle = case.result.frame_steps[local_idx] if local_idx < len(case.result.frame_steps) else local_idx
            total = case.result.meta.get("cycles", len(frames) - 1)
            points = len(frames[local_idx])
            self._case_status_labels[case_idx].setText(f"Cycle {cycle}/{total} | 점 {points}")
        if self._compare_overlay_enabled:
            self._overlay_view.show_frame(idx, fit=False)

    def fit_all_views(self) -> None:
        if not self._views:
            return
        self._syncing_viewports = True
        try:
            for view in self._views:
                view.fit_content()
        finally:
            self._syncing_viewports = False
        if self._compare_overlay_enabled:
            self._overlay_view.fit_content()

    def _on_overlay_compare_toggled(self, checked: bool) -> None:
        enabled = bool(checked)
        self._grid_scroll.setVisible(not enabled)
        self._overlay_view.setVisible(enabled)
        self.btn_overlay_compare.setText("나란히 보기" if enabled else "한 그래프 보기")
        if enabled:
            self._overlay_view.show_frame(self.slider_frame.value(), fit=True)

    def _on_overlay_opacity_changed(self, value: int) -> None:
        pct = max(10, min(100, int(value)))
        self.lbl_overlay_opacity.setText(f"투명도 {pct}%")
        self._overlay_view.set_opacity_pct(pct)

    def _sync_viewports(self, source: ResultVectorView, state: object) -> None:
        if self._syncing_viewports:
            return
        if not isinstance(state, dict):
            return
        self._syncing_viewports = True
        try:
            for view in self._views:
                if view is not source:
                    view.apply_viewport_state(state)
        finally:
            self._syncing_viewports = False

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        self._timer.stop()
        super().closeEvent(event)


class _EmulationRunWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object, bool, object, bool, str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        config: TrenchDepoConfig,
        cache_key: tuple[object, ...],
        request_note: str,
        save_artifacts: bool,
        use_preview_cache: bool,
    ) -> None:
        super().__init__()
        self._config = config
        self._cache_key = cache_key
        self._request_note = str(request_note)
        self._save_artifacts = bool(save_artifacts)
        self._use_preview_cache = bool(use_preview_cache)

    @Slot()
    def run(self) -> None:
        try:
            result = run_trench_depo(
                self._config,
                progress_cb=lambda step, total: self.progress.emit(
                    int(step),
                    int(total),
                    "실행",
                ),
                detail_cb=self._emit_detail_progress,
            )
            self.finished.emit(
                self._config,
                result,
                self._use_preview_cache,
                self._cache_key,
                self._save_artifacts,
                self._request_note,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _emit_detail_progress(self, detail: Dict[str, Any]) -> None:
        if not isinstance(detail, dict):
            return
        if "substep" not in detail or "substeps" not in detail:
            return
        cycles = max(1, int(self._config.cycles))
        substeps = max(1, int(detail.get("substeps", 1)))
        step = max(0, int(detail.get("step", 0)))
        substep = max(0, min(substeps, int(detail.get("substep", 0))))
        total = max(1, cycles * substeps)
        done = max(0, min(total, (step * substeps) + substep))
        phase = str(detail.get("phase", ""))
        cycle_label = f"{step + 1}CYC"
        sub_label = f"{substep}/{substeps}"
        suffix = "계산 중" if phase == "start" else "완료"
        self.progress.emit(done, total, f"실행 {cycle_label} sub {sub_label} {suffix}")


class DraggableParameterSectionLabel(QLabel):
    sectionMoved = Signal(str, str)

    def __init__(self, text: str, section_key: str) -> None:
        super().__init__(text)
        self.section_key = str(section_key)
        self._drag_start_pos: Optional[QPointF] = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_start_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._drag_start_pos
        if math.hypot(float(delta.x()), float(delta.y())) < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MODEL_SECTION_MIME, self.section_key.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start_pos = None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        source_key = self._source_key(event)
        if source_key and source_key != self.section_key:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        source_key = self._source_key(event)
        if source_key and source_key != self.section_key:
            self.sectionMoved.emit(source_key, self.section_key)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _source_key(event) -> str:
        mime = event.mimeData()
        if not mime or not mime.hasFormat(MODEL_SECTION_MIME):
            return ""
        return bytes(mime.data(MODEL_SECTION_MIME)).decode("utf-8", errors="ignore")


class TrenchDepoWindow(QMainWindow):
    def _make_parameter_section(
        self,
        text: str,
        *,
        color: str = "#334155",
        background: str = "#f8fafc",
        border: str = "#cbd5e1",
        section_key: Optional[str] = None,
    ) -> QLabel:
        if section_key:
            label = DraggableParameterSectionLabel(text, section_key)
            label.sectionMoved.connect(self._move_model_parameter_section)
            label.setToolTip("모델 제목을 드래그해서 파라미터 섹션 순서를 바꿉니다.")
        else:
            label = QLabel(text)
        label.setStyleSheet(
            "QLabel {"
            "font-weight: 700;"
            f"color: {color};"
            f"background: {background};"
            f"border: 1px solid {border};"
            "border-radius: 4px;"
            "padding: 4px 6px;"
            "}"
        )
        return label

    def _make_ion_shadow_slider(self, value: int) -> Tuple[QSlider, QLabel, QWidget]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setValue(max(0, min(100, int(value))))
        value_label = QLabel(f"{slider.value()}%")
        value_label.setMinimumWidth(38)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(slider, 1)
        layout.addWidget(value_label)
        row.setLayout(layout)
        return slider, value_label, row

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GFE - 트렌치 Depo 에뮬레이터")
        self.resize(1280, 820)

        self._result: Optional[TrenchDepoResult] = None
        self._last_run_dir: Optional[Path] = None
        self._continuation_base_result: Optional[TrenchDepoResult] = None
        self._continuation_base_run_dir: Optional[Path] = None
        self._continuation_stage_index = 1
        self._split_windows: List[SplitTestWindow] = []
        self._syncing_sputter_curve = False
        self._syncing_ion_curve = False
        self._syncing_redepo_lobe = False
        self._syncing_depth_curve = False
        self._syncing_inhibition_curve = False
        self._active_emulator_number = 0
        self._emulator_numbers = load_created_emulator_numbers()
        self._emulator_buttons: dict[int, QPushButton] = {}
        self._model_parameter_section_order: List[str] = list(DEFAULT_MODEL_PARAMETER_SECTION_ORDER)
        self._model_parameter_section_rows: Dict[str, List[Tuple[QWidget, int, int]]] = {}
        self._preview_result_cache: dict[tuple[object, ...], TrenchDepoResult] = {}
        self._emulation_thread: Optional[QThread] = None
        self._emulation_worker: Optional[_EmulationRunWorker] = None
        self._emulator_run_timer = QTimer(self)
        self._emulator_run_timer.setSingleShot(True)
        self._emulator_run_timer.setInterval(150)
        self._emulator_run_timer.timeout.connect(self._run_deferred_emulator_preview)
        self._result_config: Optional[TrenchDepoConfig] = None
        self._result_playback_timer = QTimer(self)
        self._result_playback_timer.setInterval(220)
        self._result_playback_timer.timeout.connect(self._advance_result_playback)

        self.view = ResultVectorView()
        self.view.setMinimumSize(560, 620)
        self.structure_view = StructureView()
        self.structure_view.setMinimumSize(560, 540)
        self.structure_view.set_point_radius_px(4.5)
        self.smoothing_view = StructureView()
        self.smoothing_view.setMinimumSize(560, 540)
        self.smoothing_view.set_point_radius_px(2.5)
        self.smoothing_view.set_profile_colors(
            current=QColor("#2563eb"),
            reference=QColor(100, 116, 139, 180),
        )
        self.progress_geometry_view = StructureView()
        self.progress_geometry_view.setMinimumSize(560, 420)
        self.progress_geometry_view.set_point_radius_px(2.5)
        self.progress_geometry_view.set_profile_colors(
            current=QColor("#2563eb"),
            reference=QColor(100, 116, 139, 180),
        )
        self.progress_geometry_view.set_editing_enabled(False)
        self.smoothing = SmoothingController()
        self._structure_points: List[Tuple[float, float]] = []
        self._smoothed_points: List[Tuple[float, float]] = []
        self._use_smoothed_geometry = False
        self._preserve_geometry_on_emulator_switch = False
        self._syncing_structure_view = False
        self._syncing_structure_table = False
        self._syncing_smoothed_table = False
        self._syncing_workflow_tabs = False
        self._syncing_emulator_preset = False
        self._syncing_quality_mode = False
        self._structure_library_path = Path(
            os.environ.get("GAPSIM_STRUCTURE_LIBRARY", str(DEFAULT_STRUCTURE_LIBRARY_PATH))
        )
        self._parameter_library_path = Path(
            os.environ.get("GAPSIM_PARAMETER_LIBRARY", str(DEFAULT_PARAMETER_LIBRARY_PATH))
        )
        self._active_structure_sheet_name = ""
        self._active_parameter_preset_name = ""
        self._overlay_opacity = 0.35
        self._overlay_path: Optional[str] = None
        self._overlay_scale_a_per_px = 1.0
        self.emulator_button_group = QButtonGroup(self)
        self.emulator_button_group.setExclusive(True)
        self.emulator_toggle_row = QHBoxLayout()
        self.emulator_toggle_row.setContentsMargins(0, 0, 0, 0)
        self.emulator_toggle_row.setSpacing(6)
        self.emulator_toggle_row.addStretch(1)
        for number in self._emulator_numbers:
            self._add_emulator_toggle(number)

        self.spin_cycles = QSpinBox()
        self.spin_cycles.setRange(0, 10000)
        self.spin_cycles.setValue(20)

        self.spin_angstrom_per_cycle = QDoubleSpinBox()
        self.spin_angstrom_per_cycle.setRange(0.0, 10000.0)
        self.spin_angstrom_per_cycle.setDecimals(3)
        self.spin_angstrom_per_cycle.setSingleStep(1.0)
        self.spin_angstrom_per_cycle.setValue(10.0)
        self.cmb_quality_mode = QComboBox()
        for label, ds_a in QUALITY_MODE_PRESETS:
            self.cmb_quality_mode.addItem(label, ds_a)
        self.cmb_quality_mode.setToolTip(
            "프로파일 조각 크기를 선택합니다. 값이 클수록 빠르고, 작을수록 형상이 더 정밀하지만 느립니다."
        )
        self.spin_reparam_ds = QDoubleSpinBox()
        self.spin_reparam_ds.setRange(0.5, 200.0)
        self.spin_reparam_ds.setDecimals(2)
        self.spin_reparam_ds.setSingleStep(2.5)
        self.spin_reparam_ds.setSuffix(" A")
        self.spin_reparam_ds.setToolTip("에뮬레이션 내부 표면 재분할 간격입니다. 큰 값은 포인트 수를 줄여 속도를 높입니다.")
        self._set_quality_mode_for_ds(DEFAULT_UI_REPARAM_DS_A)

        self.chk_sputter = QCheckBox("Etch enabled")
        self.chk_sputter.setToolTip("Master switch for the direct sputter etch stack.")
        self.chk_sputter.setChecked(True)
        self.chk_ion_transmission = QCheckBox("Ion transmission modifier")
        self.chk_ion_transmission.setToolTip(
            "Multiplier on the existing direct sputter output. Deposition is not attenuated."
        )
        self.chk_ion_transmission.setChecked(True)
        self.spin_ion_start_depth = QDoubleSpinBox()
        self.spin_ion_start_depth.setRange(0.0, 100.0)
        self.spin_ion_start_depth.setDecimals(1)
        self.spin_ion_start_depth.setSingleStep(2.5)
        self.spin_ion_start_depth.setValue(0.0)
        self.spin_ion_end_depth = QDoubleSpinBox()
        self.spin_ion_end_depth.setRange(0.0, 100.0)
        self.spin_ion_end_depth.setDecimals(1)
        self.spin_ion_end_depth.setSingleStep(2.5)
        self.spin_ion_end_depth.setValue(100.0)
        self.spin_ion_decay_strength = QDoubleSpinBox()
        self.spin_ion_decay_strength.setRange(0.0, 100.0)
        self.spin_ion_decay_strength.setDecimals(1)
        self.spin_ion_decay_strength.setSingleStep(5.0)
        self.spin_ion_decay_strength.setValue(100.0)
        self.spin_ion_floor = QDoubleSpinBox()
        self.spin_ion_floor.setRange(0.0, 100.0)
        self.spin_ion_floor.setDecimals(1)
        self.spin_ion_floor.setSingleStep(2.5)
        self.spin_ion_floor.setValue(0.0)
        self.spin_ion_curve_power = QDoubleSpinBox()
        self.spin_ion_curve_power.setRange(0.2, 6.0)
        self.spin_ion_curve_power.setDecimals(2)
        self.spin_ion_curve_power.setSingleStep(0.1)
        self.spin_ion_curve_power.setValue(1.0)
        self.slider_ion_aperture_shadow, self.lbl_ion_aperture_shadow_value, self.ion_aperture_shadow_row = (
            self._make_ion_shadow_slider(100)
        )
        self.slider_ion_lateral_shadow, self.lbl_ion_lateral_shadow_value, self.ion_lateral_shadow_row = (
            self._make_ion_shadow_slider(100)
        )
        self.slider_ion_edge_shadow, self.lbl_ion_edge_shadow_value, self.ion_edge_shadow_row = (
            self._make_ion_shadow_slider(100)
        )
        self.chk_reflected_ion = QCheckBox("Reflected ion")
        self.chk_reflected_ion.setChecked(False)
        self.spin_reflected_strength = QDoubleSpinBox()
        self.spin_reflected_strength.setRange(0.0, 100.0)
        self.spin_reflected_strength.setDecimals(1)
        self.spin_reflected_strength.setSingleStep(5.0)
        self.spin_reflected_strength.setValue(35.0)
        self.spin_reflected_bowing = QDoubleSpinBox()
        self.spin_reflected_bowing.setRange(0.0, 2.0)
        self.spin_reflected_bowing.setDecimals(2)
        self.spin_reflected_bowing.setSingleStep(0.05)
        self.spin_reflected_bowing.setValue(0.75)
        self.spin_reflected_microtrench = QDoubleSpinBox()
        self.spin_reflected_microtrench.setRange(0.0, 2.0)
        self.spin_reflected_microtrench.setDecimals(2)
        self.spin_reflected_microtrench.setSingleStep(0.05)
        self.spin_reflected_microtrench.setValue(1.0)
        self.spin_reflected_range = QDoubleSpinBox()
        self.spin_reflected_range.setRange(50.0, 10000.0)
        self.spin_reflected_range.setDecimals(0)
        self.spin_reflected_range.setSingleStep(100.0)
        self.spin_reflected_range.setValue(1600.0)
        self.chk_redepo = QCheckBox("Redepo enabled")
        self.chk_redepo.setChecked(False)
        self.cmb_redepo_source_model = QComboBox()
        self.cmb_redepo_source_model.addItem("Model2 ion source", "model2")
        self.cmb_redepo_source_model.setCurrentIndex(0)
        self.cmb_redepo_source_model.setToolTip("Redeposition source는 ion transmission 경로로 고정됩니다.")
        self.spin_redepo_efficiency = QDoubleSpinBox()
        self.spin_redepo_efficiency.setRange(0.0, 100.0)
        self.spin_redepo_efficiency.setDecimals(1)
        self.spin_redepo_efficiency.setSingleStep(5.0)
        self.spin_redepo_efficiency.setValue(25.0)
        self.spin_redepo_emit_power = QDoubleSpinBox()
        self.spin_redepo_emit_power.setRange(0.0, 8.0)
        self.spin_redepo_emit_power.setDecimals(2)
        self.spin_redepo_emit_power.setSingleStep(0.1)
        self.spin_redepo_emit_power.setValue(1.0)
        self.spin_redepo_distance_power = QDoubleSpinBox()
        self.spin_redepo_distance_power.setRange(0.0, 4.0)
        self.spin_redepo_distance_power.setDecimals(2)
        self.spin_redepo_distance_power.setSingleStep(0.1)
        self.spin_redepo_distance_power.setValue(1.0)
        self.spin_redepo_soft_los = QSpinBox()
        self.spin_redepo_soft_los.setRange(0, 2)
        self.spin_redepo_soft_los.setSingleStep(1)
        self.spin_redepo_soft_los.setValue(0)
        self.spin_redepo_soft_los.setToolTip("0=fast hard LOS, 1=soft shadow edge, 2=stronger/slow quality.")
        self.chk_lf_overhang = QCheckBox("LF overhang proxy")
        self.chk_lf_overhang.setChecked(False)
        self.chk_lf_overhang.setToolTip("upper/facet sputter source를 shadow-boundary toe에 빠른 Gaussian proxy로 재분배합니다.")
        self.spin_lf_overhang_dose = QDoubleSpinBox()
        self.spin_lf_overhang_dose.setRange(0.0, 10.0)
        self.spin_lf_overhang_dose.setDecimals(2)
        self.spin_lf_overhang_dose.setSingleStep(0.1)
        self.spin_lf_overhang_dose.setValue(1.0)
        self.spin_lf_overhang_sputter_gain = QDoubleSpinBox()
        self.spin_lf_overhang_sputter_gain.setRange(0.0, 10.0)
        self.spin_lf_overhang_sputter_gain.setDecimals(2)
        self.spin_lf_overhang_sputter_gain.setSingleStep(0.1)
        self.spin_lf_overhang_sputter_gain.setValue(1.0)
        self.spin_lf_overhang_redepo_fraction = QDoubleSpinBox()
        self.spin_lf_overhang_redepo_fraction.setRange(0.0, 100.0)
        self.spin_lf_overhang_redepo_fraction.setDecimals(1)
        self.spin_lf_overhang_redepo_fraction.setSingleStep(5.0)
        self.spin_lf_overhang_redepo_fraction.setValue(30.0)
        self.spin_lf_overhang_survival = QDoubleSpinBox()
        self.spin_lf_overhang_survival.setRange(0.0, 4.0)
        self.spin_lf_overhang_survival.setDecimals(2)
        self.spin_lf_overhang_survival.setSingleStep(0.05)
        self.spin_lf_overhang_survival.setValue(0.75)
        self.spin_lf_overhang_width = QDoubleSpinBox()
        self.spin_lf_overhang_width.setRange(1.0, 5000.0)
        self.spin_lf_overhang_width.setDecimals(1)
        self.spin_lf_overhang_width.setSingleStep(20.0)
        self.spin_lf_overhang_width.setValue(180.0)
        self.chk_closure_redepo = QCheckBox("Etch+Redepo closure")
        self.chk_closure_redepo.setChecked(False)
        self.chk_closure_redepo.setToolTip("모든 positive etch source를 LOS redeposition source로 쓰고, shadow/neck capture로 upper closure를 검증합니다.")
        self.spin_closure_redepo_efficiency = QDoubleSpinBox()
        self.spin_closure_redepo_efficiency.setRange(0.0, 100.0)
        self.spin_closure_redepo_efficiency.setDecimals(1)
        self.spin_closure_redepo_efficiency.setSingleStep(5.0)
        self.spin_closure_redepo_efficiency.setValue(35.0)
        self.spin_closure_redepo_shadow_gain = QDoubleSpinBox()
        self.spin_closure_redepo_shadow_gain.setRange(0.0, 20.0)
        self.spin_closure_redepo_shadow_gain.setDecimals(2)
        self.spin_closure_redepo_shadow_gain.setSingleStep(0.1)
        self.spin_closure_redepo_shadow_gain.setValue(2.0)
        self.spin_closure_redepo_width = QDoubleSpinBox()
        self.spin_closure_redepo_width.setRange(1.0, 5000.0)
        self.spin_closure_redepo_width.setDecimals(1)
        self.spin_closure_redepo_width.setSingleStep(20.0)
        self.spin_closure_redepo_width.setValue(160.0)
        self.spin_closure_redepo_survival = QDoubleSpinBox()
        self.spin_closure_redepo_survival.setRange(0.0, 4.0)
        self.spin_closure_redepo_survival.setDecimals(2)
        self.spin_closure_redepo_survival.setSingleStep(0.05)
        self.spin_closure_redepo_survival.setValue(0.85)
        self.spin_closure_redepo_smoothing = QDoubleSpinBox()
        self.spin_closure_redepo_smoothing.setRange(0.0, 5000.0)
        self.spin_closure_redepo_smoothing.setDecimals(1)
        self.spin_closure_redepo_smoothing.setSingleStep(20.0)
        self.spin_closure_redepo_smoothing.setValue(160.0)
        self.chk_depth_deposition = QCheckBox("Depth depletion deposition")
        self.chk_depth_deposition.setToolTip("깊이/등가 AR에 따라 deposition 양이 줄어드는 순수 depth depletion 모델입니다.")
        self.chk_depth_deposition.setChecked(True)
        self.chk_inhibition_deposition = QCheckBox("Inhibition deposition")
        self.chk_inhibition_deposition.setToolTip("표면 inhibition coverage로 상부/노출부 성장을 억제하는 별도 deposition 모델입니다.")
        self.chk_inhibition_deposition.setChecked(False)
        self.cmb_depth_feature_type = QComboBox()
        self.cmb_depth_feature_type.addItem("Hole", "hole")
        self.cmb_depth_feature_type.addItem("Line", "line")
        self.cmb_depth_feature_type.setCurrentIndex(0)
        self.spin_depth_feature_width = QDoubleSpinBox()
        self.spin_depth_feature_width.setRange(1.0, 100000.0)
        self.spin_depth_feature_width.setDecimals(1)
        self.spin_depth_feature_width.setSingleStep(10.0)
        self.spin_depth_feature_width.setValue(240.0)
        self.spin_depth_feature_depth = QDoubleSpinBox()
        self.spin_depth_feature_depth.setRange(1.0, 200000.0)
        self.spin_depth_feature_depth.setDecimals(1)
        self.spin_depth_feature_depth.setSingleStep(100.0)
        self.spin_depth_feature_depth.setValue(4700.0)
        self.spin_depth_feature_length = QDoubleSpinBox()
        self.spin_depth_feature_length.setRange(0.0, 1000000.0)
        self.spin_depth_feature_length.setDecimals(1)
        self.spin_depth_feature_length.setSingleStep(1000.0)
        self.spin_depth_feature_length.setSpecialValueText("Auto/open")
        self.spin_depth_feature_length.setValue(0.0)
        self.spin_depth_decay_k = QDoubleSpinBox()
        self.spin_depth_decay_k.setRange(0.0, 20.0)
        self.spin_depth_decay_k.setDecimals(3)
        self.spin_depth_decay_k.setSingleStep(0.1)
        self.spin_depth_decay_k.setValue(0.8)
        self.spin_depth_decay_power = QDoubleSpinBox()
        self.spin_depth_decay_power.setRange(0.05, 8.0)
        self.spin_depth_decay_power.setDecimals(2)
        self.spin_depth_decay_power.setSingleStep(0.1)
        self.spin_depth_decay_power.setValue(1.2)
        self.spin_depth_min_ratio_pct = QDoubleSpinBox()
        self.spin_depth_min_ratio_pct.setRange(0.0, 100.0)
        self.spin_depth_min_ratio_pct.setDecimals(1)
        self.spin_depth_min_ratio_pct.setSingleStep(1.0)
        self.spin_depth_min_ratio_pct.setValue(3.0)
        self.spin_depth_closure_threshold = QDoubleSpinBox()
        self.spin_depth_closure_threshold.setRange(0.0, 10000.0)
        self.spin_depth_closure_threshold.setDecimals(1)
        self.spin_depth_closure_threshold.setSingleStep(1.0)
        self.spin_depth_closure_threshold.setValue(8.0)
        self.spin_depth_post_fill_hole_pct = QDoubleSpinBox()
        self.spin_depth_post_fill_hole_pct.setRange(0.0, 100.0)
        self.spin_depth_post_fill_hole_pct.setDecimals(1)
        self.spin_depth_post_fill_hole_pct.setSingleStep(1.0)
        self.spin_depth_post_fill_hole_pct.setValue(3.0)
        self.spin_depth_post_fill_line_pct = QDoubleSpinBox()
        self.spin_depth_post_fill_line_pct.setRange(0.0, 100.0)
        self.spin_depth_post_fill_line_pct.setDecimals(1)
        self.spin_depth_post_fill_line_pct.setSingleStep(2.5)
        self.spin_depth_post_fill_line_pct.setValue(20.0)
        self.spin_depth_line_open_path = QDoubleSpinBox()
        self.spin_depth_line_open_path.setRange(0.0, 1.0)
        self.spin_depth_line_open_path.setDecimals(2)
        self.spin_depth_line_open_path.setSingleStep(0.05)
        self.spin_depth_line_open_path.setValue(1.0)
        self.spin_depth_residual_decay = QDoubleSpinBox()
        self.spin_depth_residual_decay.setRange(1.0, 200000.0)
        self.spin_depth_residual_decay.setDecimals(1)
        self.spin_depth_residual_decay.setSingleStep(100.0)
        self.spin_depth_residual_decay.setValue(1175.0)
        self.spin_inhibition_strength = QDoubleSpinBox()
        self.spin_inhibition_strength.setRange(0.0, 100.0)
        self.spin_inhibition_strength.setDecimals(1)
        self.spin_inhibition_strength.setSingleStep(5.0)
        self.spin_inhibition_strength.setValue(85.0)
        self.spin_inhibition_penetration = QDoubleSpinBox()
        self.spin_inhibition_penetration.setRange(1.0, 200000.0)
        self.spin_inhibition_penetration.setDecimals(1)
        self.spin_inhibition_penetration.setSingleStep(100.0)
        self.spin_inhibition_penetration.setValue(1100.0)
        self.spin_inhibition_decay_power = QDoubleSpinBox()
        self.spin_inhibition_decay_power.setRange(0.05, 8.0)
        self.spin_inhibition_decay_power.setDecimals(2)
        self.spin_inhibition_decay_power.setSingleStep(0.1)
        self.spin_inhibition_decay_power.setValue(1.2)
        self.spin_inhibition_min_growth = QDoubleSpinBox()
        self.spin_inhibition_min_growth.setRange(0.0, 100.0)
        self.spin_inhibition_min_growth.setDecimals(1)
        self.spin_inhibition_min_growth.setSingleStep(1.0)
        self.spin_inhibition_min_growth.setValue(8.0)
        self.spin_inhibition_bottom_boost = QDoubleSpinBox()
        self.spin_inhibition_bottom_boost.setRange(0.0, 100.0)
        self.spin_inhibition_bottom_boost.setDecimals(1)
        self.spin_inhibition_bottom_boost.setSingleStep(5.0)
        self.spin_inhibition_bottom_boost.setValue(20.0)
        self.spin_inhibition_recombination = QDoubleSpinBox()
        self.spin_inhibition_recombination.setRange(0.0, 100.0)
        self.spin_inhibition_recombination.setDecimals(1)
        self.spin_inhibition_recombination.setSingleStep(5.0)
        self.spin_inhibition_recombination.setValue(35.0)
        self.spin_inhibition_smoothing = QDoubleSpinBox()
        self.spin_inhibition_smoothing.setRange(0.0, 1000.0)
        self.spin_inhibition_smoothing.setDecimals(1)
        self.spin_inhibition_smoothing.setSingleStep(10.0)
        self.spin_inhibition_smoothing.setValue(45.0)
        self.depth_deposition_editor = DepthDepositionProfileEditor()
        self.depth_deposition_editor.set_depo_rate_a_per_cycle(float(self.spin_angstrom_per_cycle.value()))
        self.depth_deposition_editor.set_feature_geometry(
            str(self.cmb_depth_feature_type.currentData() or "hole"),
            float(self.spin_depth_feature_width.value()),
            float(self.spin_depth_feature_depth.value()),
            None,
        )
        self.depth_deposition_editor.set_parameters(
            float(self.spin_depth_decay_k.value()),
            float(self.spin_depth_decay_power.value()),
            float(self.spin_depth_min_ratio_pct.value()),
            float(self.spin_depth_closure_threshold.value()),
        )
        self.inhibition_profile_editor = InhibitionProfileEditor()
        self.inhibition_profile_editor.set_feature_depth(float(self.spin_depth_feature_depth.value()))
        self.inhibition_profile_editor.set_parameters(
            float(self.spin_inhibition_strength.value()),
            float(self.spin_inhibition_penetration.value()),
            float(self.spin_inhibition_decay_power.value()),
            float(self.spin_inhibition_min_growth.value()),
            float(self.spin_inhibition_bottom_boost.value()),
            float(self.spin_inhibition_recombination.value()),
        )
        self.spin_sputter_strength = QDoubleSpinBox()
        self.spin_sputter_strength.setRange(0.0, 100.0)
        self.spin_sputter_strength.setDecimals(3)
        self.spin_sputter_strength.setSingleStep(0.5)
        self.spin_sputter_strength.setValue(4.0)
        self.spin_sputter_peak_pct = QDoubleSpinBox()
        self.spin_sputter_peak_pct.setRange(0.0, 100.0)
        self.spin_sputter_peak_pct.setDecimals(1)
        self.spin_sputter_peak_pct.setSingleStep(5.0)
        self.spin_sputter_peak_pct.setValue(100.0)
        self.spin_sputter_peak = QDoubleSpinBox()
        self.spin_sputter_peak.setRange(0.0, 89.9)
        self.spin_sputter_peak.setDecimals(1)
        self.spin_sputter_peak.setSingleStep(1.0)
        self.spin_sputter_peak.setValue(55.0)
        self.spin_sputter_width = QDoubleSpinBox()
        self.spin_sputter_width.setRange(1.0, 60.0)
        self.spin_sputter_width.setDecimals(1)
        self.spin_sputter_width.setSingleStep(1.0)
        self.spin_sputter_width.setValue(14.0)
        self.spin_sputter_smoothing = QDoubleSpinBox()
        self.spin_sputter_smoothing.setRange(0.0, 200.0)
        self.spin_sputter_smoothing.setDecimals(1)
        self.spin_sputter_smoothing.setSingleStep(2.5)
        self.spin_sputter_smoothing.setValue(40.0)
        self.sputter_curve_editor = SputterGaussianEditor()
        self.sputter_curve_editor.set_parameters(
            float(self.spin_sputter_peak_pct.value()),
            float(self.spin_sputter_peak.value()),
            float(self.spin_sputter_width.value()),
        )
        self.sputter_curve_editor.set_etch_cap_a(float(self.spin_sputter_strength.value()))
        self.ion_transmission_editor = IonTransmissionEditor()
        self.ion_transmission_editor.set_parameters(
            float(self.spin_ion_start_depth.value()),
            float(self.spin_ion_end_depth.value()),
            float(self.spin_ion_decay_strength.value()),
            float(self.spin_ion_floor.value()),
            float(self.spin_ion_curve_power.value()),
        )
        self.redepo_lobe_editor = RedepositionLobeEditor()
        self.redepo_lobe_editor.set_parameters(
            float(self.spin_redepo_efficiency.value()),
            float(self.spin_redepo_emit_power.value()),
            float(self.spin_redepo_distance_power.value()),
        )

        self.btn_run = QPushButton("실행")
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setToolTip("현재 구조와 공정 파라미터로 에뮬레이션을 실행합니다.")
        self.btn_run.setStyleSheet("font-weight: 700;")
        self.btn_reset = QPushButton("초기화")
        self.btn_open_json = QPushButton("Run 불러오기")
        self.btn_open_json.setToolTip("저장된 run JSON을 열어 파라미터와 결과 프레임을 다시 불러옵니다.")
        self.progress_run = QProgressBar()
        self.progress_run.setRange(0, 100)
        self.progress_run.setValue(0)
        self.progress_run.setTextVisible(True)
        self.progress_run.setFormat("대기")
        self.progress_run.setVisible(False)
        self.progress_run.setFixedHeight(18)
        self.slider_frame = QSlider(Qt.Orientation.Horizontal)
        self.slider_frame.setRange(0, 0)
        self.slider_frame.setEnabled(False)
        self.btn_result_play = QPushButton("반복재생")
        self.btn_result_play.setEnabled(False)
        self.btn_next_depo = QPushButton("다음 Depo: 2차")
        self.btn_next_depo.setEnabled(False)
        self.btn_next_depo.setToolTip("현재 결과의 마지막 profile에서 다음 Depo 차수를 이어서 시작합니다.")
        self.chk_show_etch_overlay = QCheckBox("에치 파랑")
        self.chk_show_etch_overlay.setChecked(True)
        self.chk_show_etch_overlay.setToolTip("실제 에치가 강한 위치를 파란색으로 표시합니다.")
        self.chk_show_redepo_overlay = QCheckBox("리뎁 빨강")
        self.chk_show_redepo_overlay.setChecked(False)
        self.chk_show_redepo_overlay.setVisible(False)
        self.chk_show_redepo_overlay.setToolTip("활성 리데포 모델의 target field를 반투명 빨강으로 표시합니다.")
        self.lbl_status = QLabel("Cycle 0/0 | 점 0")
        self.edit_request_note = QPlainTextEdit()
        self.edit_request_note.setPlaceholderText("요청사항 / 물리 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
        self.edit_request_note.setMaximumHeight(88)
        self.edit_request_note.setPlainText("라운드 conformal offset 기반 트렌치 증착")
        self.lbl_run_dir = QLabel("저장된 run: 아직 없음")
        self.lbl_run_dir.setMinimumWidth(0)
        self.lbl_run_dir.setWordWrap(False)
        self.lbl_run_dir.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.btn_open_run_dir = QPushButton("폴더 열기")
        self.btn_open_run_dir.setEnabled(False)
        self.btn_save_result_json = QPushButton("결과 JSON 저장")
        self.btn_save_result_json.setEnabled(False)
        self.btn_save_result_json.setToolTip(
            "현재 결과의 구조, 진행/공정 파라미터, 전체 결과 frame을 날짜별 JSON 파일로 저장합니다."
        )

        self.cmb_emulator_default_preset = QComboBox()
        self.cmb_emulator_default_preset.setToolTip("선택한 에뮬레이터의 기본 공정값을 불러옵니다.")
        self.cmb_parameter_preset = QComboBox()
        self.cmb_parameter_preset.setToolTip("저장된 공정 파라미터 프리셋입니다. 구조 좌표는 포함하지 않습니다.")
        self.edit_parameter_preset_name = QLineEdit()
        self.edit_parameter_preset_name.setPlaceholderText("공정 프리셋 이름")
        self.btn_reload_parameter_presets = QPushButton("새로고침")
        self.btn_apply_parameter_preset = QPushButton("적용")
        self.btn_save_parameter_preset = QPushButton("저장")
        self.btn_delete_parameter_preset = QPushButton("삭제")
        self.lbl_parameter_preset_active = QLabel("활성: 없음")
        self.lbl_parameter_preset_active.setWordWrap(True)
        self.lbl_parameter_preset_path = QLabel("")
        self.lbl_parameter_preset_path.setWordWrap(True)

        self.cmb_split_parameter = QComboBox()
        self.spin_split_start = QDoubleSpinBox()
        self.spin_split_end = QDoubleSpinBox()
        self.spin_split_step = QDoubleSpinBox()
        for spin in (self.spin_split_start, self.spin_split_end):
            spin.setDecimals(3)
            spin.setRange(0.0, 10000.0)
            spin.setSingleStep(1.0)
        self.spin_split_step.setDecimals(3)
        self.spin_split_step.setRange(0.001, 10000.0)
        self.spin_split_step.setSingleStep(1.0)
        self.cmb_compare_target = QComboBox()
        self.btn_split_options = QPushButton("Split Test")
        self.btn_split_options.setCheckable(True)
        self.btn_compare_options = QPushButton("Compare Test")
        self.btn_compare_options.setCheckable(True)
        self.btn_run_split = QPushButton("Split Test 실행")
        self.btn_run_compare = QPushButton("Compare Test 실행")

        status = QStatusBar(self)
        self.setStatusBar(status)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(QLabel("Frame"))
        controls.addWidget(self.slider_frame, 1)
        controls.addWidget(self.lbl_status)
        controls.addWidget(self.chk_show_etch_overlay)
        controls.addWidget(self.chk_show_redepo_overlay)
        controls.addWidget(self.btn_result_play)
        controls.addWidget(self.btn_next_depo)

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 0, 0, 0)
        run_row.addWidget(self.lbl_run_dir, 1)
        run_row.addWidget(self.btn_open_run_dir)

        self.view_tabs = QTabWidget()
        self.lbl_progress_view_status = QLabel("진행 대기")
        self.lbl_progress_view_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_view_bar = QProgressBar()
        self.progress_view_bar.setRange(0, 1)
        self.progress_view_bar.setValue(0)
        self.progress_view_bar.setTextVisible(True)
        self.progress_view_bar.setFormat("대기")
        self.progress_view_bar.setFixedWidth(360)
        self.lbl_progress_geometry_source = QLabel("실행 입력: raw")
        self.lbl_progress_geometry_source.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_tab = QWidget()
        progress_layout = QVBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(6)
        progress_status_row = QHBoxLayout()
        progress_status_row.setContentsMargins(0, 0, 0, 0)
        progress_status_row.addWidget(self.lbl_progress_view_status)
        progress_status_row.addStretch(1)
        progress_status_row.addWidget(self.progress_view_bar)
        progress_layout.addWidget(self.progress_geometry_view, 1)
        progress_layout.addWidget(self.lbl_progress_geometry_source)
        progress_layout.addLayout(progress_status_row)
        progress_tab.setLayout(progress_layout)

        result_tab = QWidget()
        result_layout = QVBoxLayout()
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(self.view, 1)
        result_tab.setLayout(result_layout)

        self.btn_fit_structure = QPushButton("화면 맞춤")
        self.btn_reset_structure = QPushButton("기본 구조")
        self.chk_symmetric_structure_edit = QCheckBox("좌우대칭 이동")
        self.chk_symmetric_structure_edit.setToolTip("구조 점을 움직일 때 x=0 기준 반대편 대응점을 (-x, y)로 같이 이동합니다.")
        self.lbl_geometry_points = QLabel("구조: 0점")
        self.lbl_geometry_source = QLabel("입력: raw")
        self.lbl_geometry_source.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cmb_structure_library = QComboBox()
        self.edit_structure_name = QLineEdit()
        self.edit_structure_name.setPlaceholderText("구조 이름 / 프리셋")
        self.btn_reload_structure_library = QPushButton("새로고침")
        self.btn_save_structure = QPushButton("Excel 저장")
        self.btn_delete_structure = QPushButton("삭제")
        self.btn_export_default_structures = QPushButton("기본 구조 내보내기")
        self.btn_open_structure_workbook = QPushButton("Excel 열기")
        self.lbl_structure_library_path = QLabel("")
        self.lbl_structure_library_path.setWordWrap(True)
        self.lbl_structure_library_active = QLabel("활성: 에뮬레이터 기본값")
        self.lbl_structure_library_active.setWordWrap(True)
        structure_buttons = QHBoxLayout()
        structure_buttons.setContentsMargins(0, 0, 0, 0)
        structure_buttons.addWidget(self.btn_fit_structure)
        structure_buttons.addWidget(self.btn_reset_structure)
        structure_buttons.addWidget(self.chk_symmetric_structure_edit)
        structure_buttons.addWidget(self.lbl_geometry_points, 1)
        structure_buttons.addWidget(self.lbl_geometry_source)

        structure_tab = QWidget()
        structure_layout = QVBoxLayout()
        structure_layout.setContentsMargins(0, 0, 0, 0)
        structure_layout.setSpacing(6)
        structure_layout.addWidget(self.structure_view, 1)
        structure_layout.addLayout(structure_buttons)
        structure_tab.setLayout(structure_layout)

        self.spin_smooth_segments = QSpinBox()
        self.spin_smooth_segments.setRange(1, 5000)
        self.spin_smooth_segments.setSingleStep(20)
        self.spin_smooth_segments.setValue(240)
        self.spin_smooth_iterations = QSpinBox()
        self.spin_smooth_iterations.setRange(0, 200)
        self.spin_smooth_iterations.setSingleStep(1)
        self.spin_smooth_iterations.setValue(4)
        self.btn_apply_smoothing = QPushButton("스무딩 적용")
        self.btn_use_smoothed_geometry = QPushButton("스무딩 사용")
        self.btn_use_raw_geometry = QPushButton("Raw 사용")
        self.lbl_smoothing_status = QLabel("스무딩: 미적용")
        smooth_grid = QGridLayout()
        smooth_grid.setContentsMargins(0, 0, 0, 0)
        smooth_grid.setHorizontalSpacing(8)
        smooth_grid.setVerticalSpacing(6)
        smooth_grid.addWidget(QLabel("분할"), 0, 0)
        smooth_grid.addWidget(self.spin_smooth_segments, 0, 1)
        smooth_grid.addWidget(QLabel("반복"), 0, 2)
        smooth_grid.addWidget(self.spin_smooth_iterations, 0, 3)
        smooth_grid.addWidget(self.btn_apply_smoothing, 0, 4)
        smooth_grid.addWidget(self.btn_use_smoothed_geometry, 1, 0, 1, 2)
        smooth_grid.addWidget(self.btn_use_raw_geometry, 1, 2, 1, 2)
        smooth_grid.addWidget(self.lbl_smoothing_status, 1, 4)

        smoothing_tab = QWidget()
        smoothing_layout = QVBoxLayout()
        smoothing_layout.setContentsMargins(0, 0, 0, 0)
        smoothing_layout.setSpacing(6)
        smoothing_layout.addWidget(self.smoothing_view, 1)
        smoothing_tab.setLayout(smoothing_layout)

        self.view_tabs.addTab(structure_tab, "1 구조")
        self.view_tabs.addTab(smoothing_tab, "2 스무딩")
        self.view_tabs.addTab(progress_tab, "3 진행")
        self.view_tabs.addTab(result_tab, "4 결과")

        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(8, 8, 6, 8)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.view_tabs, 1)
        self.result_controls_widget = QWidget()
        self.result_controls_widget.setLayout(controls)
        left_layout.addWidget(self.result_controls_widget)
        left_panel.setLayout(left_layout)

        emulator_group = QGroupBox("3 진행 / 에뮬레이터 버전")
        emulator_layout = QVBoxLayout()
        emulator_layout.setContentsMargins(10, 10, 10, 10)
        emulator_layout.addLayout(self.emulator_toggle_row)
        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.addWidget(QLabel("기본 옵션"))
        preset_row.addWidget(self.cmb_emulator_default_preset, 1)
        emulator_layout.addLayout(preset_row)
        emulator_group.setLayout(emulator_layout)

        parameter_preset_group = QGroupBox("공정 파라미터 프리셋")
        parameter_preset_layout = QGridLayout()
        parameter_preset_layout.setContentsMargins(10, 10, 10, 10)
        parameter_preset_layout.setHorizontalSpacing(8)
        parameter_preset_layout.setVerticalSpacing(8)
        parameter_preset_layout.addWidget(QLabel("프리셋"), 0, 0)
        parameter_preset_layout.addWidget(self.cmb_parameter_preset, 0, 1, 1, 3)
        parameter_preset_layout.addWidget(QLabel("이름"), 1, 0)
        parameter_preset_layout.addWidget(self.edit_parameter_preset_name, 1, 1, 1, 3)
        parameter_preset_layout.addWidget(self.btn_reload_parameter_presets, 2, 0)
        parameter_preset_layout.addWidget(self.btn_apply_parameter_preset, 2, 1)
        parameter_preset_layout.addWidget(self.btn_save_parameter_preset, 2, 2)
        parameter_preset_layout.addWidget(self.btn_delete_parameter_preset, 2, 3)
        parameter_preset_layout.addWidget(self.lbl_parameter_preset_active, 3, 0, 1, 4)
        parameter_preset_layout.addWidget(self.lbl_parameter_preset_path, 4, 0, 1, 4)
        parameter_preset_group.setLayout(parameter_preset_layout)

        self.structure_points_model = PointsTableModel()
        self.structure_points_table = PointsTableView()
        self.structure_points_table.setModel(self.structure_points_model)
        self.structure_points_table.setMinimumHeight(160)
        self.structure_points_group = QGroupBox("구조 좌표")
        structure_points_layout = QVBoxLayout()
        structure_points_layout.setContentsMargins(10, 10, 10, 10)
        structure_points_layout.addWidget(self.structure_points_table, 1)
        self.structure_points_group.setLayout(structure_points_layout)

        self.structure_library_group = QGroupBox("구조 라이브러리")
        structure_library_layout = QGridLayout()
        structure_library_layout.setContentsMargins(10, 10, 10, 10)
        structure_library_layout.setHorizontalSpacing(8)
        structure_library_layout.setVerticalSpacing(8)
        structure_library_layout.addWidget(QLabel("프리셋"), 0, 0)
        structure_library_layout.addWidget(self.cmb_structure_library, 0, 1, 1, 3)
        structure_library_layout.addWidget(QLabel("이름"), 1, 0)
        structure_library_layout.addWidget(self.edit_structure_name, 1, 1, 1, 3)
        structure_library_layout.addWidget(self.btn_reload_structure_library, 2, 0)
        structure_library_layout.addWidget(self.btn_save_structure, 2, 1)
        structure_library_layout.addWidget(self.btn_open_structure_workbook, 2, 2)
        structure_library_layout.addWidget(self.btn_delete_structure, 2, 3)
        structure_library_layout.addWidget(self.btn_export_default_structures, 3, 0, 1, 2)
        structure_library_layout.addWidget(self.lbl_structure_library_active, 3, 2, 1, 2)
        structure_library_layout.addWidget(self.lbl_structure_library_path, 4, 0, 1, 4)
        self.structure_library_group.setLayout(structure_library_layout)

        self.btn_load_overlay = QPushButton("이미지 불러오기")
        self.btn_clear_overlay = QPushButton("이미지 지우기")
        self.btn_move_overlay = QPushButton("이미지 이동")
        self.btn_move_overlay.setCheckable(True)
        self.btn_move_overlay.setEnabled(False)
        self.lbl_overlay_opacity = QLabel("불투명도")
        self.slider_overlay_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_overlay_opacity.setRange(0, 100)
        self.slider_overlay_opacity.setValue(int(round(self._overlay_opacity * 100.0)))
        self.slider_overlay_opacity.setFixedWidth(160)
        self.overlay_group = QGroupBox("이미지 오버레이")
        overlay_layout = QVBoxLayout()
        overlay_layout.setContentsMargins(10, 10, 10, 10)
        overlay_buttons = QHBoxLayout()
        overlay_buttons.addWidget(self.btn_load_overlay)
        overlay_buttons.addWidget(self.btn_clear_overlay)
        overlay_buttons.addWidget(self.btn_move_overlay)
        overlay_layout.addLayout(overlay_buttons)
        overlay_opacity_row = QHBoxLayout()
        overlay_opacity_row.addWidget(self.lbl_overlay_opacity)
        overlay_opacity_row.addWidget(self.slider_overlay_opacity)
        overlay_opacity_row.addStretch(1)
        overlay_layout.addLayout(overlay_opacity_row)
        self.overlay_group.setLayout(overlay_layout)

        self.smoothing_controls_group = QGroupBox("스무딩")
        smoothing_controls_layout = QVBoxLayout()
        smoothing_controls_layout.setContentsMargins(10, 10, 10, 10)
        smoothing_controls_layout.setSpacing(8)
        smoothing_controls_layout.addLayout(smooth_grid)
        self.smoothing_controls_group.setLayout(smoothing_controls_layout)
        self.smoothed_points_model = PointsTableModel()
        self.smoothed_points_table = PointsTableView()
        self.smoothed_points_table.setModel(self.smoothed_points_model)
        self.smoothed_points_table.setEditTriggers(PointsTableView.NoEditTriggers)
        self.smoothed_points_table.setMinimumHeight(160)
        self.smoothed_points_group = QGroupBox("스무딩 결과 좌표")
        smoothed_points_layout = QVBoxLayout()
        smoothed_points_layout.setContentsMargins(10, 10, 10, 10)
        smoothed_points_layout.addWidget(self.smoothed_points_table, 1)
        self.smoothed_points_group.setLayout(smoothed_points_layout)

        params_group = QGroupBox("3 진행 / 공정 파라미터")
        params_grid = QGridLayout()
        params_grid.setContentsMargins(10, 10, 10, 10)
        params_grid.setHorizontalSpacing(8)
        params_grid.setVerticalSpacing(8)
        self.lbl_deposition_section = self._make_parameter_section("Deposition base")
        self.lbl_etch_section = self._make_parameter_section(
            "Direct angle sputter etch",
            color="#0f766e",
            background="#f0fdfa",
            border="#99f6e4",
            section_key="direct",
        )
        self.lbl_sputter_section = self._make_parameter_section(
            "Angle response kernel",
            color="#1d4ed8",
            background="#eff6ff",
            border="#bfdbfe",
        )
        self.lbl_ion_depth_section = self._make_parameter_section(
            "Ion transmission - depth curve",
            color="#0e7490",
            background="#ecfeff",
            border="#a5f3fc",
            section_key="ion",
        )
        self.lbl_ion_geometry_section = self._make_parameter_section(
            "Geometry shadowing 보정",
            color="#155e75",
            background="#f0f9ff",
            border="#bae6fd",
        )
        params_grid.addWidget(self.lbl_deposition_section, 0, 0, 1, 2)
        params_grid.addWidget(QLabel("Cycles"), 1, 0)
        params_grid.addWidget(self.spin_cycles, 1, 1)
        deposition_controls = QWidget()
        deposition_controls_layout = QGridLayout()
        deposition_controls_layout.setContentsMargins(0, 0, 0, 0)
        deposition_controls_layout.setHorizontalSpacing(6)
        deposition_controls_layout.setVerticalSpacing(4)
        self.lbl_depo_rate = QLabel("Depo A/CYC")
        self.lbl_quality_mode = QLabel("품질")
        self.lbl_reparam_ds = QLabel("조각 크기")
        deposition_controls_layout.addWidget(self.lbl_depo_rate, 0, 0)
        deposition_controls_layout.addWidget(self.spin_angstrom_per_cycle, 0, 1)
        deposition_controls_layout.addWidget(self.lbl_quality_mode, 1, 0)
        deposition_controls_layout.addWidget(self.cmb_quality_mode, 1, 1)
        deposition_controls_layout.addWidget(self.lbl_reparam_ds, 2, 0)
        deposition_controls_layout.addWidget(self.spin_reparam_ds, 2, 1)
        deposition_controls.setLayout(deposition_controls_layout)
        params_grid.addWidget(deposition_controls, 2, 0, 1, 2)
        params_grid.addWidget(self.lbl_etch_section, 3, 0, 1, 2)
        params_grid.addWidget(self.chk_sputter, 4, 0, 1, 2)
        params_grid.addWidget(self.lbl_sputter_section, 5, 0, 1, 2)
        self.lbl_sputter_strength = QLabel("Etch A/CYC")
        self.lbl_sputter_peak_pct = QLabel("Peak %")
        self.lbl_sputter_peak = QLabel("Peak")
        self.lbl_sputter_width = QLabel("Width")
        self.lbl_sputter_smoothing = QLabel("스무딩 A")
        params_grid.addWidget(self.lbl_sputter_strength, 6, 0)
        params_grid.addWidget(self.spin_sputter_strength, 6, 1)
        params_grid.addWidget(self.lbl_sputter_peak_pct, 7, 0)
        params_grid.addWidget(self.spin_sputter_peak_pct, 7, 1)
        params_grid.addWidget(self.lbl_sputter_peak, 8, 0)
        params_grid.addWidget(self.spin_sputter_peak, 8, 1)
        params_grid.addWidget(self.lbl_sputter_width, 9, 0)
        params_grid.addWidget(self.spin_sputter_width, 9, 1)
        params_grid.addWidget(self.lbl_sputter_smoothing, 10, 0)
        params_grid.addWidget(self.spin_sputter_smoothing, 10, 1)
        params_grid.addWidget(self.lbl_ion_depth_section, 11, 0, 1, 2)
        params_grid.addWidget(self.chk_ion_transmission, 12, 0, 1, 2)
        self.lbl_ion_start_depth = QLabel("Ion start %")
        self.lbl_ion_end_depth = QLabel("Ion end %")
        self.lbl_ion_decay_strength = QLabel("Ion drop %")
        self.lbl_ion_floor = QLabel("Ion floor %")
        self.lbl_ion_curve_power = QLabel("Ion curve")
        self.lbl_ion_aperture_shadow = QLabel("Aperture")
        self.lbl_ion_lateral_shadow = QLabel("Hidden")
        self.lbl_ion_edge_shadow = QLabel("Edge")
        params_grid.addWidget(self.lbl_ion_start_depth, 13, 0)
        params_grid.addWidget(self.spin_ion_start_depth, 13, 1)
        params_grid.addWidget(self.lbl_ion_end_depth, 14, 0)
        params_grid.addWidget(self.spin_ion_end_depth, 14, 1)
        params_grid.addWidget(self.lbl_ion_decay_strength, 15, 0)
        params_grid.addWidget(self.spin_ion_decay_strength, 15, 1)
        params_grid.addWidget(self.lbl_ion_floor, 16, 0)
        params_grid.addWidget(self.spin_ion_floor, 16, 1)
        params_grid.addWidget(self.lbl_ion_curve_power, 17, 0)
        params_grid.addWidget(self.spin_ion_curve_power, 17, 1)
        params_grid.addWidget(self.lbl_ion_geometry_section, 18, 0, 1, 2)
        params_grid.addWidget(self.lbl_ion_aperture_shadow, 19, 0)
        params_grid.addWidget(self.ion_aperture_shadow_row, 19, 1)
        params_grid.addWidget(self.lbl_ion_lateral_shadow, 20, 0)
        params_grid.addWidget(self.ion_lateral_shadow_row, 20, 1)
        params_grid.addWidget(self.lbl_ion_edge_shadow, 21, 0)
        params_grid.addWidget(self.ion_edge_shadow_row, 21, 1)
        self.lbl_reflected_section = self._make_parameter_section(
            "Reflected ion",
            color="#b45309",
            background="#fff7ed",
            border="#fed7aa",
            section_key="reflected",
        )
        params_grid.addWidget(self.lbl_reflected_section, 22, 0, 1, 2)
        params_grid.addWidget(self.chk_reflected_ion, 23, 0, 1, 2)
        self.lbl_reflected_strength = QLabel("Reflect %")
        self.lbl_reflected_bowing = QLabel("Bowing")
        self.lbl_reflected_microtrench = QLabel("Microtrench")
        self.lbl_reflected_range = QLabel("Range A")
        params_grid.addWidget(self.lbl_reflected_strength, 24, 0)
        params_grid.addWidget(self.spin_reflected_strength, 24, 1)
        params_grid.addWidget(self.lbl_reflected_bowing, 25, 0)
        params_grid.addWidget(self.spin_reflected_bowing, 25, 1)
        params_grid.addWidget(self.lbl_reflected_microtrench, 26, 0)
        params_grid.addWidget(self.spin_reflected_microtrench, 26, 1)
        params_grid.addWidget(self.lbl_reflected_range, 27, 0)
        params_grid.addWidget(self.spin_reflected_range, 27, 1)
        self.lbl_redepo_section = self._make_parameter_section(
            "Sputter redeposition",
            color="#7c2d12",
            background="#fff7ed",
            border="#fdba74",
            section_key="redepo",
        )
        params_grid.addWidget(self.lbl_redepo_section, 28, 0, 1, 2)
        params_grid.addWidget(self.chk_redepo, 29, 0, 1, 2)
        self.lbl_redepo_source = QLabel("Source fixed")
        self.lbl_redepo_efficiency = QLabel("Redepo %")
        self.lbl_redepo_emit_power = QLabel("Emit power")
        self.lbl_redepo_distance_power = QLabel("Dist power")
        self.lbl_redepo_soft_los = QLabel("Soft LOS")
        params_grid.addWidget(self.lbl_redepo_source, 30, 0)
        params_grid.addWidget(self.cmb_redepo_source_model, 30, 1)
        params_grid.addWidget(self.lbl_redepo_efficiency, 31, 0)
        params_grid.addWidget(self.spin_redepo_efficiency, 31, 1)
        params_grid.addWidget(self.lbl_redepo_emit_power, 32, 0)
        params_grid.addWidget(self.spin_redepo_emit_power, 32, 1)
        params_grid.addWidget(self.lbl_redepo_distance_power, 33, 0)
        params_grid.addWidget(self.spin_redepo_distance_power, 33, 1)
        params_grid.addWidget(self.lbl_redepo_soft_los, 34, 0)
        params_grid.addWidget(self.spin_redepo_soft_los, 34, 1)
        self.lbl_depth_depo_section = self._make_parameter_section(
            "Depth depletion deposition",
            color="#166534",
            background="#f0fdf4",
            border="#bbf7d0",
            section_key="depth",
        )
        params_grid.addWidget(self.lbl_depth_depo_section, 35, 0, 1, 2)
        params_grid.addWidget(self.chk_depth_deposition, 36, 0, 1, 2)
        self.lbl_depth_feature_section = self._make_parameter_section(
            "Hole / Line geometry",
            color="#365314",
            background="#f7fee7",
            border="#d9f99d",
        )
        self.lbl_depth_feature_type = QLabel("형상 타입")
        self.lbl_depth_feature_width = QLabel("입구폭 A")
        self.lbl_depth_feature_depth = QLabel("그래프 기준깊이 A")
        self.lbl_depth_feature_length = QLabel("Line 길이 A")
        self.lbl_depth_curve_section = self._make_parameter_section(
            "Depletion curve",
            color="#166534",
            background="#f0fdf4",
            border="#bbf7d0",
        )
        self.lbl_depth_decay_k = QLabel("Decay K")
        self.lbl_depth_decay_power = QLabel("Power")
        self.lbl_depth_min_ratio = QLabel("최소 depo %")
        self.lbl_depth_closure_section = self._make_parameter_section(
            "Closure 후 추가 fill",
            color="#3f6212",
            background="#f7fee7",
            border="#d9f99d",
        )
        self.lbl_depth_closure_threshold = QLabel("Close A")
        self.lbl_depth_post_fill_hole = QLabel("닫힌 뒤 추가 fill %")
        self.lbl_depth_post_fill_line = QLabel("닫힌 뒤 추가 fill %")
        self.lbl_depth_line_open_path = QLabel("Line open")
        self.lbl_depth_residual_decay = QLabel("Decay len A")
        self.btn_depth_advanced = QPushButton("고급 fill 옵션")
        self.btn_depth_advanced.setCheckable(True)
        self.lbl_inhibition_section = self._make_parameter_section(
            "Inhibition deposition",
            color="#854d0e",
            background="#fffbeb",
            border="#fde68a",
            section_key="inhibition",
        )
        self.lbl_inhibition_strength = QLabel("억제 강도 %")
        self.lbl_inhibition_penetration = QLabel("침투 깊이 A")
        self.lbl_inhibition_decay_power = QLabel("감쇠 Power")
        self.lbl_inhibition_min_growth = QLabel("최소 성장 %")
        self.lbl_inhibition_bottom_boost = QLabel("Bottom boost %")
        self.lbl_inhibition_recombination = QLabel("PEALD recomb %")
        self.lbl_inhibition_smoothing = QLabel("스무딩 A")
        self.lbl_depth_parameter_help = QLabel(
            "Depth depletion: 깊이/등가 AR이 커질수록 deposition 양을 줄입니다. Inhibition은 별도 섹션에서 켭니다."
        )
        self.lbl_depth_parameter_help.setWordWrap(True)
        self.lbl_depth_parameter_help.setStyleSheet(
            "QLabel { color: #334155; background: #f8fafc; border: 1px solid #d9f99d; "
            "border-radius: 4px; padding: 6px; }"
        )
        self.lbl_depth_display_mode = QLabel("표시")
        self.cmb_depth_display_mode = QComboBox()
        self.cmb_depth_display_mode.addItem("Dep rate 기준", "depo_rate")
        self.cmb_depth_display_mode.addItem("감쇄율 기준", "attenuation")
        self.cmb_depth_display_mode.setToolTip(
            "Depth map을 실제 dep rate 감소로 볼지, 100% 대비 감쇄율 증가로 볼지 전환합니다."
        )
        self.lbl_depth_formula = QLabel("")
        self.lbl_depth_formula.setWordWrap(True)
        self.lbl_depth_formula.setStyleSheet(
            "QLabel { color: #14532d; background: #f7fee7; border: 1px solid #bbf7d0; "
            "border-radius: 4px; padding: 5px 6px; font-family: Menlo, Consolas, monospace; }"
        )
        for widget, tooltip in (
            (self.lbl_depth_feature_type, "Hole/Line에 따라 등가 aspect ratio와 closure 후 fill 기준이 달라집니다."),
            (self.cmb_depth_feature_type, "Hole/Line에 따라 등가 aspect ratio와 closure 후 fill 기준이 달라집니다."),
            (self.lbl_depth_feature_width, "입구 폭입니다. 폭이 좁을수록 같은 깊이에서 등가 AR이 커져 증착 비율이 낮아집니다."),
            (self.spin_depth_feature_width, "입구 폭입니다. 폭이 좁을수록 같은 깊이에서 등가 AR이 커져 증착 비율이 낮아집니다."),
            (self.lbl_depth_feature_depth, "현재 구조의 표면-바닥 깊이에 자동으로 맞춰지는 depth map의 100% 기준입니다."),
            (self.spin_depth_feature_depth, "현재 구조의 표면-바닥 깊이에 자동으로 맞춰지는 depth map의 100% 기준입니다."),
            (self.lbl_depth_feature_length, "Line 구조의 길이입니다. 0이면 길게 열린 라인으로 간주합니다."),
            (self.spin_depth_feature_length, "Line 구조의 길이입니다. 0이면 길게 열린 라인으로 간주합니다."),
            (self.lbl_depth_decay_k, "깊이 감쇠 세기입니다. 값이 클수록 바닥 증착 비율이 빠르게 낮아집니다."),
            (self.spin_depth_decay_k, "깊이 감쇠 세기입니다. 값이 클수록 바닥 증착 비율이 빠르게 낮아집니다."),
            (self.lbl_depth_decay_power, "감쇠 곡선 모양입니다. 낮으면 중간 깊이부터 빨리 줄고, 높으면 깊은 쪽에서 급격히 줄어듭니다."),
            (self.spin_depth_decay_power, "감쇠 곡선 모양입니다. 낮으면 중간 깊이부터 빨리 줄고, 높으면 깊은 쪽에서 급격히 줄어듭니다."),
            (self.lbl_depth_min_ratio, "아무리 깊어도 유지되는 최저 증착률입니다."),
            (self.spin_depth_min_ratio_pct, "아무리 깊어도 유지되는 최저 증착률입니다."),
            (self.lbl_depth_closure_threshold, "입구 폭이 이 값 이하로 줄면 closure로 보고 잔류 fill 제한을 적용합니다."),
            (self.spin_depth_closure_threshold, "입구 폭이 이 값 이하로 줄면 closure로 보고 잔류 fill 제한을 적용합니다."),
            (self.lbl_depth_post_fill_hole, "현재 형상이 Hole일 때, closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.spin_depth_post_fill_hole_pct, "현재 형상이 Hole일 때, closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.lbl_depth_post_fill_line, "현재 형상이 Line일 때, closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.spin_depth_post_fill_line_pct, "현재 형상이 Line일 때, closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.lbl_depth_line_open_path, "Line 구조에서 열려 있는 우회 경로를 얼마나 인정할지 정합니다."),
            (self.spin_depth_line_open_path, "Line 구조에서 열려 있는 우회 경로를 얼마나 인정할지 정합니다."),
            (self.lbl_depth_residual_decay, "Closure 후 잔류 fill이 깊이 방향으로 줄어드는 길이 스케일입니다."),
            (self.spin_depth_residual_decay, "Closure 후 잔류 fill이 깊이 방향으로 줄어드는 길이 스케일입니다."),
            (self.lbl_inhibition_strength, "상부/노출부 성장을 얼마나 강하게 억제할지 정합니다."),
            (self.spin_inhibition_strength, "상부/노출부 성장을 얼마나 강하게 억제할지 정합니다."),
            (self.lbl_inhibition_penetration, "inhibition 영향이 trench 내부로 유지되는 깊이 스케일입니다."),
            (self.spin_inhibition_penetration, "inhibition 영향이 trench 내부로 유지되는 깊이 스케일입니다."),
            (self.lbl_inhibition_decay_power, "inhibition coverage가 깊이에 따라 줄어드는 곡선 모양입니다."),
            (self.spin_inhibition_decay_power, "inhibition coverage가 깊이에 따라 줄어드는 곡선 모양입니다."),
            (self.lbl_inhibition_min_growth, "inhibition이 강해도 유지되는 최소 성장률입니다."),
            (self.spin_inhibition_min_growth, "inhibition이 강해도 유지되는 최소 성장률입니다."),
            (self.lbl_inhibition_bottom_boost, "깊은 쪽 성장을 상대적으로 보강하는 항입니다."),
            (self.spin_inhibition_bottom_boost, "깊은 쪽 성장을 상대적으로 보강하는 항입니다."),
            (self.lbl_inhibition_recombination, "PEALD radical recombination loss 가중치입니다."),
            (self.spin_inhibition_recombination, "PEALD radical recombination loss 가중치입니다."),
            (self.lbl_inhibition_smoothing, "inhibition growth ratio field를 arc 방향으로 부드럽게 하는 길이입니다."),
            (self.spin_inhibition_smoothing, "inhibition growth ratio field를 arc 방향으로 부드럽게 하는 길이입니다."),
        ):
            widget.setToolTip(tooltip)
        params_grid.addWidget(self.lbl_depth_feature_section, 37, 0, 1, 2)
        params_grid.addWidget(self.lbl_depth_feature_type, 38, 0)
        params_grid.addWidget(self.cmb_depth_feature_type, 38, 1)
        params_grid.addWidget(self.lbl_depth_feature_width, 39, 0)
        params_grid.addWidget(self.spin_depth_feature_width, 39, 1)
        params_grid.addWidget(self.lbl_depth_feature_depth, 40, 0)
        params_grid.addWidget(self.spin_depth_feature_depth, 40, 1)
        params_grid.addWidget(self.lbl_depth_feature_length, 41, 0)
        params_grid.addWidget(self.spin_depth_feature_length, 41, 1)
        params_grid.addWidget(self.lbl_depth_curve_section, 42, 0, 1, 2)
        params_grid.addWidget(self.lbl_depth_decay_k, 43, 0)
        params_grid.addWidget(self.spin_depth_decay_k, 43, 1)
        params_grid.addWidget(self.lbl_depth_decay_power, 44, 0)
        params_grid.addWidget(self.spin_depth_decay_power, 44, 1)
        params_grid.addWidget(self.lbl_depth_min_ratio, 45, 0)
        params_grid.addWidget(self.spin_depth_min_ratio_pct, 45, 1)
        params_grid.addWidget(self.btn_depth_advanced, 46, 0, 1, 2)
        params_grid.addWidget(self.lbl_depth_closure_section, 47, 0, 1, 2)
        params_grid.addWidget(self.lbl_depth_closure_threshold, 48, 0)
        params_grid.addWidget(self.spin_depth_closure_threshold, 48, 1)
        params_grid.addWidget(self.lbl_depth_post_fill_hole, 49, 0)
        params_grid.addWidget(self.spin_depth_post_fill_hole_pct, 49, 1)
        params_grid.addWidget(self.lbl_depth_post_fill_line, 50, 0)
        params_grid.addWidget(self.spin_depth_post_fill_line_pct, 50, 1)
        params_grid.addWidget(self.lbl_depth_line_open_path, 51, 0)
        params_grid.addWidget(self.spin_depth_line_open_path, 51, 1)
        params_grid.addWidget(self.lbl_depth_residual_decay, 52, 0)
        params_grid.addWidget(self.spin_depth_residual_decay, 52, 1)
        params_grid.addWidget(self.lbl_inhibition_section, 53, 0, 1, 2)
        params_grid.addWidget(self.chk_inhibition_deposition, 54, 0, 1, 2)
        params_grid.addWidget(self.lbl_inhibition_strength, 55, 0)
        params_grid.addWidget(self.spin_inhibition_strength, 55, 1)
        params_grid.addWidget(self.lbl_inhibition_penetration, 56, 0)
        params_grid.addWidget(self.spin_inhibition_penetration, 56, 1)
        params_grid.addWidget(self.lbl_inhibition_decay_power, 57, 0)
        params_grid.addWidget(self.spin_inhibition_decay_power, 57, 1)
        params_grid.addWidget(self.lbl_inhibition_min_growth, 58, 0)
        params_grid.addWidget(self.spin_inhibition_min_growth, 58, 1)
        params_grid.addWidget(self.lbl_inhibition_bottom_boost, 59, 0)
        params_grid.addWidget(self.spin_inhibition_bottom_boost, 59, 1)
        params_grid.addWidget(self.lbl_inhibition_recombination, 60, 0)
        params_grid.addWidget(self.spin_inhibition_recombination, 60, 1)
        params_grid.addWidget(self.lbl_inhibition_smoothing, 61, 0)
        params_grid.addWidget(self.spin_inhibition_smoothing, 61, 1)
        self.lbl_lf_overhang_section = self._make_parameter_section(
            "LF overhang proxy",
            color="#7c3aed",
            background="#f5f3ff",
            border="#ddd6fe",
            section_key="lf",
        )
        params_grid.addWidget(self.lbl_lf_overhang_section, 62, 0, 1, 2)
        params_grid.addWidget(self.chk_lf_overhang, 63, 0, 1, 2)
        self.lbl_lf_overhang_dose = QLabel("LF dose")
        self.lbl_lf_overhang_sputter_gain = QLabel("Sputter gain")
        self.lbl_lf_overhang_redepo_fraction = QLabel("Redepo %")
        self.lbl_lf_overhang_survival = QLabel("Survival loss")
        self.lbl_lf_overhang_width = QLabel("Width A")
        params_grid.addWidget(self.lbl_lf_overhang_dose, 64, 0)
        params_grid.addWidget(self.spin_lf_overhang_dose, 64, 1)
        params_grid.addWidget(self.lbl_lf_overhang_sputter_gain, 65, 0)
        params_grid.addWidget(self.spin_lf_overhang_sputter_gain, 65, 1)
        params_grid.addWidget(self.lbl_lf_overhang_redepo_fraction, 66, 0)
        params_grid.addWidget(self.spin_lf_overhang_redepo_fraction, 66, 1)
        params_grid.addWidget(self.lbl_lf_overhang_survival, 67, 0)
        params_grid.addWidget(self.spin_lf_overhang_survival, 67, 1)
        params_grid.addWidget(self.lbl_lf_overhang_width, 68, 0)
        params_grid.addWidget(self.spin_lf_overhang_width, 68, 1)
        self.lbl_closure_redepo_section = self._make_parameter_section(
            "Etch+Redepo closure",
            color="#b91c1c",
            background="#fff1f2",
            border="#fecdd3",
            section_key="closure",
        )
        params_grid.addWidget(self.lbl_closure_redepo_section, 69, 0, 1, 2)
        params_grid.addWidget(self.chk_closure_redepo, 70, 0, 1, 2)
        self.lbl_closure_redepo_efficiency = QLabel("Closure redepo %")
        self.lbl_closure_redepo_shadow_gain = QLabel("Shadow capture")
        self.lbl_closure_redepo_width = QLabel("Width A")
        self.lbl_closure_redepo_survival = QLabel("Survival loss")
        self.lbl_closure_redepo_smoothing = QLabel("Smooth A")
        params_grid.addWidget(self.lbl_closure_redepo_efficiency, 71, 0)
        params_grid.addWidget(self.spin_closure_redepo_efficiency, 71, 1)
        params_grid.addWidget(self.lbl_closure_redepo_shadow_gain, 72, 0)
        params_grid.addWidget(self.spin_closure_redepo_shadow_gain, 72, 1)
        params_grid.addWidget(self.lbl_closure_redepo_width, 73, 0)
        params_grid.addWidget(self.spin_closure_redepo_width, 73, 1)
        params_grid.addWidget(self.lbl_closure_redepo_survival, 74, 0)
        params_grid.addWidget(self.spin_closure_redepo_survival, 74, 1)
        params_grid.addWidget(self.lbl_closure_redepo_smoothing, 75, 0)
        params_grid.addWidget(self.spin_closure_redepo_smoothing, 75, 1)
        self.params_grid = params_grid
        params_group.setLayout(params_grid)
        self._register_model_parameter_sections()

        self.redepo_lobe_group = QGroupBox("Redeposition Lobe")
        redepo_lobe_layout = QVBoxLayout()
        redepo_lobe_layout.setContentsMargins(8, 8, 8, 8)
        redepo_lobe_layout.addWidget(self.redepo_lobe_editor)
        self.redepo_lobe_group.setLayout(redepo_lobe_layout)

        split_group = QGroupBox("Split Test 파라미터")
        split_grid = QGridLayout()
        split_grid.setContentsMargins(10, 10, 10, 10)
        split_grid.setHorizontalSpacing(8)
        split_grid.setVerticalSpacing(8)
        split_grid.addWidget(QLabel("대상"), 0, 0)
        split_grid.addWidget(self.cmb_split_parameter, 0, 1)
        split_grid.addWidget(QLabel("시작"), 1, 0)
        split_grid.addWidget(self.spin_split_start, 1, 1)
        split_grid.addWidget(QLabel("끝"), 2, 0)
        split_grid.addWidget(self.spin_split_end, 2, 1)
        split_grid.addWidget(QLabel("간격"), 3, 0)
        split_grid.addWidget(self.spin_split_step, 3, 1)
        split_buttons = QHBoxLayout()
        split_buttons.addWidget(self.btn_run_split)
        split_grid.addLayout(split_buttons, 4, 0, 1, 2)
        split_group.setLayout(split_grid)
        split_group.setVisible(False)

        compare_group = QGroupBox("Compare Test 파라미터")
        compare_grid = QGridLayout()
        compare_grid.setContentsMargins(10, 10, 10, 10)
        compare_grid.setHorizontalSpacing(8)
        compare_grid.setVerticalSpacing(8)
        compare_grid.addWidget(QLabel("비교 대상"), 0, 0)
        compare_grid.addWidget(self.cmb_compare_target, 0, 1)
        compare_grid.addWidget(self.btn_run_compare, 1, 0, 1, 2)
        compare_group.setLayout(compare_grid)
        compare_group.setVisible(False)

        action_group = QGroupBox("3 진행 / 실행")
        action_layout = QVBoxLayout()
        action_layout.setContentsMargins(10, 10, 10, 10)
        action_layout.addWidget(self.btn_run)
        action_buttons = QHBoxLayout()
        action_buttons.addWidget(self.btn_open_json)
        action_buttons.addWidget(self.btn_reset)
        action_layout.addLayout(action_buttons)
        action_layout.addWidget(self.progress_run)
        result_option_buttons = QHBoxLayout()
        result_option_buttons.addWidget(self.btn_split_options)
        result_option_buttons.addWidget(self.btn_compare_options)
        action_layout.addLayout(result_option_buttons)
        action_layout.addWidget(split_group)
        action_layout.addWidget(compare_group)
        action_layout.addLayout(run_row)
        action_group.setLayout(action_layout)

        note_group = QGroupBox("요청사항 / 물리 메모")
        note_layout = QVBoxLayout()
        note_layout.setContentsMargins(10, 10, 10, 10)
        note_layout.addWidget(self.edit_request_note)
        note_group.setLayout(note_layout)

        gaussian_group = QGroupBox("Sputter Gaussian")
        gaussian_layout = QVBoxLayout()
        gaussian_layout.setContentsMargins(10, 10, 10, 10)
        gaussian_layout.addWidget(self.sputter_curve_editor)
        gaussian_group.setLayout(gaussian_layout)

        ion_map_group = QGroupBox("Ion Transmission Map")
        ion_map_layout = QVBoxLayout()
        ion_map_layout.setContentsMargins(10, 10, 10, 10)
        ion_map_layout.addWidget(self.ion_transmission_editor)
        ion_map_group.setLayout(ion_map_layout)

        depth_profile_group = QGroupBox("Depth Deposition Map")
        depth_profile_layout = QVBoxLayout()
        depth_profile_layout.setContentsMargins(10, 10, 10, 10)
        depth_profile_layout.setSpacing(8)
        depth_profile_layout.addWidget(self.lbl_depth_parameter_help)
        depth_display_row = QHBoxLayout()
        depth_display_row.setContentsMargins(0, 0, 0, 0)
        depth_display_row.setSpacing(6)
        depth_display_row.addWidget(self.lbl_depth_display_mode)
        depth_display_row.addWidget(self.cmb_depth_display_mode)
        depth_display_row.addStretch(1)
        depth_profile_layout.addLayout(depth_display_row)
        depth_profile_layout.addWidget(self.lbl_depth_formula)
        depth_profile_layout.addWidget(self.depth_deposition_editor)
        depth_profile_group.setLayout(depth_profile_layout)

        inhibition_profile_group = QGroupBox("Inhibition Visual Editor")
        inhibition_profile_layout = QVBoxLayout()
        inhibition_profile_layout.setContentsMargins(10, 10, 10, 10)
        inhibition_profile_layout.addWidget(self.inhibition_profile_editor)
        inhibition_profile_group.setLayout(inhibition_profile_layout)

        self.emulator_group = emulator_group
        self.parameter_preset_group = parameter_preset_group
        self.params_group = params_group
        self.action_group = action_group
        self.split_group = split_group
        self.compare_group = compare_group
        self.note_group = note_group
        self.ion_map_group = ion_map_group
        self.depth_profile_group = depth_profile_group
        self.inhibition_profile_group = inhibition_profile_group
        self.gaussian_group = gaussian_group
        self._sputter_widgets = [
            self.lbl_etch_section,
            self.chk_sputter,
            self.lbl_sputter_section,
            self.lbl_sputter_strength,
            self.spin_sputter_strength,
            self.lbl_sputter_peak_pct,
            self.spin_sputter_peak_pct,
            self.lbl_sputter_peak,
            self.spin_sputter_peak,
            self.lbl_sputter_width,
            self.spin_sputter_width,
            self.lbl_sputter_smoothing,
            self.spin_sputter_smoothing,
        ]
        self._ion_transmission_widgets = [
            self.lbl_ion_depth_section,
            self.chk_ion_transmission,
            self.lbl_ion_start_depth,
            self.spin_ion_start_depth,
            self.lbl_ion_end_depth,
            self.spin_ion_end_depth,
            self.lbl_ion_decay_strength,
            self.spin_ion_decay_strength,
            self.lbl_ion_floor,
            self.spin_ion_floor,
            self.lbl_ion_curve_power,
            self.spin_ion_curve_power,
            self.lbl_ion_geometry_section,
            self.lbl_ion_aperture_shadow,
            self.ion_aperture_shadow_row,
            self.lbl_ion_lateral_shadow,
            self.ion_lateral_shadow_row,
            self.lbl_ion_edge_shadow,
            self.ion_edge_shadow_row,
            self.ion_map_group,
        ]
        self._reflected_ion_widgets = [
            self.lbl_reflected_section,
            self.chk_reflected_ion,
            self.lbl_reflected_strength,
            self.spin_reflected_strength,
            self.lbl_reflected_bowing,
            self.spin_reflected_bowing,
            self.lbl_reflected_microtrench,
            self.spin_reflected_microtrench,
            self.lbl_reflected_range,
            self.spin_reflected_range,
        ]
        self._redeposition_widgets = [
            self.lbl_redepo_section,
            self.chk_redepo,
            self.lbl_redepo_source,
            self.cmb_redepo_source_model,
            self.lbl_redepo_efficiency,
            self.spin_redepo_efficiency,
            self.lbl_redepo_emit_power,
            self.spin_redepo_emit_power,
            self.lbl_redepo_distance_power,
            self.spin_redepo_distance_power,
            self.lbl_redepo_soft_los,
            self.spin_redepo_soft_los,
            self.redepo_lobe_group,
        ]
        self._depth_deposition_widgets = [
            self.lbl_depth_depo_section,
            self.chk_depth_deposition,
            self.lbl_depth_feature_section,
            self.lbl_depth_feature_type,
            self.cmb_depth_feature_type,
            self.lbl_depth_feature_width,
            self.spin_depth_feature_width,
            self.lbl_depth_feature_depth,
            self.spin_depth_feature_depth,
            self.lbl_depth_feature_length,
            self.spin_depth_feature_length,
            self.lbl_depth_curve_section,
            self.lbl_depth_decay_k,
            self.spin_depth_decay_k,
            self.lbl_depth_decay_power,
            self.spin_depth_decay_power,
            self.lbl_depth_min_ratio,
            self.spin_depth_min_ratio_pct,
            self.btn_depth_advanced,
            self.lbl_depth_closure_section,
            self.lbl_depth_closure_threshold,
            self.spin_depth_closure_threshold,
            self.lbl_depth_post_fill_hole,
            self.spin_depth_post_fill_hole_pct,
            self.lbl_depth_post_fill_line,
            self.spin_depth_post_fill_line_pct,
            self.lbl_depth_line_open_path,
            self.spin_depth_line_open_path,
            self.lbl_depth_residual_decay,
            self.spin_depth_residual_decay,
            self.depth_profile_group,
            self.lbl_depth_parameter_help,
            self.lbl_depth_display_mode,
            self.cmb_depth_display_mode,
            self.lbl_depth_formula,
            self.depth_deposition_editor,
        ]
        self._inhibition_widgets = [
            self.lbl_inhibition_section,
            self.chk_inhibition_deposition,
            self.lbl_inhibition_strength,
            self.spin_inhibition_strength,
            self.lbl_inhibition_penetration,
            self.spin_inhibition_penetration,
            self.lbl_inhibition_decay_power,
            self.spin_inhibition_decay_power,
            self.lbl_inhibition_min_growth,
            self.spin_inhibition_min_growth,
            self.lbl_inhibition_bottom_boost,
            self.spin_inhibition_bottom_boost,
            self.lbl_inhibition_recombination,
            self.spin_inhibition_recombination,
            self.lbl_inhibition_smoothing,
            self.spin_inhibition_smoothing,
            self.inhibition_profile_group,
            self.inhibition_profile_editor,
        ]
        self._lf_overhang_widgets = [
            self.lbl_lf_overhang_section,
            self.chk_lf_overhang,
            self.lbl_lf_overhang_dose,
            self.spin_lf_overhang_dose,
            self.lbl_lf_overhang_sputter_gain,
            self.spin_lf_overhang_sputter_gain,
            self.lbl_lf_overhang_redepo_fraction,
            self.spin_lf_overhang_redepo_fraction,
            self.lbl_lf_overhang_survival,
            self.spin_lf_overhang_survival,
            self.lbl_lf_overhang_width,
            self.spin_lf_overhang_width,
        ]
        self._closure_redepo_widgets = [
            self.lbl_closure_redepo_section,
            self.chk_closure_redepo,
            self.lbl_closure_redepo_efficiency,
            self.spin_closure_redepo_efficiency,
            self.lbl_closure_redepo_shadow_gain,
            self.spin_closure_redepo_shadow_gain,
            self.lbl_closure_redepo_width,
            self.spin_closure_redepo_width,
            self.lbl_closure_redepo_survival,
            self.spin_closure_redepo_survival,
            self.lbl_closure_redepo_smoothing,
            self.spin_closure_redepo_smoothing,
        ]

        self.btn_structure_panel_next = QPushButton("다음: 스무딩")
        self.btn_smoothing_panel_back = QPushButton("이전: 구조")
        self.btn_smoothing_panel_next = QPushButton("다음: 진행")
        self.btn_progress_panel_back = QPushButton("이전: 스무딩")
        self.btn_progress_panel_next = QPushButton("다음: 결과")
        self.btn_results_panel_back = QPushButton("이전: 진행")

        self.structure_panel_content = QWidget()
        structure_panel_layout = QVBoxLayout()
        structure_panel_layout.setContentsMargins(0, 0, 0, 0)
        structure_panel_layout.setSpacing(8)
        structure_panel_layout.addWidget(self.structure_library_group)
        structure_panel_layout.addWidget(self.structure_points_group)
        structure_panel_layout.addWidget(self.overlay_group)
        structure_panel_nav = QHBoxLayout()
        structure_panel_nav.setContentsMargins(0, 0, 0, 0)
        structure_panel_nav.addStretch(1)
        structure_panel_nav.addWidget(self.btn_structure_panel_next)
        structure_panel_layout.addLayout(structure_panel_nav)
        structure_panel_layout.addStretch(1)
        self.structure_panel_content.setLayout(structure_panel_layout)

        self.smoothing_panel_content = QWidget()
        smoothing_panel_layout = QVBoxLayout()
        smoothing_panel_layout.setContentsMargins(0, 0, 0, 0)
        smoothing_panel_layout.setSpacing(8)
        smoothing_panel_layout.addWidget(self.smoothing_controls_group)
        smoothing_panel_layout.addWidget(self.smoothed_points_group)
        smoothing_panel_nav = QHBoxLayout()
        smoothing_panel_nav.setContentsMargins(0, 0, 0, 0)
        smoothing_panel_nav.addWidget(self.btn_smoothing_panel_back)
        smoothing_panel_nav.addStretch(1)
        smoothing_panel_nav.addWidget(self.btn_smoothing_panel_next)
        smoothing_panel_layout.addLayout(smoothing_panel_nav)
        smoothing_panel_layout.addStretch(1)
        self.smoothing_panel_content.setLayout(smoothing_panel_layout)

        self.progress_panel_content = QWidget()
        progress_panel_layout = QVBoxLayout()
        progress_panel_layout.setContentsMargins(0, 0, 0, 0)
        progress_panel_layout.setSpacing(8)
        progress_panel_layout.addWidget(emulator_group)
        progress_panel_layout.addWidget(parameter_preset_group)
        progress_panel_layout.addWidget(action_group)
        progress_panel_layout.addWidget(params_group)
        progress_panel_layout.addWidget(gaussian_group)
        progress_panel_layout.addWidget(ion_map_group)
        progress_panel_layout.addWidget(self.redepo_lobe_group)
        progress_panel_layout.addWidget(depth_profile_group)
        progress_panel_layout.addWidget(self.inhibition_profile_group)
        progress_panel_layout.addWidget(note_group)
        progress_panel_nav = QHBoxLayout()
        progress_panel_nav.setContentsMargins(0, 0, 0, 0)
        progress_panel_nav.addWidget(self.btn_progress_panel_back)
        progress_panel_nav.addStretch(1)
        progress_panel_nav.addWidget(self.btn_progress_panel_next)
        progress_panel_layout.addLayout(progress_panel_nav)
        progress_panel_layout.addStretch(1)
        self.progress_panel_content.setLayout(progress_panel_layout)

        self.result_panel_content = QWidget()
        result_panel_layout = QVBoxLayout()
        result_panel_layout.setContentsMargins(0, 0, 0, 0)
        result_panel_layout.setSpacing(8)
        self.result_summary_group = QGroupBox("4 결과 / 보기")
        result_summary_layout = QVBoxLayout()
        result_summary_layout.setContentsMargins(10, 10, 10, 10)
        self.lbl_result_summary = QLabel("결과: 아직 실행 전")
        self.lbl_result_summary.setWordWrap(True)
        self.lbl_result_hint = QLabel("왼쪽 결과 화면에서 프레임 슬라이더로 cycle별 profile을 확인합니다.")
        self.lbl_result_hint.setWordWrap(True)
        self.edit_result_parameters = QPlainTextEdit()
        self.edit_result_parameters.setReadOnly(True)
        self.edit_result_parameters.setMinimumHeight(300)
        self.edit_result_parameters.setPlainText("아직 실행된 결과가 없습니다.")
        result_summary_layout.addWidget(self.lbl_result_summary)
        result_summary_layout.addWidget(self.lbl_result_hint)
        result_summary_layout.addWidget(self.edit_result_parameters, 1)
        result_save_row = QHBoxLayout()
        result_save_row.setContentsMargins(0, 0, 0, 0)
        result_save_row.addWidget(self.btn_save_result_json)
        result_save_row.addStretch(1)
        result_summary_layout.addLayout(result_save_row)
        self.result_summary_group.setLayout(result_summary_layout)
        result_panel_layout.addWidget(self.result_summary_group)
        result_panel_nav = QHBoxLayout()
        result_panel_nav.setContentsMargins(0, 0, 0, 0)
        result_panel_nav.addWidget(self.btn_results_panel_back)
        result_panel_nav.addStretch(1)
        result_panel_layout.addLayout(result_panel_nav)
        result_panel_layout.addStretch(1)
        self.result_panel_content.setLayout(result_panel_layout)

        def make_workflow_scroll(content: QWidget) -> QScrollArea:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            return scroll

        self.structure_scroll_area = make_workflow_scroll(self.structure_panel_content)
        self.smoothing_scroll_area = make_workflow_scroll(self.smoothing_panel_content)
        self.progress_scroll_area = make_workflow_scroll(self.progress_panel_content)
        self.result_scroll_area = make_workflow_scroll(self.result_panel_content)
        self.results_panel_content = self.result_panel_content
        self.results_scroll_area = self.result_scroll_area
        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.addTab(self.structure_scroll_area, "1 구조")
        self.workflow_tabs.addTab(self.smoothing_scroll_area, "2 스무딩")
        self.workflow_tabs.addTab(self.progress_scroll_area, "3 진행")
        self.workflow_tabs.addTab(self.result_scroll_area, "4 결과")

        right_panel = QWidget()
        right_panel.setMinimumWidth(440)
        right_panel.setMaximumWidth(560)
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(6, 8, 8, 8)
        right_layout.setSpacing(8)
        right_layout.addWidget(self.workflow_tabs, 1)
        right_panel.setLayout(right_layout)
        self.right_panel = right_panel

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([820, 460])
        splitter.setChildrenCollapsible(False)
        self.main_splitter = splitter

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter, 1)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._install_value_control_wheel_guards()

        self.btn_run.clicked.connect(self.run_emulation)
        self.btn_reset.clicked.connect(self.reset_defaults)
        self.btn_open_json.clicked.connect(self.open_replay_json_dialog)
        self.btn_open_run_dir.clicked.connect(self.open_last_run_dir)
        self.btn_save_result_json.clicked.connect(self.save_current_result_json)
        self.btn_run_split.clicked.connect(self.run_split_test)
        self.btn_run_compare.clicked.connect(self.run_compare_for_active_emulator)
        self.btn_split_options.toggled.connect(self._on_split_options_toggled)
        self.btn_compare_options.toggled.connect(self._on_compare_options_toggled)
        self.view_tabs.currentChanged.connect(self._on_view_workflow_tab_changed)
        self.workflow_tabs.currentChanged.connect(self._on_control_workflow_tab_changed)
        self.btn_structure_panel_next.clicked.connect(lambda: self._set_workflow_step("smoothing"))
        self.btn_smoothing_panel_back.clicked.connect(lambda: self._set_workflow_step("structure"))
        self.btn_smoothing_panel_next.clicked.connect(lambda: self._set_workflow_step("progress"))
        self.btn_progress_panel_back.clicked.connect(lambda: self._set_workflow_step("smoothing"))
        self.btn_progress_panel_next.clicked.connect(lambda: self._set_workflow_step("results"))
        self.btn_results_panel_back.clicked.connect(lambda: self._set_workflow_step("progress"))
        self.btn_result_play.clicked.connect(self.toggle_result_playback)
        self.btn_next_depo.clicked.connect(self.start_next_depo_stage)
        self.cmb_quality_mode.currentIndexChanged.connect(self._on_quality_mode_changed)
        self.spin_reparam_ds.valueChanged.connect(self._on_reparam_ds_changed)
        self.btn_load_overlay.clicked.connect(self._load_overlay_image)
        self.btn_clear_overlay.clicked.connect(self._clear_overlay_image)
        self.btn_move_overlay.toggled.connect(self._on_overlay_move_toggled)
        self.slider_overlay_opacity.valueChanged.connect(self._on_overlay_opacity_changed)
        self.structure_points_model.pointEditRequested.connect(self._on_structure_table_point_edit_requested)
        self.structure_points_table.deleteRowsRequested.connect(self._on_structure_table_delete_rows_requested)
        self.structure_points_table.replacePointsRequested.connect(self._on_structure_table_replace_points_requested)
        self.cmb_split_parameter.currentIndexChanged.connect(self.apply_split_parameter_defaults)
        self.slider_frame.valueChanged.connect(self.show_frame)
        self.chk_show_etch_overlay.toggled.connect(self.view.set_etch_overlay_visible)
        self.chk_show_redepo_overlay.toggled.connect(self.view.set_redepo_overlay_visible)
        self.chk_sputter.toggled.connect(self.sync_etch_control_availability)
        self.chk_ion_transmission.toggled.connect(self.sync_etch_control_availability)
        self.chk_reflected_ion.toggled.connect(self.sync_etch_control_availability)
        self.chk_redepo.toggled.connect(self.sync_etch_control_availability)
        self.chk_depth_deposition.toggled.connect(self.sync_etch_control_availability)
        self.chk_inhibition_deposition.toggled.connect(self.sync_etch_control_availability)
        self.chk_lf_overhang.toggled.connect(self.sync_etch_control_availability)
        self.chk_closure_redepo.toggled.connect(self.sync_etch_control_availability)
        self.spin_sputter_strength.valueChanged.connect(self.sync_sputter_curve_cap_from_spin)
        self.spin_sputter_peak_pct.valueChanged.connect(self.sync_sputter_curve_from_spins)
        self.spin_sputter_peak.valueChanged.connect(self.sync_sputter_curve_from_spins)
        self.spin_sputter_width.valueChanged.connect(self.sync_sputter_curve_from_spins)
        self.sputter_curve_editor.parametersChanged.connect(self.apply_sputter_curve_parameters)
        self.spin_angstrom_per_cycle.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_ion_start_depth.valueChanged.connect(self.sync_ion_transmission_editor_from_spins)
        self.spin_ion_decay_strength.valueChanged.connect(self.sync_ion_transmission_editor_from_spins)
        self.spin_ion_floor.valueChanged.connect(self.sync_ion_transmission_editor_from_spins)
        self.spin_ion_curve_power.valueChanged.connect(self.sync_ion_transmission_editor_from_spins)
        self.ion_transmission_editor.parametersChanged.connect(self.apply_ion_transmission_editor_parameters)
        self.spin_redepo_efficiency.valueChanged.connect(self.sync_redepo_lobe_from_spins)
        self.spin_redepo_emit_power.valueChanged.connect(self.sync_redepo_lobe_from_spins)
        self.spin_redepo_distance_power.valueChanged.connect(self.sync_redepo_lobe_from_spins)
        self.redepo_lobe_editor.parametersChanged.connect(self.apply_redepo_lobe_parameters)
        self.cmb_depth_feature_type.currentIndexChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.cmb_depth_feature_type.currentIndexChanged.connect(self.sync_etch_control_availability)
        self.spin_depth_feature_width.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_feature_depth.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_feature_length.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_decay_k.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_decay_power.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_min_ratio_pct.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_closure_threshold.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.cmb_depth_display_mode.currentIndexChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.depth_deposition_editor.parametersChanged.connect(self.apply_depth_deposition_editor_parameters)
        self.spin_depth_feature_depth.valueChanged.connect(self.sync_inhibition_profile_from_spins)
        self.spin_inhibition_strength.valueChanged.connect(self.sync_inhibition_profile_from_spins)
        self.spin_inhibition_penetration.valueChanged.connect(self.sync_inhibition_profile_from_spins)
        self.spin_inhibition_decay_power.valueChanged.connect(self.sync_inhibition_profile_from_spins)
        self.spin_inhibition_min_growth.valueChanged.connect(self.sync_inhibition_profile_from_spins)
        self.spin_inhibition_bottom_boost.valueChanged.connect(self.sync_inhibition_profile_from_spins)
        self.spin_inhibition_recombination.valueChanged.connect(self.sync_inhibition_profile_from_spins)
        self.inhibition_profile_editor.parametersChanged.connect(self.apply_inhibition_profile_parameters)
        self.slider_ion_aperture_shadow.valueChanged.connect(self.sync_ion_shadow_slider_labels)
        self.slider_ion_lateral_shadow.valueChanged.connect(self.sync_ion_shadow_slider_labels)
        self.slider_ion_edge_shadow.valueChanged.connect(self.sync_ion_shadow_slider_labels)
        self.structure_view.pointMoved.connect(self._on_structure_point_moved)
        self.structure_view.pointInserted.connect(self._on_structure_point_inserted)
        self.structure_view.pointDeleted.connect(self._on_structure_point_deleted)
        self.smoothing_view.pointMoved.connect(self._on_smoothed_point_moved)
        self.smoothing_view.pointInserted.connect(self._on_smoothed_point_inserted)
        self.smoothing_view.pointDeleted.connect(self._on_smoothed_point_deleted)
        self.btn_reload_structure_library.clicked.connect(self.refresh_structure_library)
        self.cmb_structure_library.currentIndexChanged.connect(self.load_selected_structure_from_library)
        self.btn_save_structure.clicked.connect(self.save_current_structure_to_library)
        self.btn_delete_structure.clicked.connect(self.delete_selected_structure_from_library)
        self.btn_export_default_structures.clicked.connect(self.export_default_structures_to_library)
        self.btn_open_structure_workbook.clicked.connect(self.open_structure_library_workbook)
        self.btn_reload_parameter_presets.clicked.connect(self.refresh_parameter_presets)
        self.cmb_parameter_preset.currentIndexChanged.connect(self._on_parameter_preset_selected)
        self.btn_apply_parameter_preset.clicked.connect(self.apply_selected_parameter_preset)
        self.btn_save_parameter_preset.clicked.connect(self.save_current_parameter_preset)
        self.btn_delete_parameter_preset.clicked.connect(self.delete_selected_parameter_preset)
        self.cmb_emulator_default_preset.currentIndexChanged.connect(self.apply_selected_emulator_preset)
        self.btn_depth_advanced.toggled.connect(self._sync_depth_advanced_visibility)
        self.btn_fit_structure.clicked.connect(self._fit_structure_views)
        self.btn_reset_structure.clicked.connect(self._reset_geometry_to_default)
        self.btn_apply_smoothing.clicked.connect(self.apply_structure_smoothing)
        self.btn_use_smoothed_geometry.clicked.connect(self.use_smoothed_geometry)
        self.btn_use_raw_geometry.clicked.connect(self.use_raw_geometry)
        self.sync_ion_shadow_slider_labels()
        self.spin_ion_end_depth.valueChanged.connect(self.sync_ion_transmission_editor_from_spins)

        self.refresh_structure_library(show_status=False)
        self.refresh_parameter_presets(show_status=False)
        self.apply_emulator_mode(run=False)
        self._reset_geometry_to_default()
        self.sync_depth_deposition_editor_from_spins()
        self.sync_inhibition_profile_from_spins()
        self._sync_field_overlay_toggles()
        self._set_workflow_step("structure")

    def _install_value_control_wheel_guards(self) -> None:
        for widget in [
            *self.findChildren(QSpinBox),
            *self.findChildren(QDoubleSpinBox),
            *self.findChildren(QSlider),
        ]:
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802, ANN001
        if isinstance(watched, (QSpinBox, QDoubleSpinBox, QSlider)) and event.type() == QEvent.Type.Wheel:
            focus_widget = QApplication.focusWidget()
            value_control_has_focus = focus_widget is watched or (
                focus_widget is not None and watched.isAncestorOf(focus_widget)
            )
            if not value_control_has_focus:
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def _quality_mode_index_for_ds(self, ds_a: float) -> int:
        for idx in range(self.cmb_quality_mode.count()):
            data = self.cmb_quality_mode.itemData(idx)
            if data is None:
                continue
            try:
                if abs(float(data) - float(ds_a)) <= 1e-6:
                    return idx
            except (TypeError, ValueError):
                continue
        custom_idx = self.cmb_quality_mode.findText("사용자")
        return custom_idx if custom_idx >= 0 else max(0, self.cmb_quality_mode.count() - 1)

    def _set_quality_mode_for_ds(self, ds_a: float) -> None:
        self._syncing_quality_mode = True
        try:
            self.spin_reparam_ds.setValue(float(ds_a))
            self.cmb_quality_mode.setCurrentIndex(self._quality_mode_index_for_ds(float(ds_a)))
        finally:
            self._syncing_quality_mode = False

    def _on_quality_mode_changed(self, _index: int = 0) -> None:
        if self._syncing_quality_mode:
            return
        data = self.cmb_quality_mode.currentData()
        if data is not None:
            self._syncing_quality_mode = True
            try:
                self.spin_reparam_ds.setValue(float(data))
            finally:
                self._syncing_quality_mode = False
        self._invalidate_result_for_input_change()

    def _on_reparam_ds_changed(self, value: float) -> None:
        if self._syncing_quality_mode:
            return
        self._syncing_quality_mode = True
        try:
            self.cmb_quality_mode.setCurrentIndex(self._quality_mode_index_for_ds(float(value)))
        finally:
            self._syncing_quality_mode = False
        self._invalidate_result_for_input_change()

    def _structure_library_sheet_for_emulator(self, number: int) -> str:
        return DEFAULT_EMULATOR_STRUCTURE_SHEETS.get(int(number), "")

    def _fallback_points_for_emulator(self, number: int) -> List[Tuple[float, float]]:
        if int(number) == 2:
            return [(float(x), float(y)) for x, y in ION_TRANSMISSION_STEPPED_TRENCH_POINTS]
        if int(number) in (5, 6, 10):
            return [(float(x), float(y)) for x, y in BOWED_JAR_TRENCH_POINTS]
        return [(float(x), float(y)) for x, y in TrenchDepoConfig().points]

    def _default_points_for_active_emulator(self) -> List[Tuple[float, float]]:
        number = self.active_emulator_number()
        sheet_name = self._structure_library_sheet_for_emulator(number)
        if sheet_name:
            try:
                return read_structure_points(self._structure_library_path, sheet_name)
            except StructureLibraryError:
                pass
        return self._fallback_points_for_emulator(number)

    def refresh_structure_library(self, _checked: bool = False, *, show_status: bool = True) -> None:
        try:
            names = list_structure_names(self._structure_library_path)
        except Exception as exc:  # noqa: BLE001
            names = []
            if show_status:
                QMessageBox.warning(self, "구조 라이브러리", f"구조 워크북 읽기 실패:\n{exc}")

        previous = self._selected_structure_sheet_name()
        self.cmb_structure_library.blockSignals(True)
        try:
            self.cmb_structure_library.clear()
            for label, sheet_name in _structure_preset_items(names):
                self.cmb_structure_library.addItem(label, sheet_name)
            idx = self.cmb_structure_library.findData(previous)
            if idx >= 0:
                self.cmb_structure_library.setCurrentIndex(idx)
        finally:
            self.cmb_structure_library.blockSignals(False)

        has_workbook = self._structure_library_path.exists()
        has_structures = bool(names)
        self.cmb_structure_library.setEnabled(has_structures)
        self.btn_delete_structure.setEnabled(has_structures)
        self.btn_open_structure_workbook.setEnabled(True)
        self.lbl_structure_library_path.setText(f"워크북: {self._structure_library_path}")
        self._update_structure_library_active_label()
        if show_status:
            if has_workbook:
                self.statusBar().showMessage(f"구조 워크북 로드됨: {len(names)}개 프리셋", 2200)
            else:
                self.statusBar().showMessage("구조 워크북이 아직 없습니다", 2200)

    def _update_structure_library_active_label(self) -> None:
        active = (
            _structure_preset_display_name(self._active_structure_sheet_name)
            if self._active_structure_sheet_name
            else "에뮬레이터 기본값"
        )
        self.lbl_structure_library_active.setText(f"활성: {active}")
        if self._active_structure_sheet_name and not self.edit_structure_name.text().strip():
            self.edit_structure_name.setText(_structure_preset_display_name(self._active_structure_sheet_name))

    def _selected_structure_sheet_name(self) -> str:
        data = self.cmb_structure_library.currentData()
        if data is not None:
            return str(data).strip()
        return self.cmb_structure_library.currentText().strip()

    def load_selected_structure_from_library(self, _checked: bool = False) -> None:
        sheet_name = self._selected_structure_sheet_name()
        if not sheet_name:
            QMessageBox.information(self, "구조 라이브러리", "선택된 구조 프리셋이 없습니다.")
            return
        try:
            points = read_structure_points(self._structure_library_path, sheet_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "구조 라이브러리", f"구조 '{sheet_name}' 불러오기 실패:\n{exc}")
            return
        self._clear_continuation_context()
        self._active_structure_sheet_name = sheet_name
        self.edit_structure_name.setText(_structure_preset_display_name(sheet_name))
        self._set_structure_points(points, fit=True, preserve_on_emulator_switch=True)
        self._update_structure_library_active_label()
        self.statusBar().showMessage(f"구조 프리셋 적용: {_structure_preset_display_name(sheet_name)}", 2200)

    def save_current_structure_to_library(self, _checked: bool = False) -> None:
        points = list(self._structure_points or self._current_geometry_points())
        if len(points) < 2:
            QMessageBox.warning(self, "구조 라이브러리", "XY 좌표가 최소 2개 필요합니다.")
            return
        sheet_name = sanitize_structure_name(
            self.edit_structure_name.text().strip()
            or self._selected_structure_sheet_name()
            or self._active_structure_sheet_name
            or f"structure_{self.active_emulator_number():02d}"
        )
        try:
            saved_name = save_structure_points(self._structure_library_path, sheet_name, points)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "구조 라이브러리", f"구조 저장 실패:\n{exc}")
            return
        self._active_structure_sheet_name = saved_name
        self.edit_structure_name.setText(saved_name)
        self.refresh_structure_library(show_status=False)
        idx = self.cmb_structure_library.findData(saved_name)
        if idx >= 0:
            self.cmb_structure_library.setCurrentIndex(idx)
        self._update_structure_library_active_label()
        self.statusBar().showMessage(f"구조 저장됨: {saved_name}", 2200)

    def delete_selected_structure_from_library(self, _checked: bool = False) -> None:
        sheet_name = self._selected_structure_sheet_name()
        if not sheet_name:
            QMessageBox.information(self, "구조 라이브러리", "삭제할 구조 프리셋이 없습니다.")
            return
        display_name = _structure_preset_display_name(sheet_name)
        answer = QMessageBox.question(
            self,
            "구조 프리셋 삭제",
            f"'{display_name}' 구조 프리셋을 삭제할까요?\n현재 화면의 구조 좌표는 유지됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted_name = delete_structure_sheet(self._structure_library_path, sheet_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "구조 라이브러리", f"구조 삭제 실패:\n{exc}")
            return
        if self._active_structure_sheet_name == deleted_name:
            self._active_structure_sheet_name = ""
        self.refresh_structure_library(show_status=False)
        self._update_structure_library_active_label()
        self.statusBar().showMessage(f"구조 프리셋 삭제됨: {deleted_name}", 2200)

    def export_default_structures_to_library(self, _checked: bool = False) -> None:
        try:
            written = ensure_default_structures(self._structure_library_path, overwrite=False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "구조 라이브러리", f"기본 구조 내보내기 실패:\n{exc}")
            return
        self.refresh_structure_library(show_status=False)
        if written:
            self.statusBar().showMessage(f"기본 구조 {len(written)}개 프리셋 내보냄", 2600)
        else:
            self.statusBar().showMessage("기본 구조 프리셋이 이미 있습니다", 2200)

    def open_structure_library_workbook(self, _checked: bool = False) -> None:
        if not self._structure_library_path.exists():
            self.export_default_structures_to_library()
        if self._structure_library_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._structure_library_path.resolve())))

    def refresh_parameter_presets(self, _checked: bool = False, *, show_status: bool = True) -> None:
        try:
            names = list_parameter_presets(self._parameter_library_path)
        except Exception as exc:  # noqa: BLE001
            names = []
            if show_status:
                QMessageBox.warning(self, "공정 파라미터 프리셋", f"파라미터 프리셋 읽기 실패:\n{exc}")

        previous = self._selected_parameter_preset_name()
        self.cmb_parameter_preset.blockSignals(True)
        try:
            self.cmb_parameter_preset.clear()
            for name in names:
                self.cmb_parameter_preset.addItem(name, name)
            idx = self.cmb_parameter_preset.findData(previous)
            if idx >= 0:
                self.cmb_parameter_preset.setCurrentIndex(idx)
        finally:
            self.cmb_parameter_preset.blockSignals(False)

        has_presets = bool(names)
        self.cmb_parameter_preset.setEnabled(has_presets)
        self.btn_apply_parameter_preset.setEnabled(has_presets)
        self.btn_delete_parameter_preset.setEnabled(has_presets)
        self.lbl_parameter_preset_path.setText(f"파일: {self._parameter_library_path}")
        self._on_parameter_preset_selected()
        self._update_parameter_preset_active_label()
        if show_status:
            self.statusBar().showMessage(f"공정 파라미터 프리셋 {len(names)}개 로드됨", 2200)

    def _selected_parameter_preset_name(self) -> str:
        data = self.cmb_parameter_preset.currentData()
        if data is not None:
            return str(data).strip()
        return self.cmb_parameter_preset.currentText().strip()

    def _on_parameter_preset_selected(self, _index: int = 0) -> None:
        name = self._selected_parameter_preset_name()
        if name:
            self.edit_parameter_preset_name.setText(name)

    def _update_parameter_preset_active_label(self) -> None:
        active = self._active_parameter_preset_name or "없음"
        self.lbl_parameter_preset_active.setText(f"활성: {active}")

    def save_current_parameter_preset(self, _checked: bool = False) -> None:
        name = sanitize_parameter_preset_name(
            self.edit_parameter_preset_name.text().strip()
            or self._selected_parameter_preset_name()
            or f"em{self.active_emulator_number():02d}_process"
        )
        try:
            saved_name = save_parameter_preset(
                self._parameter_library_path,
                name,
                self.current_config(),
                emulator_number=self.active_emulator_number(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "공정 파라미터 프리셋", f"파라미터 저장 실패:\n{exc}")
            return
        self._active_parameter_preset_name = saved_name
        self.edit_parameter_preset_name.setText(saved_name)
        self.refresh_parameter_presets(show_status=False)
        idx = self.cmb_parameter_preset.findData(saved_name)
        if idx >= 0:
            self.cmb_parameter_preset.setCurrentIndex(idx)
        self._update_parameter_preset_active_label()
        self.statusBar().showMessage(f"공정 파라미터 저장됨: {saved_name}", 2200)

    def _set_combo_data(self, combo: QComboBox, value: object) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _apply_parameter_config_values(self, values: Mapping[str, object]) -> None:
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion = self._active_emulator_supports_ion_transmission()
        supports_reflected = self._active_emulator_supports_reflected_ion()
        supports_redepo = self._active_emulator_supports_redeposition()
        supports_depth = self._active_emulator_supports_depth_deposition()
        supports_inhibition = self._active_emulator_supports_inhibition()
        supports_lf = self._active_emulator_supports_lf_overhang()
        supports_closure = self._active_emulator_supports_closure_redepo()

        def f(key: str, default: float) -> float:
            raw = values.get(key, default)
            return float(default if raw is None else raw)

        def i(key: str, default: int) -> int:
            raw = values.get(key, default)
            return int(default if raw is None else raw)

        def b(key: str, default: bool) -> bool:
            raw = values.get(key, default)
            return bool(default if raw is None else raw)

        self.spin_cycles.setValue(i("cycles", int(self.spin_cycles.value())))
        self.spin_angstrom_per_cycle.setValue(f("angstrom_per_cycle", float(self.spin_angstrom_per_cycle.value())))
        self._set_quality_mode_for_ds(f("reparam_ds_a", float(self.spin_reparam_ds.value())))
        self.chk_sputter.setChecked(bool(supports_sputter and b("sputter_enabled", self.chk_sputter.isChecked())))
        self.chk_ion_transmission.setChecked(
            bool(supports_ion and b("ion_transmission_enabled", self.chk_ion_transmission.isChecked()))
        )
        self.chk_reflected_ion.setChecked(
            bool(supports_reflected and b("reflected_ion_enabled", self.chk_reflected_ion.isChecked()))
        )
        self.chk_redepo.setChecked(bool(supports_redepo and b("redepo_enabled", self.chk_redepo.isChecked())))
        self.chk_depth_deposition.setChecked(
            bool(supports_depth and b("deposition_depth_enabled", self.chk_depth_deposition.isChecked()))
        )
        self.chk_inhibition_deposition.setChecked(
            bool(supports_inhibition and b("inhibition_enabled", self.chk_inhibition_deposition.isChecked()))
        )
        self.chk_lf_overhang.setChecked(
            bool(supports_lf and b("lf_overhang_enabled", self.chk_lf_overhang.isChecked()))
        )
        self.chk_closure_redepo.setChecked(
            bool(supports_closure and b("closure_redepo_enabled", self.chk_closure_redepo.isChecked()))
        )

        self.spin_sputter_strength.setValue(f("sputter_strength_a_per_cycle", self.spin_sputter_strength.value()))
        self.spin_sputter_peak_pct.setValue(f("sputter_peak_pct", self.spin_sputter_peak_pct.value()))
        self.spin_sputter_peak.setValue(f("sputter_peak_angle_deg", self.spin_sputter_peak.value()))
        self.spin_sputter_width.setValue(f("sputter_width_deg", self.spin_sputter_width.value()))
        self.spin_sputter_smoothing.setValue(f("sputter_smoothing_a", self.spin_sputter_smoothing.value()))
        self.spin_ion_start_depth.setValue(f("ion_transmission_start_depth_pct", self.spin_ion_start_depth.value()))
        self.spin_ion_end_depth.setValue(f("ion_transmission_end_depth_pct", self.spin_ion_end_depth.value()))
        self.spin_ion_decay_strength.setValue(
            f("ion_transmission_decay_strength_pct", self.spin_ion_decay_strength.value())
        )
        self.spin_ion_floor.setValue(f("ion_transmission_floor_pct", self.spin_ion_floor.value()))
        self.spin_ion_curve_power.setValue(f("ion_transmission_curve_power", self.spin_ion_curve_power.value()))
        self.slider_ion_aperture_shadow.setValue(i("ion_transmission_aperture_shadow_pct", self.slider_ion_aperture_shadow.value()))
        self.slider_ion_lateral_shadow.setValue(i("ion_transmission_lateral_shadow_pct", self.slider_ion_lateral_shadow.value()))
        self.slider_ion_edge_shadow.setValue(i("ion_transmission_edge_shadow_pct", self.slider_ion_edge_shadow.value()))
        self.spin_reflected_strength.setValue(f("reflected_ion_strength_pct", self.spin_reflected_strength.value()))
        self.spin_reflected_bowing.setValue(f("reflected_ion_bowing_weight", self.spin_reflected_bowing.value()))
        self.spin_reflected_microtrench.setValue(
            f("reflected_ion_microtrench_weight", self.spin_reflected_microtrench.value())
        )
        self.spin_reflected_range.setValue(f("reflected_ion_range_a", self.spin_reflected_range.value()))
        self._set_combo_data(self.cmb_redepo_source_model, str(values.get("redepo_source_model", "model2")))
        self.spin_redepo_efficiency.setValue(f("redepo_efficiency_pct", self.spin_redepo_efficiency.value()))
        self.spin_redepo_emit_power.setValue(f("redepo_emit_power", self.spin_redepo_emit_power.value()))
        self.spin_redepo_distance_power.setValue(f("redepo_distance_power", self.spin_redepo_distance_power.value()))
        self.spin_redepo_soft_los.setValue(i("redepo_soft_los_radius_points", self.spin_redepo_soft_los.value()))
        self.spin_lf_overhang_dose.setValue(f("lf_overhang_dose", self.spin_lf_overhang_dose.value()))
        self.spin_lf_overhang_sputter_gain.setValue(
            f("lf_overhang_sputter_gain", self.spin_lf_overhang_sputter_gain.value())
        )
        self.spin_lf_overhang_redepo_fraction.setValue(
            f("lf_overhang_redepo_fraction_pct", self.spin_lf_overhang_redepo_fraction.value())
        )
        self.spin_lf_overhang_survival.setValue(
            f("lf_overhang_survival_penalty", self.spin_lf_overhang_survival.value())
        )
        self.spin_lf_overhang_width.setValue(f("lf_overhang_width_a", self.spin_lf_overhang_width.value()))
        self.spin_closure_redepo_efficiency.setValue(
            f("closure_redepo_efficiency_pct", self.spin_closure_redepo_efficiency.value())
        )
        self.spin_closure_redepo_shadow_gain.setValue(
            f("closure_redepo_shadow_gain", self.spin_closure_redepo_shadow_gain.value())
        )
        self.spin_closure_redepo_width.setValue(
            f("closure_redepo_width_a", self.spin_closure_redepo_width.value())
        )
        self.spin_closure_redepo_survival.setValue(
            f("closure_redepo_survival_penalty", self.spin_closure_redepo_survival.value())
        )
        self.spin_closure_redepo_smoothing.setValue(
            f("closure_redepo_smoothing_a", self.spin_closure_redepo_smoothing.value())
        )
        self._set_combo_data(self.cmb_depth_feature_type, str(values.get("deposition_feature_type", "hole")))
        self.spin_depth_feature_width.setValue(f("deposition_feature_width_a", self.spin_depth_feature_width.value()))
        self.spin_depth_feature_depth.setValue(f("deposition_feature_depth_a", self.spin_depth_feature_depth.value()))
        feature_length = values.get("deposition_feature_length_a", None)
        self.spin_depth_feature_length.setValue(0.0 if feature_length is None else float(feature_length))
        self.spin_depth_decay_k.setValue(f("deposition_depth_decay_k", self.spin_depth_decay_k.value()))
        self.spin_depth_decay_power.setValue(f("deposition_depth_decay_power", self.spin_depth_decay_power.value()))
        self.spin_depth_min_ratio_pct.setValue(f("deposition_min_ratio", self.spin_depth_min_ratio_pct.value() / 100.0) * 100.0)
        self.spin_depth_closure_threshold.setValue(
            f("deposition_closure_threshold_a", self.spin_depth_closure_threshold.value())
        )
        self.spin_depth_post_fill_hole_pct.setValue(
            f("deposition_post_closure_fill_pct_hole", self.spin_depth_post_fill_hole_pct.value() / 100.0)
            * 100.0
        )
        self.spin_depth_post_fill_line_pct.setValue(
            f("deposition_post_closure_fill_pct_line", self.spin_depth_post_fill_line_pct.value() / 100.0)
            * 100.0
        )
        self.spin_depth_line_open_path.setValue(
            f("deposition_line_open_path_factor", self.spin_depth_line_open_path.value())
        )
        self.spin_depth_residual_decay.setValue(
            f("deposition_residual_fill_decay_length_a", self.spin_depth_residual_decay.value())
        )
        self.spin_inhibition_strength.setValue(f("inhibition_strength_pct", self.spin_inhibition_strength.value()))
        self.spin_inhibition_penetration.setValue(
            f("inhibition_penetration_depth_a", self.spin_inhibition_penetration.value())
        )
        self.spin_inhibition_decay_power.setValue(
            f("inhibition_decay_power", self.spin_inhibition_decay_power.value())
        )
        self.spin_inhibition_min_growth.setValue(
            f("inhibition_min_growth_ratio", self.spin_inhibition_min_growth.value() / 100.0) * 100.0
        )
        self.spin_inhibition_bottom_boost.setValue(
            f("inhibition_bottom_boost_pct", self.spin_inhibition_bottom_boost.value())
        )
        self.spin_inhibition_recombination.setValue(
            f("inhibition_peald_recombination_pct", self.spin_inhibition_recombination.value())
        )
        self.spin_inhibition_smoothing.setValue(f("inhibition_smoothing_a", self.spin_inhibition_smoothing.value()))

        self.sync_ion_shadow_slider_labels()
        self.sync_sputter_curve_from_spins()
        self.sync_ion_transmission_editor_from_spins()
        self.sync_redepo_lobe_from_spins()
        self.sync_depth_deposition_editor_from_spins()
        self.sync_inhibition_profile_from_spins()
        self.sync_etch_control_availability()
        self._populate_split_parameters()
        self._invalidate_result_for_input_change()

    def apply_selected_parameter_preset(self, _checked: bool = False) -> None:
        name = self._selected_parameter_preset_name()
        if not name:
            QMessageBox.information(self, "공정 파라미터 프리셋", "적용할 파라미터 프리셋이 없습니다.")
            return
        try:
            record = read_parameter_preset(self._parameter_library_path, name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "공정 파라미터 프리셋", f"파라미터 불러오기 실패:\n{exc}")
            return
        config_values = record.get("config", {})
        if not isinstance(config_values, dict):
            QMessageBox.warning(self, "공정 파라미터 프리셋", "프리셋 config 형식이 올바르지 않습니다.")
            return
        target_emulator = int(record.get("emulator_number", self.active_emulator_number()))
        self._preserve_geometry_on_emulator_switch = True
        self.set_active_emulator_number(target_emulator, run=False)
        self._apply_parameter_config_values(config_values)
        self._active_parameter_preset_name = sanitize_parameter_preset_name(name)
        self.edit_parameter_preset_name.setText(self._active_parameter_preset_name)
        self._update_parameter_preset_active_label()
        self.statusBar().showMessage(f"공정 파라미터 적용됨: {self._active_parameter_preset_name}", 2200)

    def delete_selected_parameter_preset(self, _checked: bool = False) -> None:
        name = self._selected_parameter_preset_name()
        if not name:
            QMessageBox.information(self, "공정 파라미터 프리셋", "삭제할 파라미터 프리셋이 없습니다.")
            return
        answer = QMessageBox.question(
            self,
            "공정 파라미터 프리셋 삭제",
            f"'{name}' 파라미터 프리셋을 삭제할까요?\n현재 화면의 파라미터 값은 유지됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted_name = delete_parameter_preset(self._parameter_library_path, name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "공정 파라미터 프리셋", f"파라미터 삭제 실패:\n{exc}")
            return
        if self._active_parameter_preset_name == deleted_name:
            self._active_parameter_preset_name = ""
        self.refresh_parameter_presets(show_status=False)
        self._update_parameter_preset_active_label()
        self.statusBar().showMessage(f"공정 파라미터 삭제됨: {deleted_name}", 2200)

    def _set_structure_points(
        self,
        points: Sequence[Tuple[float, float]],
        *,
        clear_smoothing: bool = True,
        fit: bool = True,
        preserve_on_emulator_switch: bool = False,
    ) -> None:
        pts = [(float(x), float(y)) for x, y in points]
        self._structure_points = pts
        if preserve_on_emulator_switch:
            self._preserve_geometry_on_emulator_switch = True
        self._syncing_structure_view = True
        try:
            self.structure_view.set_points_xy(list(pts))
        finally:
            self._syncing_structure_view = False
        self._sync_structure_table_from_points()
        if clear_smoothing:
            self._smoothed_points = []
            self._use_smoothed_geometry = False
            self.smoothing.revert()
            self.smoothing_view.set_reference_profiles_xy([])
            self.smoothing_view.set_points_xy(list(pts))
            self._sync_smoothed_table_from_points()
        self._update_geometry_labels()
        self._invalidate_result_for_input_change()
        if fit:
            QTimer.singleShot(0, self._fit_structure_views)

    def _sync_structure_table_from_points(self) -> None:
        if not hasattr(self, "structure_points_model") or self._syncing_structure_table:
            return
        self._syncing_structure_table = True
        try:
            self.structure_points_model.set_points(list(self._structure_points))
        finally:
            self._syncing_structure_table = False

    def _sync_smoothed_table_from_points(self) -> None:
        if not hasattr(self, "smoothed_points_model") or self._syncing_smoothed_table:
            return
        self._syncing_smoothed_table = True
        try:
            self.smoothed_points_model.set_points(list(self._smoothed_points))
        finally:
            self._syncing_smoothed_table = False

    def _refresh_structure_from_table_model(self, *, fit: bool = False) -> None:
        if self._syncing_structure_table:
            return
        pts = [(float(x), float(y)) for x, y in self.structure_points_model.get_points()]
        if len(pts) < 2:
            return
        self._structure_points = pts
        self._syncing_structure_view = True
        try:
            self.structure_view.set_points_xy(list(pts))
        finally:
            self._syncing_structure_view = False
        self._mark_structure_edited()
        if fit:
            QTimer.singleShot(0, self.structure_view.fit_points)

    def _find_symmetric_structure_point_index(
        self,
        points: Sequence[Tuple[float, float]],
        idx: int,
    ) -> Optional[int]:
        source_idx = int(idx)
        if source_idx < 0 or source_idx >= len(points):
            return None
        sx, sy = points[source_idx]
        if abs(float(sx)) <= 1e-9:
            return None
        xs = [float(x) for x, _y in points]
        ys = [float(y) for _x, y in points]
        diag = math.hypot(max(xs, default=0.0) - min(xs, default=0.0), max(ys, default=0.0) - min(ys, default=0.0))
        tolerance = max(5.0, diag * 0.04)
        best_idx: Optional[int] = None
        best_score = float("inf")
        target_x = -float(sx)
        target_y = float(sy)
        source_sign = -1 if float(sx) < 0.0 else 1
        for candidate_idx, (cx_raw, cy_raw) in enumerate(points):
            if candidate_idx == source_idx:
                continue
            cx, cy = float(cx_raw), float(cy_raw)
            if abs(cx) <= 1e-9:
                continue
            candidate_sign = -1 if cx < 0.0 else 1
            if candidate_sign == source_sign:
                continue
            score = math.hypot(cx - target_x, cy - target_y)
            if score < best_score:
                best_idx = candidate_idx
                best_score = score
        if best_idx is None or best_score > tolerance:
            return None
        return best_idx

    def _structure_points_with_symmetric_move(
        self,
        idx: int,
        x: float,
        y: float,
    ) -> Tuple[List[Tuple[float, float]], Optional[int]]:
        pts = [(float(px), float(py)) for px, py in self._structure_points]
        point_idx = int(idx)
        if point_idx < 0 or point_idx >= len(pts):
            return pts, None
        mirror_idx = (
            self._find_symmetric_structure_point_index(pts, point_idx)
            if self.chk_symmetric_structure_edit.isChecked()
            else None
        )
        pts[point_idx] = (float(x), float(y))
        if mirror_idx is not None:
            pts[mirror_idx] = (-float(x), float(y))
        return pts, mirror_idx

    def _on_structure_table_point_edit_requested(self, row: int, x: float, y: float) -> None:
        if self._syncing_structure_table:
            return
        updated_points, mirror_idx = self._structure_points_with_symmetric_move(int(row), float(x), float(y))
        self._syncing_structure_table = True
        try:
            self.structure_points_model.set_point(int(row), updated_points[int(row)])
            if mirror_idx is not None:
                self.structure_points_model.set_point(int(mirror_idx), updated_points[int(mirror_idx)])
        finally:
            self._syncing_structure_table = False
        self._refresh_structure_from_table_model()

    def _on_structure_table_delete_rows_requested(self, rows: List[int]) -> None:
        if self._syncing_structure_table:
            return
        valid_rows = sorted({int(row) for row in rows}, reverse=True)
        changed = False
        self._syncing_structure_table = True
        try:
            for row in valid_rows:
                changed = self.structure_points_model.delete_point(row) is not None or changed
        finally:
            self._syncing_structure_table = False
        if changed:
            self._refresh_structure_from_table_model(fit=True)

    def _on_structure_table_replace_points_requested(self, points: List[Tuple[float, float]]) -> None:
        if len(points) < 2:
            return
        self._set_structure_points(points, fit=True, preserve_on_emulator_switch=True)

    def _reset_geometry_to_default(self, _checked: bool = False) -> None:
        self._clear_continuation_context()
        default_sheet = self._structure_library_sheet_for_emulator(self.active_emulator_number())
        if default_sheet and self._structure_library_path.exists():
            try:
                read_structure_points(self._structure_library_path, default_sheet)
                self._active_structure_sheet_name = default_sheet
            except StructureLibraryError:
                self._active_structure_sheet_name = ""
        else:
            self._active_structure_sheet_name = ""
        self._set_structure_points(self._default_points_for_active_emulator())
        self._preserve_geometry_on_emulator_switch = False
        self._update_structure_library_active_label()
        self.statusBar().showMessage("구조를 에뮬레이터 기본값으로 되돌림", 1800)

    def _fit_structure_views(self, _checked: bool = False) -> None:
        self.structure_view.fit_points()
        self.smoothing_view.fit_points()
        if hasattr(self, "progress_geometry_view"):
            self.progress_geometry_view.fit_points()

    def _mark_structure_edited(self) -> None:
        self._clear_continuation_context()
        self._sync_structure_table_from_points()
        self._preserve_geometry_on_emulator_switch = True
        self._smoothed_points = []
        self._use_smoothed_geometry = False
        self.smoothing.revert()
        self.smoothing_view.set_reference_profiles_xy([])
        self.smoothing_view.set_points_xy(list(self._structure_points))
        self._sync_smoothed_table_from_points()
        self._update_geometry_labels()
        self._invalidate_result_for_input_change()

    def _on_structure_point_moved(self, idx: int, x: float, y: float) -> None:
        if self._syncing_structure_view:
            return
        if 0 <= int(idx) < len(self._structure_points):
            updated_points, mirror_idx = self._structure_points_with_symmetric_move(int(idx), float(x), float(y))
            self._structure_points = updated_points
            moved_x, moved_y = updated_points[int(idx)]
            self.structure_view.set_point_xy_silent(int(idx), moved_x, moved_y)
            if mirror_idx is not None:
                mirror_x, mirror_y = updated_points[int(mirror_idx)]
                self.structure_view.set_point_xy_silent(int(mirror_idx), mirror_x, mirror_y)
            self._mark_structure_edited()

    def _on_structure_point_inserted(self, idx: int, x: float, y: float) -> None:
        if self._syncing_structure_view:
            return
        insert_idx = max(0, min(int(idx), len(self._structure_points)))
        self._structure_points.insert(insert_idx, (float(x), float(y)))
        self._mark_structure_edited()

    def _on_structure_point_deleted(self, idx: int) -> None:
        if self._syncing_structure_view:
            return
        delete_idx = int(idx)
        if 0 <= delete_idx < len(self._structure_points):
            self._structure_points.pop(delete_idx)
            self._mark_structure_edited()

    def _on_smoothed_point_moved(self, idx: int, x: float, y: float) -> None:
        if 0 <= int(idx) < len(self._smoothed_points):
            self._smoothed_points[int(idx)] = (float(x), float(y))
            self._use_smoothed_geometry = True
            self._preserve_geometry_on_emulator_switch = True
            self._sync_smoothed_table_from_points()
            self._update_geometry_labels()
            self._invalidate_result_for_input_change()

    def _on_smoothed_point_inserted(self, idx: int, x: float, y: float) -> None:
        if not self._smoothed_points:
            return
        insert_idx = max(0, min(int(idx), len(self._smoothed_points)))
        self._smoothed_points.insert(insert_idx, (float(x), float(y)))
        self._use_smoothed_geometry = True
        self._preserve_geometry_on_emulator_switch = True
        self._sync_smoothed_table_from_points()
        self._update_geometry_labels()
        self._invalidate_result_for_input_change()

    def _on_smoothed_point_deleted(self, idx: int) -> None:
        delete_idx = int(idx)
        if 0 <= delete_idx < len(self._smoothed_points):
            self._smoothed_points.pop(delete_idx)
            self._use_smoothed_geometry = len(self._smoothed_points) >= 2
            self._preserve_geometry_on_emulator_switch = True
            self._sync_smoothed_table_from_points()
            self._update_geometry_labels()
            self._invalidate_result_for_input_change()

    def apply_structure_smoothing(self, _checked: bool = False) -> None:
        if len(self._structure_points) < 2:
            QMessageBox.warning(self, "구조 스무딩", "구조 좌표가 최소 2개 필요합니다.")
            return
        self.smoothing.set_base_points(list(self._structure_points))
        self.smoothing.set_params(
            int(self.spin_smooth_segments.value()),
            int(self.spin_smooth_iterations.value()),
        )
        self._smoothed_points = [(float(x), float(y)) for x, y in self.smoothing.run()]
        self._use_smoothed_geometry = True
        self._preserve_geometry_on_emulator_switch = True
        self.smoothing_view.set_reference_profiles_xy([list(self._structure_points)])
        self.smoothing_view.set_points_xy(list(self._smoothed_points))
        self._sync_smoothed_table_from_points()
        self._update_geometry_labels()
        self._invalidate_result_for_input_change()
        QTimer.singleShot(0, self.smoothing_view.fit_points)
        self.statusBar().showMessage(f"스무딩 적용됨: {len(self._smoothed_points)}점", 2500)

    def use_smoothed_geometry(self, _checked: bool = False) -> None:
        if not self._smoothed_points:
            self.apply_structure_smoothing()
            return
        self._use_smoothed_geometry = True
        self._preserve_geometry_on_emulator_switch = True
        self._update_geometry_labels()
        self._invalidate_result_for_input_change()
        self.statusBar().showMessage("실행 입력을 smoothed 구조로 변경", 1800)

    def use_raw_geometry(self, _checked: bool = False) -> None:
        self._use_smoothed_geometry = False
        self._preserve_geometry_on_emulator_switch = True
        self._update_geometry_labels()
        self._invalidate_result_for_input_change()
        self.statusBar().showMessage("실행 입력을 raw 구조로 변경", 1800)

    def _current_geometry_points(self) -> Tuple[Tuple[float, float], ...]:
        if self._use_smoothed_geometry and len(self._smoothed_points) >= 2:
            return tuple(self._smoothed_points)
        if len(self._structure_points) >= 2:
            return tuple(self._structure_points)
        return tuple(self._default_points_for_active_emulator())

    @staticmethod
    def _geometry_depth_a(points: Sequence[Tuple[float, float]]) -> float:
        pts = [(float(x), float(y)) for x, y in points]
        if len(pts) < 2:
            return 0.0
        ys = [float(y) for _x, y in pts]
        return max(0.0, max(ys) - min(ys))

    def _sync_depth_feature_depth_from_geometry(self) -> None:
        if not hasattr(self, "spin_depth_feature_depth"):
            return
        depth_a = self._geometry_depth_a(self._current_geometry_points())
        if depth_a <= 0.0:
            return
        if abs(float(self.spin_depth_feature_depth.value()) - depth_a) <= 1e-6:
            return
        self.spin_depth_feature_depth.setValue(depth_a)

    def _current_geometry_source_name(self) -> str:
        if self._use_smoothed_geometry and len(self._smoothed_points) >= 2:
            return "smooth"
        return "raw"

    def _has_active_smoothed_geometry(self) -> bool:
        return bool(self._use_smoothed_geometry and len(self._smoothed_points) >= 2)

    def _should_preserve_geometry_on_emulator_switch(self) -> bool:
        return bool(self._preserve_geometry_on_emulator_switch or self._has_active_smoothed_geometry())

    def _result_has_run_frames(self) -> bool:
        return self._result is not None and bool(self._result.frame_profiles)

    def _result_stage_index(self, result: Optional[TrenchDepoResult] = None) -> int:
        res = result or self._result
        if res is None:
            return 1
        meta = dict(res.meta)
        for key in ("stage_index", "stage_count"):
            try:
                return max(1, int(meta.get(key, 1)))
            except Exception:
                continue
        return 1

    def _next_depo_stage_index(self) -> int:
        return self._result_stage_index(self._result) + 1

    def _set_next_depo_button_state(self) -> None:
        if not hasattr(self, "btn_next_depo"):
            return
        has_result = bool(self._result is not None and self._result.final_profile and self._result.frame_profiles)
        next_stage = self._next_depo_stage_index() if has_result else max(2, int(self._continuation_stage_index or 2))
        self.btn_next_depo.setText(f"다음 Depo: {next_stage}차")
        self.btn_next_depo.setEnabled(has_result)

    def _clear_continuation_context(self) -> None:
        self._continuation_base_result = None
        self._continuation_base_run_dir = None
        self._continuation_stage_index = 1
        self._set_next_depo_button_state()

    def start_next_depo_stage(self, _checked: bool = False) -> None:
        if self._result is None or not self._result.final_profile:
            QMessageBox.warning(self, "트렌치 Depo 에뮬레이션", "이어갈 결과가 없습니다. 먼저 실행하거나 Run을 불러오세요.")
            return

        next_stage = self._next_depo_stage_index()
        seed = [(float(x), float(y)) for x, y in self._result.final_profile]
        if len(seed) < 2:
            QMessageBox.warning(self, "트렌치 Depo 에뮬레이션", "이어갈 final profile 점이 부족합니다.")
            return

        base_result = self._result
        base_run_dir = self._last_run_dir
        self._continuation_base_result = base_result
        self._continuation_base_run_dir = base_run_dir
        self._continuation_stage_index = next_stage

        self._set_structure_points(seed, clear_smoothing=True, fit=True, preserve_on_emulator_switch=True)
        self._continuation_base_result = base_result
        self._continuation_base_run_dir = base_run_dir
        self._continuation_stage_index = next_stage
        self._set_next_depo_button_state()
        self._sync_progress_geometry_view(fit=True)
        self._set_workflow_step("progress")
        self.statusBar().showMessage(
            f"다음 Depo {next_stage}차 준비 완료: 파라미터 조정 후 실행하세요.",
            4000,
        )

    def _merge_result_if_continuation(self, result: TrenchDepoResult) -> TrenchDepoResult:
        base_result = self._continuation_base_result
        if base_result is None:
            return result
        return merge_continued_trench_result(
            base_result,
            result,
            stage_index=max(2, int(self._continuation_stage_index)),
            continued_from_run=self._continuation_base_run_dir,
        )

    def _result_meta_has_overlay_samples(self, key: str) -> bool:
        if self._result is None:
            return False
        raw = self._result.meta.get(key)
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return False
        return any(bool(frame) for frame in raw)

    def _sync_field_overlay_toggles(self) -> None:
        if not all(hasattr(self, name) for name in ("chk_show_etch_overlay", "chk_show_redepo_overlay", "view")):
            return
        has_etch = self._result_meta_has_overlay_samples("frame_etch_overlays")
        has_redepo = self._result_meta_has_overlay_samples("frame_redepo_overlays")
        show_etch_toggle = bool(self._active_emulator_supports_sputter() or has_etch)
        show_redepo_toggle = bool(self._active_emulator_supports_redeposition() or has_redepo)
        self.chk_show_etch_overlay.setVisible(show_etch_toggle)
        self.chk_show_redepo_overlay.setVisible(show_redepo_toggle)
        self.chk_show_etch_overlay.setEnabled(has_etch)
        self.chk_show_redepo_overlay.setEnabled(has_redepo)
        self.view.set_etch_overlay_visible(bool(has_etch and self.chk_show_etch_overlay.isChecked()))
        self.view.set_redepo_overlay_visible(bool(has_redepo and self.chk_show_redepo_overlay.isChecked()))

    def _invalidate_result_for_input_change(self, *, fit: bool = False) -> None:
        self._stop_result_playback()
        self._result = None
        self._result_config = None
        if not hasattr(self, "slider_frame"):
            return
        self.slider_frame.blockSignals(True)
        try:
            self.slider_frame.setRange(0, 0)
            self.slider_frame.setValue(0)
            self.slider_frame.setEnabled(False)
        finally:
            self.slider_frame.blockSignals(False)
        self._set_result_playback_available(False)
        self._set_next_depo_button_state()
        self._sync_field_overlay_toggles()
        if hasattr(self, "btn_save_result_json"):
            self.btn_save_result_json.setEnabled(False)
        if hasattr(self, "edit_result_parameters"):
            self.edit_result_parameters.setPlainText("입력이 바뀌어서 기존 결과가 무효화됐습니다. 다시 실행하면 최신 파라미터가 여기에 표시됩니다.")
        if hasattr(self, "view_tabs") and self.view_tabs.currentIndex() == 3:
            self._show_result_input_preview(fit=fit)

    def _refresh_result_input_preview_if_idle(self, *, fit: bool = False) -> None:
        if self._result_has_run_frames():
            return
        if not hasattr(self, "view_tabs") or self.view_tabs.currentIndex() != 3:
            return
        self._show_result_input_preview(fit=fit)

    def _sync_structure_map_editors(self) -> None:
        if (
            not hasattr(self, "ion_transmission_editor")
            or not hasattr(self, "depth_deposition_editor")
            or not hasattr(self, "inhibition_profile_editor")
        ):
            return
        points = self._current_geometry_points()
        self.ion_transmission_editor.set_structure_points(points)
        self.depth_deposition_editor.set_structure_points(points)
        self.inhibition_profile_editor.set_structure_points(points)

    def _sync_progress_geometry_view(self, *, fit: bool = False) -> None:
        if not hasattr(self, "progress_geometry_view"):
            return
        points = [(float(x), float(y)) for x, y in self._current_geometry_points()]
        references: List[List[Tuple[float, float]]] = []
        source = self._current_geometry_source_name()
        if source == "smooth" and len(self._structure_points) >= 2:
            references.append(list(self._structure_points))
        stride = _display_decimation_stride([points, *references])
        display_points = _decimate_profile_for_display(points, stride)
        display_references = [
            _decimate_profile_for_display(reference, stride)
            for reference in references
        ]
        self.progress_geometry_view.set_reference_profiles_xy(display_references)
        self.progress_geometry_view.set_points_xy(display_points)
        label = f"실행 입력: {source} | {len(points)}점"
        if stride > 1:
            label += f" (표시 {len(display_points)}점)"
        self.lbl_progress_geometry_source.setText(label)
        if fit:
            QTimer.singleShot(0, self.progress_geometry_view.fit_points)

    def _show_result_input_preview(self, *, fit: bool = False) -> None:
        points = [(float(x), float(y)) for x, y in self._current_geometry_points()]
        if len(points) < 2:
            self.view.clear_data()
            self.lbl_status.setText("입력 미리보기: 비어 있음 | 점 0")
            if hasattr(self, "lbl_result_summary"):
                self.lbl_result_summary.setText("결과: 입력 미리보기 비어 있음 | 점 0")
            self._set_result_playback_available(False)
            return
        self.view.set_frames(
            [points],
            voids=[[]],
            redepo_overlays=[[]],
            etch_overlays=[[]],
            transport_lines=[[]],
            void_mode="current",
            dynamic_substrate_fill=False,
            history_mode="film",
        )
        self.slider_frame.blockSignals(True)
        try:
            self.slider_frame.setRange(0, 0)
            self.slider_frame.setValue(0)
            self.slider_frame.setEnabled(False)
        finally:
            self.slider_frame.blockSignals(False)
        self.view.show_frame(0, fit=fit)
        self.lbl_status.setText(
            f"입력 미리보기: {self._current_geometry_source_name()} | 점 {len(points)}"
        )
        if hasattr(self, "lbl_result_summary"):
            self.lbl_result_summary.setText(
                f"결과: 입력 미리보기 {self._current_geometry_source_name()} | 점 {len(points)}"
            )
        if hasattr(self, "edit_result_parameters"):
            self._update_result_parameter_summary(self.current_config(), None)
        self._set_result_playback_available(False)
        self._set_next_depo_button_state()
        self._sync_field_overlay_toggles()

    def _update_geometry_labels(self) -> None:
        raw_count = len(self._structure_points)
        smooth_count = len(self._smoothed_points)
        input_count = smooth_count if self._use_smoothed_geometry and smooth_count >= 2 else raw_count
        self.lbl_geometry_points.setText(f"구조: {raw_count}점")
        if self._use_smoothed_geometry and smooth_count >= 2:
            source_text = f"입력: smooth ({input_count}점)"
        else:
            source_text = f"입력: raw ({input_count}점)"
        self.lbl_geometry_source.setText(source_text)
        self.lbl_smoothing_status.setText(
            f"스무딩: {smooth_count}점" if smooth_count else "스무딩: 미적용"
        )
        self.btn_use_smoothed_geometry.setEnabled(smooth_count >= 2)
        self._sync_depth_feature_depth_from_geometry()
        self._sync_structure_map_editors()
        self._sync_progress_geometry_view()

    def _set_overlay_opacity(self, opacity: float) -> None:
        clamped = max(0.0, min(1.0, float(opacity)))
        self._overlay_opacity = clamped
        value = int(round(clamped * 100.0))
        if hasattr(self, "slider_overlay_opacity"):
            try:
                self.slider_overlay_opacity.blockSignals(True)
                self.slider_overlay_opacity.setValue(value)
            finally:
                self.slider_overlay_opacity.blockSignals(False)
        self.structure_view.set_overlay_opacity(clamped)
        self.smoothing_view.set_overlay_opacity(clamped)

    def _on_overlay_opacity_changed(self, value: int) -> None:
        self._set_overlay_opacity(float(value) / 100.0)

    def _apply_overlay_state_to_smoothing_view(self) -> None:
        state = self.structure_view.get_overlay_state()
        if not state:
            self.smoothing_view.clear_overlay_image()
            return
        image_path = state.get("image_path")
        if not image_path:
            self.smoothing_view.clear_overlay_image()
            return
        self.smoothing_view.set_overlay_image(
            str(image_path),
            scale_a_per_px=float(state.get("scale_a_per_px", 1.0)),
            opacity=float(state.get("opacity", self._overlay_opacity)),
            origin_x=float(state.get("origin_x", 0.0)),
            origin_y=float(state.get("origin_y", 0.0)),
            align_to_axes=False,
        )

    def _update_overlay_move_button_state(self) -> None:
        has_overlay = self.structure_view.get_overlay_state() is not None
        self.btn_move_overlay.setEnabled(has_overlay)
        if not has_overlay and self.btn_move_overlay.isChecked():
            try:
                self.btn_move_overlay.blockSignals(True)
                self.btn_move_overlay.setChecked(False)
            finally:
                self.btn_move_overlay.blockSignals(False)
        self.structure_view.set_overlay_drag_enabled(has_overlay and self.btn_move_overlay.isChecked())

    def _on_overlay_move_toggled(self, checked: bool) -> None:
        has_overlay = self.structure_view.get_overlay_state() is not None
        if not has_overlay and checked:
            try:
                self.btn_move_overlay.blockSignals(True)
                self.btn_move_overlay.setChecked(False)
            finally:
                self.btn_move_overlay.blockSignals(False)
            return
        self.structure_view.set_overlay_drag_enabled(has_overlay and bool(checked))
        if has_overlay:
            self.statusBar().showMessage(
                "Image move enabled" if checked else "Image move disabled",
                1500,
            )

    def _set_overlay_image(
        self,
        image_path: str,
        *,
        scale_a_per_px: float,
        align_to_axes: bool = True,
        origin_x: Optional[float] = None,
        origin_y: Optional[float] = None,
    ) -> bool:
        ok = self.structure_view.set_overlay_image(
            str(image_path),
            scale_a_per_px=float(scale_a_per_px),
            opacity=self._overlay_opacity,
            origin_x=origin_x,
            origin_y=origin_y,
            align_to_axes=align_to_axes,
        )
        if not ok:
            return False
        self._overlay_path = str(image_path)
        self._overlay_scale_a_per_px = float(scale_a_per_px)
        self._apply_overlay_state_to_smoothing_view()
        self._update_overlay_move_button_state()
        return True

    def _load_overlay_image(self, _checked: bool = False) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 불러오기",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*)",
        )
        if not path:
            return
        image_path = Path(path)
        dlg = CalibrateDialog(image_path, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        scale = dlg.scale_a_per_px
        if scale is None or scale <= 0.0:
            QMessageBox.warning(self, "이미지 오버레이", "보정 스케일은 0보다 커야 합니다.")
            return
        if not self._set_overlay_image(str(image_path), scale_a_per_px=float(scale), align_to_axes=True):
            QMessageBox.warning(self, "이미지 오버레이", "선택한 이미지를 불러오지 못했습니다.")
            return
        self.statusBar().showMessage("이미지 오버레이 불러옴", 2000)

    def _clear_overlay_image(self, _checked: bool = False) -> None:
        self.structure_view.clear_overlay_image()
        self.smoothing_view.clear_overlay_image()
        self._overlay_path = None
        self._update_overlay_move_button_state()
        self.statusBar().showMessage("이미지 오버레이 지움", 1500)

    def active_emulator_number(self) -> int:
        checked_id = self.emulator_button_group.checkedId()
        if checked_id >= 0:
            return int(checked_id)
        return int(self._active_emulator_number)

    def _workflow_index_for_step(self, step: str) -> int:
        normalized = str(step).strip().lower()
        if normalized in {"structure", "1"}:
            return 0
        if normalized in {"smoothing", "smooth", "2"}:
            return 1
        if normalized in {"progress", "process", "run", "running", "3"}:
            return 2
        if normalized in {"result", "results", "4"}:
            return 3
        return 0

    def _set_workflow_step(self, step: str) -> None:
        self._set_workflow_index(self._workflow_index_for_step(step))

    def _set_workflow_index(self, index: int) -> None:
        workflow_index = max(0, min(3, int(index)))
        if workflow_index == 1:
            self._apply_overlay_state_to_smoothing_view()
        if self._syncing_workflow_tabs:
            self._sync_result_controls_visibility(workflow_index)
            return
        self._syncing_workflow_tabs = True
        try:
            if self.view_tabs.currentIndex() != workflow_index:
                self.view_tabs.setCurrentIndex(workflow_index)
            if self.workflow_tabs.currentIndex() != workflow_index:
                self.workflow_tabs.setCurrentIndex(workflow_index)
        finally:
            self._syncing_workflow_tabs = False
        self._sync_result_controls_visibility(workflow_index)
        if workflow_index == 2:
            self._sync_progress_geometry_view(fit=True)
        if workflow_index == 3:
            self._refresh_result_input_preview_if_idle(fit=True)

    def _sync_result_controls_visibility(self, workflow_index: Optional[int] = None) -> None:
        index = self.view_tabs.currentIndex() if workflow_index is None else int(workflow_index)
        self.result_controls_widget.setVisible(index == 3)

    @staticmethod
    def _grid_row(widget: QWidget, column: int = 0, column_span: int = 1) -> Tuple[QWidget, int, int]:
        return (widget, int(column), int(column_span))

    def _register_model_parameter_sections(self) -> None:
        row = self._grid_row
        self._model_parameter_section_rows = {
            "direct": [
                row(self.lbl_etch_section, 0, 2),
                row(self.chk_sputter, 0, 2),
                row(self.lbl_sputter_section, 0, 2),
                row(self.lbl_sputter_strength),
                row(self.spin_sputter_strength, 1),
                row(self.lbl_sputter_peak_pct),
                row(self.spin_sputter_peak_pct, 1),
                row(self.lbl_sputter_peak),
                row(self.spin_sputter_peak, 1),
                row(self.lbl_sputter_width),
                row(self.spin_sputter_width, 1),
                row(self.lbl_sputter_smoothing),
                row(self.spin_sputter_smoothing, 1),
            ],
            "ion": [
                row(self.lbl_ion_depth_section, 0, 2),
                row(self.chk_ion_transmission, 0, 2),
                row(self.lbl_ion_start_depth),
                row(self.spin_ion_start_depth, 1),
                row(self.lbl_ion_end_depth),
                row(self.spin_ion_end_depth, 1),
                row(self.lbl_ion_decay_strength),
                row(self.spin_ion_decay_strength, 1),
                row(self.lbl_ion_floor),
                row(self.spin_ion_floor, 1),
                row(self.lbl_ion_curve_power),
                row(self.spin_ion_curve_power, 1),
                row(self.lbl_ion_geometry_section, 0, 2),
                row(self.lbl_ion_aperture_shadow),
                row(self.ion_aperture_shadow_row, 1),
                row(self.lbl_ion_lateral_shadow),
                row(self.ion_lateral_shadow_row, 1),
                row(self.lbl_ion_edge_shadow),
                row(self.ion_edge_shadow_row, 1),
            ],
            "reflected": [
                row(self.lbl_reflected_section, 0, 2),
                row(self.chk_reflected_ion, 0, 2),
                row(self.lbl_reflected_strength),
                row(self.spin_reflected_strength, 1),
                row(self.lbl_reflected_bowing),
                row(self.spin_reflected_bowing, 1),
                row(self.lbl_reflected_microtrench),
                row(self.spin_reflected_microtrench, 1),
                row(self.lbl_reflected_range),
                row(self.spin_reflected_range, 1),
            ],
            "redepo": [
                row(self.lbl_redepo_section, 0, 2),
                row(self.chk_redepo, 0, 2),
                row(self.lbl_redepo_source),
                row(self.cmb_redepo_source_model, 1),
                row(self.lbl_redepo_efficiency),
                row(self.spin_redepo_efficiency, 1),
                row(self.lbl_redepo_emit_power),
                row(self.spin_redepo_emit_power, 1),
                row(self.lbl_redepo_distance_power),
                row(self.spin_redepo_distance_power, 1),
                row(self.lbl_redepo_soft_los),
                row(self.spin_redepo_soft_los, 1),
            ],
            "depth": [
                row(self.lbl_depth_depo_section, 0, 2),
                row(self.chk_depth_deposition, 0, 2),
                row(self.lbl_depth_feature_section, 0, 2),
                row(self.lbl_depth_feature_type),
                row(self.cmb_depth_feature_type, 1),
                row(self.lbl_depth_feature_width),
                row(self.spin_depth_feature_width, 1),
                row(self.lbl_depth_feature_depth),
                row(self.spin_depth_feature_depth, 1),
                row(self.lbl_depth_feature_length),
                row(self.spin_depth_feature_length, 1),
                row(self.lbl_depth_curve_section, 0, 2),
                row(self.lbl_depth_decay_k),
                row(self.spin_depth_decay_k, 1),
                row(self.lbl_depth_decay_power),
                row(self.spin_depth_decay_power, 1),
                row(self.lbl_depth_min_ratio),
                row(self.spin_depth_min_ratio_pct, 1),
                row(self.btn_depth_advanced, 0, 2),
                row(self.lbl_depth_closure_section, 0, 2),
                row(self.lbl_depth_closure_threshold),
                row(self.spin_depth_closure_threshold, 1),
                row(self.lbl_depth_post_fill_hole),
                row(self.spin_depth_post_fill_hole_pct, 1),
                row(self.lbl_depth_post_fill_line),
                row(self.spin_depth_post_fill_line_pct, 1),
                row(self.lbl_depth_line_open_path),
                row(self.spin_depth_line_open_path, 1),
                row(self.lbl_depth_residual_decay),
                row(self.spin_depth_residual_decay, 1),
            ],
            "inhibition": [
                row(self.lbl_inhibition_section, 0, 2),
                row(self.chk_inhibition_deposition, 0, 2),
                row(self.lbl_inhibition_strength),
                row(self.spin_inhibition_strength, 1),
                row(self.lbl_inhibition_penetration),
                row(self.spin_inhibition_penetration, 1),
                row(self.lbl_inhibition_decay_power),
                row(self.spin_inhibition_decay_power, 1),
                row(self.lbl_inhibition_min_growth),
                row(self.spin_inhibition_min_growth, 1),
                row(self.lbl_inhibition_bottom_boost),
                row(self.spin_inhibition_bottom_boost, 1),
                row(self.lbl_inhibition_recombination),
                row(self.spin_inhibition_recombination, 1),
                row(self.lbl_inhibition_smoothing),
                row(self.spin_inhibition_smoothing, 1),
            ],
            "lf": [
                row(self.lbl_lf_overhang_section, 0, 2),
                row(self.chk_lf_overhang, 0, 2),
                row(self.lbl_lf_overhang_dose),
                row(self.spin_lf_overhang_dose, 1),
                row(self.lbl_lf_overhang_sputter_gain),
                row(self.spin_lf_overhang_sputter_gain, 1),
                row(self.lbl_lf_overhang_redepo_fraction),
                row(self.spin_lf_overhang_redepo_fraction, 1),
                row(self.lbl_lf_overhang_survival),
                row(self.spin_lf_overhang_survival, 1),
                row(self.lbl_lf_overhang_width),
                row(self.spin_lf_overhang_width, 1),
            ],
            "closure": [
                row(self.lbl_closure_redepo_section, 0, 2),
                row(self.chk_closure_redepo, 0, 2),
                row(self.lbl_closure_redepo_efficiency),
                row(self.spin_closure_redepo_efficiency, 1),
                row(self.lbl_closure_redepo_shadow_gain),
                row(self.spin_closure_redepo_shadow_gain, 1),
                row(self.lbl_closure_redepo_width),
                row(self.spin_closure_redepo_width, 1),
                row(self.lbl_closure_redepo_survival),
                row(self.spin_closure_redepo_survival, 1),
                row(self.lbl_closure_redepo_smoothing),
                row(self.spin_closure_redepo_smoothing, 1),
            ],
        }
        self._apply_model_parameter_section_order()

    def _apply_model_parameter_section_order(self) -> None:
        grid = getattr(self, "params_grid", None)
        if grid is None:
            return
        all_rows = [
            row
            for key in DEFAULT_MODEL_PARAMETER_SECTION_ORDER
            for row in self._model_parameter_section_rows.get(key, [])
        ]
        for widget, _column, _column_span in all_rows:
            grid.removeWidget(widget)
        valid_order = [key for key in self._model_parameter_section_order if key in self._model_parameter_section_rows]
        for key in DEFAULT_MODEL_PARAMETER_SECTION_ORDER:
            if key not in valid_order:
                valid_order.append(key)
        self._model_parameter_section_order = valid_order
        layout_row = 3
        for key in valid_order:
            for widget, column, column_span in self._model_parameter_section_rows.get(key, []):
                grid.addWidget(widget, layout_row, column, 1, column_span)
                if column_span > 1 or column > 0:
                    layout_row += 1
        grid.invalidate()

    def _move_model_parameter_section(self, source_key: str, target_key: str) -> None:
        if source_key == target_key:
            return
        order = [key for key in self._model_parameter_section_order if key in self._model_parameter_section_rows]
        if source_key not in order or target_key not in order:
            return
        order.remove(source_key)
        order.insert(order.index(target_key), source_key)
        self._model_parameter_section_order = order
        self._apply_model_parameter_section_order()
        self.sync_etch_control_availability()
        self.statusBar().showMessage("모델 파라미터 섹션 순서를 변경했습니다.", 1800)

    def _on_view_workflow_tab_changed(self, index: int) -> None:
        self._set_workflow_index(index)

    def _on_control_workflow_tab_changed(self, index: int) -> None:
        self._set_workflow_index(index)

    def _on_split_options_toggled(self, checked: bool) -> None:
        if checked and self.btn_compare_options.isChecked():
            self.btn_compare_options.setChecked(False)
        self.split_group.setVisible(bool(checked))

    def _on_compare_options_toggled(self, checked: bool) -> None:
        if checked and self.btn_split_options.isChecked():
            self.btn_split_options.setChecked(False)
        self.compare_group.setVisible(bool(checked and self.btn_compare_options.isEnabled()))

    def _add_emulator_toggle(self, number: int) -> None:
        target = max(0, min(MAX_EMULATOR_NUMBER, int(number)))
        if target in self._emulator_buttons:
            return
        if target not in self._emulator_numbers:
            self._emulator_numbers.append(target)
            self._emulator_numbers.sort()

        button = QPushButton(f"{target:02d}")
        button.setCheckable(True)
        button.setFixedWidth(44)
        button.setToolTip(_emulator_mode_label(target))
        button.clicked.connect(lambda _checked=False, n=target: self.set_active_emulator_number(n))
        self.emulator_button_group.addButton(button, target)
        insert_at = max(0, self.emulator_toggle_row.count() - 1)
        self.emulator_toggle_row.insertWidget(insert_at, button)
        self._emulator_buttons[target] = button
        if target == self._active_emulator_number:
            button.setChecked(True)
        self._sync_new_emulator_button()
        if hasattr(self, "cmb_compare_target"):
            self._populate_compare_targets()

    def _sync_new_emulator_button(self) -> None:
        if not hasattr(self, "btn_new_emulator"):
            return
        self.btn_new_emulator.setEnabled(next_emulator_number(self._emulator_numbers) is not None)

    def _persist_emulator_numbers(self) -> None:
        save_created_emulator_numbers(self._emulator_numbers)

    def _create_emulator_slot(self, number: int, *, create_research_slot: bool) -> None:
        if create_research_slot:
            ensure_emulator_research_slot(number)
        self._add_emulator_toggle(number)

    def create_new_emulator(self) -> None:
        number = next_emulator_number(self._emulator_numbers)
        if number is None:
            QMessageBox.information(
                self,
                "Emulator",
                f"Emulator slots are full. Valid numbers are 00 to {MAX_EMULATOR_NUMBER:02d}.",
            )
            return
        self._create_emulator_slot(number, create_research_slot=True)
        self._persist_emulator_numbers()
        self.set_active_emulator_number(number)
        self.statusBar().showMessage(f"Created emulator {number:02d}", 3500)

    def set_active_emulator_number(self, number: int, *, run: bool = False) -> None:
        target = max(0, min(MAX_EMULATOR_NUMBER, int(number)))
        previous = self.active_emulator_number()
        created_any = False
        for slot_number in range(0, target + 1):
            if slot_number not in self._emulator_buttons:
                self._create_emulator_slot(slot_number, create_research_slot=True)
                created_any = True
        if created_any:
            self._persist_emulator_numbers()
        button = self._emulator_buttons.get(target)
        if button is None:
            return
        preserve_geometry = self._should_preserve_geometry_on_emulator_switch()
        button.setChecked(True)
        self.apply_emulator_mode(run=run, preserve_geometry=preserve_geometry)
        if target != previous and not preserve_geometry:
            self._set_workflow_step("structure")
        elif target != previous:
            self._invalidate_result_for_input_change(fit=True)

    def _active_emulator_supports_sputter(self) -> bool:
        return self.active_emulator_number() in (0, 2, 3, 6)

    def _active_emulator_supports_ion_transmission(self) -> bool:
        return self.active_emulator_number() in (0, 3)

    def _active_emulator_supports_reflected_ion(self) -> bool:
        return False

    def _active_emulator_supports_redeposition(self) -> bool:
        return self.active_emulator_number() in (0, 6)

    def _active_emulator_supports_depth_deposition(self) -> bool:
        return self.active_emulator_number() in (0, 4, 5)

    def _active_emulator_supports_inhibition(self) -> bool:
        return self.active_emulator_number() in (0, 5)

    def _active_emulator_supports_lf_overhang(self) -> bool:
        return False

    def _active_emulator_supports_closure_redepo(self) -> bool:
        return False

    @staticmethod
    def _emulator_supports_sputter(number: int) -> bool:
        return int(number) in (0, 2, 3, 6)

    @staticmethod
    def _emulator_supports_ion_transmission(number: int) -> bool:
        return int(number) in (0, 3)

    @staticmethod
    def _emulator_supports_reflected_ion(number: int) -> bool:
        return False

    @staticmethod
    def _emulator_supports_redeposition(number: int) -> bool:
        return int(number) in (0, 6)

    @staticmethod
    def _emulator_supports_depth_deposition(number: int) -> bool:
        return int(number) in (0, 4, 5)

    @staticmethod
    def _emulator_supports_inhibition(number: int) -> bool:
        return int(number) in (0, 5)

    @staticmethod
    def _emulator_supports_lf_overhang(number: int) -> bool:
        return False

    @staticmethod
    def _emulator_supports_closure_redepo(number: int) -> bool:
        return False

    def _populate_compare_targets(self) -> None:
        previous = self.cmb_compare_target.currentData()
        active = self.active_emulator_number()
        default_target: object
        if active == 0:
            default_target = 1
        elif active in (2, 3):
            default_target = 1
        elif active == 6:
            default_target = 2
        elif active == 4:
            default_target = 5
        elif active == 5:
            default_target = 4
        elif self._emulator_supports_sputter(active):
            default_target = "legacy_gapsim_angle"
        else:
            default_target = 1

        self.cmb_compare_target.blockSignals(True)
        self.cmb_compare_target.clear()
        for number in self._emulator_numbers:
            target = int(number)
            if target == active:
                continue
            self.cmb_compare_target.addItem(_emulator_mode_title(target), target)
        if self._emulator_supports_sputter(active):
            self.cmb_compare_target.addItem("GapSim angle-only legacy", "legacy_gapsim_angle")

        prefer_previous = not (
            (active == 0 and previous != 1)
            or (active == 4 and previous != 5)
            or (active == 6 and previous != 2)
        )
        restored_idx = self.cmb_compare_target.findData(previous)
        default_idx = self.cmb_compare_target.findData(default_target)
        if prefer_previous and restored_idx >= 0:
            self.cmb_compare_target.setCurrentIndex(restored_idx)
        elif default_idx >= 0:
            self.cmb_compare_target.setCurrentIndex(default_idx)
        elif self.cmb_compare_target.count() > 0:
            self.cmb_compare_target.setCurrentIndex(0)
        self.cmb_compare_target.blockSignals(False)

        has_targets = self.cmb_compare_target.count() > 0
        self.btn_compare_options.setEnabled(has_targets)
        self.btn_run_compare.setEnabled(has_targets)
        if not has_targets:
            self.btn_compare_options.setChecked(False)
            self.compare_group.setVisible(False)

    def _populate_split_parameters(self) -> None:
        previous = self.cmb_split_parameter.currentData()
        options = [
            ("Depo A/CYC", "angstrom_per_cycle"),
            ("Cycles", "cycles"),
        ]
        if self._active_emulator_supports_sputter():
            options = [
                ("Etch A/CYC", "sputter_strength_a_per_cycle"),
                ("Peak %", "sputter_peak_pct"),
                ("Peak angle", "sputter_peak_angle_deg"),
                ("Width", "sputter_width_deg"),
                *options,
            ]
        if self._active_emulator_supports_ion_transmission():
            options = [
                ("Ion start %", "ion_transmission_start_depth_pct"),
                ("Ion end %", "ion_transmission_end_depth_pct"),
                ("Ion drop %", "ion_transmission_decay_strength_pct"),
                ("Ion floor %", "ion_transmission_floor_pct"),
                ("Ion curve", "ion_transmission_curve_power"),
                ("Ion aperture %", "ion_transmission_aperture_shadow_pct"),
                ("Ion hidden %", "ion_transmission_lateral_shadow_pct"),
                ("Ion edge %", "ion_transmission_edge_shadow_pct"),
                *options,
            ]
        if self._active_emulator_supports_reflected_ion():
            options = [
                ("Reflect %", "reflected_ion_strength_pct"),
                ("Bowing", "reflected_ion_bowing_weight"),
                ("Microtrench", "reflected_ion_microtrench_weight"),
                ("Reflect range", "reflected_ion_range_a"),
                *options,
            ]
        if self._active_emulator_supports_redeposition():
            options = [
                ("Reflection redepo %", "redepo_efficiency_pct"),
                ("Angular spread deg", "redepo_emit_power"),
                ("Specular bias %", "redepo_distance_power"),
                *options,
            ]
        if self._active_emulator_supports_lf_overhang():
            options = [
                ("LF dose", "lf_overhang_dose"),
                ("LF sputter gain", "lf_overhang_sputter_gain"),
                ("LF redepo %", "lf_overhang_redepo_fraction_pct"),
                ("LF survival loss", "lf_overhang_survival_penalty"),
                ("LF width", "lf_overhang_width_a"),
                *options,
            ]
        if self._active_emulator_supports_closure_redepo():
            options = [
                ("Closure redepo %", "closure_redepo_efficiency_pct"),
                ("Closure capture", "closure_redepo_shadow_gain"),
                ("Closure width", "closure_redepo_width_a"),
                ("Closure survival loss", "closure_redepo_survival_penalty"),
                ("Closure smooth", "closure_redepo_smoothing_a"),
                *options,
            ]
        if self._active_emulator_supports_depth_deposition():
            options = [
                ("Depth decay", "deposition_depth_decay_k"),
                ("Depth power", "deposition_depth_decay_power"),
                ("Min depo ratio", "deposition_min_ratio"),
                ("Closure threshold", "deposition_closure_threshold_a"),
                ("Hole after-close fill %", "deposition_post_closure_fill_pct_hole"),
                ("Line after-close fill %", "deposition_post_closure_fill_pct_line"),
                *options,
            ]
        if self._active_emulator_supports_inhibition():
            options = [
                ("Inhibit %", "inhibition_strength_pct"),
                ("Inhibit depth", "inhibition_penetration_depth_a"),
                ("Inhibit power", "inhibition_decay_power"),
                ("Inhibit floor", "inhibition_min_growth_ratio"),
                ("Bottom boost", "inhibition_bottom_boost_pct"),
                ("PEALD recomb", "inhibition_peald_recombination_pct"),
                ("Inhibit smooth", "inhibition_smoothing_a"),
                *options,
            ]

        self.cmb_split_parameter.blockSignals(True)
        self.cmb_split_parameter.clear()
        for label, key in options:
            self.cmb_split_parameter.addItem(label, key)
        restored_idx = self.cmb_split_parameter.findData(previous)
        self.cmb_split_parameter.setCurrentIndex(restored_idx if restored_idx >= 0 else 0)
        self.cmb_split_parameter.blockSignals(False)
        self.apply_split_parameter_defaults()

    def _populate_emulator_default_presets(self) -> None:
        number = self.active_emulator_number()
        previous = self.cmb_emulator_default_preset.currentText()
        options = EMULATOR_PROCESS_PRESETS.get(number, EMULATOR_PROCESS_PRESETS[0])
        self._syncing_emulator_preset = True
        self.cmb_emulator_default_preset.blockSignals(True)
        try:
            self.cmb_emulator_default_preset.clear()
            for label, settings in options:
                self.cmb_emulator_default_preset.addItem(label, settings)
            restored = self.cmb_emulator_default_preset.findText(previous)
            self.cmb_emulator_default_preset.setCurrentIndex(restored if restored >= 0 else 0)
        finally:
            self.cmb_emulator_default_preset.blockSignals(False)
            self._syncing_emulator_preset = False

    def apply_selected_emulator_preset(self, _index: int = 0) -> None:
        if self._syncing_emulator_preset:
            return
        settings = self.cmb_emulator_default_preset.currentData()
        if not isinstance(settings, dict):
            return
        self._apply_emulator_preset(settings)
        self.statusBar().showMessage(
            f"기본 옵션 불러옴: {self.cmb_emulator_default_preset.currentText()}",
            1800,
        )

    def _apply_emulator_preset(self, settings: dict[str, object]) -> None:
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion = self._active_emulator_supports_ion_transmission()
        supports_reflected = self._active_emulator_supports_reflected_ion()
        supports_redepo = self._active_emulator_supports_redeposition()
        supports_depth = self._active_emulator_supports_depth_deposition()
        supports_inhibition = self._active_emulator_supports_inhibition()
        supports_lf = self._active_emulator_supports_lf_overhang()
        supports_closure = self._active_emulator_supports_closure_redepo()

        self.spin_cycles.setValue(int(settings.get("cycles", self.spin_cycles.value())))
        self.spin_angstrom_per_cycle.setValue(float(settings.get("depo", self.spin_angstrom_per_cycle.value())))
        if "reparam" in settings:
            self._set_quality_mode_for_ds(float(settings["reparam"]))
        self.chk_sputter.setChecked(bool(supports_sputter and settings.get("sputter", supports_sputter)))
        self.chk_ion_transmission.setChecked(bool(supports_ion and settings.get("ion", supports_ion)))
        self.chk_reflected_ion.setChecked(bool(supports_reflected and settings.get("reflected", supports_reflected)))
        self.chk_redepo.setChecked(bool(supports_redepo and settings.get("redepo", supports_redepo)))
        self.chk_depth_deposition.setChecked(bool(supports_depth and settings.get("depth", supports_depth)))
        self.chk_inhibition_deposition.setChecked(
            bool(supports_inhibition and settings.get("inhibition", self.active_emulator_number() == 5))
        )
        self.chk_lf_overhang.setChecked(bool(supports_lf and settings.get("lf", supports_lf)))
        self.chk_closure_redepo.setChecked(bool(supports_closure and settings.get("closure", supports_closure)))

        self.spin_sputter_strength.setValue(float(settings.get("etch", self.spin_sputter_strength.value())))
        self.spin_sputter_peak.setValue(float(settings.get("peak", self.spin_sputter_peak.value())))
        self.spin_sputter_width.setValue(float(settings.get("width", self.spin_sputter_width.value())))
        self.spin_ion_start_depth.setValue(float(settings.get("ion_start", self.spin_ion_start_depth.value())))
        self.spin_ion_end_depth.setValue(float(settings.get("ion_end", self.spin_ion_end_depth.value())))
        self.spin_ion_decay_strength.setValue(float(settings.get("ion_drop", self.spin_ion_decay_strength.value())))
        self.spin_ion_floor.setValue(float(settings.get("ion_floor", self.spin_ion_floor.value())))
        self.spin_ion_curve_power.setValue(float(settings.get("ion_curve", self.spin_ion_curve_power.value())))
        self.spin_reflected_strength.setValue(float(settings.get("reflect", self.spin_reflected_strength.value())))
        self.spin_reflected_bowing.setValue(float(settings.get("bowing", self.spin_reflected_bowing.value())))
        self.spin_reflected_microtrench.setValue(float(settings.get("micro", self.spin_reflected_microtrench.value())))
        self.spin_reflected_range.setValue(float(settings.get("range", self.spin_reflected_range.value())))
        self.spin_redepo_efficiency.setValue(float(settings.get("redepo_eff", self.spin_redepo_efficiency.value())))
        self.spin_redepo_emit_power.setValue(float(settings.get("redepo_emit", self.spin_redepo_emit_power.value())))
        self.spin_redepo_distance_power.setValue(float(settings.get("redepo_dist", self.spin_redepo_distance_power.value())))
        self.spin_lf_overhang_dose.setValue(float(settings.get("lf_dose", self.spin_lf_overhang_dose.value())))
        self.spin_lf_overhang_sputter_gain.setValue(float(settings.get("lf_gain", self.spin_lf_overhang_sputter_gain.value())))
        self.spin_lf_overhang_redepo_fraction.setValue(float(settings.get("lf_redepo", self.spin_lf_overhang_redepo_fraction.value())))
        self.spin_lf_overhang_survival.setValue(float(settings.get("lf_survival", self.spin_lf_overhang_survival.value())))
        self.spin_lf_overhang_width.setValue(float(settings.get("lf_width", self.spin_lf_overhang_width.value())))
        self.spin_closure_redepo_efficiency.setValue(float(settings.get("closure_eff", self.spin_closure_redepo_efficiency.value())))
        self.spin_closure_redepo_shadow_gain.setValue(float(settings.get("closure_shadow", self.spin_closure_redepo_shadow_gain.value())))
        self.spin_closure_redepo_width.setValue(float(settings.get("closure_width", self.spin_closure_redepo_width.value())))
        self.spin_closure_redepo_survival.setValue(float(settings.get("closure_survival", self.spin_closure_redepo_survival.value())))
        self.spin_closure_redepo_smoothing.setValue(float(settings.get("closure_smoothing", self.spin_closure_redepo_smoothing.value())))
        self.spin_depth_feature_width.setValue(float(settings.get("depth_width", self.spin_depth_feature_width.value())))
        self.spin_depth_feature_depth.setValue(float(settings.get("depth_depth", self.spin_depth_feature_depth.value())))
        self.spin_depth_feature_length.setValue(float(settings.get("depth_length", self.spin_depth_feature_length.value())))
        self.spin_depth_decay_k.setValue(float(settings.get("depth_k", self.spin_depth_decay_k.value())))
        self.spin_depth_decay_power.setValue(float(settings.get("depth_power", self.spin_depth_decay_power.value())))
        self.spin_depth_min_ratio_pct.setValue(float(settings.get("depth_min", self.spin_depth_min_ratio_pct.value())))
        self.spin_inhibition_strength.setValue(
            float(settings.get("inhibition_strength", self.spin_inhibition_strength.value()))
        )
        self.spin_inhibition_penetration.setValue(
            float(settings.get("inhibition_depth", self.spin_inhibition_penetration.value()))
        )
        self.spin_inhibition_decay_power.setValue(
            float(settings.get("inhibition_power", settings.get("depth_power", self.spin_inhibition_decay_power.value())))
        )
        self.spin_inhibition_min_growth.setValue(
            float(settings.get("inhibition_min", settings.get("depth_min", self.spin_inhibition_min_growth.value())))
        )
        self.spin_inhibition_bottom_boost.setValue(
            float(settings.get("inhibition_bottom", self.spin_inhibition_bottom_boost.value()))
        )
        self.spin_inhibition_recombination.setValue(
            float(settings.get("inhibition_recomb", self.spin_inhibition_recombination.value()))
        )
        self.spin_inhibition_smoothing.setValue(
            float(settings.get("inhibition_smooth", self.spin_inhibition_smoothing.value()))
        )

        self.sync_sputter_curve_from_spins()
        self.sync_ion_transmission_editor_from_spins()
        self.sync_redepo_lobe_from_spins()
        self.sync_depth_deposition_editor_from_spins()
        self.sync_inhibition_profile_from_spins()
        self.sync_etch_control_availability()

    def apply_emulator_mode(
        self,
        _index: int = 0,
        *,
        run: bool = True,
        preserve_geometry: bool = False,
    ) -> None:
        number = self.active_emulator_number()
        changed = number != self._active_emulator_number or not getattr(self, "_emulator_mode_initialized", False)
        self._active_emulator_number = number
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion_transmission = self._active_emulator_supports_ion_transmission()
        supports_reflected_ion = self._active_emulator_supports_reflected_ion()
        supports_redeposition = self._active_emulator_supports_redeposition()
        supports_depth_deposition = self._active_emulator_supports_depth_deposition()
        supports_inhibition = self._active_emulator_supports_inhibition()
        supports_lf_overhang = self._active_emulator_supports_lf_overhang()
        supports_closure_redepo = self._active_emulator_supports_closure_redepo()

        self.setWindowTitle(f"GFE - {_emulator_mode_title(number)}")
        if changed and not preserve_geometry:
            self._reset_geometry_to_default()

        if supports_sputter:
            if number == 0:
                self.lbl_etch_section.setText("Direct angle sputter etch (통합 source)")
                self.lbl_sputter_section.setText("Angle response kernel")
            elif number == 3:
                self.lbl_etch_section.setText("Direct angle sputter etch (ion transmission source)")
                self.lbl_sputter_section.setText("Angle response kernel")
            elif number == 6:
                self.lbl_etch_section.setText("Direct angle sputter etch (reflection redepo source)")
                self.lbl_sputter_section.setText("Angle response kernel")
            else:
                self.lbl_etch_section.setText("Direct angle sputter etch")
                self.lbl_sputter_section.setText("Angle response kernel")

        for widget in self._sputter_widgets:
            widget.setVisible(supports_sputter)
        for widget in self._ion_transmission_widgets:
            widget.setVisible(supports_ion_transmission)
        for widget in self._reflected_ion_widgets:
            widget.setVisible(supports_reflected_ion)
        for widget in self._redeposition_widgets:
            widget.setVisible(supports_redeposition)
        for widget in self._depth_deposition_widgets:
            widget.setVisible(supports_depth_deposition)
        for widget in self._inhibition_widgets:
            widget.setVisible(supports_inhibition)
        for widget in self._lf_overhang_widgets:
            widget.setVisible(supports_lf_overhang)
        for widget in self._closure_redepo_widgets:
            widget.setVisible(supports_closure_redepo)
        self.gaussian_group.setVisible(supports_sputter)
        self._populate_compare_targets()
        self.ion_map_group.setTitle("Ion Transmission Depth Map")
        self.gaussian_group.setTitle("Direct Sputter Gaussian")
        if number in (0, 6):
            self.redepo_lobe_editor.set_mode("reflection")
            self.redepo_lobe_group.setTitle("Reflection Redeposition Visual Editor")
            self.chk_redepo.setText("Reflection redepo enabled")
            self.lbl_redepo_section.setText("Normal/specular reflection lobe redepo")
            self.lbl_redepo_efficiency.setText("Redepo efficiency %")
            self.lbl_redepo_emit_power.setText("Angular spread deg")
            self.lbl_redepo_distance_power.setText("Specular bias %")
            self.spin_redepo_emit_power.setDecimals(1)
            self.spin_redepo_emit_power.setRange(1.0, 80.0)
            self.spin_redepo_emit_power.setSingleStep(2.0)
            self.spin_redepo_distance_power.setDecimals(1)
            self.spin_redepo_distance_power.setRange(-100.0, 100.0)
            self.spin_redepo_distance_power.setSingleStep(5.0)
            if changed and (self.spin_redepo_emit_power.value() <= 8.0 or self.spin_redepo_emit_power.value() > 80.0):
                self.spin_redepo_emit_power.setValue(22.0)
                self.spin_redepo_distance_power.setValue(25.0)
        else:
            self.redepo_lobe_editor.set_mode("transport")
            self.redepo_lobe_group.setTitle("Redeposition Visual Editor")
            self.chk_redepo.setText("Redeposition")
            self.lbl_redepo_section.setText("Redeposition")
            self.lbl_redepo_efficiency.setText("Efficiency %")
            self.lbl_redepo_emit_power.setText("Emit power")
            self.lbl_redepo_distance_power.setText("Dist power")
            self.spin_redepo_emit_power.setDecimals(2)
            self.spin_redepo_emit_power.setRange(0.0, 8.0)
            self.spin_redepo_emit_power.setSingleStep(0.1)
            self.spin_redepo_distance_power.setDecimals(2)
            self.spin_redepo_distance_power.setRange(0.0, 4.0)
            self.spin_redepo_distance_power.setSingleStep(0.1)
        if number == 0:
            self.depth_profile_group.setTitle("Integrated Depth Depletion Map")
            self.inhibition_profile_group.setTitle("Integrated Inhibition Visual Editor")
        elif number == 5:
            self.depth_profile_group.setTitle("Inhibition Base Map")
            self.inhibition_profile_group.setTitle("Inhibition Visual Editor")
        else:
            self.depth_profile_group.setTitle("Depth Depletion Map")
            self.inhibition_profile_group.setTitle("Inhibition Visual Editor")

        if supports_sputter:
            if changed:
                self.chk_sputter.setChecked(True)
                self.chk_ion_transmission.setChecked(supports_ion_transmission)
                self.chk_reflected_ion.setChecked(supports_reflected_ion)
                self.chk_redepo.setChecked(supports_redeposition)
                self.chk_depth_deposition.setChecked(supports_depth_deposition)
                self.chk_inhibition_deposition.setChecked(False)
                self.chk_lf_overhang.setChecked(supports_lf_overhang)
                self.chk_closure_redepo.setChecked(supports_closure_redepo)
                if number == 0:
                    self.cmb_depth_feature_type.setCurrentIndex(0)
            elif not supports_depth_deposition:
                self.chk_depth_deposition.setChecked(False)
            if not supports_inhibition:
                self.chk_inhibition_deposition.setChecked(False)
            if number == 0:
                self.chk_depth_deposition.setText("Depth depletion")
                self.chk_inhibition_deposition.setText("Inhibition deposition")
                self.lbl_depth_depo_section.setText("Depth depletion deposition")
                self.lbl_inhibition_section.setText("Inhibition deposition")
                self.lbl_depth_parameter_help.setText(
                    "통합 모델: direct/ion etch와 normal/specular lobe redepo 위에 Depth depletion과 Inhibition deposition을 각각 또는 동시에 결합합니다. Reflected/LF/closure는 제외됩니다."
                )
                self.edit_request_note.setPlaceholderText("요청사항 / 통합모델 리데포/감쇠/인히비션 관찰 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            elif supports_ion_transmission:
                self.chk_depth_deposition.setText("Depth depletion deposition")
                self.edit_request_note.setPlaceholderText("요청사항 / ion transmission, shadowing 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            elif number == 6:
                self.chk_depth_deposition.setText("Depth depletion deposition")
                self.edit_request_note.setPlaceholderText("요청사항 / 반사 hit 기반 Gaussian+ballistic redepo 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            else:
                self.chk_depth_deposition.setText("Depth depletion deposition")
                self.edit_request_note.setPlaceholderText("요청사항 / etch 물리 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
        elif supports_depth_deposition or supports_inhibition:
            self.chk_sputter.setChecked(False)
            self.chk_ion_transmission.setChecked(False)
            self.chk_reflected_ion.setChecked(False)
            self.chk_redepo.setChecked(False)
            self.chk_lf_overhang.setChecked(False)
            self.chk_closure_redepo.setChecked(False)
            if changed:
                self.chk_depth_deposition.setChecked(supports_depth_deposition)
                self.chk_inhibition_deposition.setChecked(supports_inhibition)
                self.cmb_depth_feature_type.setCurrentIndex(0)
            if number == 5:
                self.chk_inhibition_deposition.setText("Inhibition deposition")
                self.lbl_inhibition_section.setText("Inhibition-weighted deposition")
                self.lbl_depth_parameter_help.setText(
                    "Inhibition model: 상부/노출부 성장 억제와 depth depletion을 각각 또는 동시에 켤 수 있습니다. 동시에 켜면 depth ratio와 inhibition growth ratio를 곱해 한 번만 성장시킵니다."
                )
                self.edit_request_note.setPlaceholderText("요청사항 / inhibition 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            else:
                self.chk_depth_deposition.setText("Depth depletion deposition")
                self.lbl_depth_depo_section.setText("Depth depletion deposition")
                self.lbl_depth_parameter_help.setText(
                    "Depth depletion: 깊이/등가 AR이 커질수록 deposition 양을 줄입니다."
                )
                self.edit_request_note.setPlaceholderText("요청사항 / depth fill 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
        else:
            self.chk_depth_deposition.setText("Depth depletion deposition")
            self.chk_sputter.setChecked(False)
            self.chk_ion_transmission.setChecked(False)
            self.chk_reflected_ion.setChecked(False)
            self.chk_redepo.setChecked(False)
            self.chk_lf_overhang.setChecked(False)
            self.chk_closure_redepo.setChecked(False)
            self.chk_depth_deposition.setChecked(False)
            self.chk_inhibition_deposition.setChecked(False)
            if number == 1:
                self.edit_request_note.setPlaceholderText("요청사항 / conformal depo 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            else:
                self.edit_request_note.setPlaceholderText("아직 물리 모델이 배정되지 않은 슬롯입니다. 기본 conformal depo로만 실행됩니다.")

        self._populate_emulator_default_presets()

        self.sync_depth_deposition_editor_from_spins()
        self.sync_inhibition_profile_from_spins()
        self._populate_split_parameters()
        self.sync_etch_control_availability()
        self._sync_field_overlay_toggles()
        self._sync_depth_advanced_visibility()
        self._emulator_mode_initialized = True
        if run:
            self._schedule_emulator_preview_run()

    def _schedule_emulator_preview_run(self) -> None:
        self.statusBar().showMessage("에뮬레이터 모드 변경됨", 1200)
        self._emulator_run_timer.start()

    def _run_deferred_emulator_preview(self) -> None:
        self.run_emulation(save_artifacts=False, use_preview_cache=True)

    def sync_sputter_curve_from_spins(self, _value: float = 0.0) -> None:
        if self._syncing_sputter_curve:
            return
        self._syncing_sputter_curve = True
        try:
            self.sputter_curve_editor.set_parameters(
                float(self.spin_sputter_peak_pct.value()),
                float(self.spin_sputter_peak.value()),
                float(self.spin_sputter_width.value()),
            )
            self.sputter_curve_editor.set_etch_cap_a(float(self.spin_sputter_strength.value()))
        finally:
            self._syncing_sputter_curve = False

    def sync_sputter_curve_cap_from_spin(self, _value: float = 0.0) -> None:
        self.sputter_curve_editor.set_etch_cap_a(float(self.spin_sputter_strength.value()))

    def apply_sputter_curve_parameters(self, peak_pct: float, peak_deg: float, width_deg: float) -> None:
        if self._syncing_sputter_curve:
            return
        self._syncing_sputter_curve = True
        try:
            self.spin_sputter_peak_pct.setValue(float(peak_pct))
            self.spin_sputter_peak.setValue(float(peak_deg))
            self.spin_sputter_width.setValue(float(width_deg))
            self.sputter_curve_editor.set_parameters(
                float(self.spin_sputter_peak_pct.value()),
                float(self.spin_sputter_peak.value()),
                float(self.spin_sputter_width.value()),
            )
            self.sputter_curve_editor.set_etch_cap_a(float(self.spin_sputter_strength.value()))
        finally:
            self._syncing_sputter_curve = False

    def sync_ion_transmission_editor_from_spins(self, _value: float = 0.0) -> None:
        if self._syncing_ion_curve:
            return
        self._syncing_ion_curve = True
        try:
            self.ion_transmission_editor.set_parameters(
                float(self.spin_ion_start_depth.value()),
                float(self.spin_ion_end_depth.value()),
                float(self.spin_ion_decay_strength.value()),
                float(self.spin_ion_floor.value()),
                float(self.spin_ion_curve_power.value()),
            )
        finally:
            self._syncing_ion_curve = False

    def apply_ion_transmission_editor_parameters(
        self,
        start_depth_pct: float,
        end_depth_pct: float,
        decay_strength_pct: float,
        floor_pct: float,
        curve_power: float,
    ) -> None:
        if self._syncing_ion_curve:
            return
        self._syncing_ion_curve = True
        try:
            self.spin_ion_start_depth.setValue(float(start_depth_pct))
            self.spin_ion_end_depth.setValue(float(end_depth_pct))
            self.spin_ion_decay_strength.setValue(float(decay_strength_pct))
            self.spin_ion_floor.setValue(float(floor_pct))
            self.spin_ion_curve_power.setValue(float(curve_power))
            self.ion_transmission_editor.set_parameters(
                float(self.spin_ion_start_depth.value()),
                float(self.spin_ion_end_depth.value()),
                float(self.spin_ion_decay_strength.value()),
                float(self.spin_ion_floor.value()),
                float(self.spin_ion_curve_power.value()),
            )
        finally:
            self._syncing_ion_curve = False

    def sync_redepo_lobe_from_spins(self, _value: float = 0.0) -> None:
        if self._syncing_redepo_lobe:
            return
        self._syncing_redepo_lobe = True
        try:
            self.redepo_lobe_editor.set_parameters(
                float(self.spin_redepo_efficiency.value()),
                float(self.spin_redepo_emit_power.value()),
                float(self.spin_redepo_distance_power.value()),
            )
        finally:
            self._syncing_redepo_lobe = False

    def apply_redepo_lobe_parameters(self, efficiency_pct: float, emit_power: float, distance_power: float) -> None:
        if self._syncing_redepo_lobe:
            return
        self._syncing_redepo_lobe = True
        try:
            self.spin_redepo_efficiency.setValue(float(efficiency_pct))
            self.spin_redepo_emit_power.setValue(float(emit_power))
            self.spin_redepo_distance_power.setValue(float(distance_power))
            self.redepo_lobe_editor.set_parameters(
                float(self.spin_redepo_efficiency.value()),
                float(self.spin_redepo_emit_power.value()),
                float(self.spin_redepo_distance_power.value()),
            )
        finally:
            self._syncing_redepo_lobe = False

    def _current_depth_display_mode(self) -> str:
        if not hasattr(self, "cmb_depth_display_mode"):
            return "depo_rate"
        return _depth_deposition_display_mode(self.cmb_depth_display_mode.currentData())

    def _sync_depth_formula_label(self) -> None:
        if not hasattr(self, "lbl_depth_formula"):
            return
        mode = self._current_depth_display_mode()
        feature_type = str(self.cmb_depth_feature_type.currentData() or "hole")
        feature_length = float(self.spin_depth_feature_length.value())
        text = _depth_deposition_formula_text(
            display_mode=mode,
            base_rate_a_per_cycle=float(self.spin_angstrom_per_cycle.value()),
            attenuation_model="exponential",
            depth_decay_k=float(self.spin_depth_decay_k.value()),
            depth_decay_power=float(self.spin_depth_decay_power.value()),
            min_ratio_pct=float(self.spin_depth_min_ratio_pct.value()),
            feature_type=feature_type,
            feature_width_a=float(self.spin_depth_feature_width.value()),
            feature_length_a=None if feature_type != "line" or feature_length <= 0.0 else feature_length,
        )
        self.lbl_depth_formula.setText(text)
        if mode == "attenuation":
            self.lbl_depth_formula.setStyleSheet(
                "QLabel { color: #1e3a8a; background: #eff6ff; border: 1px solid #bfdbfe; "
                "border-radius: 4px; padding: 5px 6px; font-family: Menlo, Consolas, monospace; }"
            )
        else:
            self.lbl_depth_formula.setStyleSheet(
                "QLabel { color: #14532d; background: #f7fee7; border: 1px solid #bbf7d0; "
                "border-radius: 4px; padding: 5px 6px; font-family: Menlo, Consolas, monospace; }"
            )

    def sync_depth_deposition_editor_from_spins(self, _value: object = 0.0) -> None:
        if self._syncing_depth_curve:
            return
        self._syncing_depth_curve = True
        try:
            self.depth_deposition_editor.set_depo_rate_a_per_cycle(float(self.spin_angstrom_per_cycle.value()))
            self.depth_deposition_editor.set_display_mode(self._current_depth_display_mode())
            feature_type = str(self.cmb_depth_feature_type.currentData() or "hole")
            length_enabled = feature_type == "line"
            self.lbl_depth_feature_length.setEnabled(length_enabled)
            self.spin_depth_feature_length.setEnabled(length_enabled)
            depth_feature_length = float(self.spin_depth_feature_length.value())
            self.depth_deposition_editor.set_feature_geometry(
                feature_type,
                float(self.spin_depth_feature_width.value()),
                float(self.spin_depth_feature_depth.value()),
                None if (not length_enabled or depth_feature_length <= 0.0) else depth_feature_length,
            )
            self.depth_deposition_editor.set_parameters(
                float(self.spin_depth_decay_k.value()),
                float(self.spin_depth_decay_power.value()),
                float(self.spin_depth_min_ratio_pct.value()),
                float(self.spin_depth_closure_threshold.value()),
            )
            self._sync_depth_formula_label()
        finally:
            self._syncing_depth_curve = False

    def apply_depth_deposition_editor_parameters(
        self,
        decay_k: float,
        decay_power: float,
        min_ratio_pct: float,
        closure_threshold_a: float,
    ) -> None:
        if self._syncing_depth_curve:
            return
        self._syncing_depth_curve = True
        try:
            self.spin_depth_decay_k.setValue(float(decay_k))
            self.spin_depth_decay_power.setValue(float(decay_power))
            self.spin_depth_min_ratio_pct.setValue(float(min_ratio_pct))
            self.spin_depth_closure_threshold.setValue(float(closure_threshold_a))
            self.depth_deposition_editor.set_depo_rate_a_per_cycle(float(self.spin_angstrom_per_cycle.value()))
            self.depth_deposition_editor.set_display_mode(self._current_depth_display_mode())
            feature_type = str(self.cmb_depth_feature_type.currentData() or "hole")
            length_enabled = feature_type == "line"
            self.lbl_depth_feature_length.setEnabled(length_enabled)
            self.spin_depth_feature_length.setEnabled(length_enabled)
            depth_feature_length = float(self.spin_depth_feature_length.value())
            self.depth_deposition_editor.set_feature_geometry(
                feature_type,
                float(self.spin_depth_feature_width.value()),
                float(self.spin_depth_feature_depth.value()),
                None if (not length_enabled or depth_feature_length <= 0.0) else depth_feature_length,
            )
            self.depth_deposition_editor.set_parameters(
                float(self.spin_depth_decay_k.value()),
                float(self.spin_depth_decay_power.value()),
                float(self.spin_depth_min_ratio_pct.value()),
                float(self.spin_depth_closure_threshold.value()),
            )
            self._sync_depth_formula_label()
        finally:
            self._syncing_depth_curve = False

    def sync_inhibition_profile_from_spins(self, _value: object = 0.0) -> None:
        if self._syncing_inhibition_curve:
            return
        self._syncing_inhibition_curve = True
        try:
            self.inhibition_profile_editor.set_feature_depth(float(self.spin_depth_feature_depth.value()))
            self.inhibition_profile_editor.set_parameters(
                float(self.spin_inhibition_strength.value()),
                float(self.spin_inhibition_penetration.value()),
                float(self.spin_inhibition_decay_power.value()),
                float(self.spin_inhibition_min_growth.value()),
                float(self.spin_inhibition_bottom_boost.value()),
                float(self.spin_inhibition_recombination.value()),
            )
        finally:
            self._syncing_inhibition_curve = False

    def apply_inhibition_profile_parameters(
        self,
        strength_pct: float,
        penetration_depth_a: float,
        decay_power: float,
        min_growth_pct: float,
        bottom_boost_pct: float,
        recombination_pct: float,
    ) -> None:
        if self._syncing_inhibition_curve:
            return
        self._syncing_inhibition_curve = True
        try:
            self.spin_inhibition_strength.setValue(float(strength_pct))
            self.spin_inhibition_penetration.setValue(float(penetration_depth_a))
            self.spin_inhibition_decay_power.setValue(float(decay_power))
            self.spin_inhibition_min_growth.setValue(float(min_growth_pct))
            self.spin_inhibition_bottom_boost.setValue(float(bottom_boost_pct))
            self.spin_inhibition_recombination.setValue(float(recombination_pct))
            self.inhibition_profile_editor.set_feature_depth(float(self.spin_depth_feature_depth.value()))
            self.inhibition_profile_editor.set_parameters(
                float(self.spin_inhibition_strength.value()),
                float(self.spin_inhibition_penetration.value()),
                float(self.spin_inhibition_decay_power.value()),
                float(self.spin_inhibition_min_growth.value()),
                float(self.spin_inhibition_bottom_boost.value()),
                float(self.spin_inhibition_recombination.value()),
            )
        finally:
            self._syncing_inhibition_curve = False

    def sync_ion_shadow_slider_labels(self, _value: int = 0) -> None:
        self.lbl_ion_aperture_shadow_value.setText(f"{int(self.slider_ion_aperture_shadow.value())}%")
        self.lbl_ion_lateral_shadow_value.setText(f"{int(self.slider_ion_lateral_shadow.value())}%")
        self.lbl_ion_edge_shadow_value.setText(f"{int(self.slider_ion_edge_shadow.value())}%")

    def _depth_advanced_widgets(self) -> List[QWidget]:
        return [
            self.lbl_depth_closure_section,
            self.lbl_depth_closure_threshold,
            self.spin_depth_closure_threshold,
            self.lbl_depth_post_fill_hole,
            self.spin_depth_post_fill_hole_pct,
            self.lbl_depth_post_fill_line,
            self.spin_depth_post_fill_line_pct,
            self.lbl_depth_line_open_path,
            self.spin_depth_line_open_path,
            self.lbl_depth_residual_decay,
            self.spin_depth_residual_decay,
        ]

    def _sync_depth_advanced_visibility(self, _checked: bool = False) -> None:
        supports_depth = self._active_emulator_supports_depth_deposition()
        show_advanced = bool(
            supports_depth
            and self.chk_depth_deposition.isChecked()
            and self.btn_depth_advanced.isChecked()
        )
        for widget in self._depth_advanced_widgets():
            widget.setVisible(False)
        if not show_advanced:
            return
        feature_type = str(self.cmb_depth_feature_type.currentData() or "hole")
        active_fill_widgets = (
            (self.lbl_depth_post_fill_line, self.spin_depth_post_fill_line_pct)
            if feature_type == "line"
            else (self.lbl_depth_post_fill_hole, self.spin_depth_post_fill_hole_pct)
        )
        for widget in [
            self.lbl_depth_closure_section,
            self.lbl_depth_closure_threshold,
            self.spin_depth_closure_threshold,
            *active_fill_widgets,
        ]:
            widget.setVisible(True)

    def _sync_collapsible_section(
        self,
        *,
        section_header: QWidget,
        master_checkbox: QCheckBox,
        detail_widgets: Sequence[QWidget],
        supported: bool,
        checkbox_enabled: bool,
        expanded: bool,
        detail_enabled: bool,
    ) -> None:
        section_header.setVisible(bool(supported))
        section_header.setEnabled(bool(supported))
        master_checkbox.setVisible(bool(supported))
        master_checkbox.setEnabled(bool(supported and checkbox_enabled))
        show_detail = bool(supported and expanded)
        for widget in detail_widgets:
            widget.setVisible(show_detail)
            widget.setEnabled(bool(detail_enabled))

    def sync_etch_control_availability(self, _checked: bool = False) -> None:
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion_transmission = self._active_emulator_supports_ion_transmission()
        supports_reflected_ion = self._active_emulator_supports_reflected_ion()
        supports_redeposition = self._active_emulator_supports_redeposition()
        supports_depth_deposition = self._active_emulator_supports_depth_deposition()
        supports_inhibition = self._active_emulator_supports_inhibition()
        supports_lf_overhang = self._active_emulator_supports_lf_overhang()
        supports_closure_redepo = self._active_emulator_supports_closure_redepo()
        etch_enabled = bool(supports_sputter and self.chk_sputter.isChecked())

        direct_sputter_detail_widgets = [
            self.lbl_sputter_section,
            self.lbl_sputter_strength,
            self.spin_sputter_strength,
            self.lbl_sputter_peak_pct,
            self.spin_sputter_peak_pct,
            self.lbl_sputter_peak,
            self.spin_sputter_peak,
            self.lbl_sputter_width,
            self.spin_sputter_width,
            self.lbl_sputter_smoothing,
            self.spin_sputter_smoothing,
            self.gaussian_group,
        ]
        for widget in direct_sputter_detail_widgets:
            widget.setEnabled(etch_enabled)
        self._sync_collapsible_section(
            section_header=self.lbl_etch_section,
            master_checkbox=self.chk_sputter,
            detail_widgets=direct_sputter_detail_widgets,
            supported=supports_sputter,
            checkbox_enabled=True,
            expanded=etch_enabled,
            detail_enabled=etch_enabled,
        )

        self.chk_ion_transmission.setEnabled(etch_enabled and supports_ion_transmission)
        ion_enabled = bool(
            etch_enabled
            and supports_ion_transmission
            and self.chk_ion_transmission.isChecked()
        )
        ion_detail_widgets = [
            self.lbl_ion_depth_section,
            self.lbl_ion_start_depth,
            self.spin_ion_start_depth,
            self.lbl_ion_end_depth,
            self.spin_ion_end_depth,
            self.lbl_ion_decay_strength,
            self.spin_ion_decay_strength,
            self.lbl_ion_floor,
            self.spin_ion_floor,
            self.lbl_ion_curve_power,
            self.spin_ion_curve_power,
            self.lbl_ion_geometry_section,
            self.lbl_ion_aperture_shadow,
            self.ion_aperture_shadow_row,
            self.lbl_ion_lateral_shadow,
            self.ion_lateral_shadow_row,
            self.lbl_ion_edge_shadow,
            self.ion_edge_shadow_row,
            self.ion_map_group,
        ]
        for widget in ion_detail_widgets:
            widget.setEnabled(ion_enabled)
        self._sync_collapsible_section(
            section_header=self.lbl_ion_depth_section,
            master_checkbox=self.chk_ion_transmission,
            detail_widgets=[widget for widget in ion_detail_widgets if widget is not self.lbl_ion_depth_section],
            supported=supports_ion_transmission,
            checkbox_enabled=etch_enabled,
            expanded=ion_enabled,
            detail_enabled=ion_enabled,
        )

        self.chk_reflected_ion.setEnabled(etch_enabled and supports_reflected_ion)
        reflected_enabled = bool(
            etch_enabled
            and supports_reflected_ion
            and self.chk_reflected_ion.isChecked()
        )
        for widget in [
            self.lbl_reflected_section,
            self.lbl_reflected_strength,
            self.spin_reflected_strength,
            self.lbl_reflected_bowing,
            self.spin_reflected_bowing,
            self.lbl_reflected_microtrench,
            self.spin_reflected_microtrench,
            self.lbl_reflected_range,
            self.spin_reflected_range,
        ]:
            widget.setEnabled(reflected_enabled)
        self._sync_collapsible_section(
            section_header=self.lbl_reflected_section,
            master_checkbox=self.chk_reflected_ion,
            detail_widgets=[
                self.lbl_reflected_strength,
                self.spin_reflected_strength,
                self.lbl_reflected_bowing,
                self.spin_reflected_bowing,
                self.lbl_reflected_microtrench,
                self.spin_reflected_microtrench,
                self.lbl_reflected_range,
                self.spin_reflected_range,
            ],
            supported=supports_reflected_ion,
            checkbox_enabled=etch_enabled,
            expanded=reflected_enabled,
            detail_enabled=reflected_enabled,
        )

        self.chk_redepo.setEnabled(etch_enabled and supports_redeposition)
        redepo_enabled = bool(
            etch_enabled
            and supports_redeposition
            and self.chk_redepo.isChecked()
        )
        redepo_source_widgets = [
            self.lbl_redepo_efficiency,
            self.spin_redepo_efficiency,
            self.lbl_redepo_emit_power,
            self.spin_redepo_emit_power,
            self.lbl_redepo_distance_power,
            self.spin_redepo_distance_power,
        ]
        redepo_visual_widgets = [
            self.redepo_lobe_group,
        ]
        redepo_advanced_widgets = [
            self.lbl_redepo_source,
            self.cmb_redepo_source_model,
            self.lbl_redepo_soft_los,
            self.spin_redepo_soft_los,
        ]
        for widget in [*redepo_source_widgets, *redepo_visual_widgets, *redepo_advanced_widgets]:
            widget.setEnabled(redepo_enabled)
        if self.active_emulator_number() in (0, 6):
            redepo_detail_widgets = [*redepo_source_widgets, *redepo_visual_widgets]
        else:
            redepo_detail_widgets = [*redepo_source_widgets, *redepo_visual_widgets, *redepo_advanced_widgets]
        self._sync_collapsible_section(
            section_header=self.lbl_redepo_section,
            master_checkbox=self.chk_redepo,
            detail_widgets=redepo_detail_widgets,
            supported=supports_redeposition,
            checkbox_enabled=etch_enabled,
            expanded=redepo_enabled,
            detail_enabled=redepo_enabled,
        )
        if self.active_emulator_number() in (0, 6):
            for widget in redepo_advanced_widgets:
                widget.setVisible(False)

        self.chk_lf_overhang.setEnabled(etch_enabled and supports_lf_overhang)
        lf_overhang_enabled = bool(
            etch_enabled
            and supports_lf_overhang
            and self.chk_lf_overhang.isChecked()
        )
        self._sync_collapsible_section(
            section_header=self.lbl_lf_overhang_section,
            master_checkbox=self.chk_lf_overhang,
            detail_widgets=[
                self.lbl_lf_overhang_dose,
                self.spin_lf_overhang_dose,
                self.lbl_lf_overhang_sputter_gain,
                self.spin_lf_overhang_sputter_gain,
                self.lbl_lf_overhang_redepo_fraction,
                self.spin_lf_overhang_redepo_fraction,
                self.lbl_lf_overhang_survival,
                self.spin_lf_overhang_survival,
                self.lbl_lf_overhang_width,
                self.spin_lf_overhang_width,
            ],
            supported=supports_lf_overhang,
            checkbox_enabled=etch_enabled,
            expanded=lf_overhang_enabled,
            detail_enabled=lf_overhang_enabled,
        )

        self.chk_closure_redepo.setEnabled(etch_enabled and supports_closure_redepo)
        closure_redepo_enabled = bool(
            etch_enabled
            and supports_closure_redepo
            and self.chk_closure_redepo.isChecked()
        )
        self._sync_collapsible_section(
            section_header=self.lbl_closure_redepo_section,
            master_checkbox=self.chk_closure_redepo,
            detail_widgets=[
                self.lbl_closure_redepo_efficiency,
                self.spin_closure_redepo_efficiency,
                self.lbl_closure_redepo_shadow_gain,
                self.spin_closure_redepo_shadow_gain,
                self.lbl_closure_redepo_width,
                self.spin_closure_redepo_width,
                self.lbl_closure_redepo_survival,
                self.spin_closure_redepo_survival,
                self.lbl_closure_redepo_smoothing,
                self.spin_closure_redepo_smoothing,
            ],
            supported=supports_closure_redepo,
            checkbox_enabled=etch_enabled,
            expanded=closure_redepo_enabled,
            detail_enabled=closure_redepo_enabled,
        )

        self.chk_depth_deposition.setEnabled(supports_depth_deposition)
        depth_enabled = bool(supports_depth_deposition and self.chk_depth_deposition.isChecked())
        depth_detail_widgets = [
            self.lbl_depth_feature_section,
            self.lbl_depth_feature_type,
            self.cmb_depth_feature_type,
            self.lbl_depth_feature_width,
            self.spin_depth_feature_width,
            self.lbl_depth_feature_depth,
            self.spin_depth_feature_depth,
            self.lbl_depth_feature_length,
            self.spin_depth_feature_length,
            self.lbl_depth_curve_section,
            self.lbl_depth_decay_k,
            self.spin_depth_decay_k,
            self.lbl_depth_decay_power,
            self.spin_depth_decay_power,
            self.lbl_depth_min_ratio,
            self.spin_depth_min_ratio_pct,
            self.btn_depth_advanced,
            self.lbl_depth_closure_section,
            self.lbl_depth_closure_threshold,
            self.spin_depth_closure_threshold,
            self.lbl_depth_post_fill_hole,
            self.spin_depth_post_fill_hole_pct,
            self.lbl_depth_post_fill_line,
            self.spin_depth_post_fill_line_pct,
            self.lbl_depth_line_open_path,
            self.spin_depth_line_open_path,
            self.lbl_depth_residual_decay,
            self.spin_depth_residual_decay,
            self.depth_profile_group,
            self.lbl_depth_parameter_help,
            self.lbl_depth_display_mode,
            self.cmb_depth_display_mode,
            self.lbl_depth_formula,
            self.depth_deposition_editor,
        ]
        for widget in depth_detail_widgets:
            widget.setEnabled(depth_enabled)
        self._sync_collapsible_section(
            section_header=self.lbl_depth_depo_section,
            master_checkbox=self.chk_depth_deposition,
            detail_widgets=depth_detail_widgets,
            supported=supports_depth_deposition,
            checkbox_enabled=True,
            expanded=depth_enabled,
            detail_enabled=depth_enabled,
        )
        length_enabled = bool(
            depth_enabled and str(self.cmb_depth_feature_type.currentData() or "hole") == "line"
        )
        self.lbl_depth_feature_length.setVisible(length_enabled)
        self.spin_depth_feature_length.setVisible(length_enabled)
        self.lbl_depth_feature_length.setEnabled(length_enabled)
        self.spin_depth_feature_length.setEnabled(length_enabled)
        self._sync_depth_advanced_visibility()

        self.chk_inhibition_deposition.setEnabled(supports_inhibition)
        inhibition_enabled = bool(supports_inhibition and self.chk_inhibition_deposition.isChecked())
        inhibition_detail_widgets = [
            self.lbl_inhibition_strength,
            self.spin_inhibition_strength,
            self.lbl_inhibition_penetration,
            self.spin_inhibition_penetration,
            self.lbl_inhibition_decay_power,
            self.spin_inhibition_decay_power,
            self.lbl_inhibition_min_growth,
            self.spin_inhibition_min_growth,
            self.lbl_inhibition_bottom_boost,
            self.spin_inhibition_bottom_boost,
            self.lbl_inhibition_recombination,
            self.spin_inhibition_recombination,
            self.lbl_inhibition_smoothing,
            self.spin_inhibition_smoothing,
            self.inhibition_profile_group,
            self.inhibition_profile_editor,
        ]
        for widget in inhibition_detail_widgets:
            widget.setEnabled(inhibition_enabled)
        self._sync_collapsible_section(
            section_header=self.lbl_inhibition_section,
            master_checkbox=self.chk_inhibition_deposition,
            detail_widgets=inhibition_detail_widgets,
            supported=supports_inhibition,
            checkbox_enabled=True,
            expanded=inhibition_enabled,
            detail_enabled=inhibition_enabled,
        )
        feature_geometry_visible = bool((supports_depth_deposition or supports_inhibition) and (depth_enabled or inhibition_enabled))
        feature_geometry_widgets = [
            self.lbl_depth_feature_section,
            self.lbl_depth_feature_type,
            self.cmb_depth_feature_type,
            self.lbl_depth_feature_width,
            self.spin_depth_feature_width,
            self.lbl_depth_feature_depth,
            self.spin_depth_feature_depth,
        ]
        for widget in feature_geometry_widgets:
            widget.setVisible(feature_geometry_visible)
            widget.setEnabled(feature_geometry_visible)
        line_geometry_visible = bool(
            feature_geometry_visible and str(self.cmb_depth_feature_type.currentData() or "hole") == "line"
        )
        self.lbl_depth_feature_length.setVisible(line_geometry_visible)
        self.spin_depth_feature_length.setVisible(line_geometry_visible)
        self.lbl_depth_feature_length.setEnabled(line_geometry_visible)
        self.spin_depth_feature_length.setEnabled(line_geometry_visible)

    def reset_defaults(self) -> None:
        self._clear_continuation_context()
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion_transmission = self._active_emulator_supports_ion_transmission()
        supports_reflected_ion = self._active_emulator_supports_reflected_ion()
        supports_redeposition = self._active_emulator_supports_redeposition()
        supports_depth_deposition = self._active_emulator_supports_depth_deposition()
        supports_inhibition = self._active_emulator_supports_inhibition()
        supports_lf_overhang = self._active_emulator_supports_lf_overhang()
        supports_closure_redepo = self._active_emulator_supports_closure_redepo()
        self.spin_cycles.setValue(20)
        self.spin_angstrom_per_cycle.setValue(10.0)
        self._set_quality_mode_for_ds(DEFAULT_UI_REPARAM_DS_A)
        self.chk_sputter.setChecked(supports_sputter)
        self.chk_ion_transmission.setChecked(supports_ion_transmission)
        self.chk_reflected_ion.setChecked(supports_reflected_ion)
        self.chk_redepo.setChecked(supports_redeposition)
        self.chk_depth_deposition.setChecked(supports_depth_deposition)
        self.chk_inhibition_deposition.setChecked(supports_inhibition and self.active_emulator_number() == 5)
        self.chk_lf_overhang.setChecked(supports_lf_overhang)
        self.chk_closure_redepo.setChecked(supports_closure_redepo)
        self.spin_ion_start_depth.setValue(0.0)
        self.spin_ion_end_depth.setValue(100.0)
        self.spin_ion_decay_strength.setValue(100.0)
        self.spin_ion_floor.setValue(0.0)
        self.spin_ion_curve_power.setValue(1.0)
        self.slider_ion_aperture_shadow.setValue(100)
        self.slider_ion_lateral_shadow.setValue(100)
        self.slider_ion_edge_shadow.setValue(100)
        self.sync_ion_shadow_slider_labels()
        self.spin_reflected_strength.setValue(35.0)
        self.spin_reflected_bowing.setValue(0.75)
        self.spin_reflected_microtrench.setValue(1.0)
        self.spin_reflected_range.setValue(1600.0)
        self.cmb_redepo_source_model.setCurrentIndex(0)
        if self.active_emulator_number() in (0, 6):
            self.spin_redepo_efficiency.setValue(30.0)
            self.spin_redepo_emit_power.setValue(22.0)
            self.spin_redepo_distance_power.setValue(25.0)
        else:
            self.spin_redepo_efficiency.setValue(25.0)
            self.spin_redepo_emit_power.setValue(1.0)
            self.spin_redepo_distance_power.setValue(1.0)
        self.spin_redepo_soft_los.setValue(0)
        self.spin_lf_overhang_dose.setValue(1.0)
        self.spin_lf_overhang_sputter_gain.setValue(1.0)
        self.spin_lf_overhang_redepo_fraction.setValue(30.0)
        self.spin_lf_overhang_survival.setValue(0.75)
        self.spin_lf_overhang_width.setValue(180.0)
        self.spin_closure_redepo_efficiency.setValue(35.0)
        self.spin_closure_redepo_shadow_gain.setValue(2.0)
        self.spin_closure_redepo_width.setValue(160.0)
        self.spin_closure_redepo_survival.setValue(0.85)
        self.spin_closure_redepo_smoothing.setValue(160.0)
        self.cmb_depth_feature_type.setCurrentIndex(0)
        self.spin_depth_feature_width.setValue(240.0)
        self.spin_depth_feature_depth.setValue(4700.0)
        self.spin_depth_feature_length.setValue(0.0)
        if self.active_emulator_number() == 0:
            self.spin_depth_decay_k.setValue(0.55)
            self.spin_depth_decay_power.setValue(1.2)
            self.spin_depth_min_ratio_pct.setValue(8.0)
        elif self.active_emulator_number() == 5:
            self.spin_depth_decay_k.setValue(0.35)
            self.spin_depth_decay_power.setValue(1.2)
            self.spin_depth_min_ratio_pct.setValue(8.0)
        else:
            self.spin_depth_decay_k.setValue(0.8)
            self.spin_depth_decay_power.setValue(1.2)
            self.spin_depth_min_ratio_pct.setValue(3.0)
        self.spin_depth_closure_threshold.setValue(8.0)
        self.spin_depth_post_fill_hole_pct.setValue(3.0)
        self.spin_depth_post_fill_line_pct.setValue(20.0)
        self.spin_depth_line_open_path.setValue(1.0)
        self.spin_depth_residual_decay.setValue(1175.0)
        self.spin_inhibition_strength.setValue(85.0)
        self.spin_inhibition_penetration.setValue(1100.0)
        self.spin_inhibition_decay_power.setValue(1.2)
        self.spin_inhibition_min_growth.setValue(8.0)
        self.spin_inhibition_bottom_boost.setValue(20.0)
        self.spin_inhibition_recombination.setValue(35.0)
        self.spin_inhibition_smoothing.setValue(45.0)
        self.spin_sputter_strength.setValue(4.0)
        self.spin_sputter_peak_pct.setValue(100.0)
        self.spin_sputter_peak.setValue(55.0)
        self.spin_sputter_width.setValue(14.0)
        self.spin_sputter_smoothing.setValue(40.0)
        self._populate_split_parameters()
        self.sync_inhibition_profile_from_spins()
        self.sync_etch_control_availability()
        if self.active_emulator_number() == 0:
            self.edit_request_note.setPlainText("통합모델: conformal + direct/ion etch + normal/specular lobe redepo + depth/inhibition deposition. reflected/LF/closure 제외")
        elif self.active_emulator_number() == 5:
            self.edit_request_note.setPlainText("PECVD/PEALD inhibition-weighted deposition: top/opening growth suppression with smooth trench fill")
        elif self.active_emulator_number() == 4:
            self.edit_request_note.setPlainText("길쭉한 항아리형 구조에서 depth-dependent depo와 closure 후 잔류 fill 검증")
        elif self.active_emulator_number() == 3:
            self.edit_request_note.setPlainText("direct sputter 출력에 ion transmission / geometric shadowing 결합 검증")
        elif self.active_emulator_number() == 2:
            self.edit_request_note.setPlainText("각도기반 direct sputter etch 검증")
        elif self.active_emulator_number() == 6:
            self.edit_request_note.setPlainText("입사 ion의 정반사 hit 지점을 기준으로 Gaussian 분포를 만들고 ballistic hit map으로 보정하는 리데포 검증")
        elif self.active_emulator_number() == 1:
            self.edit_request_note.setPlainText("라운드 conformal offset 기반 트렌치 증착")
        else:
            self.edit_request_note.setPlainText("미배정 슬롯: 기본 conformal deposition만 실행")
        self._reset_geometry_to_default()
        self.run_emulation(save_artifacts=False)

    def apply_split_parameter_defaults(self, _index: int = 0) -> None:
        parameter = str(self.cmb_split_parameter.currentData())
        if parameter == "cycles":
            values = (5.0, 30.0, 5.0, 0, 0.0, 10000.0)
        elif parameter == "angstrom_per_cycle":
            values = (0.0, 20.0, 5.0, 3, 0.0, 10000.0)
        elif parameter == "sputter_peak_pct":
            values = (40.0, 100.0, 20.0, 1, 0.0, 100.0)
        elif parameter == "sputter_peak_angle_deg":
            values = (35.0, 75.0, 10.0, 1, 0.0, 89.9)
        elif parameter == "sputter_width_deg":
            values = (6.0, 24.0, 6.0, 1, 1.0, 60.0)
        elif parameter == "ion_transmission_start_depth_pct":
            values = (0.0, 60.0, 20.0, 1, 0.0, 100.0)
        elif parameter == "ion_transmission_end_depth_pct":
            values = (40.0, 100.0, 20.0, 1, 0.0, 100.0)
        elif parameter == "ion_transmission_decay_strength_pct":
            values = (0.0, 100.0, 25.0, 1, 0.0, 100.0)
        elif parameter == "ion_transmission_floor_pct":
            values = (0.0, 40.0, 10.0, 1, 0.0, 100.0)
        elif parameter == "ion_transmission_curve_power":
            values = (0.5, 2.0, 0.5, 2, 0.2, 6.0)
        elif parameter in {
            "ion_transmission_aperture_shadow_pct",
            "ion_transmission_lateral_shadow_pct",
            "ion_transmission_edge_shadow_pct",
        }:
            values = (0.0, 100.0, 25.0, 1, 0.0, 100.0)
        elif parameter == "reflected_ion_strength_pct":
            values = (0.0, 60.0, 20.0, 1, 0.0, 100.0)
        elif parameter == "reflected_ion_bowing_weight":
            values = (0.0, 1.2, 0.4, 2, 0.0, 2.0)
        elif parameter == "reflected_ion_microtrench_weight":
            values = (0.0, 1.5, 0.5, 2, 0.0, 2.0)
        elif parameter == "reflected_ion_range_a":
            values = (600.0, 2400.0, 600.0, 0, 50.0, 10000.0)
        elif parameter == "redepo_efficiency_pct":
            values = (0.0, 50.0, 10.0, 1, 0.0, 100.0)
        elif parameter == "redepo_emit_power" and self.active_emulator_number() in (0, 6):
            values = (8.0, 40.0, 8.0, 1, 1.0, 80.0)
        elif parameter == "redepo_distance_power" and self.active_emulator_number() in (0, 6):
            values = (-60.0, 60.0, 30.0, 1, -100.0, 100.0)
        elif parameter in {"redepo_emit_power", "redepo_distance_power"}:
            values = (0.5, 2.0, 0.5, 2, 0.0, 8.0)
        elif parameter == "redepo_soft_los_radius_points":
            values = (0.0, 2.0, 1.0, 0, 0.0, 2.0)
        elif parameter == "lf_overhang_dose":
            values = (0.0, 2.0, 0.5, 2, 0.0, 10.0)
        elif parameter == "lf_overhang_sputter_gain":
            values = (0.5, 2.0, 0.5, 2, 0.0, 10.0)
        elif parameter == "lf_overhang_redepo_fraction_pct":
            values = (0.0, 60.0, 15.0, 1, 0.0, 100.0)
        elif parameter == "lf_overhang_survival_penalty":
            values = (0.0, 1.5, 0.3, 2, 0.0, 4.0)
        elif parameter == "lf_overhang_width_a":
            values = (80.0, 320.0, 80.0, 0, 1.0, 5000.0)
        elif parameter == "closure_redepo_efficiency_pct":
            values = (0.0, 60.0, 15.0, 1, 0.0, 100.0)
        elif parameter == "closure_redepo_shadow_gain":
            values = (0.0, 4.0, 1.0, 2, 0.0, 20.0)
        elif parameter == "closure_redepo_width_a":
            values = (80.0, 320.0, 80.0, 0, 1.0, 5000.0)
        elif parameter == "closure_redepo_survival_penalty":
            values = (0.0, 1.5, 0.3, 2, 0.0, 4.0)
        elif parameter == "closure_redepo_smoothing_a":
            values = (0.0, 320.0, 80.0, 0, 0.0, 5000.0)
        elif parameter == "deposition_depth_decay_k":
            values = (0.2, 1.4, 0.3, 2, 0.0, 20.0)
        elif parameter == "deposition_depth_decay_power":
            values = (0.8, 2.0, 0.4, 2, 0.05, 8.0)
        elif parameter in {
            "deposition_min_ratio",
            "deposition_post_closure_fill_pct_hole",
            "deposition_post_closure_fill_pct_line",
            "deposition_line_open_path_factor",
        }:
            values = (0.0, 1.0, 0.25, 2, 0.0, 1.0)
        elif parameter == "deposition_closure_threshold_a":
            values = (0.0, 24.0, 6.0, 1, 0.0, 10000.0)
        elif parameter == "deposition_residual_fill_decay_length_a":
            values = (400.0, 2200.0, 600.0, 0, 1.0, 200000.0)
        elif parameter == "inhibition_strength_pct":
            values = (50.0, 95.0, 15.0, 1, 0.0, 100.0)
        elif parameter == "inhibition_penetration_depth_a":
            values = (400.0, 1800.0, 350.0, 0, 1.0, 200000.0)
        elif parameter == "inhibition_decay_power":
            values = (0.8, 2.0, 0.4, 2, 0.05, 8.0)
        elif parameter == "inhibition_min_growth_ratio":
            values = (0.02, 0.20, 0.06, 2, 0.0, 1.0)
        elif parameter == "inhibition_bottom_boost_pct":
            values = (0.0, 40.0, 10.0, 1, 0.0, 100.0)
        elif parameter == "inhibition_peald_recombination_pct":
            values = (0.0, 60.0, 15.0, 1, 0.0, 100.0)
        elif parameter == "inhibition_smoothing_a":
            values = (0.0, 90.0, 30.0, 1, 0.0, 1000.0)
        else:
            values = (0.0, 16.0, 4.0, 3, 0.0, 100.0)

        start, end, step, decimals, minimum, maximum = values
        for spin in (self.spin_split_start, self.spin_split_end):
            spin.setDecimals(int(decimals))
            spin.setRange(float(minimum), float(maximum))
            spin.setSingleStep(max(float(step), 1.0))
        self.spin_split_step.setDecimals(int(decimals))
        self.spin_split_step.setRange(0.001 if int(decimals) > 0 else 1.0, float(maximum))
        self.spin_split_step.setSingleStep(max(float(step), 1.0))
        self.spin_split_start.setValue(float(start))
        self.spin_split_end.setValue(float(end))
        self.spin_split_step.setValue(float(step))

    def current_config(self) -> TrenchDepoConfig:
        active_emulator = self.active_emulator_number()
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion_transmission = self._active_emulator_supports_ion_transmission()
        supports_reflected_ion = self._active_emulator_supports_reflected_ion()
        supports_redeposition = self._active_emulator_supports_redeposition()
        supports_depth_deposition = self._active_emulator_supports_depth_deposition()
        supports_inhibition = self._active_emulator_supports_inhibition()
        supports_lf_overhang = self._active_emulator_supports_lf_overhang()
        supports_closure_redepo = self._active_emulator_supports_closure_redepo()
        etch_enabled = bool(supports_sputter and self.chk_sputter.isChecked())
        depth_feature_type = str(self.cmb_depth_feature_type.currentData() or "hole")
        depth_feature_length = float(self.spin_depth_feature_length.value())
        return TrenchDepoConfig(
            points=self._current_geometry_points(),
            cycles=int(self.spin_cycles.value()),
            emulator_number=int(active_emulator),
            angstrom_per_cycle=float(self.spin_angstrom_per_cycle.value()),
            reparam_ds_a=float(self.spin_reparam_ds.value()),
            sputter_enabled=etch_enabled,
            sputter_strength_a_per_cycle=(
                float(self.spin_sputter_strength.value()) if supports_sputter else 0.0
            ),
            sputter_peak_pct=float(self.spin_sputter_peak_pct.value()),
            sputter_peak_angle_deg=float(self.spin_sputter_peak.value()),
            sputter_width_deg=float(self.spin_sputter_width.value()),
            sputter_smoothing_a=float(self.spin_sputter_smoothing.value()),
            ion_transmission_enabled=bool(
                etch_enabled and supports_ion_transmission and self.chk_ion_transmission.isChecked()
            ),
            ion_transmission_start_depth_pct=(
                float(self.spin_ion_start_depth.value()) if supports_ion_transmission else 0.0
            ),
            ion_transmission_end_depth_pct=(
                float(self.spin_ion_end_depth.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_decay_strength_pct=(
                float(self.spin_ion_decay_strength.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_floor_pct=(
                float(self.spin_ion_floor.value()) if supports_ion_transmission else 0.0
            ),
            ion_transmission_curve_power=(
                float(self.spin_ion_curve_power.value()) if supports_ion_transmission else 1.0
            ),
            ion_transmission_aperture_shadow_pct=(
                float(self.slider_ion_aperture_shadow.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_lateral_shadow_pct=(
                float(self.slider_ion_lateral_shadow.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_edge_shadow_pct=(
                float(self.slider_ion_edge_shadow.value()) if supports_ion_transmission else 100.0
            ),
            reflected_ion_enabled=bool(
                etch_enabled and supports_reflected_ion and self.chk_reflected_ion.isChecked()
            ),
            reflected_ion_strength_pct=(
                float(self.spin_reflected_strength.value()) if supports_reflected_ion else 0.0
            ),
            reflected_ion_bowing_weight=float(self.spin_reflected_bowing.value()),
            reflected_ion_microtrench_weight=float(self.spin_reflected_microtrench.value()),
            reflected_ion_range_a=float(self.spin_reflected_range.value()),
            redepo_enabled=bool(
                etch_enabled and supports_redeposition and self.chk_redepo.isChecked()
            ),
            redepo_source_model=str(self.cmb_redepo_source_model.currentData() or "model2"),
            redepo_efficiency_pct=(
                float(self.spin_redepo_efficiency.value()) if supports_redeposition else 0.0
            ),
            redepo_emit_power=float(self.spin_redepo_emit_power.value()),
            redepo_distance_power=float(self.spin_redepo_distance_power.value()),
            redepo_soft_los_radius_points=int(self.spin_redepo_soft_los.value()),
            redepo_transport_model=TrenchDepoConfig().redepo_transport_model,
            lf_overhang_enabled=bool(
                etch_enabled and supports_lf_overhang and self.chk_lf_overhang.isChecked()
            ),
            lf_overhang_dose=float(self.spin_lf_overhang_dose.value()),
            lf_overhang_sputter_gain=float(self.spin_lf_overhang_sputter_gain.value()),
            lf_overhang_redepo_fraction_pct=float(self.spin_lf_overhang_redepo_fraction.value()),
            lf_overhang_survival_penalty=float(self.spin_lf_overhang_survival.value()),
            lf_overhang_width_a=float(self.spin_lf_overhang_width.value()),
            closure_redepo_enabled=bool(
                etch_enabled and supports_closure_redepo and self.chk_closure_redepo.isChecked()
            ),
            closure_redepo_efficiency_pct=float(self.spin_closure_redepo_efficiency.value()),
            closure_redepo_shadow_gain=float(self.spin_closure_redepo_shadow_gain.value()),
            closure_redepo_width_a=float(self.spin_closure_redepo_width.value()),
            closure_redepo_survival_penalty=float(self.spin_closure_redepo_survival.value()),
            closure_redepo_smoothing_a=float(self.spin_closure_redepo_smoothing.value()),
            deposition_depth_enabled=bool(
                supports_depth_deposition and self.chk_depth_deposition.isChecked()
            ),
            deposition_feature_type=depth_feature_type,
            deposition_feature_width_a=float(self.spin_depth_feature_width.value()),
            deposition_feature_depth_a=float(self.spin_depth_feature_depth.value()),
            deposition_feature_length_a=(
                None if depth_feature_type != "line" or depth_feature_length <= 0.0 else depth_feature_length
            ),
            deposition_attenuation_model="exponential",
            deposition_depth_decay_k=float(self.spin_depth_decay_k.value()),
            deposition_depth_decay_power=float(self.spin_depth_decay_power.value()),
            deposition_min_ratio=float(self.spin_depth_min_ratio_pct.value()) / 100.0,
            deposition_use_equivalent_ar=True,
            deposition_closure_threshold_a=float(self.spin_depth_closure_threshold.value()),
            deposition_post_closure_fill_pct_hole=float(self.spin_depth_post_fill_hole_pct.value()) / 100.0,
            deposition_post_closure_fill_pct_line=float(self.spin_depth_post_fill_line_pct.value()) / 100.0,
            deposition_line_open_path_factor=float(self.spin_depth_line_open_path.value()),
            deposition_residual_fill_decay_length_a=float(self.spin_depth_residual_decay.value()),
            deposition_residual_fill_distribution="exponential_from_closure",
            deposition_conserve_volume=True,
            inhibition_enabled=bool(
                supports_inhibition and self.chk_inhibition_deposition.isChecked()
            ),
            inhibition_process_model="hybrid",
            inhibition_strength_pct=float(self.spin_inhibition_strength.value()),
            inhibition_penetration_depth_a=float(self.spin_inhibition_penetration.value()),
            inhibition_decay_power=float(self.spin_inhibition_decay_power.value()),
            inhibition_min_growth_ratio=float(self.spin_inhibition_min_growth.value()) / 100.0,
            inhibition_bottom_boost_pct=float(self.spin_inhibition_bottom_boost.value()),
            inhibition_peald_recombination_pct=float(self.spin_inhibition_recombination.value()),
            inhibition_smoothing_a=float(self.spin_inhibition_smoothing.value()),
        )

    @staticmethod
    def _fmt_a(value: float) -> str:
        return f"{float(value):.3f} A"

    @staticmethod
    def _fmt_pct(value: float) -> str:
        return f"{float(value):.1f}%"

    @staticmethod
    def _on_off(enabled: bool) -> str:
        return "ON" if bool(enabled) else "OFF"

    def _format_result_parameters(
        self,
        config: TrenchDepoConfig,
        result: Optional[TrenchDepoResult],
    ) -> str:
        meta = dict(result.meta) if result is not None else {}
        number = self.active_emulator_number()
        title = EMULATOR_MODE_TITLES.get(number, "Custom emulator")
        geometry_source = self._current_geometry_source_name()
        frames = len(result.frame_profiles) if result is not None else 0
        final_points = len(result.final_profile) if result is not None else 0
        stage_index = int(meta.get("stage_index", 1) or 1)
        stage_cycles = int(meta.get("stage_cycles", config.cycles) or config.cycles)

        lines = [
            f"에뮬레이터: {title}",
            f"상태: {'실행 결과' if result is not None else '입력 미리보기'}",
            f"구조 입력: {geometry_source} | {len(config.points)}점",
            "",
            "[기본 공정]",
            f"차수: {stage_index}차" if result is not None and stage_index > 1 else "차수: 1차",
            f"현재 stage cycles: {stage_cycles}",
            f"표시 누적 cycles: {int(meta.get('cycles', config.cycles) or config.cycles) if result is not None else int(config.cycles)}",
            f"Depo: {float(config.angstrom_per_cycle):.3f} A/CYC",
            f"Reparam ds: {float(config.reparam_ds_a):.3f} A",
        ]

        lines.extend(
            [
                "",
                "[Etch / Sputter]",
                f"Direct sputter: {self._on_off(config.sputter_enabled)}",
            ]
        )
        if config.sputter_enabled:
            lines.extend(
                [
                    f"Etch: {float(config.sputter_strength_a_per_cycle):.3f} A/CYC",
                    f"Peak: {float(config.sputter_peak_pct):.1f}% @ {float(config.sputter_peak_angle_deg):.1f} deg",
                    f"Width: {float(config.sputter_width_deg):.1f} deg",
                    f"Smoothing: {self._fmt_a(config.sputter_smoothing_a)}",
                ]
            )

        lines.append(f"Ion transmission: {self._on_off(config.ion_transmission_enabled)}")
        if config.ion_transmission_enabled:
            lines.extend(
                [
                    f"Depth window: {float(config.ion_transmission_start_depth_pct):.1f}% -> {float(config.ion_transmission_end_depth_pct):.1f}%",
                    f"Drop/Floor/Curve: {self._fmt_pct(config.ion_transmission_decay_strength_pct)} / {self._fmt_pct(config.ion_transmission_floor_pct)} / {float(config.ion_transmission_curve_power):.2f}",
                    f"Shadow aperture/hidden/edge: {self._fmt_pct(config.ion_transmission_aperture_shadow_pct)} / {self._fmt_pct(config.ion_transmission_lateral_shadow_pct)} / {self._fmt_pct(config.ion_transmission_edge_shadow_pct)}",
                ]
            )

        lines.append(f"Reflection redepo: {self._on_off(config.redepo_enabled)}")
        if config.redepo_enabled:
            lines.extend(
                [
                    f"Redepo efficiency: {self._fmt_pct(config.redepo_efficiency_pct)}",
                    f"Angular spread: {float(config.redepo_emit_power):.1f} deg",
                    f"Specular bias: {self._fmt_pct(config.redepo_distance_power)}",
                ]
            )
        excluded = ["reflected ion", "LF proxy", "closure redepo"]
        if not config.redepo_enabled:
            excluded.insert(1, "redeposition")
        lines.append(f"제외: {' / '.join(excluded)}")

        lines.extend(
            [
                "",
                "[Deposition modifiers]",
                f"Depth depletion: {self._on_off(config.deposition_depth_enabled)}",
            ]
        )
        if config.deposition_depth_enabled:
            feature_length = (
                "None"
                if config.deposition_feature_length_a is None
                else self._fmt_a(float(config.deposition_feature_length_a))
            )
            post_fill = (
                float(config.deposition_post_closure_fill_pct_line)
                if str(config.deposition_feature_type) == "line"
                else float(config.deposition_post_closure_fill_pct_hole)
            )
            lines.extend(
                [
                    f"Feature geometry: {config.deposition_feature_type} | W {self._fmt_a(config.deposition_feature_width_a)} | Ref D {self._fmt_a(config.deposition_feature_depth_a)} | L {feature_length}",
                    f"Decay k/power/min: {float(config.deposition_depth_decay_k):.3f} / {float(config.deposition_depth_decay_power):.3f} / {float(config.deposition_min_ratio) * 100.0:.1f}%",
                    _depth_deposition_formula_text(
                        display_mode="depo_rate",
                        base_rate_a_per_cycle=float(config.angstrom_per_cycle),
                        attenuation_model=str(config.deposition_attenuation_model),
                        depth_decay_k=float(config.deposition_depth_decay_k),
                        depth_decay_power=float(config.deposition_depth_decay_power),
                        min_ratio_pct=float(config.deposition_min_ratio) * 100.0,
                        feature_type=str(config.deposition_feature_type),
                        feature_width_a=float(config.deposition_feature_width_a),
                        feature_length_a=config.deposition_feature_length_a,
                    ),
                    _depth_deposition_formula_text(
                        display_mode="attenuation",
                        base_rate_a_per_cycle=float(config.angstrom_per_cycle),
                        attenuation_model=str(config.deposition_attenuation_model),
                        depth_decay_k=float(config.deposition_depth_decay_k),
                        depth_decay_power=float(config.deposition_depth_decay_power),
                        min_ratio_pct=float(config.deposition_min_ratio) * 100.0,
                        feature_type=str(config.deposition_feature_type),
                        feature_width_a=float(config.deposition_feature_width_a),
                        feature_length_a=config.deposition_feature_length_a,
                    ),
                    f"Closure threshold: {self._fmt_a(config.deposition_closure_threshold_a)}",
                    f"After-close fill budget: {post_fill * 100.0:.1f}%",
                ]
            )

        lines.append(f"Inhibition: {self._on_off(config.inhibition_enabled)}")
        if config.inhibition_enabled:
            lines.extend(
                [
                    f"Process: {config.inhibition_process_model}",
                    f"Strength: {self._fmt_pct(config.inhibition_strength_pct)}",
                    f"Penetration: {self._fmt_a(config.inhibition_penetration_depth_a)}",
                    f"Floor/Bottom boost/Recomb: {float(config.inhibition_min_growth_ratio) * 100.0:.1f}% / {self._fmt_pct(config.inhibition_bottom_boost_pct)} / {self._fmt_pct(config.inhibition_peald_recombination_pct)}",
                ]
            )

        if result is not None:
            lines.extend(
                [
                    "",
                    "[결과 요약]",
                    f"Frames: {frames}",
                    f"Final points: {final_points}",
                    f"Growth model: {meta.get('growth_model', 'unknown')}",
                ]
            )
            if meta.get("deposition_closure_detected"):
                lines.append(
                    f"Closure: step {meta.get('deposition_closure_step')} | depth {float(meta.get('deposition_closure_depth_a') or 0.0):.3f} A"
                )

        return "\n".join(lines)

    def _update_result_parameter_summary(
        self,
        config: Optional[TrenchDepoConfig] = None,
        result: Optional[TrenchDepoResult] = None,
    ) -> None:
        if not hasattr(self, "edit_result_parameters"):
            return
        cfg = config or self._result_config
        if cfg is None:
            self.edit_result_parameters.setPlainText("아직 실행된 결과가 없습니다.")
            return
        self.edit_result_parameters.setPlainText(self._format_result_parameters(cfg, result))

    def current_etch_config(self) -> TrenchDepoConfig:
        cfg = self.current_config()
        if cfg.sputter_enabled or cfg.sputter_strength_a_per_cycle <= 0.0:
            return cfg
        return TrenchDepoConfig(
            points=cfg.points,
            cycles=cfg.cycles,
            emulator_number=cfg.emulator_number,
            angstrom_per_cycle=cfg.angstrom_per_cycle,
            reparam_ds_a=cfg.reparam_ds_a,
            sputter_enabled=True,
            sputter_strength_a_per_cycle=cfg.sputter_strength_a_per_cycle,
            sputter_peak_pct=cfg.sputter_peak_pct,
            sputter_peak_angle_deg=cfg.sputter_peak_angle_deg,
            sputter_width_deg=cfg.sputter_width_deg,
            sputter_smoothing_a=cfg.sputter_smoothing_a,
            ion_transmission_enabled=cfg.ion_transmission_enabled,
            ion_transmission_override=cfg.ion_transmission_override,
            ion_transmission_start_depth_pct=cfg.ion_transmission_start_depth_pct,
            ion_transmission_end_depth_pct=cfg.ion_transmission_end_depth_pct,
            ion_transmission_decay_strength_pct=cfg.ion_transmission_decay_strength_pct,
            ion_transmission_floor_pct=cfg.ion_transmission_floor_pct,
            ion_transmission_curve_power=cfg.ion_transmission_curve_power,
            ion_transmission_aperture_shadow_pct=cfg.ion_transmission_aperture_shadow_pct,
            ion_transmission_lateral_shadow_pct=cfg.ion_transmission_lateral_shadow_pct,
            ion_transmission_edge_shadow_pct=cfg.ion_transmission_edge_shadow_pct,
            reflected_ion_enabled=cfg.reflected_ion_enabled,
            reflected_ion_strength_pct=cfg.reflected_ion_strength_pct,
            reflected_ion_bowing_weight=cfg.reflected_ion_bowing_weight,
            reflected_ion_microtrench_weight=cfg.reflected_ion_microtrench_weight,
            reflected_ion_range_a=cfg.reflected_ion_range_a,
            redepo_enabled=cfg.redepo_enabled,
            redepo_source_model=cfg.redepo_source_model,
            redepo_efficiency_pct=cfg.redepo_efficiency_pct,
            redepo_emit_power=cfg.redepo_emit_power,
            redepo_distance_power=cfg.redepo_distance_power,
            redepo_neighbor_exclusion=cfg.redepo_neighbor_exclusion,
            redepo_max_distance_a=cfg.redepo_max_distance_a,
            redepo_soft_los_radius_points=cfg.redepo_soft_los_radius_points,
            redepo_transport_model=cfg.redepo_transport_model,
            redepo_ray_count=cfg.redepo_ray_count,
            redepo_footprint_sigma_a=cfg.redepo_footprint_sigma_a,
            redepo_footprint_radius_sigma=cfg.redepo_footprint_radius_sigma,
            lf_overhang_enabled=cfg.lf_overhang_enabled,
            lf_overhang_dose=cfg.lf_overhang_dose,
            lf_overhang_sputter_gain=cfg.lf_overhang_sputter_gain,
            lf_overhang_redepo_fraction_pct=cfg.lf_overhang_redepo_fraction_pct,
            lf_overhang_survival_penalty=cfg.lf_overhang_survival_penalty,
            lf_overhang_width_a=cfg.lf_overhang_width_a,
            closure_redepo_enabled=cfg.closure_redepo_enabled,
            closure_redepo_efficiency_pct=cfg.closure_redepo_efficiency_pct,
            closure_redepo_shadow_gain=cfg.closure_redepo_shadow_gain,
            closure_redepo_width_a=cfg.closure_redepo_width_a,
            closure_redepo_survival_penalty=cfg.closure_redepo_survival_penalty,
            closure_redepo_smoothing_a=cfg.closure_redepo_smoothing_a,
        )

    def _config_for_emulator_number(
        self,
        number: int,
        *,
        force_model_enabled: bool = False,
    ) -> TrenchDepoConfig:
        target = max(0, min(MAX_EMULATOR_NUMBER, int(number)))
        cfg = self.current_config()
        supports_sputter = self._emulator_supports_sputter(target)
        supports_ion_transmission = self._emulator_supports_ion_transmission(target)
        supports_reflected_ion = self._emulator_supports_reflected_ion(target)
        supports_redeposition = self._emulator_supports_redeposition(target)
        supports_depth_deposition = self._emulator_supports_depth_deposition(target)
        supports_inhibition = self._emulator_supports_inhibition(target)
        supports_lf_overhang = self._emulator_supports_lf_overhang(target)
        supports_closure_redepo = self._emulator_supports_closure_redepo(target)
        etch_enabled = bool(supports_sputter and (force_model_enabled or self.chk_sputter.isChecked()))
        depth_enabled = bool(
            supports_depth_deposition and (force_model_enabled or self.chk_depth_deposition.isChecked())
        )
        return replace(
            cfg,
            emulator_number=int(target),
            sputter_enabled=etch_enabled,
            sputter_strength_a_per_cycle=(
                float(self.spin_sputter_strength.value()) if supports_sputter else 0.0
            ),
            ion_transmission_enabled=bool(
                etch_enabled
                and supports_ion_transmission
                and (force_model_enabled or self.chk_ion_transmission.isChecked())
            ),
            ion_transmission_start_depth_pct=(
                float(self.spin_ion_start_depth.value()) if supports_ion_transmission else 0.0
            ),
            ion_transmission_end_depth_pct=(
                float(self.spin_ion_end_depth.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_decay_strength_pct=(
                float(self.spin_ion_decay_strength.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_floor_pct=(
                float(self.spin_ion_floor.value()) if supports_ion_transmission else 0.0
            ),
            ion_transmission_curve_power=(
                float(self.spin_ion_curve_power.value()) if supports_ion_transmission else 1.0
            ),
            ion_transmission_aperture_shadow_pct=(
                float(self.slider_ion_aperture_shadow.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_lateral_shadow_pct=(
                float(self.slider_ion_lateral_shadow.value()) if supports_ion_transmission else 100.0
            ),
            ion_transmission_edge_shadow_pct=(
                float(self.slider_ion_edge_shadow.value()) if supports_ion_transmission else 100.0
            ),
            reflected_ion_enabled=bool(
                etch_enabled
                and supports_reflected_ion
                and (force_model_enabled or self.chk_reflected_ion.isChecked())
            ),
            reflected_ion_strength_pct=(
                float(self.spin_reflected_strength.value()) if supports_reflected_ion else 0.0
            ),
            redepo_enabled=bool(
                etch_enabled
                and supports_redeposition
                and (force_model_enabled or self.chk_redepo.isChecked())
            ),
            redepo_source_model=str(self.cmb_redepo_source_model.currentData() or "model2"),
            redepo_efficiency_pct=(
                float(self.spin_redepo_efficiency.value()) if supports_redeposition else 0.0
            ),
            redepo_transport_model=TrenchDepoConfig().redepo_transport_model,
            lf_overhang_enabled=bool(
                etch_enabled
                and supports_lf_overhang
                and (force_model_enabled or self.chk_lf_overhang.isChecked())
            ),
            lf_overhang_dose=float(self.spin_lf_overhang_dose.value()),
            lf_overhang_sputter_gain=float(self.spin_lf_overhang_sputter_gain.value()),
            lf_overhang_redepo_fraction_pct=float(self.spin_lf_overhang_redepo_fraction.value()),
            lf_overhang_survival_penalty=float(self.spin_lf_overhang_survival.value()),
            lf_overhang_width_a=float(self.spin_lf_overhang_width.value()),
            closure_redepo_enabled=bool(
                etch_enabled
                and supports_closure_redepo
                and (force_model_enabled or self.chk_closure_redepo.isChecked())
            ),
            closure_redepo_efficiency_pct=float(self.spin_closure_redepo_efficiency.value()),
            closure_redepo_shadow_gain=float(self.spin_closure_redepo_shadow_gain.value()),
            closure_redepo_width_a=float(self.spin_closure_redepo_width.value()),
            closure_redepo_survival_penalty=float(self.spin_closure_redepo_survival.value()),
            closure_redepo_smoothing_a=float(self.spin_closure_redepo_smoothing.value()),
            deposition_depth_enabled=depth_enabled,
            inhibition_enabled=bool(
                supports_inhibition and (force_model_enabled or self.chk_inhibition_deposition.isChecked())
            ),
            inhibition_strength_pct=float(self.spin_inhibition_strength.value()),
            inhibition_penetration_depth_a=float(self.spin_inhibition_penetration.value()),
            inhibition_decay_power=float(self.spin_inhibition_decay_power.value()),
            inhibition_min_growth_ratio=float(self.spin_inhibition_min_growth.value()) / 100.0,
            inhibition_bottom_boost_pct=float(self.spin_inhibition_bottom_boost.value()),
            inhibition_peald_recombination_pct=float(self.spin_inhibition_recombination.value()),
            inhibition_smoothing_a=float(self.spin_inhibition_smoothing.value()),
        )

    def _set_run_dir_label(self, run_dir: Optional[Path]) -> None:
        if run_dir is None:
            self.lbl_run_dir.setText("저장된 run: 아직 없음")
            self.lbl_run_dir.setToolTip("")
            return
        resolved = Path(run_dir).resolve()
        self.lbl_run_dir.setText(f"저장된 run: {_elide_middle(resolved.name, 34)}")
        self.lbl_run_dir.setToolTip(str(resolved))

    def _preview_cache_key(self, config: TrenchDepoConfig) -> tuple[object, ...]:
        return (
            tuple((float(x), float(y)) for x, y in config.points),
            int(config.cycles),
            int(getattr(config, "emulator_number", 0) or 0),
            float(config.angstrom_per_cycle),
            float(config.reparam_ds_a),
            bool(config.sputter_enabled),
            float(config.sputter_strength_a_per_cycle),
            float(config.sputter_peak_pct),
            float(config.sputter_peak_angle_deg),
            float(config.sputter_width_deg),
            float(config.sputter_smoothing_a),
            bool(config.ion_transmission_enabled),
            (
                None
                if config.ion_transmission_override is None
                else float(config.ion_transmission_override)
            ),
            float(config.ion_transmission_start_depth_pct),
            float(config.ion_transmission_end_depth_pct),
            float(config.ion_transmission_decay_strength_pct),
            float(config.ion_transmission_floor_pct),
            float(config.ion_transmission_curve_power),
            float(config.ion_transmission_aperture_shadow_pct),
            float(config.ion_transmission_lateral_shadow_pct),
            float(config.ion_transmission_edge_shadow_pct),
            bool(config.reflected_ion_enabled),
            float(config.reflected_ion_strength_pct),
            float(config.reflected_ion_bowing_weight),
            float(config.reflected_ion_microtrench_weight),
            float(config.reflected_ion_range_a),
            bool(config.redepo_enabled),
            str(config.redepo_source_model),
            float(config.redepo_efficiency_pct),
            float(config.redepo_emit_power),
            float(config.redepo_distance_power),
            int(config.redepo_neighbor_exclusion),
            float(config.redepo_max_distance_a),
            int(config.redepo_soft_los_radius_points),
            str(config.redepo_transport_model),
            int(config.redepo_ray_count),
            float(config.redepo_footprint_sigma_a),
            float(config.redepo_footprint_radius_sigma),
            bool(config.lf_overhang_enabled),
            float(config.lf_overhang_dose),
            float(config.lf_overhang_sputter_gain),
            float(config.lf_overhang_redepo_fraction_pct),
            float(config.lf_overhang_survival_penalty),
            float(config.lf_overhang_width_a),
            bool(config.closure_redepo_enabled),
            float(config.closure_redepo_efficiency_pct),
            float(config.closure_redepo_shadow_gain),
            float(config.closure_redepo_width_a),
            float(config.closure_redepo_survival_penalty),
            float(config.closure_redepo_smoothing_a),
            bool(config.deposition_depth_enabled),
            str(config.deposition_feature_type),
            float(config.deposition_feature_width_a),
            float(config.deposition_feature_depth_a),
            (
                None
                if config.deposition_feature_length_a is None
                else float(config.deposition_feature_length_a)
            ),
            str(config.deposition_attenuation_model),
            float(config.deposition_depth_decay_k),
            float(config.deposition_depth_decay_power),
            float(config.deposition_min_ratio),
            bool(config.deposition_use_equivalent_ar),
            float(config.deposition_closure_threshold_a),
            float(config.deposition_post_closure_fill_pct_hole),
            float(config.deposition_post_closure_fill_pct_line),
            float(config.deposition_line_open_path_factor),
            float(config.deposition_residual_fill_decay_length_a),
            str(config.deposition_residual_fill_distribution),
            (
                None
                if config.deposition_max_depo_per_cell_a is None
                else float(config.deposition_max_depo_per_cell_a)
            ),
            bool(config.deposition_conserve_volume),
            bool(config.inhibition_enabled),
            str(config.inhibition_process_model),
            float(config.inhibition_strength_pct),
            float(config.inhibition_penetration_depth_a),
            float(config.inhibition_decay_power),
            float(config.inhibition_min_growth_ratio),
            float(config.inhibition_bottom_boost_pct),
            float(config.inhibition_peald_recombination_pct),
            float(config.inhibition_smoothing_a),
        )

    def _start_run_progress(self, label: str) -> None:
        self.progress_run.setRange(0, 0)
        self.progress_run.setValue(0)
        self.progress_run.setFormat(label)
        self.progress_run.setVisible(True)
        if hasattr(self, "lbl_progress_view_status"):
            self.lbl_progress_view_status.setText(label)
            self.progress_view_bar.setRange(0, 0)
            self.progress_view_bar.setValue(0)
            self.progress_view_bar.setFormat(label)
        QApplication.processEvents()

    def _update_run_progress(self, step: int, total: int, *, label: str = "실행 중") -> None:
        total_i = max(0, int(total))
        step_i = max(0, int(step))
        if total_i <= 0:
            self.progress_run.setRange(0, 1)
            self.progress_run.setValue(1)
            self.progress_run.setFormat(f"{label}: 완료")
            self.lbl_status.setText(f"{label}: 완료")
            if hasattr(self, "lbl_progress_view_status"):
                self.lbl_progress_view_status.setText(f"{label}: 완료")
                self.progress_view_bar.setRange(0, 1)
                self.progress_view_bar.setValue(1)
                self.progress_view_bar.setFormat("완료")
        else:
            step_i = min(step_i, total_i)
            if step_i <= 0:
                self.progress_run.setRange(0, 0)
            else:
                self.progress_run.setRange(0, total_i)
                self.progress_run.setValue(step_i)
            self.progress_run.setFormat(f"{label}: {step_i}/{total_i}")
            self.lbl_status.setText(f"{label}: {step_i}/{total_i}")
            if hasattr(self, "lbl_progress_view_status"):
                self.lbl_progress_view_status.setText(f"{label}: {step_i}/{total_i}")
                if step_i <= 0:
                    self.progress_view_bar.setRange(0, 0)
                else:
                    self.progress_view_bar.setRange(0, total_i)
                    self.progress_view_bar.setValue(step_i)
                self.progress_view_bar.setFormat(f"{step_i}/{total_i}")
        self.progress_run.setVisible(True)
        QApplication.processEvents()

    def _finish_run_progress(self, *, success: bool) -> None:
        if success:
            maximum = max(1, self.progress_run.maximum())
            self.progress_run.setRange(0, maximum)
            self.progress_run.setValue(maximum)
            self.progress_run.setFormat("완료")
            if hasattr(self, "lbl_progress_view_status"):
                self.lbl_progress_view_status.setText("진행 완료")
                self.progress_view_bar.setRange(0, maximum)
                self.progress_view_bar.setValue(maximum)
                self.progress_view_bar.setFormat("완료")
            QApplication.processEvents()
        elif hasattr(self, "lbl_progress_view_status"):
            self.lbl_progress_view_status.setText("진행 실패")
            self.progress_view_bar.setRange(0, 1)
            self.progress_view_bar.setValue(0)
            self.progress_view_bar.setFormat("실패")
        self.progress_run.setVisible(False)

    def _apply_emulation_result(
        self,
        config: TrenchDepoConfig,
        result: TrenchDepoResult,
        run_dir: Optional[Path],
        *,
        use_preview_cache: bool,
    ) -> None:
        self._result = result
        self._result_config = config
        self._last_run_dir = run_dir.resolve() if run_dir is not None else None
        solid_playback = _use_solid_playback(result)
        self.view.set_frames(
            result.frame_profiles,
            voids=result.frame_voids,
            redepo_overlays=result.meta.get("frame_redepo_overlays"),
            etch_overlays=result.meta.get("frame_etch_overlays"),
            transport_lines=result.meta.get("frame_transport_lines"),
            void_mode="current",
            dynamic_substrate_fill=solid_playback,
            history_mode="mixed_etch" if solid_playback else "film",
        )
        self._sync_field_overlay_toggles()
        max_idx = max(0, len(result.frame_profiles) - 1)
        self.slider_frame.blockSignals(True)
        self.slider_frame.setRange(0, max_idx)
        self.slider_frame.setValue(max_idx)
        self.slider_frame.setEnabled(max_idx > 0)
        self.slider_frame.blockSignals(False)
        self._set_result_playback_available(max_idx > 0)
        self._set_next_depo_button_state()
        self.btn_save_result_json.setEnabled(True)
        self._update_result_parameter_summary(config, result)
        self.show_frame(max_idx)
        if not use_preview_cache:
            self._set_workflow_step("results")
        QTimer.singleShot(0, self.view.fit_content)
        if run_dir is not None:
            self._set_run_dir_label(self._last_run_dir)
            self.btn_open_run_dir.setEnabled(True)
            self.statusBar().showMessage(f"런 저장 완료: {self._last_run_dir}", 5000)
        else:
            self.btn_open_run_dir.setEnabled(self._last_run_dir is not None)

    def _on_emulation_worker_progress(self, step: int, total: int, label: str) -> None:
        self._update_run_progress(int(step), int(total), label=str(label or "실행"))

    def _on_emulation_worker_finished(
        self,
        config: TrenchDepoConfig,
        result: TrenchDepoResult,
        use_preview_cache: bool,
        cache_key: tuple[object, ...],
        save_artifacts: bool,
        request_note: str,
    ) -> None:
        run_dir: Optional[Path] = None
        result = self._merge_result_if_continuation(result)
        if bool(save_artifacts):
            try:
                self._start_run_progress("run 저장 중")
                run_dir = export_trench_depo_run(
                    config,
                    result,
                    request_note=str(request_note),
                    runs_root=DEFAULT_RUNS_ROOT,
                )
                self._update_run_progress(1, 1, label="저장")
            except Exception as exc:  # noqa: BLE001
                self.btn_run.setEnabled(True)
                self._finish_run_progress(success=False)
                QMessageBox.critical(
                    self,
                    "트렌치 Depo 에뮬레이션",
                    f"Run 저장 실패:\n{exc}",
                )
                return
        self._preview_result_cache[cache_key] = result
        self.btn_run.setEnabled(True)
        self._finish_run_progress(success=True)
        self._apply_emulation_result(
            config,
            result,
            run_dir,
            use_preview_cache=bool(use_preview_cache),
        )
        self._clear_continuation_context()

    def _on_emulation_worker_failed(self, message: str) -> None:
        self.btn_run.setEnabled(True)
        self._finish_run_progress(success=False)
        QMessageBox.critical(
            self,
            "트렌치 Depo 에뮬레이션",
            f"트렌치 증착 에뮬레이션 실행 실패:\n{message}",
        )

    def _on_emulation_thread_finished(self) -> None:
        self._emulation_thread = None
        self._emulation_worker = None

    def run_emulation(
        self,
        _checked: bool = False,
        *,
        save_artifacts: bool = True,
        use_preview_cache: bool = False,
    ) -> None:
        if self._emulation_thread is not None:
            self.statusBar().showMessage("이미 시뮬레이션 실행 중입니다.", 2000)
            return
        self._emulator_run_timer.stop()
        self._stop_result_playback()
        self.btn_run.setEnabled(False)
        success = False
        try:
            config = self.current_config()
            run_dir: Optional[Path] = None
            cache_key = self._preview_cache_key(config)
            if use_preview_cache and not save_artifacts and cache_key in self._preview_result_cache:
                self._start_run_progress("캐시 run 불러오는 중")
                result = self._preview_result_cache[cache_key]
                self._update_run_progress(1, 1, label="캐시 run")
                success = True
            elif save_artifacts:
                self._start_run_progress("시뮬레이션 실행 중")
                worker = _EmulationRunWorker(
                    config=config,
                    cache_key=cache_key,
                    request_note=self.edit_request_note.toPlainText(),
                    save_artifacts=save_artifacts,
                    use_preview_cache=use_preview_cache,
                )
                thread = QThread(self)
                worker.moveToThread(thread)
                self._emulation_thread = thread
                self._emulation_worker = worker
                thread.started.connect(worker.run)
                worker.progress.connect(self._on_emulation_worker_progress)
                worker.finished.connect(self._on_emulation_worker_finished)
                worker.failed.connect(self._on_emulation_worker_failed)
                worker.finished.connect(worker.deleteLater)
                worker.failed.connect(worker.deleteLater)
                worker.finished.connect(thread.quit)
                worker.failed.connect(thread.quit)
                thread.finished.connect(self._on_emulation_thread_finished)
                thread.finished.connect(thread.deleteLater)
                thread.start()
                return
            else:
                self._start_run_progress("시뮬레이션 실행 중")
                result = run_trench_depo(
                    config,
                    progress_cb=lambda step, total: self._update_run_progress(
                        step,
                        total,
                        label="실행",
                    ),
                )
                self._preview_result_cache[cache_key] = result
                success = True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "트렌치 Depo 에뮬레이션",
                f"트렌치 증착 에뮬레이션 실행 실패:\n{exc}",
            )
            return
        finally:
            if self._emulation_thread is None:
                self.btn_run.setEnabled(True)
                self._finish_run_progress(success=success)

        if success:
            result = self._merge_result_if_continuation(result)
            self._preview_result_cache[cache_key] = result
        self._apply_emulation_result(
            config,
            result,
            run_dir,
            use_preview_cache=use_preview_cache,
        )
        if success:
            self._clear_continuation_context()

    def run_split_test(self, _checked: bool = False) -> None:
        self.btn_run_split.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Split test 계산 중...")
        success = False
        self._start_run_progress("Split 실행 중")
        try:
            parameter = str(self.cmb_split_parameter.currentData())
            cases = run_trench_depo_sweep(
                self.current_config(),
                parameter,
                float(self.spin_split_start.value()),
                float(self.spin_split_end.value()),
                float(self.spin_split_step.value()),
                max_cases=24,
                progress_cb=lambda idx, total, _cfg: self._update_run_progress(
                    idx,
                    total,
                    label="Split",
                ),
            )
            self._start_run_progress("Saving split")
            saved_dirs = export_trench_depo_sweep_runs(
                cases,
                request_note=self.edit_request_note.toPlainText(),
                runs_root=DEFAULT_RUNS_ROOT,
            )
            self._update_run_progress(1, 1, label="저장")
            success = True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Trench Depo Split Test",
                f"Split test 실행 또는 저장 실패:\n{exc}",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_run_split.setEnabled(True)
            self._finish_run_progress(success=success)

        if not cases:
            return
        if saved_dirs:
            self._last_run_dir = saved_dirs[-1].resolve()
            self._set_run_dir_label(self._last_run_dir)
            self.btn_open_run_dir.setEnabled(True)
        window = SplitTestWindow(cases)
        window.destroyed.connect(lambda _obj=None, w=window: self._forget_split_window(w))
        self._split_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        self.statusBar().showMessage(f"Split test 완료/저장: {len(cases)} cases", 5000)

    def run_compare_for_active_emulator(self, _checked: bool = False) -> None:
        target = self.cmb_compare_target.currentData()
        if target == "legacy_gapsim_angle":
            self.run_gapsim_angle_compare()
            return
        if target is None:
            QMessageBox.information(self, "Emulator Compare", "Select an emulator to compare.")
            return
        self.run_emulator_compare(int(target))

    def run_emulator_compare(self, target_number: int) -> None:
        active_number = self.active_emulator_number()
        target = max(0, min(MAX_EMULATOR_NUMBER, int(target_number)))
        if target == active_number:
            QMessageBox.information(
                self,
                "Emulator Compare",
                "Choose a different emulator as the compare target.",
            )
            return
        self.btn_run_compare.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        active_title = _emulator_mode_title(active_number)
        target_title = _emulator_mode_title(target)
        self.statusBar().showMessage(f"{active_title} / {target_title} 비교 계산 중...")
        success = False
        self._start_run_progress(f"{active_title} 실행 중")
        try:
            current_cfg = self._config_for_emulator_number(active_number, force_model_enabled=True)
            target_cfg = self._config_for_emulator_number(target, force_model_enabled=True)
            t0 = time.perf_counter()
            current_result = run_trench_depo(
                current_cfg,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label=active_title,
                ),
            )
            current_elapsed = time.perf_counter() - t0
            t1 = time.perf_counter()
            self._start_run_progress(f"{target_title} 실행 중")
            target_result = run_trench_depo(
                target_cfg,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label=target_title,
                ),
            )
            target_elapsed = time.perf_counter() - t1
            cases = [
                TrenchSweepResult(
                    parameter="emulator_compare",
                    label=f"Current {active_title} ({current_elapsed:.2f}s)",
                    value=float(active_number),
                    config=current_cfg,
                    result=current_result,
                ),
                TrenchSweepResult(
                    parameter="emulator_compare",
                    label=f"Compare {target_title} ({target_elapsed:.2f}s)",
                    value=float(target),
                    config=target_cfg,
                    result=target_result,
                ),
            ]
            success = True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Emulator Compare",
                f"{active_title} / {target_title} 비교 실패:\n{exc}",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_run_compare.setEnabled(True)
            self._finish_run_progress(success=success)

        window = SplitTestWindow(cases)
        window.destroyed.connect(lambda _obj=None, w=window: self._forget_split_window(w))
        self._split_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        self.statusBar().showMessage(f"{active_title} / {target_title} 비교 완료", 5000)

    def run_gapsim_angle_compare(self, _checked: bool = False) -> None:
        if not self._active_emulator_supports_sputter():
            QMessageBox.information(
                self,
                "Model Compare",
                "Angle/model comparison is available in sputter-based emulators.",
            )
            return
        self.btn_run_compare.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("GapSim angle-only 비교 계산 중...")
        success = False
        self._start_run_progress("현재 모델 실행 중")
        try:
            config = self._config_for_emulator_number(self.active_emulator_number(), force_model_enabled=True)
            t0 = time.perf_counter()
            mini_result = run_trench_depo(
                config,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label="Current model",
                ),
            )
            mini_elapsed = time.perf_counter() - t0
            t1 = time.perf_counter()
            baseline_config = config
            self._start_run_progress("GapSim legacy 실행 중")
            comparison_result = run_trench_depo_legacy_sputter(
                config,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label="GapSim legacy",
                ),
            )
            comparison_label = "GapSim angle-only"
            comparison_elapsed = time.perf_counter() - t1
            cases = [
                TrenchSweepResult(
                    parameter="model_compare",
                    label=f"Current {_emulator_mode_title(self.active_emulator_number())} ({mini_elapsed:.2f}s)",
                    value=0.0,
                    config=config,
                    result=mini_result,
                ),
                TrenchSweepResult(
                    parameter="model_compare",
                    label=f"{comparison_label} ({comparison_elapsed:.2f}s)",
                    value=1.0,
                    config=baseline_config,
                    result=comparison_result,
                ),
            ]
            success = True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "GapSim Angle Compare",
                f"GapSim angle-only 비교 실패:\n{exc}",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_run_compare.setEnabled(True)
            self._finish_run_progress(success=success)

        window = SplitTestWindow(cases)
        window.destroyed.connect(lambda _obj=None, w=window: self._forget_split_window(w))
        self._split_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        self.statusBar().showMessage("GapSim angle-only 비교 완료", 5000)

    def run_gapsim_redepo_compare(self, _checked: bool = False) -> None:
        if not self._active_emulator_supports_redeposition():
            QMessageBox.information(
                self,
                "Model Compare",
                "GapSim redeposition comparison is available in the redeposition model.",
            )
            return
        self.btn_run_compare.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("GapSim redepo 비교 계산 중...")
        success = False
        self._start_run_progress("Mini Model4 실행 중")
        try:
            config = self._config_for_emulator_number(self.active_emulator_number(), force_model_enabled=True)
            t0 = time.perf_counter()
            mini_result = run_trench_depo(
                config,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label="Mini Model4",
                ),
            )
            mini_elapsed = time.perf_counter() - t0
            t1 = time.perf_counter()
            self._start_run_progress("GapSim redepo 실행 중")
            comparison_result = run_trench_depo_legacy_redeposition(
                config,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label="GapSim redepo",
                ),
            )
            comparison_elapsed = time.perf_counter() - t1
            cases = [
                TrenchSweepResult(
                    parameter="model_compare",
                    label=f"Mini {_emulator_mode_title(self.active_emulator_number())} redepo ({mini_elapsed:.2f}s)",
                    value=0.0,
                    config=config,
                    result=mini_result,
                ),
                TrenchSweepResult(
                    parameter="model_compare",
                    label=f"GapSim original redepo ({comparison_elapsed:.2f}s)",
                    value=1.0,
                    config=config,
                    result=comparison_result,
                ),
            ]
            success = True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "GapSim Redepo Compare",
                f"GapSim redeposition 비교 실패:\n{exc}",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_run_compare.setEnabled(True)
            self._finish_run_progress(success=success)

        window = SplitTestWindow(cases)
        window.destroyed.connect(lambda _obj=None, w=window: self._forget_split_window(w))
        self._split_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        self.statusBar().showMessage("GapSim redepo 비교 완료", 5000)

    def _forget_split_window(self, window: SplitTestWindow) -> None:
        if window in self._split_windows:
            self._split_windows.remove(window)

    def _show_split_group_window(self, cases: Sequence[TrenchSweepResult], *, status: str) -> None:
        if len(cases) <= 1:
            return
        window = SplitTestWindow(cases)
        window.destroyed.connect(lambda _obj=None, w=window: self._forget_split_window(w))
        self._split_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        self.statusBar().showMessage(status, 5000)

    def _open_split_group_for_replay(self, replay_path: Path) -> None:
        cases = load_trench_depo_split_group(replay_path)
        if len(cases) <= 1:
            return
        self._show_split_group_window(cases, status=f"Split 묶음 로드 완료: {len(cases)} cases")

    def _set_result_playback_available(self, available: bool) -> None:
        if not hasattr(self, "btn_result_play"):
            return
        enabled = bool(available)
        self.btn_result_play.setEnabled(enabled)
        if not enabled:
            self._stop_result_playback()

    def _stop_result_playback(self) -> None:
        if hasattr(self, "_result_playback_timer") and self._result_playback_timer.isActive():
            self._result_playback_timer.stop()
        if hasattr(self, "btn_result_play"):
            self.btn_result_play.setText("반복재생")

    def toggle_result_playback(self, _checked: bool = False) -> None:
        if self._result is None or self.slider_frame.maximum() <= 0:
            self._set_result_playback_available(False)
            return
        if self._result_playback_timer.isActive():
            self._stop_result_playback()
            return
        if self.slider_frame.value() >= self.slider_frame.maximum():
            self.slider_frame.setValue(0)
        self._result_playback_timer.start()
        self.btn_result_play.setText("정지")

    def _advance_result_playback(self) -> None:
        if self._result is None or self.slider_frame.maximum() <= 0:
            self._set_result_playback_available(False)
            return
        next_index = int(self.slider_frame.value()) + 1
        if next_index > self.slider_frame.maximum():
            next_index = 0
        self.slider_frame.setValue(next_index)

    def show_frame(self, index: int) -> None:
        if self._result is None or not self._result.frame_profiles:
            self._show_result_input_preview(fit=False)
            return

        idx = max(0, min(int(index), len(self._result.frame_profiles) - 1))
        self.view.show_frame(idx, fit=False)
        cycle = self._result.frame_steps[idx] if idx < len(self._result.frame_steps) else idx
        total = self._result.meta.get("cycles", len(self._result.frame_profiles) - 1)
        points = len(self._result.frame_profiles[idx])
        self.lbl_status.setText(f"Cycle {cycle}/{total} | 점 {points}")
        if hasattr(self, "lbl_result_summary"):
            self.lbl_result_summary.setText(f"결과: Cycle {cycle}/{total} | 점 {points}")

    def load_replay_json(self, path: Path | str) -> None:
        self._stop_result_playback()
        self._clear_continuation_context()
        replay_path = Path(path).resolve()
        config, result, note = load_trench_depo_run(replay_path)
        if bool(config.sputter_enabled) and bool(config.ion_transmission_enabled) and (
            bool(config.deposition_depth_enabled) or bool(config.inhibition_enabled)
        ):
            replay_emulator = 0
        elif bool(config.inhibition_enabled):
            replay_emulator = 5
        elif bool(config.deposition_depth_enabled):
            replay_emulator = 4
        elif bool(config.sputter_enabled) and bool(config.ion_transmission_enabled):
            replay_emulator = 3
        elif bool(config.sputter_enabled) and bool(config.redepo_enabled):
            replay_emulator = 6
        elif bool(config.sputter_enabled):
            replay_emulator = 2
        else:
            replay_emulator = 1
        self.set_active_emulator_number(replay_emulator, run=False)
        self._set_structure_points(config.points, preserve_on_emulator_switch=True)
        self.spin_cycles.setValue(int(config.cycles))
        self.spin_angstrom_per_cycle.setValue(float(config.angstrom_per_cycle))
        self._set_quality_mode_for_ds(float(config.reparam_ds_a))
        self.chk_sputter.setChecked(
            bool(self._active_emulator_supports_sputter() and config.sputter_enabled)
        )
        self.chk_ion_transmission.setChecked(
            bool(self._active_emulator_supports_ion_transmission() and config.ion_transmission_enabled)
        )
        self.chk_reflected_ion.setChecked(False)
        self.chk_redepo.setChecked(False)
        self.chk_lf_overhang.setChecked(False)
        self.chk_closure_redepo.setChecked(False)
        self.spin_ion_start_depth.setValue(float(config.ion_transmission_start_depth_pct))
        self.spin_ion_end_depth.setValue(float(config.ion_transmission_end_depth_pct))
        self.spin_ion_decay_strength.setValue(float(config.ion_transmission_decay_strength_pct))
        self.spin_ion_floor.setValue(float(config.ion_transmission_floor_pct))
        self.spin_ion_curve_power.setValue(float(config.ion_transmission_curve_power))
        self.slider_ion_aperture_shadow.setValue(int(round(float(config.ion_transmission_aperture_shadow_pct))))
        self.slider_ion_lateral_shadow.setValue(int(round(float(config.ion_transmission_lateral_shadow_pct))))
        self.slider_ion_edge_shadow.setValue(int(round(float(config.ion_transmission_edge_shadow_pct))))
        self.sync_ion_shadow_slider_labels()
        self.spin_reflected_strength.setValue(float(config.reflected_ion_strength_pct))
        self.spin_reflected_bowing.setValue(float(config.reflected_ion_bowing_weight))
        self.spin_reflected_microtrench.setValue(float(config.reflected_ion_microtrench_weight))
        self.spin_reflected_range.setValue(float(config.reflected_ion_range_a))
        source_index = self.cmb_redepo_source_model.findData(str(config.redepo_source_model))
        self.cmb_redepo_source_model.setCurrentIndex(source_index if source_index >= 0 else 0)
        self.spin_redepo_efficiency.setValue(float(config.redepo_efficiency_pct))
        self.spin_redepo_emit_power.setValue(float(config.redepo_emit_power))
        self.spin_redepo_distance_power.setValue(float(config.redepo_distance_power))
        self.spin_redepo_soft_los.setValue(int(config.redepo_soft_los_radius_points))
        self.spin_lf_overhang_dose.setValue(float(config.lf_overhang_dose))
        self.spin_lf_overhang_sputter_gain.setValue(float(config.lf_overhang_sputter_gain))
        self.spin_lf_overhang_redepo_fraction.setValue(float(config.lf_overhang_redepo_fraction_pct))
        self.spin_lf_overhang_survival.setValue(float(config.lf_overhang_survival_penalty))
        self.spin_lf_overhang_width.setValue(float(config.lf_overhang_width_a))
        self.spin_closure_redepo_efficiency.setValue(float(config.closure_redepo_efficiency_pct))
        self.spin_closure_redepo_shadow_gain.setValue(float(config.closure_redepo_shadow_gain))
        self.spin_closure_redepo_width.setValue(float(config.closure_redepo_width_a))
        self.spin_closure_redepo_survival.setValue(float(config.closure_redepo_survival_penalty))
        self.spin_closure_redepo_smoothing.setValue(float(config.closure_redepo_smoothing_a))
        self.chk_depth_deposition.setChecked(
            bool(self._active_emulator_supports_depth_deposition() and config.deposition_depth_enabled)
        )
        self.chk_inhibition_deposition.setChecked(
            bool(self._active_emulator_supports_inhibition() and config.inhibition_enabled)
        )
        feature_index = self.cmb_depth_feature_type.findData(str(config.deposition_feature_type))
        self.cmb_depth_feature_type.setCurrentIndex(feature_index if feature_index >= 0 else 0)
        self.spin_depth_feature_width.setValue(float(config.deposition_feature_width_a))
        self.spin_depth_feature_depth.setValue(float(config.deposition_feature_depth_a))
        self.spin_depth_feature_length.setValue(
            0.0 if config.deposition_feature_length_a is None else float(config.deposition_feature_length_a)
        )
        self.spin_depth_decay_k.setValue(float(config.deposition_depth_decay_k))
        self.spin_depth_decay_power.setValue(float(config.deposition_depth_decay_power))
        self.spin_depth_min_ratio_pct.setValue(float(config.deposition_min_ratio) * 100.0)
        self.spin_depth_closure_threshold.setValue(float(config.deposition_closure_threshold_a))
        self.spin_depth_post_fill_hole_pct.setValue(float(config.deposition_post_closure_fill_pct_hole) * 100.0)
        self.spin_depth_post_fill_line_pct.setValue(float(config.deposition_post_closure_fill_pct_line) * 100.0)
        self.spin_depth_line_open_path.setValue(float(config.deposition_line_open_path_factor))
        self.spin_depth_residual_decay.setValue(float(config.deposition_residual_fill_decay_length_a))
        self.spin_inhibition_strength.setValue(float(config.inhibition_strength_pct))
        self.spin_inhibition_penetration.setValue(float(config.inhibition_penetration_depth_a))
        self.spin_inhibition_decay_power.setValue(float(config.inhibition_decay_power))
        self.spin_inhibition_min_growth.setValue(float(config.inhibition_min_growth_ratio) * 100.0)
        self.spin_inhibition_bottom_boost.setValue(float(config.inhibition_bottom_boost_pct))
        self.spin_inhibition_recombination.setValue(float(config.inhibition_peald_recombination_pct))
        self.spin_inhibition_smoothing.setValue(float(config.inhibition_smoothing_a))
        self.spin_sputter_strength.setValue(float(config.sputter_strength_a_per_cycle))
        self.spin_sputter_peak_pct.setValue(float(config.sputter_peak_pct))
        self.spin_sputter_peak.setValue(float(config.sputter_peak_angle_deg))
        self.spin_sputter_width.setValue(float(config.sputter_width_deg))
        self.spin_sputter_smoothing.setValue(float(config.sputter_smoothing_a))
        self.sync_inhibition_profile_from_spins()
        self.sync_etch_control_availability()
        self.edit_request_note.setPlainText(note)
        self._result = result
        self._result_config = config
        self._last_run_dir = replay_path.parent
        solid_playback = _use_solid_playback(result)
        self.view.set_frames(
            result.frame_profiles,
            voids=result.frame_voids,
            redepo_overlays=result.meta.get("frame_redepo_overlays"),
            etch_overlays=result.meta.get("frame_etch_overlays"),
            transport_lines=result.meta.get("frame_transport_lines"),
            void_mode="current",
            dynamic_substrate_fill=solid_playback,
            history_mode="mixed_etch" if solid_playback else "film",
        )
        self._sync_field_overlay_toggles()
        max_idx = max(0, len(result.frame_profiles) - 1)
        self.slider_frame.blockSignals(True)
        self.slider_frame.setRange(0, max_idx)
        self.slider_frame.setValue(max_idx)
        self.slider_frame.setEnabled(max_idx > 0)
        self.slider_frame.blockSignals(False)
        self._set_result_playback_available(max_idx > 0)
        self._set_next_depo_button_state()
        self.btn_save_result_json.setEnabled(True)
        self._update_result_parameter_summary(config, result)
        self.show_frame(max_idx)
        self._set_workflow_step("results")
        QTimer.singleShot(0, self.view.fit_content)
        self._set_run_dir_label(self._last_run_dir)
        self.btn_open_run_dir.setEnabled(True)
        self.statusBar().showMessage(f"Run 불러오기 완료: {replay_path}", 5000)
        self._open_split_group_for_replay(replay_path)

    def save_current_result_json(self, _checked: bool = False) -> None:
        if self._result is None or self._result_config is None:
            QMessageBox.information(self, "결과 JSON 저장", "저장할 실행 결과가 없습니다. 먼저 실행을 완료하세요.")
            self.btn_save_result_json.setEnabled(False)
            return
        try:
            result_path = save_trench_depo_result_json(
                self._result_config,
                self._result,
                request_note=self.edit_request_note.toPlainText(),
                results_root=DEFAULT_RESULTS_ROOT,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "결과 JSON 저장", f"결과 저장 실패:\n{exc}")
            return

        self._last_run_dir = result_path.parent.resolve()
        self.lbl_run_dir.setText(f"결과 저장: {_elide_middle(result_path.name, 34)}")
        self.lbl_run_dir.setToolTip(str(result_path.resolve()))
        self.btn_open_run_dir.setEnabled(True)
        self.statusBar().showMessage(f"결과 JSON 저장 완료: {result_path}", 5000)

    def open_replay_json_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "저장된 Run 불러오기",
            str(self._last_run_dir or DEFAULT_RUNS_ROOT),
            "JSON (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.load_replay_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "트렌치 Depo 에뮬레이션", f"Run 불러오기 실패:\n{exc}")

    def open_last_run_dir(self) -> None:
        if self._last_run_dir is None:
            return
        run_dir = self._last_run_dir.resolve()
        if not run_dir.exists():
            QMessageBox.warning(self, "트렌치 Depo 에뮬레이션", f"저장 폴더를 찾을 수 없습니다:\n{run_dir}")
            self.btn_open_run_dir.setEnabled(False)
            return

        if platform.system() == "Darwin":
            try:
                subprocess.run(["open", str(run_dir)], check=True)
                return
            except Exception:
                pass

        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(run_dir)))
        if not ok:
            QMessageBox.warning(self, "트렌치 Depo 에뮬레이션", f"저장 폴더 열기 실패:\n{run_dir}")

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._emulation_thread is not None and self._emulation_thread.isRunning():
            self.statusBar().showMessage("시뮬레이션 실행 중에는 창을 닫을 수 없습니다.", 2500)
            event.ignore()
            return
        self._emulator_run_timer.stop()
        self._stop_result_playback()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = TrenchDepoWindow()
    replay_arg: Optional[str] = None
    args = list(sys.argv[1:])
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--emulator" and idx + 1 < len(args):
            window.set_active_emulator_number(int(args[idx + 1]), run=False)
            idx += 2
            continue
        if arg.startswith("--emulator="):
            window.set_active_emulator_number(int(arg.split("=", 1)[1]), run=False)
            idx += 1
            continue
        replay_arg = arg
        idx += 1

    if replay_arg:
        try:
            window.load_replay_json(replay_arg)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(window, "트렌치 Depo 에뮬레이션", f"Run 불러오기 실패:\n{exc}")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
