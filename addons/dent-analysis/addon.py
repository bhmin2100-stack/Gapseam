from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dent_analysis import (
    DentLine,
    DentRegion,
    DentSample,
    analyze_dent_frames,
    dent_samples_to_payload,
)

DENT_ANALYSIS_ADDON_ID = "dent-analysis"


class DentAnalysisGraph(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._samples: List[DentSample] = []
        self._x_mode = "cycle"
        self.setMinimumHeight(190)

    def set_samples(self, samples: Sequence[DentSample], *, x_mode: str = "cycle") -> None:
        self._samples = list(samples)
        self._x_mode = str(x_mode or "cycle")
        self.update()

    def _x_value(self, sample: DentSample) -> float:
        if self._x_mode == "thickness":
            return float(sample.thickness_a)
        return float(sample.cycle)

    @staticmethod
    def _range(values: Sequence[float], *, zero_floor: bool = False) -> Tuple[float, float]:
        if not values:
            return (0.0, 1.0)
        lo = min(values)
        hi = max(values)
        if zero_floor:
            lo = min(0.0, lo)
        if abs(hi - lo) <= 1e-12:
            pad = max(1.0, abs(hi) * 0.12)
        else:
            pad = (hi - lo) * 0.12
        return (lo - pad if not zero_floor else min(0.0, lo - pad), hi + pad)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(10.0, 8.0, -10.0, -8.0)
        painter.fillRect(rect, QColor(255, 255, 255))
        painter.setPen(QPen(QColor(203, 213, 225), 1.0))
        painter.drawRect(rect)

        samples = [sample for sample in self._samples if sample.dent_depth_a is not None]
        if not samples:
            painter.setPen(QColor(100, 116, 139))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Dent 결과 없음")
            return

        plot = rect.adjusted(52.0, 18.0, -52.0, -34.0)
        if plot.width() <= 4.0 or plot.height() <= 4.0:
            return

        x_values = [self._x_value(sample) for sample in samples]
        depth_values = [float(sample.dent_depth_a or 0.0) for sample in samples]
        slope_samples = [sample for sample in samples if sample.slope_delta_deg is not None]
        slope_values = [float(sample.slope_delta_deg or 0.0) for sample in slope_samples]
        x_min, x_max = self._range(x_values)
        depth_min, depth_max = self._range(depth_values, zero_floor=True)
        slope_min, slope_max = self._range(slope_values)

        def map_x(value: float) -> float:
            if abs(x_max - x_min) <= 1e-12:
                return float(plot.left())
            return float(plot.left() + ((value - x_min) / (x_max - x_min)) * plot.width())

        def map_depth(value: float) -> float:
            if abs(depth_max - depth_min) <= 1e-12:
                return float(plot.bottom())
            return float(plot.bottom() - ((value - depth_min) / (depth_max - depth_min)) * plot.height())

        def map_slope(value: float) -> float:
            if abs(slope_max - slope_min) <= 1e-12:
                return float(plot.center().y())
            return float(plot.bottom() - ((value - slope_min) / (slope_max - slope_min)) * plot.height())

        grid_pen = QPen(QColor(226, 232, 240), 1.0)
        painter.setPen(grid_pen)
        for idx in range(5):
            y = plot.top() + plot.height() * float(idx) / 4.0
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        axis_pen = QPen(QColor(71, 85, 105), 1.2)
        painter.setPen(axis_pen)
        painter.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))
        painter.drawLine(QPointF(plot.right(), plot.top()), QPointF(plot.right(), plot.bottom()))
        painter.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

        painter.setPen(QColor(71, 85, 105))
        painter.drawText(QRectF(rect.left(), plot.top() - 8.0, 50.0, 18.0), Qt.AlignmentFlag.AlignRight, "Depth")
        painter.drawText(
            QRectF(plot.right() + 5.0, plot.top() - 8.0, 48.0, 18.0),
            Qt.AlignmentFlag.AlignLeft,
            "Slope",
        )
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 8.0, plot.width(), 20.0),
            Qt.AlignmentFlag.AlignCenter,
            "Thickness A" if self._x_mode == "thickness" else "Cycle",
        )
        painter.drawText(
            QRectF(rect.left(), plot.top(), 48.0, 18.0),
            Qt.AlignmentFlag.AlignRight,
            f"{depth_max:.1f}",
        )
        painter.drawText(
            QRectF(rect.left(), plot.bottom() - 12.0, 48.0, 18.0),
            Qt.AlignmentFlag.AlignRight,
            f"{depth_min:.1f}",
        )
        if slope_values:
            painter.drawText(
                QRectF(plot.right() + 5.0, plot.top(), 48.0, 18.0),
                Qt.AlignmentFlag.AlignLeft,
                f"{slope_max:.1f}",
            )
            painter.drawText(
                QRectF(plot.right() + 5.0, plot.bottom() - 12.0, 48.0, 18.0),
                Qt.AlignmentFlag.AlignLeft,
                f"{slope_min:.1f}",
            )

        def draw_series(values: Sequence[Tuple[float, float]], color: QColor, width: float) -> None:
            if not values:
                return
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            last: Optional[QPointF] = None
            for x, y in values:
                point = QPointF(float(x), float(y))
                painter.setBrush(color)
                painter.drawEllipse(point, 2.7, 2.7)
                if last is not None:
                    painter.drawLine(last, point)
                last = point

        draw_series(
            [(map_x(self._x_value(sample)), map_depth(float(sample.dent_depth_a or 0.0))) for sample in samples],
            QColor("#2563eb"),
            2.2,
        )
        if slope_samples:
            draw_series(
                [
                    (map_x(self._x_value(sample)), map_slope(float(sample.slope_delta_deg or 0.0)))
                    for sample in slope_samples
                ],
                QColor("#ea580c"),
                2.0,
            )

        legend_y = rect.top() + 4.0
        painter.setPen(QPen(QColor("#2563eb"), 2.4))
        painter.drawLine(QPointF(plot.left(), legend_y + 6.0), QPointF(plot.left() + 26.0, legend_y + 6.0))
        painter.setPen(QColor(15, 23, 42))
        painter.drawText(QPointF(plot.left() + 32.0, legend_y + 10.0), "Dent depth")
        painter.setPen(QPen(QColor("#ea580c"), 2.4))
        painter.drawLine(QPointF(plot.left() + 132.0, legend_y + 6.0), QPointF(plot.left() + 158.0, legend_y + 6.0))
        painter.setPen(QColor(15, 23, 42))
        painter.drawText(QPointF(plot.left() + 164.0, legend_y + 10.0), "Slope delta")


