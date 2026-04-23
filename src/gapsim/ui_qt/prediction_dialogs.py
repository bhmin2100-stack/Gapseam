from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gapsim.prediction import Point, auto_anchor_spec, sanitize_anchor_spec
from gapsim.ui_qt.controllers.smoothing_ctrl import SmoothingController
from gapsim.ui_qt.models.points_table import PointsTableModel
from gapsim.ui_qt.models.points_table_view import PointsTableView
from gapsim.ui_qt.views.structure_view import StructureView


def _tx(lang: str, key: str) -> str:
    ko = {
        "post_editor.title": "POST DEPO 구조 입력",
        "post_editor.hint": "PRE 구조는 참조용으로 고정되고, POST 구조만 편집됩니다.",
        "post_editor.reset": "PRE 기준으로 초기화",
        "post_editor.accept": "다음: POST smoothing",
        "post_editor.cancel": "취소",
        "post_smoothing.title": "POST DEPO smoothing",
        "post_smoothing.hint": "POST raw는 유지되고, 예측에는 현재 smoothing 결과가 사용됩니다.",
        "post_smoothing.apply": "Smoothing 적용",
        "post_smoothing.raw": "Raw 보기",
        "post_smoothing.fit": "화면 맞춤",
        "post_smoothing.accept": "다음: anchor 설정",
        "post_smoothing.cancel": "취소",
        "post_smoothing.summary.raw": "현재 표시: RAW ({n} pts)",
        "post_smoothing.summary.smooth": "현재 표시: SMOOTH ({n} pts)",
        "anchor.title": "예측 지점 선택",
        "anchor.hint": "lip / sidewall / bottom guide를 조정한 뒤 예측 실행을 누르세요.",
        "anchor.accept": "예측 실행",
        "anchor.cancel": "취소",
        "anchor.division_count": "Sidewall 분할 수",
        "anchor.left_lip_x": "Left lip X",
        "anchor.left_lip_y": "Left lip Y",
        "anchor.right_lip_x": "Right lip X",
        "anchor.right_lip_y": "Right lip Y",
        "anchor.top_left_x": "Top 비교 X (좌)",
        "anchor.top_right_x": "Top 비교 X (우)",
        "anchor.bottom_y": "Bottom 기준 Y",
        "anchor.weight_top": "Top weight",
        "anchor.weight_lip": "Lip weight",
        "anchor.weight_sidewall": "Sidewall weight",
        "anchor.weight_bottom": "Bottom weight",
        "anchor.section_group": "Section 상세",
        "anchor.section_enabled": "사용",
        "anchor.section_y": "Y",
        "anchor.section_weight": "Weight",
        "anchor.fit": "화면 맞춤",
    }
    en = {
        "post_editor.title": "POST DEPO Profile",
        "post_editor.hint": "PRE stays read-only as reference while only the POST profile is editable.",
        "post_editor.reset": "Reset From PRE",
        "post_editor.accept": "Next: POST smoothing",
        "post_editor.cancel": "Cancel",
        "post_smoothing.title": "POST DEPO Smoothing",
        "post_smoothing.hint": "POST raw stays untouched. Prediction uses the currently displayed smoothing result.",
        "post_smoothing.apply": "Apply smoothing",
        "post_smoothing.raw": "Show raw",
        "post_smoothing.fit": "Fit",
        "post_smoothing.accept": "Next: Anchor setup",
        "post_smoothing.cancel": "Cancel",
        "post_smoothing.summary.raw": "Current view: RAW ({n} pts)",
        "post_smoothing.summary.smooth": "Current view: SMOOTH ({n} pts)",
        "anchor.title": "Prediction Anchors",
        "anchor.hint": "Adjust the lip / sidewall / bottom guides, then run prediction.",
        "anchor.accept": "Run prediction",
        "anchor.cancel": "Cancel",
        "anchor.division_count": "Sidewall divisions",
        "anchor.left_lip_x": "Left lip X",
        "anchor.left_lip_y": "Left lip Y",
        "anchor.right_lip_x": "Right lip X",
        "anchor.right_lip_y": "Right lip Y",
        "anchor.top_left_x": "Top sample X (L)",
        "anchor.top_right_x": "Top sample X (R)",
        "anchor.bottom_y": "Bottom reference Y",
        "anchor.weight_top": "Top weight",
        "anchor.weight_lip": "Lip weight",
        "anchor.weight_sidewall": "Sidewall weight",
        "anchor.weight_bottom": "Bottom weight",
        "anchor.section_group": "Section Details",
        "anchor.section_enabled": "Enabled",
        "anchor.section_y": "Y",
        "anchor.section_weight": "Weight",
        "anchor.fit": "Fit",
    }
    table = ko if lang == "ko" else en
    return table.get(key, key)


