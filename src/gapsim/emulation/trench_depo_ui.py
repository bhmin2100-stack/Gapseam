from __future__ import annotations

from dataclasses import replace
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
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
from gapsim.emulation.structure_library import (
    DEFAULT_EMULATOR_STRUCTURE_SHEETS,
    DEFAULT_STRUCTURE_LIBRARY_PATH,
    StructureLibraryError,
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
    run_trench_depo_legacy_sputter,
    run_trench_depo_sweep,
)
from gapsim.emulation.trench_depo_export import (
    DEFAULT_RUNS_ROOT,
    export_trench_depo_run,
    export_trench_depo_sweep_runs,
    load_trench_depo_run,
    load_trench_depo_split_group,
)
from gapsim.ui_qt.calibrate_dialog import CalibrateDialog
from gapsim.ui_qt.controllers.smoothing_ctrl import SmoothingController
from gapsim.ui_qt.models.points_table import PointsTableModel
from gapsim.ui_qt.models.points_table_view import PointsTableView
from gapsim.ui_qt.views.result_vector_view import ResultVectorView
from gapsim.ui_qt.views.structure_view import StructureView


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


EMULATOR_MODE_TITLES = {
    0: "Conformal depo baseline",
    1: "Direct angle sputter etch",
    2: "Ion transmission shadowing",
    3: "Discarded reflected ion etch",
    4: "Sputter redeposition",
    5: "Depth-dependent depo fill",
    6: "Inhibition deposition fill",
}


def _emulator_mode_title(number: int) -> str:
    number_i = int(number)
    if number_i in EMULATOR_MODE_TITLES:
        return EMULATOR_MODE_TITLES[number_i]
    return "Unassigned conformal baseline"


def _emulator_mode_label(number: int) -> str:
    return f"{int(number):02d} - {_emulator_mode_title(int(number))}"


EMULATOR_PROCESS_PRESETS: dict[int, list[tuple[str, dict[str, object]]]] = {
    0: [
        ("Baseline conformal", {"cycles": 20, "depo": 10.0}),
        ("Quick conformal", {"cycles": 8, "depo": 10.0}),
    ],
    1: [
        ("Direct sputter default", {"cycles": 20, "depo": 10.0, "sputter": True, "etch": 4.0, "peak": 55.0, "width": 14.0}),
        ("Soft direct etch", {"cycles": 20, "depo": 10.0, "sputter": True, "etch": 2.0, "peak": 55.0, "width": 18.0}),
        ("Strong direct etch", {"cycles": 20, "depo": 10.0, "sputter": True, "etch": 7.0, "peak": 58.0, "width": 12.0}),
    ],
    2: [
        ("Ion depth default", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "ion_start": 0.0, "ion_end": 100.0, "ion_drop": 100.0, "ion_floor": 0.0, "ion_curve": 1.0}),
        ("Top-open ion", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "ion_start": 20.0, "ion_end": 100.0, "ion_drop": 80.0, "ion_floor": 10.0, "ion_curve": 1.2}),
        ("Deep-select ion", {"cycles": 20, "depo": 10.0, "sputter": True, "ion": True, "ion_start": 45.0, "ion_end": 100.0, "ion_drop": 100.0, "ion_floor": 0.0, "ion_curve": 1.8}),
    ],
    3: [
        ("Reflected ion default", {"cycles": 20, "depo": 10.0, "sputter": True, "reflected": True, "reflect": 35.0, "bowing": 0.75, "micro": 1.0, "range": 1600.0}),
        ("Bowing focus", {"cycles": 20, "depo": 10.0, "sputter": True, "reflected": True, "reflect": 50.0, "bowing": 1.15, "micro": 0.8, "range": 1900.0}),
    ],
    4: [
        ("Redepo default", {"cycles": 20, "depo": 10.0, "sputter": True, "redepo": True, "redepo_eff": 25.0, "redepo_emit": 1.0, "redepo_dist": 1.0}),
        ("Soft redepo", {"cycles": 20, "depo": 10.0, "sputter": True, "redepo": True, "redepo_eff": 15.0, "redepo_emit": 0.7, "redepo_dist": 1.3}),
        ("Strong redepo", {"cycles": 20, "depo": 10.0, "sputter": True, "redepo": True, "redepo_eff": 40.0, "redepo_emit": 1.4, "redepo_dist": 0.8}),
    ],
    5: [
        ("Depth fill default", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.8, "depth_power": 1.2, "depth_min": 3.0}),
        ("Gentle depth fill", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.45, "depth_power": 1.0, "depth_min": 8.0}),
        ("Strong top loss", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 1.35, "depth_power": 1.4, "depth_min": 2.0}),
    ],
    6: [
        ("Inhibition default", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.8, "depth_power": 1.2, "depth_min": 8.0}),
        ("Soft inhibition", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 0.45, "depth_power": 1.0, "depth_min": 12.0}),
        ("Strong inhibition", {"cycles": 20, "depo": 10.0, "depth": True, "depth_k": 1.25, "depth_power": 1.5, "depth_min": 5.0}),
    ],
}