class DentAnalysisController:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.window = context.window
        self._connections: List[Tuple[Any, Any]] = []
        self._region: Optional[DentRegion] = None
        self._slope_line: Optional[DentLine] = None
        self._samples: List[DentSample] = []
        self._result: Optional[Any] = None
        self._result_config: Optional[Any] = None

        self.progress_widget = self._build_progress_widget()
        self.result_widget = self._build_result_widget()
        context.add_progress_widget(self.progress_widget, title="Dent 분석")
        context.add_result_widget(self.result_widget, title="Dent 분석 결과")
        self._connect_host_signals()
        self._refresh_input_labels()
        self._refresh_result_views()

    def teardown(self) -> None:
        if self._result is not None:
            self._result.meta.pop("dent_analysis", None)
        self._samples = []
        view = self._progress_view()
        clear_overlays = getattr(view, "clear_measurement_overlays", None)
        if callable(clear_overlays):
            clear_overlays()
        self._refresh_host_result_summary(self._current_frame_index())
        self._refresh_host_parameter_summary()
        for signal, slot in reversed(self._connections):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()

    def _connect(self, signal: Any, slot: Any) -> None:
        if signal is None:
            return
        signal.connect(slot)
        self._connections.append((signal, slot))

    def _build_progress_widget(self) -> QWidget:
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.cmb_orientation = QComboBox()
        self.cmb_orientation.addItem("세로방향 dent (깊이 Y)", "vertical")
        self.cmb_orientation.addItem("가로방향 dent (깊이 X)", "horizontal")
        self.cmb_orientation.setToolTip("field의 아래쪽 dent는 세로방향, 벽 dent는 가로방향을 선택합니다.")
        self.cmb_x_axis = QComboBox()
        self.cmb_x_axis.addItem("X축: Cycle", "cycle")
        self.cmb_x_axis.addItem("X축: 두께 A", "thickness")
        self.btn_select_region = QPushButton("Dent 영역 지정")
        self.btn_select_region.setToolTip("왼쪽 3 진행 화면에서 dent 부위를 네모로 드래그합니다.")
        self.btn_select_slope_line = QPushButton("Slope 기준선")
        self.btn_select_slope_line.setToolTip("왼쪽 3 진행 화면에서 slope 기준 선분을 드래그합니다.")
        self.btn_clear = QPushButton("Dent 설정 지우기")
        self.lbl_region = QLabel("영역: 미지정")
        self.lbl_region.setWordWrap(True)
        self.lbl_slope_line = QLabel("기준선: 미지정")
        self.lbl_slope_line.setWordWrap(True)
        self.lbl_status = QLabel("스무딩 후 실행 전에 영역과 기준선을 지정하세요.")
        self.lbl_status.setWordWrap(True)

        layout.addWidget(QLabel("방향"), 0, 0)
        layout.addWidget(self.cmb_orientation, 0, 1, 1, 2)
        layout.addWidget(QLabel("그래프"), 1, 0)
        layout.addWidget(self.cmb_x_axis, 1, 1, 1, 2)
        layout.addWidget(self.btn_select_region, 2, 0, 1, 2)
        layout.addWidget(self.btn_select_slope_line, 2, 2)
        layout.addWidget(self.btn_clear, 3, 0, 1, 3)
        layout.addWidget(self.lbl_region, 4, 0, 1, 3)
        layout.addWidget(self.lbl_slope_line, 5, 0, 1, 3)
        layout.addWidget(self.lbl_status, 6, 0, 1, 3)
        return widget

    def _build_result_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.lbl_current = QLabel("Dent 결과 없음")
        self.lbl_current.setWordWrap(True)
        self.graph = DentAnalysisGraph()
        self.edit_table = QPlainTextEdit()
        self.edit_table.setReadOnly(True)
        self.edit_table.setMinimumHeight(110)
        self.edit_table.setPlainText("Dent 영역을 지정한 뒤 실행하면 cycle별 값이 표시됩니다.")
        layout.addWidget(self.lbl_current)
        layout.addWidget(self.graph)
        layout.addWidget(self.edit_table)
        return widget

    def _connect_host_signals(self) -> None:
        self._connect(self.btn_select_region.clicked, self.begin_region_selection)
        self._connect(self.btn_select_slope_line.clicked, self.begin_slope_line_selection)
        self._connect(self.btn_clear.clicked, self.clear)
        self._connect(self.cmb_orientation.currentIndexChanged, self._on_settings_changed)
        self._connect(self.cmb_x_axis.currentIndexChanged, self._on_x_axis_changed)

        view = self._progress_view()
        if view is not None:
            self._connect(getattr(view, "measurementRegionSelected", None), self._on_region_selected)
            self._connect(getattr(view, "measurementLineSelected", None), self._on_slope_line_selected)
        self._connect(getattr(self.context, "result_applied", None), self._on_result_applied)
        self._connect(getattr(self.context, "frame_shown", None), self._on_frame_shown)

    def _progress_view(self) -> Optional[Any]:
        return getattr(self.window, "progress_geometry_view", None)

    def _orientation(self) -> str:
        data = self.cmb_orientation.currentData()
        return str(data or "vertical")

    def _x_mode(self) -> str:
        data = self.cmb_x_axis.currentData()
        return str(data or "cycle")

    def _current_frame_index(self) -> int:
        slider = getattr(self.window, "slider_frame", None)
        if slider is not None:
            try:
                return int(slider.value())
            except (TypeError, ValueError):
                pass
        if self._samples:
            return int(self._samples[-1].frame_index)
        return 0

    def _show_progress_step(self) -> None:
        set_step = getattr(self.window, "_set_workflow_step", None)
        if callable(set_step):
            set_step("progress")
        sync = getattr(self.window, "_sync_progress_geometry_view", None)
        if callable(sync):
            sync(fit=False)

    def begin_region_selection(self, _checked: bool = False) -> None:
        view = self._progress_view()
        begin = getattr(view, "begin_measurement_region_selection", None)
        if not callable(begin):
            QMessageBox.information(self.window, "Dent 분석", "현재 GFE가 영역 선택 API를 지원하지 않습니다.")
            return
        self._show_progress_step()
        begin()
        self.lbl_status.setText("왼쪽 3 진행 화면에서 dent 부위를 네모로 드래그하세요.")

    def begin_slope_line_selection(self, _checked: bool = False) -> None:
        view = self._progress_view()
        begin = getattr(view, "begin_measurement_line_selection", None)
        if not callable(begin):
            QMessageBox.information(self.window, "Dent 분석", "현재 GFE가 선분 선택 API를 지원하지 않습니다.")
            return
        self._show_progress_step()
        begin()
        self.lbl_status.setText("왼쪽 3 진행 화면에서 slope 기준 선분을 드래그하세요.")

    def _on_region_selected(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self._region = DentRegion(float(x0), float(y0), float(x1), float(y1)).normalized()
        self._refresh_input_labels()
        self.lbl_status.setText("Dent 영역 지정 완료")
        self._recalculate()

    def _on_slope_line_selected(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self._slope_line = DentLine(float(x0), float(y0), float(x1), float(y1))
        self._refresh_input_labels()
        self.lbl_status.setText("Slope 기준선 지정 완료")
        self._recalculate()

    def clear(self, _checked: bool = False) -> None:
        self._region = None
        self._slope_line = None
        self._samples = []
        if self._result is not None:
            self._result.meta.pop("dent_analysis", None)
        view = self._progress_view()
        clear_overlays = getattr(view, "clear_measurement_overlays", None)
        if callable(clear_overlays):
            clear_overlays()
        self._refresh_input_labels()
        self._refresh_result_views()
        self._refresh_host_parameter_summary()
        self._refresh_host_result_summary(self._current_frame_index())
        self.lbl_status.setText("Dent 설정을 지웠습니다.")

    def _on_settings_changed(self, _index: int = 0) -> None:
        self._recalculate()

    def _on_x_axis_changed(self, _index: int = 0) -> None:
        self._refresh_result_views()

    def _recalculate(self) -> None:
        if self._result is None or self._result_config is None:
            self._refresh_result_views()
            return
        self._update_for_result(self._result_config, self._result)

    def _refresh_input_labels(self) -> None:
        view = self._progress_view()
        if self._region is None:
            self.lbl_region.setText("영역: 미지정")
        else:
            reg = self._region.normalized()
            self.lbl_region.setText(f"영역: x {reg.x0:.2f}..{reg.x1:.2f} A | y {reg.y0:.2f}..{reg.y1:.2f} A")
            set_region = getattr(view, "set_measurement_region_xy", None)
            if callable(set_region):
                set_region(reg.x0, reg.y0, reg.x1, reg.y1)

        if self._slope_line is None:
            self.lbl_slope_line.setText("기준선: 미지정")
        else:
            line = self._slope_line
            self.lbl_slope_line.setText(
                f"기준선: ({line.x0:.2f}, {line.y0:.2f}) -> ({line.x1:.2f}, {line.y1:.2f})"
            )
            set_line = getattr(view, "set_measurement_line_xy", None)
            if callable(set_line):
                set_line(line.x0, line.y0, line.x1, line.y1)

    def _restore_from_result_meta(self, result: Any) -> bool:
        raw = getattr(result, "meta", {}).get("dent_analysis")
        if not isinstance(raw, Mapping):
            return False
        region = raw.get("region")
        if isinstance(region, Mapping):
            try:
                self._region = DentRegion(
                    float(region["x0"]),
                    float(region["y0"]),
                    float(region["x1"]),
                    float(region["y1"]),
                ).normalized()
            except (KeyError, TypeError, ValueError):
                self._region = None
        slope_line = raw.get("slope_line")
        if isinstance(slope_line, Mapping):
            try:
                self._slope_line = DentLine(
                    float(slope_line["x0"]),
                    float(slope_line["y0"]),
                    float(slope_line["x1"]),
                    float(slope_line["y1"]),
                )
            except (KeyError, TypeError, ValueError):
                self._slope_line = None
        orientation = str(raw.get("orientation") or "")
        if orientation:
            idx = self.cmb_orientation.findData(orientation)
            if idx >= 0:
                self.cmb_orientation.setCurrentIndex(idx)
        self._refresh_input_labels()
        return True

    def _on_result_applied(self, config: Any, result: Any) -> None:
        self._result_config = config
        self._result = result
        self._restore_from_result_meta(result)
        self._update_for_result(config, result)

    def _update_for_result(self, config: Any, result: Any) -> None:
        if self._region is None:
            self._samples = []
            self._refresh_result_views()
            self._refresh_host_result_summary(self._current_frame_index())
            self._refresh_host_parameter_summary()
            return

        self._samples = analyze_dent_frames(
            result.frame_profiles,
            result.frame_steps,
            self._region,
            self._orientation(),
            slope_line=self._slope_line,
            angstrom_per_cycle=float(getattr(config, "angstrom_per_cycle", 0.0)),
        )
        result.meta["dent_analysis"] = {
            "addon_id": DENT_ANALYSIS_ADDON_ID,
            "orientation": self._orientation(),
            "region": {
                "x0": float(self._region.x0),
                "y0": float(self._region.y0),
                "x1": float(self._region.x1),
                "y1": float(self._region.y1),
            },
            "slope_line": (
                None
                if self._slope_line is None
                else {
                    "x0": float(self._slope_line.x0),
                    "y0": float(self._slope_line.y0),
                    "x1": float(self._slope_line.x1),
                    "y1": float(self._slope_line.y1),
                }
            ),
            "samples": dent_samples_to_payload(self._samples),
        }
        self._refresh_result_views()
        self._refresh_host_result_summary(self._current_frame_index())
        self._refresh_host_parameter_summary()

    def _sample_for_frame(self, frame_index: int) -> Optional[DentSample]:
        if not self._samples:
            return None
        idx = max(0, min(int(frame_index), len(self._samples) - 1))
        for sample in self._samples:
            if sample.frame_index == frame_index:
                return sample
        return self._samples[idx]

    def _current_summary_text(self, frame_index: int) -> str:
        sample = self._sample_for_frame(frame_index)
        if sample is None or sample.dent_depth_a is None:
            return ""
        parts = [f"Dent 깊이 {float(sample.dent_depth_a):.3f} A"]
        if sample.slope_delta_deg is not None:
            parts.append(f"Slope delta {float(sample.slope_delta_deg):.3f} deg")
        return " | ".join(parts)

    def _refresh_result_views(self) -> None:
        self.graph.set_samples(self._samples, x_mode=self._x_mode())
        if not self._samples:
            self.edit_table.setPlainText("Dent 영역을 지정한 뒤 실행하면 cycle별 값이 표시됩니다.")
        else:
            lines = ["cycle\tthickness_A\tdepth_A\tslope_delta_deg"]
            for sample in self._samples:
                depth = "" if sample.dent_depth_a is None else f"{float(sample.dent_depth_a):.5f}"
                slope = "" if sample.slope_delta_deg is None else f"{float(sample.slope_delta_deg):.5f}"
                lines.append(f"{sample.cycle}\t{sample.thickness_a:.5f}\t{depth}\t{slope}")
            self.edit_table.setPlainText("\n".join(lines))
        self._update_current_label(self._current_frame_index())

    def _update_current_label(self, frame_index: int) -> None:
        if self._region is None:
            self.lbl_current.setText("Dent 영역 미지정")
            return
        summary = self._current_summary_text(frame_index)
        if not summary:
            self.lbl_current.setText("Dent 결과 없음")
            return
        sample = self._sample_for_frame(frame_index)
        cycle_text = "" if sample is None else f"Cycle {sample.cycle} | "
        self.lbl_current.setText(f"{cycle_text}{summary}")

    def _strip_host_dent_summary(self, text: str) -> str:
        lines = [line for line in str(text or "").splitlines() if not line.startswith("Dent ")]
        return "\n".join(lines)

    def _refresh_host_result_summary(self, frame_index: int) -> None:
        label = getattr(self.window, "lbl_result_summary", None)
        if label is None:
            return
        base = self._strip_host_dent_summary(label.text())
        summary = self._current_summary_text(frame_index)
        label.setText(f"{base}\n{summary}" if summary else base)

    def _dent_parameter_lines(self) -> List[str]:
        if not self._samples or self._region is None:
            return []
        final_sample = next((sample for sample in reversed(self._samples) if sample.dent_depth_a is not None), None)
        final_depth = "" if final_sample is None else f"{float(final_sample.dent_depth_a):.3f} A"
        final_slope = (
            ""
            if final_sample is None or final_sample.slope_delta_deg is None
            else f"{float(final_sample.slope_delta_deg):.3f} deg"
        )
        reg = self._region.normalized()
        lines = [
            "[Dent Analysis]",
            f"Orientation: {self._orientation()}",
            f"Region: x {reg.x0:.3f}..{reg.x1:.3f} A | y {reg.y0:.3f}..{reg.y1:.3f} A",
            f"Final depth: {final_depth}",
        ]
        if self._slope_line is not None:
            line = self._slope_line
            lines.append(f"Slope line: ({line.x0:.3f}, {line.y0:.3f}) -> ({line.x1:.3f}, {line.y1:.3f})")
            lines.append(f"Final slope delta: {final_slope}")
        return lines

    def _refresh_host_parameter_summary(self) -> None:
        editor = getattr(self.window, "edit_result_parameters", None)
        if editor is None:
            return
        refresh = getattr(self.window, "_update_result_parameter_summary", None)
        if callable(refresh) and self._result_config is not None:
            refresh(self._result_config, self._result)
        text = str(editor.toPlainText())
        marker = "\n\n[Dent Analysis]"
        if marker in text:
            text = text.split(marker, 1)[0]
        lines = self._dent_parameter_lines()
        editor.setPlainText(f"{text}\n\n{chr(10).join(lines)}" if lines else text)

    def _on_frame_shown(self, frame_index: int) -> None:
        idx = int(frame_index)
        self._update_current_label(idx)
        self._refresh_host_result_summary(idx)


def register(context: Any) -> DentAnalysisController:
    return DentAnalysisController(context)