class EditableProfileWidget(QWidget):
    def __init__(
        self,
        *,
        reference_points: List[Point],
        editable_points: List[Point],
        lang: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self._reference_points = [(float(x), float(y)) for x, y in reference_points]
        self._default_points = [(float(x), float(y)) for x, y in (editable_points or reference_points)]
        self._model_change_from_view = False
        self._dragging_point_idx: Optional[int] = None
        self._drag_points: Optional[List[Point]] = None

        root = QVBoxLayout(self)
        self.view = StructureView()
        self.view.set_profile_colors(
            current=QColor(220, 90, 45),
            reference=QColor(40, 110, 205, 180),
        )
        self.view.set_reference_profiles_xy([self._reference_points])
        self.view.set_point_radius_px(4.0)
        root.addWidget(self.view, 1)

        self.model = PointsTableModel()
        self.table = PointsTableView()
        self.table.setModel(self.model)
        root.addWidget(self.table, 0)

        btn_row = QHBoxLayout()
        self.btn_reset = QPushButton(_tx(self.lang, "post_editor.reset"))
        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.model.dataChanged.connect(self._sync_view_from_model)
        self.model.modelReset.connect(self._sync_view_from_model)
        self.model.rowsInserted.connect(self._sync_view_from_model)
        self.model.rowsRemoved.connect(self._sync_view_from_model)
        self.model.pointEditRequested.connect(self._on_table_point_edit_requested)
        self.table.deleteRowsRequested.connect(self._on_table_delete_rows_requested)
        self.table.replacePointsRequested.connect(self._on_table_replace_points_requested)
        self.view.pointDragStarted.connect(self._on_view_drag_started)
        self.view.pointDragFinished.connect(self._on_view_drag_finished)
        self.view.pointMoved.connect(self._on_view_point_moved)
        self.view.pointInserted.connect(self._on_view_point_inserted)
        self.view.pointDeleted.connect(self._on_view_point_deleted)
        self.btn_reset.clicked.connect(self._reset_from_reference)

        self.model.set_points(self._default_points)
        self._sync_view_from_model()

    def points(self) -> List[Point]:
        return self.model.get_points()

    def _reset_from_reference(self) -> None:
        self.model.set_points(self._reference_points)

    def _sync_view_from_model(self, *_args) -> None:
        if self._model_change_from_view:
            return
        self.view.set_points_xy(self.model.get_points())
        self.view.fit_points()

    def _on_view_drag_started(self, idx: int, _x: float, _y: float) -> None:
        points = self.model.get_points()
        if not (0 <= idx < len(points)):
            self._dragging_point_idx = None
            self._drag_points = None
            return
        self._dragging_point_idx = int(idx)
        self._drag_points = list(points)

    def _on_view_drag_finished(self, idx: int, x: float, y: float) -> None:
        if self._dragging_point_idx == idx and self._drag_points is not None and 0 <= idx < len(self._drag_points):
            self._drag_points[idx] = (float(x), float(y))
            self._model_change_from_view = True
            try:
                self.model.set_point(idx, (float(x), float(y)))
            finally:
                self._model_change_from_view = False
        self._dragging_point_idx = None
        self._drag_points = None
        self.view.set_points_xy(self.model.get_points())

    def _on_view_point_moved(self, idx: int, x: float, y: float) -> None:
        if self._dragging_point_idx == idx and self._drag_points is not None and 0 <= idx < len(self._drag_points):
            self._drag_points[idx] = (float(x), float(y))
            return
        self._model_change_from_view = True
        try:
            self.model.set_point(idx, (x, y))
        finally:
            self._model_change_from_view = False

    def _on_view_point_inserted(self, idx: int, x: float, y: float) -> None:
        self._model_change_from_view = True
        try:
            self.model.insert_point(idx, (x, y))
        finally:
            self._model_change_from_view = False
        self._dragging_point_idx = int(idx)
        self._drag_points = list(self.model.get_points())
        self.view.set_points_xy(self.model.get_points())

    def _on_view_point_deleted(self, idx: int) -> None:
        self._model_change_from_view = True
        try:
            self.model.delete_point(idx)
        finally:
            self._model_change_from_view = False
        self._dragging_point_idx = None
        self._drag_points = None
        self.view.set_points_xy(self.model.get_points())

    def _on_table_point_edit_requested(self, row: int, x: float, y: float) -> None:
        self.model.set_point(row, (x, y))

    def _on_table_delete_rows_requested(self, rows: List[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            self.model.delete_point(int(row))

    def _on_table_replace_points_requested(self, rows: List[Point]) -> None:
        if len(rows) < 2:
            return
        self.model.set_points([(float(x), float(y)) for x, y in rows])


class PredictionPostEditorDialog(QDialog):
    def __init__(
        self,
        *,
        pre_points: List[Point],
        initial_post_points: List[Point],
        lang: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self.setWindowTitle(_tx(lang, "post_editor.title"))
        self.resize(1040, 760)

        root = QVBoxLayout(self)
        hint = QLabel(_tx(lang, "post_editor.hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.editor = EditableProfileWidget(
            reference_points=pre_points,
            editable_points=initial_post_points or pre_points,
            lang=lang,
        )
        root.addWidget(self.editor, 1)

        btns = QDialogButtonBox(self)
        self.btn_accept = btns.addButton(_tx(lang, "post_editor.accept"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_cancel = btns.addButton(_tx(lang, "post_editor.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_accept.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        root.addWidget(btns)

    @property
    def post_points(self) -> List[Point]:
        return self.editor.points()


class PredictionPostSmoothingDialog(QDialog):
    def __init__(
        self,
        *,
        pre_points: List[Point],
        post_points_raw: List[Point],
        initial_post_points_smooth: List[Point],
        segments: int,
        iterations: int,
        lang: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self._raw_points = [(float(x), float(y)) for x, y in post_points_raw]
        self._smoothed_points = [(float(x), float(y)) for x, y in initial_post_points_smooth]
        self._display_points: List[Point] = []
        self._controller = SmoothingController()
        self._controller.set_base_points(self._raw_points)

        self.setWindowTitle(_tx(lang, "post_smoothing.title"))
        self.resize(980, 720)

        root = QVBoxLayout(self)
        hint = QLabel(_tx(lang, "post_smoothing.hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        control_row = QHBoxLayout()
        self.spin_segments = QSpinBox()
        self.spin_segments.setRange(1, 100_000)
        self.spin_segments.setValue(max(1, int(segments)))
        self.spin_iterations = QSpinBox()
        self.spin_iterations.setRange(0, 10_000)
        self.spin_iterations.setValue(max(0, int(iterations)))
        self.btn_apply = QPushButton(_tx(lang, "post_smoothing.apply"))
        self.btn_show_raw = QPushButton(_tx(lang, "post_smoothing.raw"))
        self.btn_fit = QPushButton(_tx(lang, "post_smoothing.fit"))
        control_row.addWidget(QLabel("Segments"))
        control_row.addWidget(self.spin_segments)
        control_row.addWidget(QLabel("Iterations"))
        control_row.addWidget(self.spin_iterations)
        control_row.addWidget(self.btn_apply)
        control_row.addWidget(self.btn_show_raw)
        control_row.addWidget(self.btn_fit)
        control_row.addStretch(1)
        root.addLayout(control_row)

        self.lbl_summary = QLabel()
        root.addWidget(self.lbl_summary)

        self.view = StructureView()
        self.view.set_profile_colors(
            current=QColor(220, 90, 45),
            reference=QColor(40, 110, 205, 180),
        )
        self.view.set_reference_profiles_xy([[(float(x), float(y)) for x, y in pre_points]])
        self.view.set_point_radius_px(1.5)
        root.addWidget(self.view, 1)

        btns = QDialogButtonBox(self)
        self.btn_accept = btns.addButton(_tx(lang, "post_smoothing.accept"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_cancel = btns.addButton(_tx(lang, "post_smoothing.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_accept.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        root.addWidget(btns)

        self.btn_apply.clicked.connect(self._apply_smoothing)
        self.btn_show_raw.clicked.connect(self._show_raw)
        self.btn_fit.clicked.connect(self.view.fit_points)

        if len(self._smoothed_points) >= 2:
            self._set_display_points(self._smoothed_points, mode="smooth")
        else:
            self._apply_smoothing()

    def _set_display_points(self, points: List[Point], *, mode: str) -> None:
        self._display_points = [(float(x), float(y)) for x, y in points]
        self.view.set_points_xy(self._display_points)
        self.view.fit_points()
        if mode == "smooth":
            self.lbl_summary.setText(_tx(self.lang, "post_smoothing.summary.smooth").format(n=len(self._display_points)))
        else:
            self.lbl_summary.setText(_tx(self.lang, "post_smoothing.summary.raw").format(n=len(self._display_points)))

    def _apply_smoothing(self) -> None:
        self._controller.set_base_points(self._raw_points)
        self._controller.set_params(self.spin_segments.value(), self.spin_iterations.value())
        self._smoothed_points = self._controller.run()
        self._set_display_points(self._smoothed_points, mode="smooth")

    def _show_raw(self) -> None:
        self._set_display_points(self._raw_points, mode="raw")

    @property
    def post_points_smooth(self) -> List[Point]:
        if len(self._display_points) >= 2:
            return [(float(x), float(y)) for x, y in self._display_points]
        return [(float(x), float(y)) for x, y in self._raw_points]


class _GuideHandle(QGraphicsEllipseItem):
    def __init__(self, radius_px: float, *, brush: QColor, pen: QColor, on_move) -> None:
        super().__init__(-radius_px, -radius_px, 2 * radius_px, 2 * radius_px)
        self._on_move = on_move
        self.setBrush(QBrush(QColor(brush)))
        self.setPen(QPen(QColor(pen)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(30.0)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            p: QPointF = value
            x, y = self._on_move(float(p.x()), float(p.y()))
            return QPointF(x, y)
        return super().itemChange(change, value)


class _SectionHandle(QGraphicsRectItem):
    def __init__(self, width_px: float, *, brush: QColor, pen: QColor, on_move) -> None:
        super().__init__(-0.5 * width_px, -0.5 * width_px, width_px, width_px)
        self._on_move = on_move
        self.setBrush(QBrush(QColor(brush)))
        self.setPen(QPen(QColor(pen)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(30.0)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            p: QPointF = value
            x, y = self._on_move(float(p.x()), float(p.y()))
            return QPointF(x, y)
        return super().itemChange(change, value)


class PredictionAnchorView(QGraphicsView):
    anchorChanged = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        self._pre_points: List[Point] = []
        self._post_points: List[Point] = []
        self._anchor_spec: Dict[str, Any] = {}
        self._bounds: Dict[str, float] = {
            "min_x": -1.0,
            "max_x": 1.0,
            "top_y": 0.0,
            "bottom_y": -1.0,
        }
        self._updating = False
        self._scene_margin = 40.0

        self._left_lip_line: Optional[QGraphicsLineItem] = None
        self._right_lip_line: Optional[QGraphicsLineItem] = None
        self._top_left_line: Optional[QGraphicsLineItem] = None
        self._top_right_line: Optional[QGraphicsLineItem] = None
        self._bottom_line: Optional[QGraphicsLineItem] = None
        self._left_lip_handle: Optional[_GuideHandle] = None
        self._right_lip_handle: Optional[_GuideHandle] = None
        self._bottom_handle: Optional[_SectionHandle] = None
        self._section_lines: Dict[str, QGraphicsLineItem] = {}
        self._section_handles: Dict[str, _SectionHandle] = {}

    def set_profiles(self, pre_points: List[Point], post_points: List[Point]) -> None:
        self._pre_points = [(float(x), float(y)) for x, y in pre_points]
        self._post_points = [(float(x), float(y)) for x, y in post_points]
        all_points = self._pre_points + self._post_points
        xs = [x for x, _y in all_points] or [-1.0, 1.0]
        ys = [y for _x, y in all_points] or [0.0, -1.0]
        self._bounds = {
            "min_x": min(xs),
            "max_x": max(xs),
            "top_y": max(ys),
            "bottom_y": min(ys),
        }
        if not self._anchor_spec:
            self._anchor_spec = auto_anchor_spec(self._pre_points, self._post_points)
        else:
            self._anchor_spec = sanitize_anchor_spec(self._pre_points, self._post_points, self._anchor_spec)
        self._rebuild_scene()

    def set_anchor_spec(self, anchor_spec: Dict[str, Any]) -> None:
        self._anchor_spec = sanitize_anchor_spec(self._pre_points, self._post_points, anchor_spec)
        self._rebuild_scene()

    def anchor_spec(self) -> Dict[str, Any]:
        return dict(self._anchor_spec)

    def fit_content(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            return
        self.fitInView(
            rect.adjusted(-self._scene_margin, -self._scene_margin, self._scene_margin, self._scene_margin),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_content()

    def _scene_y(self, user_y: float) -> float:
        return -float(user_y)

    def _emit_anchor_changed(self) -> None:
        self.anchorChanged.emit(self.anchor_spec())

    def _path_from_points(self, points: List[Point]) -> QPainterPath:
        path = QPainterPath()
        if not points:
            return path
        path.moveTo(float(points[0][0]), self._scene_y(float(points[0][1])))
        for x, y in points[1:]:
            path.lineTo(float(x), self._scene_y(float(y)))
        return path

    def _scene_bounds_rect(self) -> Tuple[float, float, float, float]:
        min_x = float(self._bounds["min_x"])
        max_x = float(self._bounds["max_x"])
        top_scene = self._scene_y(float(self._bounds["top_y"]))
        bottom_scene = self._scene_y(float(self._bounds["bottom_y"]))
        top = min(top_scene, bottom_scene)
        bottom = max(top_scene, bottom_scene)
        return min_x, max_x, top, bottom

    def _rebuild_scene(self) -> None:
        self._scene.clear()
        self._section_lines = {}
        self._section_handles = {}

        pre_item = QGraphicsPathItem(self._path_from_points(self._pre_points))
        pre_pen = QPen(QColor(40, 110, 205, 220), 1.6)
        pre_pen.setCosmetic(True)
        pre_item.setPen(pre_pen)
        self._scene.addItem(pre_item)

        post_item = QGraphicsPathItem(self._path_from_points(self._post_points))
        post_pen = QPen(QColor(220, 90, 45), 1.8)
        post_pen.setCosmetic(True)
        post_item.setPen(post_pen)
        self._scene.addItem(post_item)

        dashed_green = QPen(QColor(40, 165, 95, 210), 1.3, Qt.PenStyle.DashLine)
        dashed_green.setCosmetic(True)
        dotted_green = QPen(QColor(40, 165, 95, 180), 1.1, Qt.PenStyle.DotLine)
        dotted_green.setCosmetic(True)

        self._left_lip_line = QGraphicsLineItem()
        self._left_lip_line.setPen(dashed_green)
        self._scene.addItem(self._left_lip_line)

        self._right_lip_line = QGraphicsLineItem()
        self._right_lip_line.setPen(dashed_green)
        self._scene.addItem(self._right_lip_line)

        self._top_left_line = QGraphicsLineItem()
        self._top_left_line.setPen(dotted_green)
        self._scene.addItem(self._top_left_line)

        self._top_right_line = QGraphicsLineItem()
        self._top_right_line.setPen(dotted_green)
        self._scene.addItem(self._top_right_line)

        self._bottom_line = QGraphicsLineItem()
        self._bottom_line.setPen(dashed_green)
        self._scene.addItem(self._bottom_line)

        self._left_lip_handle = _GuideHandle(
            5.0,
            brush=QColor(40, 165, 95),
            pen=QColor(25, 100, 55),
            on_move=lambda x, y: self._move_lip("left", x, y),
        )
        self._scene.addItem(self._left_lip_handle)

        self._right_lip_handle = _GuideHandle(
            5.0,
            brush=QColor(40, 165, 95),
            pen=QColor(25, 100, 55),
            on_move=lambda x, y: self._move_lip("right", x, y),
        )
        self._scene.addItem(self._right_lip_handle)

        self._bottom_handle = _SectionHandle(
            9.0,
            brush=QColor(40, 165, 95),
            pen=QColor(25, 100, 55),
            on_move=lambda x, y: self._move_bottom(y),
        )
        self._scene.addItem(self._bottom_handle)

        for section in self._anchor_spec.get("sections", []):
            sid = str(section["id"])
            line_item = QGraphicsLineItem()
            line_item.setPen(dashed_green)
            self._scene.addItem(line_item)
            self._section_lines[sid] = line_item

            handle = _SectionHandle(
                8.0,
                brush=QColor(80, 190, 120),
                pen=QColor(40, 115, 70),
                on_move=lambda x, y, section_id=sid: self._move_section(section_id, y),
            )
            self._scene.addItem(handle)
            self._section_handles[sid] = handle

        min_x, max_x, top, bottom = self._scene_bounds_rect()
        pad = max((max_x - min_x) * 0.15, 80.0)
        self._scene.setSceneRect(
            min_x - pad,
            top - 60.0,
            (max_x - min_x) + 2.0 * pad,
            (bottom - top) + 120.0,
        )
        self._update_guides_from_spec()
        self.fit_content()

    def _update_guides_from_spec(self) -> None:
        if not self._anchor_spec:
            return
        min_x, max_x, top, bottom = self._scene_bounds_rect()
        handle_x = max_x + max((max_x - min_x) * 0.08, 40.0)
        left = self._anchor_spec["left_lip"]
        right = self._anchor_spec["right_lip"]
        bottom_spec = self._anchor_spec["bottom"]
        top_spec = self._anchor_spec["top"]

        self._updating = True
        try:
            left_scene_y = self._scene_y(left["y"])
            right_scene_y = self._scene_y(right["y"])
            bottom_scene_y = self._scene_y(bottom_spec["y"])

            if self._left_lip_line is not None:
                self._left_lip_line.setLine(left["x"], top, left["x"], bottom)
            if self._right_lip_line is not None:
                self._right_lip_line.setLine(right["x"], top, right["x"], bottom)
            if self._top_left_line is not None:
                self._top_left_line.setLine(top_spec["left_x"], top, top_spec["left_x"], bottom)
            if self._top_right_line is not None:
                self._top_right_line.setLine(top_spec["right_x"], top, top_spec["right_x"], bottom)
            if self._bottom_line is not None:
                self._bottom_line.setLine(min_x, bottom_scene_y, max_x, bottom_scene_y)
            if self._left_lip_handle is not None:
                self._left_lip_handle.setPos(QPointF(left["x"], left_scene_y))
            if self._right_lip_handle is not None:
                self._right_lip_handle.setPos(QPointF(right["x"], right_scene_y))
            if self._bottom_handle is not None:
                self._bottom_handle.setPos(QPointF(handle_x, bottom_scene_y))
            for section in self._anchor_spec.get("sections", []):
                sid = str(section["id"])
                line_item = self._section_lines.get(sid)
                handle = self._section_handles.get(sid)
                scene_y = self._scene_y(section["y"])
                visible = bool(section.get("enabled", True))
                if line_item is not None:
                    line_item.setVisible(visible)
                    line_item.setLine(min_x, scene_y, max_x, scene_y)
                if handle is not None:
                    handle.setVisible(visible)
                    handle.setPos(QPointF(handle_x, scene_y))
        finally:
            self._updating = False

    def _move_lip(self, side: str, scene_x: float, scene_y: float) -> Tuple[float, float]:
        if self._updating:
            return scene_x, scene_y
        other = self._anchor_spec["right_lip"] if side == "left" else self._anchor_spec["left_lip"]
        min_x = float(self._bounds["min_x"])
        max_x = float(self._bounds["max_x"])
        top_y = float(self._bounds["top_y"])
        bottom_y = float(self._bounds["bottom_y"])
        user_y = -float(scene_y)
        if side == "left":
            user_x = max(min_x, min(float(scene_x), float(other["x"]) - 0.5))
        else:
            user_x = min(max_x, max(float(scene_x), float(other["x"]) + 0.5))
        user_y = max(bottom_y, min(top_y, user_y))
        self._anchor_spec[f"{side}_lip"] = {"x": user_x, "y": user_y}
        self._anchor_spec = sanitize_anchor_spec(self._pre_points, self._post_points, self._anchor_spec)
        self._update_guides_from_spec()
        self._emit_anchor_changed()
        point = self._anchor_spec[f"{side}_lip"]
        return float(point["x"]), self._scene_y(float(point["y"]))

    def _move_bottom(self, scene_y: float) -> Tuple[float, float]:
        if self._updating:
            return 0.0, scene_y
        top_y = max(float(self._anchor_spec["left_lip"]["y"]), float(self._anchor_spec["right_lip"]["y"]))
        bottom_limit = float(self._bounds["bottom_y"])
        user_y = max(bottom_limit, min(top_y, -float(scene_y)))
        self._anchor_spec["bottom"]["y"] = user_y
        self._anchor_spec = sanitize_anchor_spec(self._pre_points, self._post_points, self._anchor_spec)
        self._update_guides_from_spec()
        self._emit_anchor_changed()
        handle_x = self._bounds["max_x"] + max((self._bounds["max_x"] - self._bounds["min_x"]) * 0.08, 40.0)
        return float(handle_x), self._scene_y(float(self._anchor_spec["bottom"]["y"]))

    def _move_section(self, section_id: str, scene_y: float) -> Tuple[float, float]:
        if self._updating:
            return 0.0, scene_y
        upper_y = max(float(self._anchor_spec["left_lip"]["y"]), float(self._anchor_spec["right_lip"]["y"]))
        lower_y = float(self._anchor_spec["bottom"]["y"])
        user_y = max(lower_y, min(upper_y, -float(scene_y)))
        for section in self._anchor_spec.get("sections", []):
            if str(section["id"]) == str(section_id):
                section["y"] = user_y
                break
        self._anchor_spec = sanitize_anchor_spec(self._pre_points, self._post_points, self._anchor_spec)
        self._update_guides_from_spec()
        self._emit_anchor_changed()
        handle_x = self._bounds["max_x"] + max((self._bounds["max_x"] - self._bounds["min_x"]) * 0.08, 40.0)
        section = next((item for item in self._anchor_spec.get("sections", []) if str(item["id"]) == str(section_id)), None)
        section_y = self._scene_y(float(section["y"])) if section is not None else scene_y
        return float(handle_x), section_y


class PredictionAnchorDialog(QDialog):
    def __init__(
        self,
        *,
        pre_points: List[Point],
        post_points: List[Point],
        initial_anchor_spec: Dict[str, Any],
        lang: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self._pre_points = [(float(x), float(y)) for x, y in pre_points]
        self._post_points = [(float(x), float(y)) for x, y in post_points]
        self._anchor_spec = sanitize_anchor_spec(self._pre_points, self._post_points, initial_anchor_spec)
        self._syncing = False
        self._section_rows: List[Dict[str, Any]] = []

        self.setWindowTitle(_tx(lang, "anchor.title"))
        self.resize(1280, 860)

        root = QVBoxLayout(self)
        hint = QLabel(_tx(lang, "anchor.hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        self.view = PredictionAnchorView()
        self.view.set_profiles(self._pre_points, self._post_points)
        self.view.set_anchor_spec(self._anchor_spec)
        splitter.addWidget(self.view)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([860, 360])

        basic_group = QGroupBox()
        basic_form = QFormLayout(basic_group)
        self.spin_division_count = QSpinBox()
        self.spin_division_count.setRange(1, 30)
        basic_form.addRow(_tx(lang, "anchor.division_count"), self.spin_division_count)

        self.spin_left_lip_x = self._make_float_spin()
        self.spin_left_lip_y = self._make_float_spin()
        self.spin_right_lip_x = self._make_float_spin()
        self.spin_right_lip_y = self._make_float_spin()
        self.spin_top_left_x = self._make_float_spin()
        self.spin_top_right_x = self._make_float_spin()
        self.spin_bottom_y = self._make_float_spin()

        basic_form.addRow(_tx(lang, "anchor.left_lip_x"), self.spin_left_lip_x)
        basic_form.addRow(_tx(lang, "anchor.left_lip_y"), self.spin_left_lip_y)
        basic_form.addRow(_tx(lang, "anchor.right_lip_x"), self.spin_right_lip_x)
        basic_form.addRow(_tx(lang, "anchor.right_lip_y"), self.spin_right_lip_y)
        basic_form.addRow(_tx(lang, "anchor.top_left_x"), self.spin_top_left_x)
        basic_form.addRow(_tx(lang, "anchor.top_right_x"), self.spin_top_right_x)
        basic_form.addRow(_tx(lang, "anchor.bottom_y"), self.spin_bottom_y)
        right_layout.addWidget(basic_group)

        weight_group = QGroupBox()
        weight_form = QFormLayout(weight_group)
        self.spin_weight_top = self._make_float_spin(0.0, 100.0, 3, 0.1)
        self.spin_weight_lip = self._make_float_spin(0.0, 100.0, 3, 0.1)
        self.spin_weight_sidewall = self._make_float_spin(0.0, 100.0, 3, 0.1)
        self.spin_weight_bottom = self._make_float_spin(0.0, 100.0, 3, 0.1)
        weight_form.addRow(_tx(lang, "anchor.weight_top"), self.spin_weight_top)
        weight_form.addRow(_tx(lang, "anchor.weight_lip"), self.spin_weight_lip)
        weight_form.addRow(_tx(lang, "anchor.weight_sidewall"), self.spin_weight_sidewall)
        weight_form.addRow(_tx(lang, "anchor.weight_bottom"), self.spin_weight_bottom)
        right_layout.addWidget(weight_group)

        section_group = QGroupBox(_tx(lang, "anchor.section_group"))
        section_layout = QVBoxLayout(section_group)
        section_controls = QHBoxLayout()
        self.btn_fit = QPushButton(_tx(lang, "anchor.fit"))
        section_controls.addWidget(self.btn_fit)
        section_controls.addStretch(1)
        section_layout.addLayout(section_controls)

        self.section_scroll = QScrollArea()
        self.section_scroll.setWidgetResizable(True)
        self.section_container = QWidget()
        self.section_container_layout = QVBoxLayout(self.section_container)
        self.section_container_layout.setContentsMargins(0, 0, 0, 0)
        self.section_container_layout.setSpacing(6)
        self.section_scroll.setWidget(self.section_container)
        section_layout.addWidget(self.section_scroll, 1)
        right_layout.addWidget(section_group, 1)

        btns = QDialogButtonBox(self)
        self.btn_accept = btns.addButton(_tx(lang, "anchor.accept"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_cancel = btns.addButton(_tx(lang, "anchor.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_accept.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        root.addWidget(btns)

        self.view.anchorChanged.connect(self._on_view_anchor_changed)
        self.btn_fit.clicked.connect(self.view.fit_content)

        for spin in (
            self.spin_division_count,
            self.spin_left_lip_x,
            self.spin_left_lip_y,
            self.spin_right_lip_x,
            self.spin_right_lip_y,
            self.spin_top_left_x,
            self.spin_top_right_x,
            self.spin_bottom_y,
            self.spin_weight_top,
            self.spin_weight_lip,
            self.spin_weight_sidewall,
            self.spin_weight_bottom,
        ):
            spin.valueChanged.connect(self._on_controls_changed)

        self._set_spin_ranges()
        self._set_controls_from_spec(self._anchor_spec)
        self._rebuild_section_rows(self._anchor_spec)

    def _make_float_spin(
        self,
        minimum: float = -1_000_000_000.0,
        maximum: float = 1_000_000_000.0,
        decimals: int = 4,
        step: float = 1.0,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(int(decimals))
        spin.setRange(float(minimum), float(maximum))
        spin.setSingleStep(float(step))
        return spin

    def _set_spin_ranges(self) -> None:
        xs = [x for x, _y in self._pre_points + self._post_points]
        ys = [y for _x, y in self._pre_points + self._post_points]
        min_x = min(xs) if xs else -1000.0
        max_x = max(xs) if xs else 1000.0
        min_y = min(ys) if ys else -1000.0
        max_y = max(ys) if ys else 1000.0
        for spin in (
            self.spin_left_lip_x,
            self.spin_right_lip_x,
            self.spin_top_left_x,
            self.spin_top_right_x,
        ):
            spin.setRange(min_x - 5000.0, max_x + 5000.0)
        for spin in (
            self.spin_left_lip_y,
            self.spin_right_lip_y,
            self.spin_bottom_y,
        ):
            spin.setRange(min_y - 5000.0, max_y + 5000.0)

    def _set_controls_from_spec(self, spec: Dict[str, Any]) -> None:
        self._syncing = True
        try:
            self.spin_division_count.setValue(int(spec["division_count"]))
            self.spin_left_lip_x.setValue(float(spec["left_lip"]["x"]))
            self.spin_left_lip_y.setValue(float(spec["left_lip"]["y"]))
            self.spin_right_lip_x.setValue(float(spec["right_lip"]["x"]))
            self.spin_right_lip_y.setValue(float(spec["right_lip"]["y"]))
            self.spin_top_left_x.setValue(float(spec["top"]["left_x"]))
            self.spin_top_right_x.setValue(float(spec["top"]["right_x"]))
            self.spin_bottom_y.setValue(float(spec["bottom"]["y"]))
            self.spin_weight_top.setValue(float(spec["weights"]["top"]))
            self.spin_weight_lip.setValue(float(spec["weights"]["lip"]))
            self.spin_weight_sidewall.setValue(float(spec["weights"]["sidewall"]))
            self.spin_weight_bottom.setValue(float(spec["weights"]["bottom"]))
        finally:
            self._syncing = False

    def _rebuild_section_rows(self, spec: Dict[str, Any]) -> None:
        self._syncing = True
        try:
            while self.section_container_layout.count() > 0:
                item = self.section_container_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self._section_rows = []
            for idx, section in enumerate(spec.get("sections", [])):
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                title = QLabel(str(section.get("id") or f"S{idx + 1}"))
                chk = QCheckBox(_tx(self.lang, "anchor.section_enabled"))
                chk.setChecked(bool(section.get("enabled", True)))
                spin_y = self._make_float_spin()
                spin_y.setRange(self.spin_bottom_y.minimum(), self.spin_left_lip_y.maximum())
                spin_y.setValue(float(section.get("y", 0.0)))
                spin_weight = self._make_float_spin(0.0, 100.0, 3, 0.1)
                spin_weight.setValue(float(section.get("weight", 1.0)))

                row_layout.addWidget(title)
                row_layout.addWidget(chk)
                row_layout.addWidget(QLabel(_tx(self.lang, "anchor.section_y")))
                row_layout.addWidget(spin_y)
                row_layout.addWidget(QLabel(_tx(self.lang, "anchor.section_weight")))
                row_layout.addWidget(spin_weight)
                self.section_container_layout.addWidget(row_widget)
                row = {"id": str(section["id"]), "enabled": chk, "y": spin_y, "weight": spin_weight}
                self._section_rows.append(row)
                chk.toggled.connect(self._on_controls_changed)
                spin_y.valueChanged.connect(self._on_controls_changed)
                spin_weight.valueChanged.connect(self._on_controls_changed)
            self.section_container_layout.addStretch(1)
        finally:
            self._syncing = False

    def _collect_spec_from_controls(self) -> Dict[str, Any]:
        spec = {
            "division_count": int(self.spin_division_count.value()),
            "left_lip": {"x": float(self.spin_left_lip_x.value()), "y": float(self.spin_left_lip_y.value())},
            "right_lip": {"x": float(self.spin_right_lip_x.value()), "y": float(self.spin_right_lip_y.value())},
            "bottom": {
                "x": 0.5 * (float(self.spin_left_lip_x.value()) + float(self.spin_right_lip_x.value())),
                "y": float(self.spin_bottom_y.value()),
            },
            "top": {
                "left_x": float(self.spin_top_left_x.value()),
                "right_x": float(self.spin_top_right_x.value()),
            },
            "weights": {
                "top": float(self.spin_weight_top.value()),
                "lip": float(self.spin_weight_lip.value()),
                "sidewall": float(self.spin_weight_sidewall.value()),
                "bottom": float(self.spin_weight_bottom.value()),
            },
            "sections": [
                {
                    "id": row["id"],
                    "enabled": bool(row["enabled"].isChecked()),
                    "y": float(row["y"].value()),
                    "weight": float(row["weight"].value()),
                }
                for row in self._section_rows
            ],
        }
        return sanitize_anchor_spec(self._pre_points, self._post_points, spec)

    def _on_controls_changed(self, *_args) -> None:
        if self._syncing:
            return
        spec = self._collect_spec_from_controls()
        if len(spec.get("sections", [])) != len(self._section_rows):
            self._anchor_spec = spec
            self._set_controls_from_spec(spec)
            self._rebuild_section_rows(spec)
        self.view.set_anchor_spec(spec)
        self._anchor_spec = self.view.anchor_spec()

    def _on_view_anchor_changed(self, spec_obj: object) -> None:
        spec = spec_obj if isinstance(spec_obj, dict) else {}
        self._anchor_spec = sanitize_anchor_spec(self._pre_points, self._post_points, spec)
        self._set_controls_from_spec(self._anchor_spec)
        for section, row in zip(self._anchor_spec.get("sections", []), self._section_rows):
            self._syncing = True
            try:
                row["enabled"].setChecked(bool(section.get("enabled", True)))
                row["y"].setValue(float(section.get("y", 0.0)))
                row["weight"].setValue(float(section.get("weight", 1.0)))
            finally:
                self._syncing = False

    @property
    def anchor_spec(self) -> Dict[str, Any]:
        return self.view.anchor_spec()

    def accept(self) -> None:
        self._anchor_spec = self._collect_spec_from_controls()
        self.view.set_anchor_spec(self._anchor_spec)
        super().accept()