def _draw_structure_minimap(
    painter: QPainter,
    points: Sequence[Tuple[float, float]],
    rect: QRectF,
    *,
    label: str = "Structure",
) -> None:
    if len(points) < 2:
        return
    xs = [float(x) for x, _y in points]
    ys = [float(y) for _x, y in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = max(x_max - x_min, 1e-9)
    y_span = max(y_max - y_min, 1e-9)
    pad = 8.0
    draw_rect = rect.adjusted(pad, 17.0, -pad, -pad)
    scale = min(draw_rect.width() / x_span, draw_rect.height() / y_span)
    used_w = x_span * scale
    used_h = y_span * scale
    x_offset = draw_rect.left() + (draw_rect.width() - used_w) * 0.5
    y_offset = draw_rect.top() + (draw_rect.height() - used_h) * 0.5

    def map_point(point: Tuple[float, float]) -> QPointF:
        x, y = point
        return QPointF(
            x_offset + ((float(x) - x_min) * scale),
            y_offset + ((y_max - float(y)) * scale),
        )

    path = QPainterPath()
    for idx, point in enumerate(points):
        mapped = map_point(point)
        if idx == 0:
            path.moveTo(mapped)
        else:
            path.lineTo(mapped)

    painter.setPen(QPen(QColor(203, 213, 225), 1.0))
    painter.setBrush(QColor(255, 255, 255, 230))
    painter.drawRoundedRect(rect, 5.0, 5.0)
    painter.setPen(QPen(QColor(71, 85, 105), 1.0))
    painter.drawText(QPointF(rect.left() + 7.0, rect.top() + 12.0), label)
    painter.setPen(QPen(QColor(30, 41, 59), 1.7))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)


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

    def _bounds(self) -> Tuple[float, float, float, float]:
        xs = [float(x) for x, _y in self._points]
        ys = [float(y) for _x, y in self._points]
        return (min(xs), max(xs), min(ys), max(ys))

    def _point_to_widget(self, point: Tuple[float, float]) -> QPointF:
        rect = self._map_rect()
        x_min, x_max, y_min, y_max = self._bounds()
        x_span = max(x_max - x_min, 1e-9)
        y_span = max(y_max - y_min, 1e-9)
        x, y = point
        tx = (float(x) - x_min) / x_span
        ty = (y_max - float(y)) / y_span
        return QPointF(rect.left() + rect.width() * tx, rect.top() + rect.height() * ty)

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

        painter.setPen(QPen(QColor(226, 232, 240), 1.0))
        for depth_pct in (0.0, 25.0, 50.0, 75.0, 100.0):
            y = self._y_for_depth_pct(depth_pct)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for factor in (0.0, 0.5, 1.0):
            x = self._x_for_factor(factor)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        trench_path = QPainterPath()
        for idx, point in enumerate(self._points):
            mapped = self._point_to_widget(point)
            if idx == 0:
                trench_path.moveTo(mapped)
            else:
                trench_path.lineTo(mapped)
        painter.setPen(QPen(QColor(51, 65, 85), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(trench_path)

        inset = QRectF(rect.left() + 8.0, rect.top() + 8.0, min(128.0, rect.width() * 0.28), min(78.0, rect.height() * 0.42))
        _draw_structure_minimap(painter, self._points, inset)

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

    def _handle_points(self) -> dict[str, QPointF]:
        rect = self._plot_rect()
        return {
            "floor": QPointF(self._x_for_ratio(float(self._min_ratio_pct) / 100.0), rect.bottom() - 11.0),
            "attenuation": QPointF(self._x_for_ratio(self._ratio_at_depth_ratio(1.0)), rect.bottom()),
            "power": QPointF(self._x_for_ratio(self._ratio_at_depth_ratio(0.5)), self._y_for_depth_ratio(0.5)),
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
            self._decay_k = self._decay_k_for_bottom_ratio(self._ratio_for_x(pos.x()))
        elif handle == "power":
            self._decay_power = self._decay_power_for_mid_ratio(self._ratio_for_x(pos.x()))
        elif handle == "floor":
            self._min_ratio_pct = self._clamp(self._ratio_for_x(pos.x()) * 100.0, 0.0, 100.0)
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

        painter.setPen(QPen(QColor(226, 232, 240), 1.0))
        for depth_ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = self._y_for_depth_ratio(depth_ratio)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for ratio in (0.0, 0.5, 1.0):
            x = self._x_for_ratio(ratio)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        conformal_x = self._x_for_ratio(1.0)
        curve_points = self._curve_points()
        reduction_area = QPainterPath()
        reduction_area.moveTo(QPointF(conformal_x, rect.top()))
        reduction_area.lineTo(QPointF(conformal_x, rect.bottom()))
        for depth_ratio, ratio in reversed(curve_points):
            reduction_area.lineTo(QPointF(self._x_for_ratio(ratio), self._y_for_depth_ratio(depth_ratio)))
        reduction_area.closeSubpath()
        painter.fillPath(reduction_area, QColor(219, 234, 254, 72))

        painter.setPen(QPen(QColor(37, 99, 235, 165), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(conformal_x, rect.top()), QPointF(conformal_x, rect.bottom()))
        painter.setPen(QPen(QColor(30, 64, 175), 1.0))
        painter.drawText(QPointF(max(rect.left(), conformal_x - 92.0), rect.top() - 8.0), "Conformal 100%")

        for depth_ratio in (0.18, 0.36, 0.54, 0.72, 0.90):
            y = self._y_for_depth_ratio(depth_ratio)
            ratio = self._ratio_at_depth_ratio(depth_ratio)
            self._draw_arrow(
                painter,
                QPointF(conformal_x - 4.0, y),
                QPointF(self._x_for_ratio(ratio) + 4.0, y),
                QColor(37, 99, 235, 150),
            )

        bottom_ear = self._effective_ar_at_depth_ratio(1.0)
        inset = QRectF(rect.left() + 8.0, rect.top() + 12.0, min(150.0, rect.width() * 0.30), min(96.0, rect.height() * 0.48))
        _draw_structure_minimap(painter, self._structure_points, inset)
        painter.setPen(QPen(QColor(15, 23, 42), 1.0))
        painter.drawText(QPointF(inset.left() + 7.0, min(rect.bottom() - 4.0, inset.bottom() + 15.0)), f"Eff AR {bottom_ear:.2f}")

        floor_x = self._x_for_ratio(float(self._min_ratio_pct) / 100.0)
        painter.setPen(QPen(QColor(22, 163, 74), 1.4, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(floor_x, rect.top()), QPointF(floor_x, rect.bottom()))

        curve = QPainterPath()
        for idx, (depth_ratio, ratio) in enumerate(curve_points):
            point = QPointF(self._x_for_ratio(ratio), self._y_for_depth_ratio(depth_ratio))
            if idx == 0:
                curve.moveTo(point)
            else:
                curve.lineTo(point)
        painter.setPen(QPen(QColor(21, 128, 61), 2.7))
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
                f"K {self._decay_k:.2f}    "
                f"P {self._decay_power:.2f}    "
                f"Min {self._min_ratio_pct:.1f}%    "
                f"Close {self._closure_threshold_a:.1f} A"
            ),
        )
        painter.setPen(QPen(QColor(100, 116, 139), 1.0))
        painter.drawText(QPointF(rect.left() - 28.0, rect.top() + 4.0), "0")
        painter.drawText(QPointF(rect.left() - 34.0, rect.bottom() + 4.0), "100")
        painter.drawText(QPointF(rect.right() - 64.0, rect.bottom() + 18.0), "depo ratio")


class RedepositionLobeEditor(QWidget):
    parametersChanged = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._efficiency_pct = 25.0
        self._emit_power = 1.0
        self._distance_power = 1.0
        self._drag_handle: Optional[str] = None
        self.setMinimumHeight(142)
        self.setMaximumHeight(172)
        self.setMouseTracking(True)
        self.setToolTip(
            "Drag the density handle for redeposition amount, cone edge handles for emit, and axis handle for distance fade."
        )

    def parameters(self) -> Tuple[float, float, float]:
        return (float(self._efficiency_pct), float(self._emit_power), float(self._distance_power))

    def set_parameters(self, efficiency_pct: float, emit_power: float, distance_power: float) -> None:
        eff_f = self._clamp(float(efficiency_pct), 0.0, 100.0)
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

    def _axis_angle_deg(self) -> float:
        return 17.0

    def _axis_vec(self) -> Tuple[float, float]:
        angle = math.radians(self._axis_angle_deg())
        return (math.cos(angle), math.sin(angle))

    def _emit_to_half_angle(self, emit_power: float) -> float:
        return 10.0 + (52.0 / (1.0 + (0.9 * self._clamp(float(emit_power), 0.0, 8.0))))

    def _half_angle_to_emit(self, half_angle_deg: float) -> float:
        half = self._clamp(float(half_angle_deg), 12.0, 62.0)
        return self._clamp(((52.0 / max(0.1, half - 10.0)) - 1.0) / 0.9, 0.0, 8.0)

    def _distance_handle_t(self) -> float:
        return 0.90 - (0.68 * self._clamp(self._distance_power, 0.0, 4.0) / 4.0)

    def _distance_from_t(self, t: float) -> float:
        return self._clamp((0.90 - self._clamp(float(t), 0.22, 0.90)) * 4.0 / 0.68, 0.0, 4.0)

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
        painter.drawText(
            QPointF(rect.left(), 17.0),
            f"Redepo {self._efficiency_pct:.1f}%    Cone {2.0 * half:.0f} deg    Dist {self._distance_power:.2f}",
        )


class SplitTestWindow(QMainWindow):
    def __init__(self, cases: Sequence[TrenchSweepResult]) -> None:
        super().__init__()
        self._cases = list(cases)
        self._views: List[ResultVectorView] = []
        self._case_status_labels: List[QLabel] = []
        self._syncing_viewports = False

        title = "Split Test"
        if self._cases:
            if self._cases[0].parameter == "model_compare":
                title = "Model Compare - GapSim Angle Only"
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

        self.btn_play = QPushButton("Pause" if max_idx > 0 else "Play")
        self.btn_play.setEnabled(max_idx > 0)
        self.btn_play.clicked.connect(self.toggle_playback)
        self.lbl_frame = QLabel("Frame 0/0")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Frame"))
        controls.addWidget(self.slider_frame, 1)
        controls.addWidget(self.lbl_frame)
        controls.addWidget(self.btn_play)

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
            status = QLabel("Cycle 0/0 | Points 0")
            view = ResultVectorView()
            view.setMinimumSize(360, 260)
            solid_playback = _use_solid_playback(case.result)
            view.set_frames(
                case.result.frame_profiles,
                voids=case.result.frame_voids,
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

        root = QVBoxLayout()
        root.addLayout(controls)
        root.addWidget(scroll, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self.show_frame(0)
        QTimer.singleShot(0, self.fit_all_views)
        if max_idx > 0:
            self._timer.start()

    def _case_label(self, case: TrenchSweepResult) -> str:
        if case.parameter == "model_compare":
            return case.label
        if case.parameter == "cycles":
            value_text = str(int(case.value))
        else:
            value_text = f"{case.value:g}"
        return f"{case.label}: {value_text}"

    def toggle_playback(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.btn_play.setText("Play")
            return
        if self.slider_frame.value() >= self.slider_frame.maximum():
            self.slider_frame.setValue(0)
        self._timer.start()
        self.btn_play.setText("Pause")

    def _advance_frame(self) -> None:
        current = self.slider_frame.value()
        if current >= self.slider_frame.maximum():
            self._timer.stop()
            self.btn_play.setText("Replay")
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
            self._case_status_labels[case_idx].setText(f"Cycle {cycle}/{total} | Points {points}")

    def fit_all_views(self) -> None:
        if not self._views:
            return
        self._syncing_viewports = True
        try:
            for view in self._views:
                view.fit_content()
        finally:
            self._syncing_viewports = False

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


class TrenchDepoWindow(QMainWindow):
    def _make_parameter_section(
        self,
        text: str,
        *,
        color: str = "#334155",
        background: str = "#f8fafc",
        border: str = "#cbd5e1",
    ) -> QLabel:
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
        self.setWindowTitle("Trench Depo Emulation")
        self.resize(1280, 820)

        self._result: Optional[TrenchDepoResult] = None
        self._last_run_dir: Optional[Path] = None
        self._split_windows: List[SplitTestWindow] = []
        self._syncing_sputter_curve = False
        self._syncing_ion_curve = False
        self._syncing_redepo_lobe = False
        self._syncing_depth_curve = False
        self._active_emulator_number = 0
        self._emulator_numbers = load_created_emulator_numbers()
        self._emulator_buttons: dict[int, QPushButton] = {}
        self._preview_result_cache: dict[tuple[object, ...], TrenchDepoResult] = {}
        self._emulator_run_timer = QTimer(self)
        self._emulator_run_timer.setSingleShot(True)
        self._emulator_run_timer.setInterval(150)
        self._emulator_run_timer.timeout.connect(self._run_deferred_emulator_preview)

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
        self.smoothing = SmoothingController()
        self._structure_points: List[Tuple[float, float]] = []
        self._smoothed_points: List[Tuple[float, float]] = []
        self._use_smoothed_geometry = False
        self._syncing_structure_view = False
        self._syncing_structure_table = False
        self._syncing_smoothed_table = False
        self._syncing_workflow_tabs = False
        self._syncing_emulator_preset = False
        self._structure_library_path = Path(
            os.environ.get("GAPSIM_STRUCTURE_LIBRARY", str(DEFAULT_STRUCTURE_LIBRARY_PATH))
        )
        self._active_structure_sheet_name = ""
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

        self.chk_sputter = QCheckBox("Etch enabled")
        self.chk_sputter.setToolTip("Master switch for the direct sputter etch stack.")
        self.chk_sputter.setChecked(False)
        self.chk_ion_transmission = QCheckBox("2 Ion transmission modifier")
        self.chk_ion_transmission.setToolTip(
            "Multiplier on the existing direct sputter output. Deposition is not attenuated."
        )
        self.chk_ion_transmission.setChecked(False)
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
        self.cmb_redepo_source_model.setToolTip("4번 redeposition source는 Model2 ion transmission 경로로 고정됩니다.")
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
        self.chk_depth_deposition = QCheckBox("Depth-dependent deposition")
        self.chk_depth_deposition.setToolTip("5번은 etch/redeposition 없이 기본 deposition에만 깊이 감쇠를 적용합니다.")
        self.chk_depth_deposition.setChecked(False)
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
        self.depth_deposition_editor = DepthDepositionProfileEditor()
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

        self.btn_run = QPushButton("Run")
        self.btn_reset = QPushButton("Reset")
        self.btn_open_json = QPushButton("Open JSON")
        self.progress_run = QProgressBar()
        self.progress_run.setRange(0, 100)
        self.progress_run.setValue(0)
        self.progress_run.setTextVisible(True)
        self.progress_run.setFormat("Ready")
        self.progress_run.setVisible(False)
        self.progress_run.setFixedHeight(18)
        self.slider_frame = QSlider(Qt.Orientation.Horizontal)
        self.slider_frame.setRange(0, 0)
        self.slider_frame.setEnabled(False)
        self.lbl_status = QLabel("Cycle 0/0 | Points 0")
        self.edit_request_note = QPlainTextEdit()
        self.edit_request_note.setPlaceholderText("요청사항 / 물리 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
        self.edit_request_note.setMaximumHeight(88)
        self.edit_request_note.setPlainText("라운드 conformal offset 기반 트렌치 증착")
        self.lbl_run_dir = QLabel("저장된 run: 아직 없음")
        self.lbl_run_dir.setMinimumWidth(0)
        self.lbl_run_dir.setWordWrap(False)
        self.lbl_run_dir.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.btn_open_run_dir = QPushButton("Open Folder")
        self.btn_open_run_dir.setEnabled(False)

        self.cmb_emulator_default_preset = QComboBox()
        self.cmb_emulator_default_preset.setToolTip("Load the default process values for the selected emulator.")

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
        self.btn_split_options = QPushButton("Split Options")
        self.btn_split_options.setCheckable(True)
        self.btn_compare_options = QPushButton("Compare Options")
        self.btn_compare_options.setCheckable(True)
        self.btn_run_split = QPushButton("Run Split")
        self.btn_run_compare = QPushButton("Run Compare")

        status = QStatusBar(self)
        self.setStatusBar(status)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(QLabel("Frame"))
        controls.addWidget(self.slider_frame, 1)
        controls.addWidget(self.lbl_status)

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 0, 0, 0)
        run_row.addWidget(self.lbl_run_dir, 1)
        run_row.addWidget(self.btn_open_run_dir)

        self.view_tabs = QTabWidget()
        result_tab = QWidget()
        result_layout = QVBoxLayout()
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(self.view, 1)
        result_tab.setLayout(result_layout)

        self.btn_fit_structure = QPushButton("Fit")
        self.btn_reset_structure = QPushButton("Default")
        self.btn_load_structure_view = QPushButton("Load Structure")
        self.btn_save_structure_view = QPushButton("Save to Excel")
        self.btn_structure_next = QPushButton("Next: Smoothing")
        self.lbl_geometry_points = QLabel("Geometry: 0 pts")
        self.lbl_geometry_source = QLabel("Input: raw")
        self.lbl_geometry_source.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cmb_structure_library = QComboBox()
        self.edit_structure_name = QLineEdit()
        self.edit_structure_name.setPlaceholderText("Structure name / Excel sheet")
        self.btn_reload_structure_library = QPushButton("Reload")
        self.btn_load_structure = QPushButton("Load Structure")
        self.btn_save_structure = QPushButton("Save to Excel")
        self.btn_export_default_structures = QPushButton("Export Defaults")
        self.btn_open_structure_workbook = QPushButton("Open Excel")
        self.lbl_structure_library_path = QLabel("")
        self.lbl_structure_library_path.setWordWrap(True)
        self.lbl_structure_library_active = QLabel("Active: emulator default")
        self.lbl_structure_library_active.setWordWrap(True)
        structure_buttons = QHBoxLayout()
        structure_buttons.setContentsMargins(0, 0, 0, 0)
        structure_buttons.addWidget(self.btn_fit_structure)
        structure_buttons.addWidget(self.btn_reset_structure)
        structure_buttons.addWidget(self.btn_load_structure_view)
        structure_buttons.addWidget(self.btn_save_structure_view)
        structure_buttons.addWidget(self.lbl_geometry_points, 1)
        structure_buttons.addWidget(self.lbl_geometry_source)
        structure_buttons.addWidget(self.btn_structure_next)

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
        self.btn_apply_smoothing = QPushButton("Smooth")
        self.btn_use_smoothed_geometry = QPushButton("Use Smooth")
        self.btn_use_raw_geometry = QPushButton("Use Raw")
        self.btn_smoothing_back = QPushButton("Back: Structure")
        self.btn_smoothing_next = QPushButton("Next: Results")
        self.lbl_smoothing_status = QLabel("Smooth: not applied")
        smooth_grid = QGridLayout()
        smooth_grid.setContentsMargins(0, 0, 0, 0)
        smooth_grid.setHorizontalSpacing(8)
        smooth_grid.setVerticalSpacing(6)
        smooth_grid.addWidget(QLabel("Segments"), 0, 0)
        smooth_grid.addWidget(self.spin_smooth_segments, 0, 1)
        smooth_grid.addWidget(QLabel("Iters"), 0, 2)
        smooth_grid.addWidget(self.spin_smooth_iterations, 0, 3)
        smooth_grid.addWidget(self.btn_apply_smoothing, 0, 4)
        smooth_grid.addWidget(self.btn_use_smoothed_geometry, 1, 0, 1, 2)
        smooth_grid.addWidget(self.btn_use_raw_geometry, 1, 2, 1, 2)
        smooth_grid.addWidget(self.lbl_smoothing_status, 1, 4)

        smooth_nav = QHBoxLayout()
        smooth_nav.setContentsMargins(0, 0, 0, 0)
        smooth_nav.addWidget(self.btn_smoothing_back)
        smooth_nav.addStretch(1)
        smooth_nav.addWidget(self.btn_smoothing_next)

        smoothing_tab = QWidget()
        smoothing_layout = QVBoxLayout()
        smoothing_layout.setContentsMargins(0, 0, 0, 0)
        smoothing_layout.setSpacing(6)
        smoothing_layout.addWidget(self.smoothing_view, 1)
        smoothing_tab.setLayout(smoothing_layout)

        self.view_tabs.addTab(structure_tab, "1 Structure")
        self.view_tabs.addTab(smoothing_tab, "2 Smoothing")
        self.view_tabs.addTab(result_tab, "3 Result")

        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(8, 8, 6, 8)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.view_tabs, 1)
        self.result_controls_widget = QWidget()
        self.result_controls_widget.setLayout(controls)
        left_layout.addWidget(self.result_controls_widget)
        left_panel.setLayout(left_layout)

        emulator_group = QGroupBox("3 Result / Emulator Version")
        emulator_layout = QVBoxLayout()
        emulator_layout.setContentsMargins(10, 10, 10, 10)
        emulator_layout.addLayout(self.emulator_toggle_row)
        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.addWidget(QLabel("Default option"))
        preset_row.addWidget(self.cmb_emulator_default_preset, 1)
        emulator_layout.addLayout(preset_row)
        emulator_group.setLayout(emulator_layout)

        self.structure_points_model = PointsTableModel()
        self.structure_points_table = PointsTableView()
        self.structure_points_table.setModel(self.structure_points_model)
        self.structure_points_table.setMinimumHeight(160)
        self.structure_points_group = QGroupBox("Structure Points")
        structure_points_layout = QVBoxLayout()
        structure_points_layout.setContentsMargins(10, 10, 10, 10)
        structure_points_layout.addWidget(self.structure_points_table, 1)
        self.structure_points_group.setLayout(structure_points_layout)

        self.structure_library_group = QGroupBox("Structure Library")
        structure_library_layout = QGridLayout()
        structure_library_layout.setContentsMargins(10, 10, 10, 10)
        structure_library_layout.setHorizontalSpacing(8)
        structure_library_layout.setVerticalSpacing(8)
        structure_library_layout.addWidget(QLabel("Sheet"), 0, 0)
        structure_library_layout.addWidget(self.cmb_structure_library, 0, 1, 1, 3)
        structure_library_layout.addWidget(QLabel("Name"), 1, 0)
        structure_library_layout.addWidget(self.edit_structure_name, 1, 1, 1, 3)
        structure_library_layout.addWidget(self.btn_reload_structure_library, 2, 0)
        structure_library_layout.addWidget(self.btn_load_structure, 2, 1)
        structure_library_layout.addWidget(self.btn_save_structure, 2, 2)
        structure_library_layout.addWidget(self.btn_open_structure_workbook, 2, 3)
        structure_library_layout.addWidget(self.btn_export_default_structures, 3, 0, 1, 2)
        structure_library_layout.addWidget(self.lbl_structure_library_active, 3, 2, 1, 2)
        structure_library_layout.addWidget(self.lbl_structure_library_path, 4, 0, 1, 4)
        self.structure_library_group.setLayout(structure_library_layout)

        self.btn_load_overlay = QPushButton("Load Image")
        self.btn_clear_overlay = QPushButton("Clear Image")
        self.btn_move_overlay = QPushButton("Move Image")
        self.btn_move_overlay.setCheckable(True)
        self.btn_move_overlay.setEnabled(False)
        self.lbl_overlay_opacity = QLabel("Opacity")
        self.slider_overlay_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_overlay_opacity.setRange(0, 100)
        self.slider_overlay_opacity.setValue(int(round(self._overlay_opacity * 100.0)))
        self.slider_overlay_opacity.setFixedWidth(160)
        self.overlay_group = QGroupBox("Image Overlay")
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

        self.smoothing_controls_group = QGroupBox("Smoothing")
        smoothing_controls_layout = QVBoxLayout()
        smoothing_controls_layout.setContentsMargins(10, 10, 10, 10)
        smoothing_controls_layout.setSpacing(8)
        smoothing_controls_layout.addLayout(smooth_grid)
        smoothing_controls_layout.addLayout(smooth_nav)
        self.smoothing_controls_group.setLayout(smoothing_controls_layout)
        self.smoothed_points_model = PointsTableModel()
        self.smoothed_points_table = PointsTableView()
        self.smoothed_points_table.setModel(self.smoothed_points_model)
        self.smoothed_points_table.setEditTriggers(PointsTableView.NoEditTriggers)
        self.smoothed_points_table.setMinimumHeight(160)
        self.smoothed_points_group = QGroupBox("Smoothing Result Points")
        smoothed_points_layout = QVBoxLayout()
        smoothed_points_layout.setContentsMargins(10, 10, 10, 10)
        smoothed_points_layout.addWidget(self.smoothed_points_table, 1)
        self.smoothed_points_group.setLayout(smoothed_points_layout)

        params_group = QGroupBox("3 Result / Process Parameters")
        params_grid = QGridLayout()
        params_grid.setContentsMargins(10, 10, 10, 10)
        params_grid.setHorizontalSpacing(8)
        params_grid.setVerticalSpacing(8)
        self.lbl_deposition_section = self._make_parameter_section("Deposition base")
        self.lbl_etch_section = self._make_parameter_section(
            "Etch switch",
            color="#0f766e",
            background="#f0fdfa",
            border="#99f6e4",
        )
        self.lbl_sputter_section = self._make_parameter_section(
            "1번 Direct sputter kernel",
            color="#1d4ed8",
            background="#eff6ff",
            border="#bfdbfe",
        )
        self.lbl_ion_depth_section = self._make_parameter_section(
            "2번 Ion transmission - depth curve",
            color="#0e7490",
            background="#ecfeff",
            border="#a5f3fc",
        )
        self.lbl_ion_geometry_section = self._make_parameter_section(
            "2번 Geometry shadowing modifiers",
            color="#155e75",
            background="#f0f9ff",
            border="#bae6fd",
        )
        params_grid.addWidget(self.lbl_deposition_section, 0, 0, 1, 2)
        params_grid.addWidget(QLabel("Cycles"), 1, 0)
        params_grid.addWidget(self.spin_cycles, 1, 1)
        params_grid.addWidget(QLabel("Depo A/CYC"), 2, 0)
        params_grid.addWidget(self.spin_angstrom_per_cycle, 2, 1)
        params_grid.addWidget(self.lbl_etch_section, 3, 0, 1, 2)
        params_grid.addWidget(self.chk_sputter, 4, 0, 1, 2)
        params_grid.addWidget(self.lbl_sputter_section, 5, 0, 1, 2)
        self.lbl_sputter_strength = QLabel("Etch A/CYC")
        self.lbl_sputter_peak_pct = QLabel("Peak %")
        self.lbl_sputter_peak = QLabel("Peak")
        self.lbl_sputter_width = QLabel("Width")
        self.lbl_sputter_smoothing = QLabel("Smooth A")
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
            "3번 신규 Reflected ion",
            color="#b45309",
            background="#fff7ed",
            border="#fed7aa",
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
            "4번 Sputter redeposition",
            color="#7c2d12",
            background="#fff7ed",
            border="#fdba74",
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
            "5번 Depth depo only",
            color="#166534",
            background="#f0fdf4",
            border="#bbf7d0",
        )
        params_grid.addWidget(self.lbl_depth_depo_section, 35, 0, 1, 2)
        params_grid.addWidget(self.chk_depth_deposition, 36, 0, 1, 2)
        self.lbl_depth_feature_type = QLabel("Feature")
        self.lbl_depth_feature_width = QLabel("Width A")
        self.lbl_depth_feature_depth = QLabel("Depth A")
        self.lbl_depth_feature_length = QLabel("Length A")
        self.lbl_depth_decay_k = QLabel("Decay K")
        self.lbl_depth_decay_power = QLabel("Power")
        self.lbl_depth_min_ratio = QLabel("Min %")
        self.lbl_depth_closure_section = self._make_parameter_section(
            "Closure residual fill",
            color="#3f6212",
            background="#f7fee7",
            border="#d9f99d",
        )
        self.lbl_depth_closure_threshold = QLabel("Close A")
        self.lbl_depth_post_fill_hole = QLabel("Hole fill %")
        self.lbl_depth_post_fill_line = QLabel("Line fill %")
        self.lbl_depth_line_open_path = QLabel("Line open")
        self.lbl_depth_residual_decay = QLabel("Decay len A")
        self.btn_depth_advanced = QPushButton("Advanced fill options")
        self.btn_depth_advanced.setCheckable(True)
        self.lbl_depth_parameter_help = QLabel(
            "Depth map: deeper areas receive less deposition. Drag the dots or use the fields."
        )
        self.lbl_depth_parameter_help.setWordWrap(True)
        self.lbl_depth_parameter_help.setStyleSheet(
            "QLabel { color: #334155; background: #f8fafc; border: 1px solid #d9f99d; "
            "border-radius: 4px; padding: 6px; }"
        )
        for widget, tooltip in (
            (self.lbl_depth_feature_type, "Hole은 원형/컨택홀, Line은 길게 열린 트렌치의 등가 aspect ratio로 계산합니다."),
            (self.cmb_depth_feature_type, "Hole은 원형/컨택홀, Line은 길게 열린 트렌치의 등가 aspect ratio로 계산합니다."),
            (self.lbl_depth_feature_width, "입구 폭입니다. 폭이 좁을수록 같은 깊이에서 등가 AR이 커져 증착 비율이 낮아집니다."),
            (self.spin_depth_feature_width, "입구 폭입니다. 폭이 좁을수록 같은 깊이에서 등가 AR이 커져 증착 비율이 낮아집니다."),
            (self.lbl_depth_feature_depth, "시각 편집기의 100% 깊이와 depth-dependent attenuation 계산 기준 깊이입니다."),
            (self.spin_depth_feature_depth, "시각 편집기의 100% 깊이와 depth-dependent attenuation 계산 기준 깊이입니다."),
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
            (self.lbl_depth_post_fill_hole, "Hole closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.spin_depth_post_fill_hole_pct, "Hole closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.lbl_depth_post_fill_line, "Line closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.spin_depth_post_fill_line_pct, "Line closure 후 남은 void 중 추가로 채울 수 있는 면적 비율입니다."),
            (self.lbl_depth_line_open_path, "Line 구조에서 열려 있는 우회 경로를 얼마나 인정할지 정합니다."),
            (self.spin_depth_line_open_path, "Line 구조에서 열려 있는 우회 경로를 얼마나 인정할지 정합니다."),
            (self.lbl_depth_residual_decay, "Closure 후 잔류 fill이 깊이 방향으로 줄어드는 길이 스케일입니다."),
            (self.spin_depth_residual_decay, "Closure 후 잔류 fill이 깊이 방향으로 줄어드는 길이 스케일입니다."),
        ):
            widget.setToolTip(tooltip)
        params_grid.addWidget(self.lbl_depth_feature_type, 37, 0)
        params_grid.addWidget(self.cmb_depth_feature_type, 37, 1)
        params_grid.addWidget(self.lbl_depth_feature_width, 38, 0)
        params_grid.addWidget(self.spin_depth_feature_width, 38, 1)
        params_grid.addWidget(self.lbl_depth_feature_depth, 39, 0)
        params_grid.addWidget(self.spin_depth_feature_depth, 39, 1)
        params_grid.addWidget(self.lbl_depth_feature_length, 40, 0)
        params_grid.addWidget(self.spin_depth_feature_length, 40, 1)
        params_grid.addWidget(self.lbl_depth_decay_k, 41, 0)
        params_grid.addWidget(self.spin_depth_decay_k, 41, 1)
        params_grid.addWidget(self.lbl_depth_decay_power, 42, 0)
        params_grid.addWidget(self.spin_depth_decay_power, 42, 1)
        params_grid.addWidget(self.lbl_depth_min_ratio, 43, 0)
        params_grid.addWidget(self.spin_depth_min_ratio_pct, 43, 1)
        params_grid.addWidget(self.btn_depth_advanced, 44, 0, 1, 2)
        params_grid.addWidget(self.lbl_depth_closure_section, 45, 0, 1, 2)
        params_grid.addWidget(self.lbl_depth_closure_threshold, 46, 0)
        params_grid.addWidget(self.spin_depth_closure_threshold, 46, 1)
        params_grid.addWidget(self.lbl_depth_post_fill_hole, 47, 0)
        params_grid.addWidget(self.spin_depth_post_fill_hole_pct, 47, 1)
        params_grid.addWidget(self.lbl_depth_post_fill_line, 48, 0)
        params_grid.addWidget(self.spin_depth_post_fill_line_pct, 48, 1)
        params_grid.addWidget(self.lbl_depth_line_open_path, 49, 0)
        params_grid.addWidget(self.spin_depth_line_open_path, 49, 1)
        params_grid.addWidget(self.lbl_depth_residual_decay, 50, 0)
        params_grid.addWidget(self.spin_depth_residual_decay, 50, 1)
        params_group.setLayout(params_grid)

        self.redepo_lobe_group = QGroupBox("4 Redeposition Lobe")
        redepo_lobe_layout = QVBoxLayout()
        redepo_lobe_layout.setContentsMargins(8, 8, 8, 8)
        redepo_lobe_layout.addWidget(self.redepo_lobe_editor)
        self.redepo_lobe_group.setLayout(redepo_lobe_layout)

        action_group = QGroupBox("3 Results / Run")
        action_layout = QVBoxLayout()
        action_layout.setContentsMargins(10, 10, 10, 10)
        action_buttons = QHBoxLayout()
        action_buttons.addWidget(self.btn_open_json)
        action_buttons.addWidget(self.btn_run)
        action_buttons.addWidget(self.btn_reset)
        action_layout.addLayout(action_buttons)
        action_layout.addWidget(self.progress_run)
        result_option_buttons = QHBoxLayout()
        result_option_buttons.addWidget(self.btn_split_options)
        result_option_buttons.addWidget(self.btn_compare_options)
        action_layout.addLayout(result_option_buttons)
        action_layout.addLayout(run_row)
        action_group.setLayout(action_layout)

        split_group = QGroupBox("Split Options")
        split_grid = QGridLayout()
        split_grid.setContentsMargins(10, 10, 10, 10)
        split_grid.setHorizontalSpacing(8)
        split_grid.setVerticalSpacing(8)
        split_grid.addWidget(QLabel("Target"), 0, 0)
        split_grid.addWidget(self.cmb_split_parameter, 0, 1)
        split_grid.addWidget(QLabel("Start"), 1, 0)
        split_grid.addWidget(self.spin_split_start, 1, 1)
        split_grid.addWidget(QLabel("End"), 2, 0)
        split_grid.addWidget(self.spin_split_end, 2, 1)
        split_grid.addWidget(QLabel("Step"), 3, 0)
        split_grid.addWidget(self.spin_split_step, 3, 1)
        split_buttons = QHBoxLayout()
        split_buttons.addWidget(self.btn_run_split)
        split_grid.addLayout(split_buttons, 4, 0, 1, 2)
        split_group.setLayout(split_grid)
        split_group.setVisible(False)

        compare_group = QGroupBox("Compare Options")
        compare_grid = QGridLayout()
        compare_grid.setContentsMargins(10, 10, 10, 10)
        compare_grid.setHorizontalSpacing(8)
        compare_grid.setVerticalSpacing(8)
        compare_grid.addWidget(QLabel("Compare to"), 0, 0)
        compare_grid.addWidget(self.cmb_compare_target, 0, 1)
        compare_grid.addWidget(self.btn_run_compare, 1, 0, 1, 2)
        compare_group.setLayout(compare_grid)
        compare_group.setVisible(False)

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

        depth_profile_group = QGroupBox("5 Depth Deposition Map")
        depth_profile_layout = QVBoxLayout()
        depth_profile_layout.setContentsMargins(10, 10, 10, 10)
        depth_profile_layout.setSpacing(8)
        depth_profile_layout.addWidget(self.lbl_depth_parameter_help)
        depth_profile_layout.addWidget(self.depth_deposition_editor)
        depth_profile_group.setLayout(depth_profile_layout)

        self.emulator_group = emulator_group
        self.params_group = params_group
        self.action_group = action_group
        self.split_group = split_group
        self.compare_group = compare_group
        self.note_group = note_group
        self.ion_map_group = ion_map_group
        self.depth_profile_group = depth_profile_group
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
            self.lbl_depth_feature_type,
            self.cmb_depth_feature_type,
            self.lbl_depth_feature_width,
            self.spin_depth_feature_width,
            self.lbl_depth_feature_depth,
            self.spin_depth_feature_depth,
            self.lbl_depth_feature_length,
            self.spin_depth_feature_length,
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
            self.depth_deposition_editor,
        ]

        self.btn_structure_panel_next = QPushButton("Next: Smoothing")
        self.btn_smoothing_panel_back = QPushButton("Back: Structure")
        self.btn_smoothing_panel_next = QPushButton("Next: Results")
        self.btn_results_panel_back = QPushButton("Back: Smoothing")

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

        self.results_panel_content = QWidget()
        results_panel_layout = QVBoxLayout()
        results_panel_layout.setContentsMargins(0, 0, 0, 0)
        results_panel_layout.setSpacing(8)
        results_panel_layout.addWidget(emulator_group)
        results_panel_layout.addWidget(action_group)
        results_panel_layout.addWidget(params_group)
        results_panel_layout.addWidget(gaussian_group)
        results_panel_layout.addWidget(ion_map_group)
        results_panel_layout.addWidget(self.redepo_lobe_group)
        results_panel_layout.addWidget(depth_profile_group)
        results_panel_layout.addWidget(split_group)
        results_panel_layout.addWidget(compare_group)
        results_panel_layout.addWidget(note_group)
        results_panel_nav = QHBoxLayout()
        results_panel_nav.setContentsMargins(0, 0, 0, 0)
        results_panel_nav.addWidget(self.btn_results_panel_back)
        results_panel_nav.addStretch(1)
        results_panel_layout.addLayout(results_panel_nav)
        results_panel_layout.addStretch(1)
        self.results_panel_content.setLayout(results_panel_layout)

        def make_workflow_scroll(content: QWidget) -> QScrollArea:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            return scroll

        self.structure_scroll_area = make_workflow_scroll(self.structure_panel_content)
        self.smoothing_scroll_area = make_workflow_scroll(self.smoothing_panel_content)
        self.results_scroll_area = make_workflow_scroll(self.results_panel_content)
        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.addTab(self.structure_scroll_area, "1 Structure")
        self.workflow_tabs.addTab(self.smoothing_scroll_area, "2 Smoothing")
        self.workflow_tabs.addTab(self.results_scroll_area, "3 Result")

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

        self.btn_run.clicked.connect(self.run_emulation)
        self.btn_reset.clicked.connect(self.reset_defaults)
        self.btn_open_json.clicked.connect(self.open_replay_json_dialog)
        self.btn_open_run_dir.clicked.connect(self.open_last_run_dir)
        self.btn_run_split.clicked.connect(self.run_split_test)
        self.btn_run_compare.clicked.connect(self.run_compare_for_active_emulator)
        self.btn_split_options.toggled.connect(self._on_split_options_toggled)
        self.btn_compare_options.toggled.connect(self._on_compare_options_toggled)
        self.view_tabs.currentChanged.connect(self._on_view_workflow_tab_changed)
        self.workflow_tabs.currentChanged.connect(self._on_control_workflow_tab_changed)
        self.btn_structure_next.clicked.connect(lambda: self._set_workflow_step("smoothing"))
        self.btn_smoothing_back.clicked.connect(lambda: self._set_workflow_step("structure"))
        self.btn_smoothing_next.clicked.connect(lambda: self._set_workflow_step("results"))
        self.btn_structure_panel_next.clicked.connect(lambda: self._set_workflow_step("smoothing"))
        self.btn_smoothing_panel_back.clicked.connect(lambda: self._set_workflow_step("structure"))
        self.btn_smoothing_panel_next.clicked.connect(lambda: self._set_workflow_step("results"))
        self.btn_results_panel_back.clicked.connect(lambda: self._set_workflow_step("smoothing"))
        self.btn_load_overlay.clicked.connect(self._load_overlay_image)
        self.btn_clear_overlay.clicked.connect(self._clear_overlay_image)
        self.btn_move_overlay.toggled.connect(self._on_overlay_move_toggled)
        self.slider_overlay_opacity.valueChanged.connect(self._on_overlay_opacity_changed)
        self.structure_points_model.pointEditRequested.connect(self._on_structure_table_point_edit_requested)
        self.structure_points_table.deleteRowsRequested.connect(self._on_structure_table_delete_rows_requested)
        self.structure_points_table.replacePointsRequested.connect(self._on_structure_table_replace_points_requested)
        self.cmb_split_parameter.currentIndexChanged.connect(self.apply_split_parameter_defaults)
        self.slider_frame.valueChanged.connect(self.show_frame)
        self.chk_sputter.toggled.connect(self.sync_etch_control_availability)
        self.chk_ion_transmission.toggled.connect(self.sync_etch_control_availability)
        self.chk_reflected_ion.toggled.connect(self.sync_etch_control_availability)
        self.chk_redepo.toggled.connect(self.sync_etch_control_availability)
        self.chk_depth_deposition.toggled.connect(self.sync_etch_control_availability)
        self.spin_sputter_strength.valueChanged.connect(self.sync_sputter_curve_cap_from_spin)
        self.spin_sputter_peak_pct.valueChanged.connect(self.sync_sputter_curve_from_spins)
        self.spin_sputter_peak.valueChanged.connect(self.sync_sputter_curve_from_spins)
        self.spin_sputter_width.valueChanged.connect(self.sync_sputter_curve_from_spins)
        self.sputter_curve_editor.parametersChanged.connect(self.apply_sputter_curve_parameters)
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
        self.spin_depth_feature_width.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_feature_depth.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_feature_length.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_decay_k.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_decay_power.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_min_ratio_pct.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.spin_depth_closure_threshold.valueChanged.connect(self.sync_depth_deposition_editor_from_spins)
        self.depth_deposition_editor.parametersChanged.connect(self.apply_depth_deposition_editor_parameters)
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
        self.btn_load_structure.clicked.connect(self.load_selected_structure_from_library)
        self.btn_load_structure_view.clicked.connect(self.load_selected_structure_from_library)
        self.btn_save_structure.clicked.connect(self.save_current_structure_to_library)
        self.btn_save_structure_view.clicked.connect(self.save_current_structure_to_library)
        self.btn_export_default_structures.clicked.connect(self.export_default_structures_to_library)
        self.btn_open_structure_workbook.clicked.connect(self.open_structure_library_workbook)
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
        self.apply_emulator_mode(run=False)
        self._reset_geometry_to_default()
        self.sync_depth_deposition_editor_from_spins()
        self._set_workflow_step("structure")

    def _structure_library_sheet_for_emulator(self, number: int) -> str:
        return DEFAULT_EMULATOR_STRUCTURE_SHEETS.get(int(number), "")

    def _fallback_points_for_emulator(self, number: int) -> List[Tuple[float, float]]:
        if int(number) == 2:
            return [(float(x), float(y)) for x, y in ION_TRANSMISSION_STEPPED_TRENCH_POINTS]
        if int(number) in (5, 6):
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
                QMessageBox.warning(self, "Structure Library", f"Failed to read structure workbook:\n{exc}")

        previous = self.cmb_structure_library.currentText()
        self.cmb_structure_library.blockSignals(True)
        try:
            self.cmb_structure_library.clear()
            self.cmb_structure_library.addItems(names)
            idx = self.cmb_structure_library.findText(previous)
            if idx >= 0:
                self.cmb_structure_library.setCurrentIndex(idx)
        finally:
            self.cmb_structure_library.blockSignals(False)

        has_workbook = self._structure_library_path.exists()
        has_structures = bool(names)
        self.cmb_structure_library.setEnabled(has_structures)
        self.btn_load_structure.setEnabled(has_structures)
        self.btn_load_structure_view.setEnabled(has_structures)
        self.btn_open_structure_workbook.setEnabled(True)
        self.lbl_structure_library_path.setText(f"Workbook: {self._structure_library_path}")
        self._update_structure_library_active_label()
        if show_status:
            if has_workbook:
                self.statusBar().showMessage(f"Structure workbook loaded: {len(names)} sheets", 2200)
            else:
                self.statusBar().showMessage("Structure workbook not created yet", 2200)

    def _update_structure_library_active_label(self) -> None:
        active = self._active_structure_sheet_name or "emulator default"
        self.lbl_structure_library_active.setText(f"Active: {active}")
        if self._active_structure_sheet_name and not self.edit_structure_name.text().strip():
            self.edit_structure_name.setText(self._active_structure_sheet_name)

    def load_selected_structure_from_library(self, _checked: bool = False) -> None:
        sheet_name = self.cmb_structure_library.currentText().strip()
        if not sheet_name:
            QMessageBox.information(self, "Structure Library", "No structure sheet is selected.")
            return
        try:
            points = read_structure_points(self._structure_library_path, sheet_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Structure Library", f"Failed to load structure '{sheet_name}':\n{exc}")
            return
        self._active_structure_sheet_name = sheet_name
        self.edit_structure_name.setText(sheet_name)
        self._set_structure_points(points, fit=True)
        self._update_structure_library_active_label()
        self.statusBar().showMessage(f"Loaded structure: {sheet_name}", 2200)

    def save_current_structure_to_library(self, _checked: bool = False) -> None:
        points = list(self._structure_points or self._current_geometry_points())
        if len(points) < 2:
            QMessageBox.warning(self, "Structure Library", "At least two XY points are required.")
            return
        sheet_name = sanitize_structure_name(
            self.edit_structure_name.text().strip()
            or self.cmb_structure_library.currentText().strip()
            or self._active_structure_sheet_name
            or f"structure_{self.active_emulator_number():02d}"
        )
        try:
            saved_name = save_structure_points(self._structure_library_path, sheet_name, points)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Structure Library", f"Failed to save structure:\n{exc}")
            return
        self._active_structure_sheet_name = saved_name
        self.edit_structure_name.setText(saved_name)
        self.refresh_structure_library(show_status=False)
        idx = self.cmb_structure_library.findText(saved_name)
        if idx >= 0:
            self.cmb_structure_library.setCurrentIndex(idx)
        self._update_structure_library_active_label()
        self.statusBar().showMessage(f"Saved structure: {saved_name}", 2200)

    def export_default_structures_to_library(self, _checked: bool = False) -> None:
        try:
            written = ensure_default_structures(self._structure_library_path, overwrite=False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Structure Library", f"Failed to export default structures:\n{exc}")
            return
        self.refresh_structure_library(show_status=False)
        if written:
            self.statusBar().showMessage(f"Exported {len(written)} default structure sheets", 2600)
        else:
            self.statusBar().showMessage("Default structure sheets already exist", 2200)

    def open_structure_library_workbook(self, _checked: bool = False) -> None:
        if not self._structure_library_path.exists():
            self.export_default_structures_to_library()
        if self._structure_library_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._structure_library_path.resolve())))

    def _set_structure_points(
        self,
        points: Sequence[Tuple[float, float]],
        *,
        clear_smoothing: bool = True,
        fit: bool = True,
    ) -> None:
        pts = [(float(x), float(y)) for x, y in points]
        self._structure_points = pts
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
        self._refresh_result_input_preview_if_idle()
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

    def _on_structure_table_point_edit_requested(self, row: int, x: float, y: float) -> None:
        if self._syncing_structure_table:
            return
        self._syncing_structure_table = True
        try:
            self.structure_points_model.set_point(int(row), (float(x), float(y)))
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
        self._set_structure_points(points, fit=True)

    def _reset_geometry_to_default(self, _checked: bool = False) -> None:
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
        self._update_structure_library_active_label()
        self.statusBar().showMessage("Geometry reset to emulator default", 1800)

    def _fit_structure_views(self, _checked: bool = False) -> None:
        self.structure_view.fit_points()
        self.smoothing_view.fit_points()

    def _mark_structure_edited(self) -> None:
        self._sync_structure_table_from_points()
        if self._smoothed_points or self._use_smoothed_geometry:
            self._smoothed_points = []
            self._use_smoothed_geometry = False
            self.smoothing.revert()
            self.smoothing_view.set_reference_profiles_xy([])
            self.smoothing_view.set_points_xy(list(self._structure_points))
            self._sync_smoothed_table_from_points()
        self._update_geometry_labels()
        self._refresh_result_input_preview_if_idle()

    def _on_structure_point_moved(self, idx: int, x: float, y: float) -> None:
        if self._syncing_structure_view:
            return
        if 0 <= int(idx) < len(self._structure_points):
            self._structure_points[int(idx)] = (float(x), float(y))
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
            self._sync_smoothed_table_from_points()
            self._update_geometry_labels()
            self._refresh_result_input_preview_if_idle()

    def _on_smoothed_point_inserted(self, idx: int, x: float, y: float) -> None:
        if not self._smoothed_points:
            return
        insert_idx = max(0, min(int(idx), len(self._smoothed_points)))
        self._smoothed_points.insert(insert_idx, (float(x), float(y)))
        self._use_smoothed_geometry = True
        self._sync_smoothed_table_from_points()
        self._update_geometry_labels()
        self._refresh_result_input_preview_if_idle()

    def _on_smoothed_point_deleted(self, idx: int) -> None:
        delete_idx = int(idx)
        if 0 <= delete_idx < len(self._smoothed_points):
            self._smoothed_points.pop(delete_idx)
            self._use_smoothed_geometry = len(self._smoothed_points) >= 2
            self._sync_smoothed_table_from_points()
            self._update_geometry_labels()
            self._refresh_result_input_preview_if_idle()

    def apply_structure_smoothing(self, _checked: bool = False) -> None:
        if len(self._structure_points) < 2:
            QMessageBox.warning(self, "Structure Smoothing", "At least two geometry points are required.")
            return
        self.smoothing.set_base_points(list(self._structure_points))
        self.smoothing.set_params(
            int(self.spin_smooth_segments.value()),
            int(self.spin_smooth_iterations.value()),
        )
        self._smoothed_points = [(float(x), float(y)) for x, y in self.smoothing.run()]
        self._use_smoothed_geometry = True
        self.smoothing_view.set_reference_profiles_xy([list(self._structure_points)])
        self.smoothing_view.set_points_xy(list(self._smoothed_points))
        self._sync_smoothed_table_from_points()
        self._update_geometry_labels()
        self._refresh_result_input_preview_if_idle()
        QTimer.singleShot(0, self.smoothing_view.fit_points)
        self.statusBar().showMessage(f"Smoothing applied: {len(self._smoothed_points)} points", 2500)

    def use_smoothed_geometry(self, _checked: bool = False) -> None:
        if not self._smoothed_points:
            self.apply_structure_smoothing()
            return
        self._use_smoothed_geometry = True
        self._update_geometry_labels()
        self._refresh_result_input_preview_if_idle()
        self.statusBar().showMessage("Run input switched to smoothed geometry", 1800)

    def use_raw_geometry(self, _checked: bool = False) -> None:
        self._use_smoothed_geometry = False
        self._update_geometry_labels()
        self._refresh_result_input_preview_if_idle()
        self.statusBar().showMessage("Run input switched to raw geometry", 1800)

    def _current_geometry_points(self) -> Tuple[Tuple[float, float], ...]:
        if self._use_smoothed_geometry and len(self._smoothed_points) >= 2:
            return tuple(self._smoothed_points)
        if len(self._structure_points) >= 2:
            return tuple(self._structure_points)
        return tuple(self._default_points_for_active_emulator())

    def _current_geometry_source_name(self) -> str:
        if self._use_smoothed_geometry and len(self._smoothed_points) >= 2:
            return "smooth"
        return "raw"

    def _has_active_smoothed_geometry(self) -> bool:
        return bool(self._use_smoothed_geometry and len(self._smoothed_points) >= 2)

    def _result_has_run_frames(self) -> bool:
        return self._result is not None and bool(self._result.frame_profiles)

    def _refresh_result_input_preview_if_idle(self, *, fit: bool = False) -> None:
        if self._result_has_run_frames():
            return
        if not hasattr(self, "view_tabs") or self.view_tabs.currentIndex() != 2:
            return
        self._show_result_input_preview(fit=fit)

    def _sync_structure_minimap_editors(self) -> None:
        if not hasattr(self, "ion_transmission_editor") or not hasattr(self, "depth_deposition_editor"):
            return
        points = self._current_geometry_points()
        self.ion_transmission_editor.set_structure_points(points)
        self.depth_deposition_editor.set_structure_points(points)

    def _show_result_input_preview(self, *, fit: bool = False) -> None:
        points = [(float(x), float(y)) for x, y in self._current_geometry_points()]
        if len(points) < 2:
            self.view.clear_data()
            self.lbl_status.setText("Input preview: empty | Points 0")
            return
        self.view.set_frames(
            [points],
            voids=[[]],
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
            f"Input preview: {self._current_geometry_source_name()} | Points {len(points)}"
        )

    def _update_geometry_labels(self) -> None:
        raw_count = len(self._structure_points)
        smooth_count = len(self._smoothed_points)
        input_count = smooth_count if self._use_smoothed_geometry and smooth_count >= 2 else raw_count
        self.lbl_geometry_points.setText(f"Geometry: {raw_count} pts")
        if self._use_smoothed_geometry and smooth_count >= 2:
            source_text = f"Input: smooth ({input_count} pts)"
        else:
            source_text = f"Input: raw ({input_count} pts)"
        self.lbl_geometry_source.setText(source_text)
        self.lbl_smoothing_status.setText(
            f"Smooth: {smooth_count} pts" if smooth_count else "Smooth: not applied"
        )
        self.btn_use_smoothed_geometry.setEnabled(smooth_count >= 2)
        self._sync_structure_minimap_editors()

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
            "Load Image",
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
            QMessageBox.warning(self, "Image Overlay", "Calibration scale must be greater than zero.")
            return
        if not self._set_overlay_image(str(image_path), scale_a_per_px=float(scale), align_to_axes=True):
            QMessageBox.warning(self, "Image Overlay", "Failed to load the selected image.")
            return
        self.statusBar().showMessage("Image overlay loaded", 2000)

    def _clear_overlay_image(self, _checked: bool = False) -> None:
        self.structure_view.clear_overlay_image()
        self.smoothing_view.clear_overlay_image()
        self._overlay_path = None
        self._update_overlay_move_button_state()
        self.statusBar().showMessage("Image overlay cleared", 1500)

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
        if normalized in {"result", "results", "3"}:
            return 2
        return 0

    def _set_workflow_step(self, step: str) -> None:
        self._set_workflow_index(self._workflow_index_for_step(step))

    def _set_workflow_index(self, index: int) -> None:
        workflow_index = max(0, min(2, int(index)))
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
            self._refresh_result_input_preview_if_idle(fit=True)

    def _sync_result_controls_visibility(self, workflow_index: Optional[int] = None) -> None:
        index = self.view_tabs.currentIndex() if workflow_index is None else int(workflow_index)
        self.result_controls_widget.setVisible(index == 2)

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
        preserve_smoothed_geometry = self._has_active_smoothed_geometry()
        button.setChecked(True)
        self.apply_emulator_mode(run=run, preserve_geometry=preserve_smoothed_geometry)
        if target != previous and not preserve_smoothed_geometry:
            self._set_workflow_step("structure")
        elif target != previous:
            self._refresh_result_input_preview_if_idle(fit=True)

    def _active_emulator_supports_sputter(self) -> bool:
        return self.active_emulator_number() in (1, 2, 3, 4)

    def _active_emulator_supports_ion_transmission(self) -> bool:
        return self.active_emulator_number() == 2

    def _active_emulator_supports_reflected_ion(self) -> bool:
        return self.active_emulator_number() == 3

    def _active_emulator_supports_redeposition(self) -> bool:
        return self.active_emulator_number() == 4

    def _active_emulator_supports_depth_deposition(self) -> bool:
        return self.active_emulator_number() in (5, 6)

    @staticmethod
    def _emulator_supports_sputter(number: int) -> bool:
        return int(number) in (1, 2, 3, 4)

    @staticmethod
    def _emulator_supports_ion_transmission(number: int) -> bool:
        return int(number) == 2

    @staticmethod
    def _emulator_supports_reflected_ion(number: int) -> bool:
        return int(number) == 3

    @staticmethod
    def _emulator_supports_redeposition(number: int) -> bool:
        return int(number) == 4

    @staticmethod
    def _emulator_supports_depth_deposition(number: int) -> bool:
        return int(number) in (5, 6)

    def _populate_compare_targets(self) -> None:
        previous = self.cmb_compare_target.currentData()
        active = self.active_emulator_number()
        default_target: object
        if active in (2, 3, 4):
            default_target = 1
        elif active == 5:
            default_target = 6
        elif active == 6:
            default_target = 5
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
            self.cmb_compare_target.addItem(f"Emulator {target:02d} - {_emulator_mode_title(target)}", target)
        if self._emulator_supports_sputter(active):
            self.cmb_compare_target.addItem("GapSim angle-only legacy", "legacy_gapsim_angle")

        restored_idx = self.cmb_compare_target.findData(previous)
        default_idx = self.cmb_compare_target.findData(default_target)
        if restored_idx >= 0:
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
                ("Redepo %", "redepo_efficiency_pct"),
                ("Emit power", "redepo_emit_power"),
                ("Dist power", "redepo_distance_power"),
                ("Soft LOS", "redepo_soft_los_radius_points"),
                *options,
            ]
        if self._active_emulator_supports_depth_deposition():
            options = [
                ("Depth decay", "deposition_depth_decay_k"),
                ("Depth power", "deposition_depth_decay_power"),
                ("Min depo ratio", "deposition_min_ratio"),
                ("Closure threshold", "deposition_closure_threshold_a"),
                ("Hole post-fill", "deposition_post_closure_fill_pct_hole"),
                ("Line post-fill", "deposition_post_closure_fill_pct_line"),
                ("Line open path", "deposition_line_open_path_factor"),
                ("Residual decay", "deposition_residual_fill_decay_length_a"),
                *options,
            ]
            if self.active_emulator_number() == 6:
                options = [
                    ("Inhibit %", "inhibition_strength_pct"),
                    ("Inhibit depth", "inhibition_penetration_depth_a"),
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
            f"Default option loaded: {self.cmb_emulator_default_preset.currentText()}",
            1800,
        )

    def _apply_emulator_preset(self, settings: dict[str, object]) -> None:
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion = self._active_emulator_supports_ion_transmission()
        supports_reflected = self._active_emulator_supports_reflected_ion()
        supports_redepo = self._active_emulator_supports_redeposition()
        supports_depth = self._active_emulator_supports_depth_deposition()

        self.spin_cycles.setValue(int(settings.get("cycles", self.spin_cycles.value())))
        self.spin_angstrom_per_cycle.setValue(float(settings.get("depo", self.spin_angstrom_per_cycle.value())))
        self.chk_sputter.setChecked(bool(supports_sputter and settings.get("sputter", supports_sputter)))
        self.chk_ion_transmission.setChecked(bool(supports_ion and settings.get("ion", supports_ion)))
        self.chk_reflected_ion.setChecked(bool(supports_reflected and settings.get("reflected", supports_reflected)))
        self.chk_redepo.setChecked(bool(supports_redepo and settings.get("redepo", supports_redepo)))
        self.chk_depth_deposition.setChecked(bool(supports_depth and settings.get("depth", supports_depth)))

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
        self.spin_depth_decay_k.setValue(float(settings.get("depth_k", self.spin_depth_decay_k.value())))
        self.spin_depth_decay_power.setValue(float(settings.get("depth_power", self.spin_depth_decay_power.value())))
        self.spin_depth_min_ratio_pct.setValue(float(settings.get("depth_min", self.spin_depth_min_ratio_pct.value())))

        self.sync_sputter_curve_from_spins()
        self.sync_ion_transmission_editor_from_spins()
        self.sync_redepo_lobe_from_spins()
        self.sync_depth_deposition_editor_from_spins()
        self.sync_etch_control_availability()

    def apply_emulator_mode(
        self,
        _index: int = 0,
        *,
        run: bool = True,
        preserve_geometry: bool = False,
    ) -> None:
        number = self.active_emulator_number()
        changed = number != self._active_emulator_number
        self._active_emulator_number = number
        supports_sputter = self._active_emulator_supports_sputter()

        self.setWindowTitle(f"Trench Depo Emulation - Emulator {number:02d}")
        if changed and not preserve_geometry:
            self._reset_geometry_to_default()
        if supports_sputter:
            if number == 2:
                self.lbl_etch_section.setText("Etch switch (1번 direct + 2번 modifier)")
            elif number == 3:
                self.lbl_etch_section.setText("Etch switch (1번 direct + 3번 reflected)")
            elif number == 4:
                self.lbl_etch_section.setText("Etch switch (2번 source + 4번 redepo)")
            else:
                self.lbl_etch_section.setText("Etch switch (1번 direct)")
            self.lbl_sputter_section.setText(
                "1번 Direct sputter kernel" if number == 1 else "기존 1번 Direct sputter kernel"
            )
        for widget in self._sputter_widgets:
            widget.setVisible(supports_sputter)
        supports_ion_transmission = self._active_emulator_supports_ion_transmission()
        supports_reflected_ion = self._active_emulator_supports_reflected_ion()
        supports_redeposition = self._active_emulator_supports_redeposition()
        supports_depth_deposition = self._active_emulator_supports_depth_deposition()
        for widget in self._ion_transmission_widgets:
            widget.setVisible(supports_ion_transmission)
        for widget in self._reflected_ion_widgets:
            widget.setVisible(supports_reflected_ion)
        for widget in self._redeposition_widgets:
            widget.setVisible(supports_redeposition)
        for widget in self._depth_deposition_widgets:
            widget.setVisible(supports_depth_deposition)
        self.gaussian_group.setVisible(supports_sputter)
        self._populate_compare_targets()
        self.ion_map_group.setTitle("2 Ion Transmission Depth Map")
        self.gaussian_group.setTitle("1 Direct Sputter Gaussian")
        self.depth_profile_group.setTitle(
            "6 Inhibition Base Depth Map" if number == 6 else "5 Depth Deposition Map"
        )

        if supports_sputter:
            self.chk_depth_deposition.setChecked(False)
            if changed:
                self.chk_sputter.setChecked(True)
                self.chk_ion_transmission.setChecked(supports_ion_transmission)
                self.chk_reflected_ion.setChecked(supports_reflected_ion)
                self.chk_redepo.setChecked(supports_redeposition)
            if supports_ion_transmission:
                self.edit_request_note.setPlaceholderText("요청사항 / ion transmission, shadowing 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            elif supports_reflected_ion:
                self.edit_request_note.setPlaceholderText("요청사항 / reflected ion, bowing, microtrenching 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            elif supports_redeposition:
                self.edit_request_note.setPlaceholderText("요청사항 / redeposition 결합 가설과 비교 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            else:
                self.edit_request_note.setPlaceholderText("요청사항 / etch 물리 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
        elif supports_depth_deposition:
            self.chk_sputter.setChecked(False)
            self.chk_ion_transmission.setChecked(False)
            self.chk_reflected_ion.setChecked(False)
            self.chk_redepo.setChecked(False)
            if changed:
                self.chk_depth_deposition.setChecked(True)
                self.cmb_depth_feature_type.setCurrentIndex(0)
            if number == 6:
                self.chk_depth_deposition.setText("Inhibition deposition")
                self.lbl_depth_depo_section.setText("6 Inhibition-weighted deposition")
                self.lbl_depth_parameter_help.setText(
                    "Inhibition map: top growth is suppressed first. The mini-map shows the active structure."
                )
                self.edit_request_note.setPlaceholderText("Request note / inhibition notes are saved with the run.")
            else:
                self.chk_depth_deposition.setText("Depth-dependent deposition")
                self.lbl_depth_depo_section.setText("5 Depth-dependent deposition")
                self.lbl_depth_parameter_help.setText(
                    "Depth map: deeper areas receive less deposition. The mini-map shows the active structure."
                )
                self.edit_request_note.setPlaceholderText("Request note / depth fill notes are saved with the run.")
        else:
            self.chk_depth_deposition.setText("Depth-dependent deposition")
            self.chk_sputter.setChecked(False)
            self.chk_ion_transmission.setChecked(False)
            self.chk_reflected_ion.setChecked(False)
            self.chk_redepo.setChecked(False)
            self.chk_depth_deposition.setChecked(False)
            if number == 0:
                self.edit_request_note.setPlaceholderText("요청사항 / conformal depo 메모를 적으면 run 파일명과 요약에 같이 들어갑니다.")
            else:
                self.edit_request_note.setPlaceholderText("아직 물리 모델이 배정되지 않은 슬롯입니다. 기본 conformal depo로만 실행됩니다.")

        self._populate_emulator_default_presets()
        if changed:
            settings = self.cmb_emulator_default_preset.currentData()
            if isinstance(settings, dict):
                self._apply_emulator_preset(settings)

        self.sync_depth_deposition_editor_from_spins()
        self._populate_split_parameters()
        self.sync_etch_control_availability()
        self._sync_depth_advanced_visibility()
        if run:
            self._schedule_emulator_preview_run()

    def _schedule_emulator_preview_run(self) -> None:
        self.statusBar().showMessage("Emulator mode changed", 1200)
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

    def sync_depth_deposition_editor_from_spins(self, _value: object = 0.0) -> None:
        if self._syncing_depth_curve:
            return
        self._syncing_depth_curve = True
        try:
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
        finally:
            self._syncing_depth_curve = False

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
        show_advanced = bool(supports_depth and self.btn_depth_advanced.isChecked())
        for widget in self._depth_advanced_widgets():
            widget.setVisible(show_advanced)

    def sync_etch_control_availability(self, _checked: bool = False) -> None:
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion_transmission = self._active_emulator_supports_ion_transmission()
        supports_reflected_ion = self._active_emulator_supports_reflected_ion()
        supports_redeposition = self._active_emulator_supports_redeposition()
        supports_depth_deposition = self._active_emulator_supports_depth_deposition()
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

        self.chk_redepo.setEnabled(etch_enabled and supports_redeposition)
        redepo_enabled = bool(
            etch_enabled
            and supports_redeposition
            and self.chk_redepo.isChecked()
        )
        for widget in [
            self.lbl_redepo_section,
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
        ]:
            widget.setEnabled(redepo_enabled)

        self.chk_depth_deposition.setEnabled(supports_depth_deposition)
        depth_enabled = bool(supports_depth_deposition and self.chk_depth_deposition.isChecked())
        for widget in [
            self.lbl_depth_depo_section,
            self.lbl_depth_feature_type,
            self.cmb_depth_feature_type,
            self.lbl_depth_feature_width,
            self.spin_depth_feature_width,
            self.lbl_depth_feature_depth,
            self.spin_depth_feature_depth,
            self.lbl_depth_feature_length,
            self.spin_depth_feature_length,
            self.lbl_depth_decay_k,
            self.spin_depth_decay_k,
            self.lbl_depth_decay_power,
            self.spin_depth_decay_power,
            self.lbl_depth_min_ratio,
            self.spin_depth_min_ratio_pct,
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
            self.depth_deposition_editor,
        ]:
            widget.setEnabled(depth_enabled)
        length_enabled = bool(
            depth_enabled and str(self.cmb_depth_feature_type.currentData() or "hole") == "line"
        )
        self.lbl_depth_feature_length.setEnabled(length_enabled)
        self.spin_depth_feature_length.setEnabled(length_enabled)
        self._sync_depth_advanced_visibility()

    def reset_defaults(self) -> None:
        supports_sputter = self._active_emulator_supports_sputter()
        supports_ion_transmission = self._active_emulator_supports_ion_transmission()
        supports_reflected_ion = self._active_emulator_supports_reflected_ion()
        supports_redeposition = self._active_emulator_supports_redeposition()
        supports_depth_deposition = self._active_emulator_supports_depth_deposition()
        self.spin_cycles.setValue(20)
        self.spin_angstrom_per_cycle.setValue(10.0)
        self.chk_sputter.setChecked(supports_sputter)
        self.chk_ion_transmission.setChecked(supports_ion_transmission)
        self.chk_reflected_ion.setChecked(supports_reflected_ion)
        self.chk_redepo.setChecked(supports_redeposition)
        self.chk_depth_deposition.setChecked(supports_depth_deposition)
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
        self.spin_redepo_efficiency.setValue(25.0)
        self.spin_redepo_emit_power.setValue(1.0)
        self.spin_redepo_distance_power.setValue(1.0)
        self.spin_redepo_soft_los.setValue(0)
        self.cmb_depth_feature_type.setCurrentIndex(0)
        self.spin_depth_feature_width.setValue(240.0)
        self.spin_depth_feature_depth.setValue(4700.0)
        self.spin_depth_feature_length.setValue(0.0)
        if self.active_emulator_number() == 6:
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
        self.spin_sputter_strength.setValue(4.0)
        self.spin_sputter_peak_pct.setValue(100.0)
        self.spin_sputter_peak.setValue(55.0)
        self.spin_sputter_width.setValue(14.0)
        self.spin_sputter_smoothing.setValue(40.0)
        self._populate_split_parameters()
        self.sync_etch_control_availability()
        if self.active_emulator_number() == 6:
            self.edit_request_note.setPlainText("PECVD/PEALD inhibition-weighted deposition: top/opening growth suppression with smooth trench fill")
        elif self.active_emulator_number() == 5:
            self.edit_request_note.setPlainText("길쭉한 항아리형 구조에서 depth-dependent depo와 closure 후 잔류 fill 검증")
        elif self.active_emulator_number() == 3:
            self.edit_request_note.setPlainText("1번 direct sputter 위에 reflected ion bowing/microtrenching 추가 검증")
        elif self.active_emulator_number() == 4:
            self.edit_request_note.setPlainText("2번 source 기반 GapSim-style binned lobe LOS redeposition 결합 검증")
        elif self.active_emulator_number() == 2:
            self.edit_request_note.setPlainText("계단식 넓은 트렌치에서 ion transmission shadowing 검증")
        elif self.active_emulator_number() == 1:
            self.edit_request_note.setPlainText("각도기반 direct sputter etch 검증")
        elif self.active_emulator_number() == 0:
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
        elif parameter in {"redepo_emit_power", "redepo_distance_power"}:
            values = (0.5, 2.0, 0.5, 2, 0.0, 8.0)
        elif parameter == "redepo_soft_los_radius_points":
            values = (0.0, 2.0, 1.0, 0, 0.0, 2.0)
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
        etch_enabled = bool(supports_sputter and self.chk_sputter.isChecked())
        depth_feature_type = str(self.cmb_depth_feature_type.currentData() or "hole")
        depth_feature_length = float(self.spin_depth_feature_length.value())
        return TrenchDepoConfig(
            points=self._current_geometry_points(),
            cycles=int(self.spin_cycles.value()),
            angstrom_per_cycle=float(self.spin_angstrom_per_cycle.value()),
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
                active_emulator == 6 and supports_depth_deposition and self.chk_depth_deposition.isChecked()
            ),
            inhibition_process_model="hybrid",
            inhibition_strength_pct=85.0,
            inhibition_penetration_depth_a=max(80.0, float(self.spin_depth_feature_depth.value()) * 0.24),
            inhibition_decay_power=float(self.spin_depth_decay_power.value()),
            inhibition_min_growth_ratio=float(self.spin_depth_min_ratio_pct.value()) / 100.0,
            inhibition_bottom_boost_pct=20.0,
            inhibition_peald_recombination_pct=35.0,
            inhibition_smoothing_a=45.0,
        )

    def current_etch_config(self) -> TrenchDepoConfig:
        cfg = self.current_config()
        if cfg.sputter_enabled or cfg.sputter_strength_a_per_cycle <= 0.0:
            return cfg
        return TrenchDepoConfig(
            points=cfg.points,
            cycles=cfg.cycles,
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
        etch_enabled = bool(supports_sputter and (force_model_enabled or self.chk_sputter.isChecked()))
        depth_enabled = bool(
            supports_depth_deposition and (force_model_enabled or self.chk_depth_deposition.isChecked())
        )
        return replace(
            cfg,
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
            deposition_depth_enabled=depth_enabled,
            inhibition_enabled=bool(target == 6 and depth_enabled),
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
        QApplication.processEvents()

    def _update_run_progress(self, step: int, total: int, *, label: str = "Running") -> None:
        total_i = max(0, int(total))
        step_i = max(0, int(step))
        if total_i <= 0:
            self.progress_run.setRange(0, 1)
            self.progress_run.setValue(1)
            self.progress_run.setFormat(f"{label}: complete")
            self.lbl_status.setText(f"{label}: complete")
        else:
            step_i = min(step_i, total_i)
            self.progress_run.setRange(0, total_i)
            self.progress_run.setValue(step_i)
            self.progress_run.setFormat(f"{label}: {step_i}/{total_i}")
            self.lbl_status.setText(f"{label}: {step_i}/{total_i}")
        self.progress_run.setVisible(True)
        QApplication.processEvents()

    def _finish_run_progress(self, *, success: bool) -> None:
        if success:
            maximum = max(1, self.progress_run.maximum())
            self.progress_run.setRange(0, maximum)
            self.progress_run.setValue(maximum)
            self.progress_run.setFormat("Done")
            QApplication.processEvents()
        self.progress_run.setVisible(False)

    def run_emulation(
        self,
        _checked: bool = False,
        *,
        save_artifacts: bool = True,
        use_preview_cache: bool = False,
    ) -> None:
        self._emulator_run_timer.stop()
        self.btn_run.setEnabled(False)
        success = False
        try:
            config = self.current_config()
            run_dir: Optional[Path] = None
            cache_key = self._preview_cache_key(config)
            if use_preview_cache and not save_artifacts and cache_key in self._preview_result_cache:
                self._start_run_progress("Loading cached run")
                result = self._preview_result_cache[cache_key]
                self._update_run_progress(1, 1, label="Cached run")
            else:
                self._start_run_progress("Running simulation")
                result = run_trench_depo(
                    config,
                    progress_cb=lambda step, total: self._update_run_progress(
                        step,
                        total,
                        label="Run",
                    ),
                )
                self._preview_result_cache[cache_key] = result
            if save_artifacts:
                self._start_run_progress("Saving run")
                run_dir = export_trench_depo_run(
                    config,
                    result,
                    request_note=self.edit_request_note.toPlainText(),
                    runs_root=DEFAULT_RUNS_ROOT,
                )
                self._update_run_progress(1, 1, label="Saved")
            success = True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Trench Depo Emulation",
                f"Failed to run trench deposition emulation:\n{exc}",
            )
            return
        finally:
            self.btn_run.setEnabled(True)
            self._finish_run_progress(success=success)

        self._result = result
        self._last_run_dir = run_dir.resolve() if run_dir is not None else None
        solid_playback = _use_solid_playback(result)
        self.view.set_frames(
            result.frame_profiles,
            voids=result.frame_voids,
            void_mode="current",
            dynamic_substrate_fill=solid_playback,
            history_mode="mixed_etch" if solid_playback else "film",
        )
        max_idx = max(0, len(result.frame_profiles) - 1)
        self.slider_frame.blockSignals(True)
        self.slider_frame.setRange(0, max_idx)
        self.slider_frame.setValue(max_idx)
        self.slider_frame.setEnabled(max_idx > 0)
        self.slider_frame.blockSignals(False)
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

    def run_split_test(self, _checked: bool = False) -> None:
        self.btn_run_split.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Split test 계산 중...")
        success = False
        self._start_run_progress("Running split")
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
            self._update_run_progress(1, 1, label="Saved")
            success = True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Trench Depo Split Test",
                f"Failed to run or save split test:\n{exc}",
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
        self.statusBar().showMessage(f"Emulator {active_number:02d}/{target:02d} 비교 계산 중...")
        success = False
        self._start_run_progress(f"Running emulator {active_number:02d}")
        try:
            current_cfg = self._config_for_emulator_number(active_number, force_model_enabled=True)
            target_cfg = self._config_for_emulator_number(target, force_model_enabled=True)
            t0 = time.perf_counter()
            current_result = run_trench_depo(
                current_cfg,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label=f"Emulator {active_number:02d}",
                ),
            )
            current_elapsed = time.perf_counter() - t0
            t1 = time.perf_counter()
            self._start_run_progress(f"Running emulator {target:02d}")
            target_result = run_trench_depo(
                target_cfg,
                progress_cb=lambda step, total: self._update_run_progress(
                    step,
                    total,
                    label=f"Emulator {target:02d}",
                ),
            )
            target_elapsed = time.perf_counter() - t1
            cases = [
                TrenchSweepResult(
                    parameter="emulator_compare",
                    label=f"Current Emulator {active_number:02d} - {_emulator_mode_title(active_number)} ({current_elapsed:.2f}s)",
                    value=float(active_number),
                    config=current_cfg,
                    result=current_result,
                ),
                TrenchSweepResult(
                    parameter="emulator_compare",
                    label=f"Compare Emulator {target:02d} - {_emulator_mode_title(target)} ({target_elapsed:.2f}s)",
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
                f"Failed to compare Emulator {active_number:02d} and {target:02d}:\n{exc}",
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
        self.statusBar().showMessage(f"Emulator {active_number:02d}/{target:02d} 비교 완료", 5000)

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
        self._start_run_progress("Running current model")
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
            self._start_run_progress("Running GapSim legacy")
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
                    label=f"Current Emulator {self.active_emulator_number():02d} ({mini_elapsed:.2f}s)",
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
                f"Failed to run GapSim angle-only comparison:\n{exc}",
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

    def show_frame(self, index: int) -> None:
        if self._result is None or not self._result.frame_profiles:
            self._show_result_input_preview(fit=False)
            return

        idx = max(0, min(int(index), len(self._result.frame_profiles) - 1))
        self.view.show_frame(idx, fit=False)
        cycle = self._result.frame_steps[idx] if idx < len(self._result.frame_steps) else idx
        total = self._result.meta.get("cycles", len(self._result.frame_profiles) - 1)
        points = len(self._result.frame_profiles[idx])
        self.lbl_status.setText(f"Cycle {cycle}/{total} | Points {points}")

    def load_replay_json(self, path: Path | str) -> None:
        replay_path = Path(path).resolve()
        config, result, note = load_trench_depo_run(replay_path)
        replay_emulator = (
            6
            if bool(config.inhibition_enabled)
            else 5
            if bool(config.deposition_depth_enabled)
            else (
                4
                if bool(config.redepo_enabled)
                else (
                    3
                    if bool(config.reflected_ion_enabled)
                    else (2 if bool(config.ion_transmission_enabled) else (1 if bool(config.sputter_enabled) else 0))
                )
            )
        )
        self.set_active_emulator_number(replay_emulator, run=False)
        self._set_structure_points(config.points)
        self.spin_cycles.setValue(int(config.cycles))
        self.spin_angstrom_per_cycle.setValue(float(config.angstrom_per_cycle))
        self.chk_sputter.setChecked(bool(config.sputter_enabled))
        self.chk_ion_transmission.setChecked(bool(config.ion_transmission_enabled))
        self.chk_reflected_ion.setChecked(bool(config.reflected_ion_enabled))
        self.chk_redepo.setChecked(bool(config.redepo_enabled))
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
        self.chk_depth_deposition.setChecked(bool(config.deposition_depth_enabled))
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
        self.spin_sputter_strength.setValue(float(config.sputter_strength_a_per_cycle))
        self.spin_sputter_peak_pct.setValue(float(config.sputter_peak_pct))
        self.spin_sputter_peak.setValue(float(config.sputter_peak_angle_deg))
        self.spin_sputter_width.setValue(float(config.sputter_width_deg))
        self.spin_sputter_smoothing.setValue(float(config.sputter_smoothing_a))
        self.sync_etch_control_availability()
        self.edit_request_note.setPlainText(note)
        self._result = result
        self._last_run_dir = replay_path.parent
        solid_playback = _use_solid_playback(result)
        self.view.set_frames(
            result.frame_profiles,
            voids=result.frame_voids,
            void_mode="current",
            dynamic_substrate_fill=solid_playback,
            history_mode="mixed_etch" if solid_playback else "film",
        )
        max_idx = max(0, len(result.frame_profiles) - 1)
        self.slider_frame.blockSignals(True)
        self.slider_frame.setRange(0, max_idx)
        self.slider_frame.setValue(max_idx)
        self.slider_frame.setEnabled(max_idx > 0)
        self.slider_frame.blockSignals(False)
        self.show_frame(max_idx)
        self._set_workflow_step("results")
        QTimer.singleShot(0, self.view.fit_content)
        self._set_run_dir_label(self._last_run_dir)
        self.btn_open_run_dir.setEnabled(True)
        self.statusBar().showMessage(f"JSON 런 로드 완료: {replay_path}", 5000)
        self._open_split_group_for_replay(replay_path)

    def open_replay_json_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Trench Replay JSON",
            str(self._last_run_dir or DEFAULT_RUNS_ROOT),
            "JSON (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.load_replay_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Trench Depo Emulation", f"Failed to open replay JSON:\n{exc}")

    def open_last_run_dir(self) -> None:
        if self._last_run_dir is None:
            return
        run_dir = self._last_run_dir.resolve()
        if not run_dir.exists():
            QMessageBox.warning(self, "Trench Depo Emulation", f"Run folder not found:\n{run_dir}")
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
            QMessageBox.warning(self, "Trench Depo Emulation", f"Failed to open run folder:\n{run_dir}")


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
            QMessageBox.critical(window, "Trench Depo Emulation", f"Failed to open replay JSON:\n{exc}")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
