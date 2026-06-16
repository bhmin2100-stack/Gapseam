from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

Point = Tuple[float, float]  # USER coords (x, y_user), depth is negative


def _nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    base = raw / (10 ** exp)
    if base <= 1:
        nice = 1
    elif base <= 2:
        nice = 2
    elif base <= 5:
        nice = 5
    else:
        nice = 10
    return nice * (10 ** exp)


def _fmt_tick(v: float, step: float) -> str:
    s = abs(step)
    if s >= 100:
        return f"{v:.0f}"
    if s >= 1:
        return f"{v:.1f}"
    return f"{v:.2f}"


class _DraggablePoint(QGraphicsEllipseItem):
    def __init__(
        self,
        idx: int,
        x: float,
        y: float,
        r_px: float,
        on_move: Callable[[int, float, float], Tuple[float, float]],
        on_press: Callable[[int, float, float], None],
        on_release: Callable[[int, float, float], None],
    ):
        super().__init__(-r_px, -r_px, 2 * r_px, 2 * r_px)
        self.idx = idx
        self._on_move = on_move
        self._on_press = on_press
        self._on_release = on_release
        self.setPos(QPointF(x, y))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            p: QPointF = value
            sx, sy = self._on_move(self.idx, float(p.x()), float(p.y()))
            return QPointF(sx, sy)
        return super().itemChange(change, value)

    def set_radius_px(self, r_px: float) -> None:
        self.setRect(-r_px, -r_px, 2 * r_px, 2 * r_px)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            p = self.pos()
            self._on_press(self.idx, float(p.x()), float(p.y()))

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            p = self.pos()
            self._on_release(self.idx, float(p.x()), float(p.y()))


class StructureView(QGraphicsView):
    pointMoved = Signal(int, float, float)  # idx, x_user, y_user
    pointInserted = Signal(int, float, float)  # idx, x_user, y_user
    pointDeleted = Signal(int)  # idx
    pointDragStarted = Signal(int, float, float)  # idx, x_user, y_user
    pointDragFinished = Signal(int, float, float)  # idx, x_user, y_user
    pointsMoved = Signal(list)  # [(idx, x_user, y_user), ...]

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pts: List[Tuple[float, float]] = []  # SCENE coords
        self._reference_profiles: List[List[Tuple[float, float]]] = []  # SCENE coords
        self._point_items: List[_DraggablePoint] = []
        self._path_item: Optional[QGraphicsPathItem] = None
        self._reference_items: List[QGraphicsPathItem] = []
        self._overlay_item: Optional[QGraphicsPixmapItem] = None
        self._overlay_pixmap: Optional[QPixmap] = None
        self._overlay_path: Optional[str] = None
        self._overlay_scale_a_per_px = 1.0
        self._overlay_opacity = 0.35
        self._overlay_origin = (0.0, 0.0)
        self._current_color = QColor(Qt.GlobalColor.blue)
        self._reference_color = QColor(125, 125, 125, 220)
        self._editing_enabled = True
        self._overlay_drag_enabled = False
        self._overlay_dragging = False
        self._overlay_drag_last_scene: Optional[QPointF] = None
        self._suppress_point_item_change = False
        self._multi_select_enabled = False
        self._selected_indices: set[int] = set()
        self._selection_start_scene: Optional[QPointF] = None
        self._selection_rect_item: Optional[QGraphicsRectItem] = None
        self._multi_drag_anchor_idx: Optional[int] = None
        self._multi_drag_start_pts: Optional[List[Tuple[float, float]]] = None
        self._multi_drag_indices: List[int] = []

        self._drag_label: Optional[QGraphicsSimpleTextItem] = None
        self._recreate_drag_label()

        self._radius_px = 4.0

        self._panning = False
        self._pan_start: Optional[QPointF] = None
        self._inserting_idx: Optional[int] = None

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        self._major_target_lines = 10
        self._minor_div = 5

    def _recreate_drag_label(self) -> None:
        self._drag_label = QGraphicsSimpleTextItem()
        self._drag_label.setZValue(10_000)
        self._drag_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self._drag_label.setVisible(False)
        self._scene.addItem(self._drag_label)

    def _set_drag_label_position(self, sx: float, sy: float) -> None:
        if self._drag_label is None:
            return
        anchor_scene = QPointF(float(sx), float(sy))
        anchor_view = self.mapFromScene(anchor_scene)
        # Keep a stable on-screen offset from the dragged point so the text stays readable.
        label_view = anchor_view + QPoint(10, -14)
        self._drag_label.setPos(self.mapToScene(label_view))

    def set_point_radius_px(self, r: float) -> None:
        self._radius_px = float(r)
        self._rebuild_items()

    def set_multi_select_enabled(self, enabled: bool) -> None:
        self._multi_select_enabled = bool(enabled)
        if not self._multi_select_enabled:
            self.clear_point_selection()

    def selected_point_indices(self) -> List[int]:
        return sorted(idx for idx in self._selected_indices if 0 <= idx < len(self._pts))

    def clear_point_selection(self) -> None:
        if not self._selected_indices:
            return
        self._selected_indices.clear()
        self._sync_selected_point_items()

    def set_points_xy(self, pts: List[Point]) -> None:
        # USER -> SCENE conversion: y_scene = -y_user (depth goes down visually)
        self._pts = [(float(x), -float(y)) for x, y in pts]
        self._selected_indices.clear()
        self._multi_drag_anchor_idx = None
        self._multi_drag_start_pts = None
        self._multi_drag_indices = []
        self._selection_start_scene = None
        self._selection_rect_item = None
        self._rebuild_items()
        self._fit_if_first()

    def set_point_xy_silent(self, idx: int, x: float, y: float) -> None:
        point_idx = int(idx)
        if point_idx < 0 or point_idx >= len(self._pts):
            return
        sx, sy = float(x), -float(y)
        self._pts[point_idx] = (sx, sy)
        if point_idx < len(self._point_items):
            self._suppress_point_item_change = True
            try:
                self._point_items[point_idx].setPos(QPointF(sx, sy))
            finally:
                self._suppress_point_item_change = False
        self._update_path_from_points()

    def set_reference_profiles_xy(self, profiles: List[List[Point]]) -> None:
        converted: List[List[Tuple[float, float]]] = []
        for profile in profiles:
            if not isinstance(profile, list) or len(profile) < 2:
                continue
            try:
                converted.append([(float(x), -float(y)) for x, y in profile])
            except Exception:
                continue
        self._reference_profiles = converted
        self._rebuild_items()

    def set_profile_colors(
        self,
        *,
        current: Optional[QColor] = None,
        reference: Optional[QColor] = None,
    ) -> None:
        changed = False
        if current is not None:
            self._current_color = QColor(current)
            changed = True
        if reference is not None:
            self._reference_color = QColor(reference)
            changed = True
        if changed:
            self._rebuild_items()

    def set_editing_enabled(self, enabled: bool) -> None:
        enabled_bool = bool(enabled)
        if self._editing_enabled == enabled_bool:
            return
        self._editing_enabled = enabled_bool
        self._rebuild_items()

    def fit_points(self, padding: float = 50.0, center_x_on_origin: bool = True) -> None:
        all_profiles: List[List[Tuple[float, float]]] = []
        if self._pts:
            all_profiles.append(self._pts)
        if self._reference_profiles:
            all_profiles.extend(self._reference_profiles)
        if not all_profiles:
            return
        xs = [x for profile in all_profiles for x, _ in profile]
        ys = [y for profile in all_profiles for _, y in profile]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        # Keep origin and x-axis in view on first fit.
        y0 = min(y0, 0.0)
        y1 = max(y1, 0.0)
        if center_x_on_origin:
            half = max(abs(x0), abs(x1), 1.0)
            x0, x1 = -half, half
        if abs(x1 - x0) < 1e-9:
            x1 = x0 + 1.0
        if abs(y1 - y0) < 1e-9:
            y1 = y0 + 1.0
        rect = QRectF(x0, y0, x1 - x0, y1 - y0)
        self.resetTransform()
        self.fitInView(
            rect.adjusted(-padding, -padding, padding, padding),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def set_overlay_image(
        self,
        image_path: str,
        *,
        scale_a_per_px: float,
        opacity: float = 0.35,
        origin_x: Optional[float] = None,
        origin_y: Optional[float] = None,
        align_to_axes: bool = True,
    ) -> bool:
        pix = QPixmap(image_path)
        if pix.isNull():
            return False
        self._overlay_pixmap = pix
        self._overlay_path = str(image_path)
        self._overlay_scale_a_per_px = max(float(scale_a_per_px), 1e-12)
        self._overlay_opacity = max(0.0, min(1.0, float(opacity)))
        if align_to_axes:
            ox = -0.5 * float(pix.width()) * self._overlay_scale_a_per_px
            oy = 0.0
        else:
            ox = float(origin_x or 0.0)
            oy = float(origin_y or 0.0)
        self._overlay_origin = (ox, oy)
        self._rebuild_items()
        return True

    def set_overlay_drag_enabled(self, enabled: bool) -> None:
        self._overlay_drag_enabled = bool(enabled)
        if not self._overlay_drag_enabled:
            self._overlay_dragging = False
            self._overlay_drag_last_scene = None
        if self._overlay_drag_enabled:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def clear_overlay_image(self) -> None:
        self._overlay_item = None
        self._overlay_pixmap = None
        self._overlay_path = None
        self.set_overlay_drag_enabled(False)
        self._rebuild_items()

    def set_overlay_opacity(self, opacity: float) -> None:
        self._overlay_opacity = max(0.0, min(1.0, float(opacity)))
        if self._overlay_item is not None:
            self._overlay_item.setOpacity(self._overlay_opacity)

    def get_overlay_state(self) -> Optional[dict]:
        if self._overlay_path is None or self._overlay_pixmap is None:
            return None
        return {
            "image_path": self._overlay_path,
            "scale_a_per_px": float(self._overlay_scale_a_per_px),
            "opacity": float(self._overlay_opacity),
            "origin_x": float(self._overlay_origin[0]),
            "origin_y": float(self._overlay_origin[1]),
            "align_to_axes": True,
        }

    def _fit_if_first(self) -> None:
        if not self._pts:
            return
        if not hasattr(self, "_ever_fit"):
            self._ever_fit = True
            self.resetTransform()
            self.fitInView(self._scene.itemsBoundingRect().adjusted(-50, -50, 50, 50), Qt.AspectRatioMode.KeepAspectRatio)

    def _snap(self, x: float, y: float) -> Tuple[float, float]:
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        major_step = _nice_step(rect.width() / self._major_target_lines)
        minor_step = major_step / self._minor_div
        snap = minor_step / 2.0
        if snap <= 0:
            return x, y
        sx = round(x / snap) * snap
        sy = round(y / snap) * snap
        return sx, sy

    def _on_item_move_raw(self, idx: int, x: float, y: float) -> Tuple[float, float]:
        if self._suppress_point_item_change:
            return float(x), float(y)
        if not self._editing_enabled:
            if 0 <= idx < len(self._pts):
                return self._pts[idx]
            return float(x), float(y)
        sx, sy = self._snap(x, y)
        if (
            self._multi_select_enabled
            and self._multi_drag_anchor_idx == idx
            and self._multi_drag_start_pts is not None
            and len(self._multi_drag_indices) > 1
            and 0 <= idx < len(self._multi_drag_start_pts)
        ):
            base_x, base_y = self._multi_drag_start_pts[idx]
            dx, dy = sx - base_x, sy - base_y
            moved: List[Tuple[int, float, float]] = []
            self._suppress_point_item_change = True
            try:
                for point_idx in self._multi_drag_indices:
                    if point_idx < 0 or point_idx >= len(self._pts) or point_idx >= len(self._multi_drag_start_pts):
                        continue
                    ox, oy = self._multi_drag_start_pts[point_idx]
                    nx, ny = ox + dx, oy + dy
                    self._pts[point_idx] = (nx, ny)
                    if point_idx != idx and point_idx < len(self._point_items):
                        self._point_items[point_idx].setPos(QPointF(nx, ny))
                    moved.append((point_idx, nx, -ny))
            finally:
                self._suppress_point_item_change = False
            self._update_path_from_points()
            if self._drag_label is not None:
                self._drag_label.setText(f"{len(moved)} pts | ({sx:.1f}, {-sy:.1f})")
                self._set_drag_label_position(sx, sy)
                self._drag_label.setVisible(True)
            if moved:
                self.pointsMoved.emit(moved)
            return sx, sy
        if 0 <= idx < len(self._pts):
            self._pts[idx] = (sx, sy)
            self._update_path_from_points()
        if self._drag_label is not None:
            self._drag_label.setText(f"({sx:.1f}, {-sy:.1f})")
            self._set_drag_label_position(sx, sy)
            self._drag_label.setVisible(True)
        self.pointMoved.emit(idx, sx, -sy)
        return sx, sy

    def _on_item_drag_start_raw(self, idx: int, x: float, y: float) -> None:
        self._multi_drag_anchor_idx = None
        self._multi_drag_start_pts = None
        self._multi_drag_indices = []
        if self._multi_select_enabled:
            if idx not in self._selected_indices:
                self._selected_indices = {int(idx)}
                self._sync_selected_point_items()
            selected = self.selected_point_indices()
            if idx in selected and len(selected) > 1:
                self._multi_drag_anchor_idx = int(idx)
                self._multi_drag_start_pts = list(self._pts)
                self._multi_drag_indices = selected
        self.pointDragStarted.emit(idx, float(x), -float(y))

    def _on_item_drag_finish_raw(self, idx: int, x: float, y: float) -> None:
        self.pointDragFinished.emit(idx, float(x), -float(y))
        self._multi_drag_anchor_idx = None
        self._multi_drag_start_pts = None
        self._multi_drag_indices = []

    def _rebuild_items(self) -> None:
        self._scene.clear()
        self._selection_start_scene = None
        self._selection_rect_item = None
        self._recreate_drag_label()
        self._add_overlay_item()
        self._reference_items = []
        ref_pen = QPen(QColor(self._reference_color), 1.4)
        ref_pen.setCosmetic(True)
        for prof in self._reference_profiles:
            if len(prof) < 2:
                continue
            ref_path = QPainterPath()
            ref_path.moveTo(prof[0][0], prof[0][1])
            for x, y in prof[1:]:
                ref_path.lineTo(x, y)
            ref_item = QGraphicsPathItem(ref_path)
            ref_item.setPen(ref_pen)
            ref_item.setZValue(-5.0)
            self._scene.addItem(ref_item)
            self._reference_items.append(ref_item)

        path = QPainterPath()
        if self._pts:
            path.moveTo(self._pts[0][0], self._pts[0][1])
            for x, y in self._pts[1:]:
                path.lineTo(x, y)

        self._path_item = QGraphicsPathItem(path)
        path_pen = QPen(QColor(self._current_color), 1.6)
        path_pen.setCosmetic(True)
        self._path_item.setPen(path_pen)
        self._scene.addItem(self._path_item)

        self._point_items = []
        r_px = max(self._radius_px, 0.5)
        for i, (x, y) in enumerate(self._pts):
            it = _DraggablePoint(
                i,
                x,
                y,
                r_px,
                self._on_item_move_raw,
                self._on_item_drag_start_raw,
                self._on_item_drag_finish_raw,
            )
            if not self._editing_enabled:
                it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                it.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            it.setBrush(QBrush(QColor(self._current_color)))
            it.setPen(QPen(QColor(self._current_color)))
            self._scene.addItem(it)
            self._point_items.append(it)

        self._selected_indices = {idx for idx in self._selected_indices if 0 <= idx < len(self._point_items)}
        self._sync_selected_point_items()
        self._ensure_scene_margin()

    def _sync_selected_point_items(self) -> None:
        selected_pen = QPen(QColor("#f59e0b"), 2.2)
        selected_pen.setCosmetic(True)
        normal_pen = QPen(QColor(self._current_color))
        normal_pen.setCosmetic(True)
        selected_brush = QBrush(QColor("#fbbf24"))
        normal_brush = QBrush(QColor(self._current_color))
        for idx, item in enumerate(self._point_items):
            is_selected = self._multi_select_enabled and idx in self._selected_indices
            item.setSelected(is_selected)
            item.setPen(selected_pen if is_selected else normal_pen)
            item.setBrush(selected_brush if is_selected else normal_brush)

    def _add_overlay_item(self) -> None:
        self._overlay_item = None
        if self._overlay_pixmap is None:
            return
        item = QGraphicsPixmapItem(self._overlay_pixmap)
        item.setPos(QPointF(float(self._overlay_origin[0]), float(self._overlay_origin[1])))
        item.setScale(float(self._overlay_scale_a_per_px))
        item.setOpacity(float(self._overlay_opacity))
        item.setZValue(-1000.0)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._scene.addItem(item)
        self._overlay_item = item

    def _update_path_from_points(self) -> None:
        if self._path_item is None:
            return
        path = QPainterPath()
        if self._pts:
            path.moveTo(self._pts[0][0], self._pts[0][1])
            for x, y in self._pts[1:]:
                path.lineTo(x, y)
        self._path_item.setPath(path)

    def _dist_point_to_segment_px(self, p: QPointF, a: QPointF, b: QPointF) -> float:
        ax, ay = float(a.x()), float(a.y())
        bx, by = float(b.x()), float(b.y())
        px, py = float(p.x()), float(p.y())
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        vv = vx * vx + vy * vy
        if vv <= 1e-12:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
        cx, cy = ax + t * vx, ay + t * vy
        return math.hypot(px - cx, py - cy)

    def _find_point_near_click(self, scene_pos: QPointF, thresh_px: float = 10.0) -> Optional[int]:
        if not self._pts:
            return None
        pv = QPointF(self.mapFromScene(scene_pos))
        best_i: Optional[int] = None
        best_d = 1e18
        for i, (x, y) in enumerate(self._pts):
            qv = QPointF(self.mapFromScene(QPointF(x, y)))
            d = math.hypot(float(pv.x() - qv.x()), float(pv.y() - qv.y()))
            if d < best_d:
                best_d = d
                best_i = i
        if best_i is not None and best_d <= thresh_px:
            return best_i
        return None

    def _find_segment_near_click(self, scene_pos: QPointF, thresh_px: float = 8.0) -> Optional[int]:
        if len(self._pts) < 2:
            return None
        pv = QPointF(self.mapFromScene(scene_pos))
        best_i: Optional[int] = None
        best_d = 1e18
        for i in range(len(self._pts) - 1):
            ax, ay = self._pts[i]
            bx, by = self._pts[i + 1]
            av = QPointF(self.mapFromScene(QPointF(ax, ay)))
            bv = QPointF(self.mapFromScene(QPointF(bx, by)))
            d = self._dist_point_to_segment_px(pv, av, bv)
            if d < best_d:
                best_d = d
                best_i = i
        if best_i is not None and best_d <= thresh_px:
            return best_i
        return None

    def _insert_point_and_start_drag(self, seg_i: int, scene_pos: QPointF) -> None:
        sx, sy = self._snap(float(scene_pos.x()), float(scene_pos.y()))
        insert_idx = seg_i + 1
        self._pts.insert(insert_idx, (sx, sy))
        self._selected_indices = {insert_idx} if self._multi_select_enabled else set()
        self._rebuild_items()
        self._inserting_idx = insert_idx
        if self._drag_label is not None:
            self._drag_label.setText(f"({sx:.1f}, {-sy:.1f})")
            self._set_drag_label_position(sx, sy)
            self._drag_label.setVisible(True)
        self.pointInserted.emit(insert_idx, sx, -sy)
        self.pointDragStarted.emit(insert_idx, sx, -sy)

    def _delete_point_at(self, idx: int) -> bool:
        if len(self._pts) <= 2:
            return False
        if idx <= 0 or idx >= (len(self._pts) - 1):
            return False
        self._pts.pop(idx)
        if self._multi_select_enabled:
            self._selected_indices = {
                (selected_idx - 1 if selected_idx > idx else selected_idx)
                for selected_idx in self._selected_indices
                if selected_idx != idx
            }
        self._inserting_idx = None
        self._rebuild_items()
        if self._drag_label is not None:
            self._drag_label.setVisible(False)
        self.pointDeleted.emit(idx)
        return True

    def _ensure_scene_margin(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            self._scene.setSceneRect(-1000, -1000, 2000, 2000)
            return
        margin = max(rect.width(), rect.height(), 300.0) * 2.0
        self._scene.setSceneRect(rect.adjusted(-margin, -margin, margin, margin))

    def _mouse_event_pos(self, event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def drawBackground(self, painter, rect) -> None:
        super().drawBackground(painter, rect)

        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        w = visible.width()
        if w <= 0:
            return
        major_step = _nice_step(w / self._major_target_lines)
        minor_step = major_step / self._minor_div

        # minor dotted grid
        minor_pen = QPen(Qt.GlobalColor.lightGray, 1, Qt.PenStyle.DotLine)
        minor_pen.setCosmetic(True)
        painter.setPen(minor_pen)
        x0 = math.floor(visible.left() / minor_step) * minor_step
        x = x0
        while x <= visible.right():
            painter.drawLine(x, visible.top(), x, visible.bottom())
            x += minor_step
        y0 = math.floor(visible.top() / minor_step) * minor_step
        y = y0
        while y <= visible.bottom():
            painter.drawLine(visible.left(), y, visible.right(), y)
            y += minor_step

        # major dashed grid
        major_pen = QPen(Qt.GlobalColor.gray, 1, Qt.PenStyle.DashLine)
        major_pen.setCosmetic(True)
        painter.setPen(major_pen)
        x0 = math.floor(visible.left() / major_step) * major_step
        x = x0
        while x <= visible.right():
            painter.drawLine(x, visible.top(), x, visible.bottom())
            x += major_step
        y0 = math.floor(visible.top() / major_step) * major_step
        y = y0
        while y <= visible.bottom():
            painter.drawLine(visible.left(), y, visible.right(), y)
            y += major_step

        # axes (draw last so they stay visible)
        axis_pen = QPen(Qt.GlobalColor.black, 2)
        axis_pen.setCosmetic(True)
        painter.setPen(axis_pen)
        painter.drawLine(visible.left(), 0, visible.right(), 0)
        painter.drawLine(0, visible.top(), 0, visible.bottom())
        self._draw_axis_labels(painter, visible, major_step)

    def _draw_axis_labels(self, painter, rect, major_step: float) -> None:
        painter.save()
        painter.resetTransform()
        painter.setPen(Qt.GlobalColor.darkGray)

        vp_rect = self.viewport().rect()
        x_axis_v = self.mapFromScene(QPointF(0.0, 0.0)).y()
        y_axis_v = self.mapFromScene(QPointF(0.0, 0.0)).x()

        x_label_y = min(max(x_axis_v + 14, 14), vp_rect.height() - 4)
        y_label_x = min(max(y_axis_v + 6, 4), vp_rect.width() - 40)

        x0 = math.floor(rect.left() / major_step) * major_step
        x = x0
        last_x_label = -1e18
        while x <= rect.right():
            p = self.mapFromScene(QPointF(x, 0.0))
            if 0 <= p.x() <= vp_rect.width() and (p.x() - last_x_label) >= 46:
                painter.drawText(p.x() + 2, x_label_y, _fmt_tick(x, major_step))
                last_x_label = p.x()
            x += major_step

        y0 = math.floor(rect.top() / major_step) * major_step
        y = y0
        last_y_label = -1e18
        while y <= rect.bottom():
            p = self.mapFromScene(QPointF(0.0, y))
            if 0 <= p.y() <= vp_rect.height() and (p.y() - last_y_label) >= 20:
                painter.drawText(y_label_x, p.y() - 2, _fmt_tick(-y, major_step))
                last_y_label = p.y()
            y += major_step

        painter.restore()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.0015 ** angle
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if (
            self._multi_select_enabled
            and self._editing_enabled
            and event.button() == Qt.MouseButton.LeftButton
            and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            event_pos = self._mouse_event_pos(event)
            self._selection_start_scene = self.mapToScene(event_pos)
            if self._selection_rect_item is not None:
                self._scene.removeItem(self._selection_rect_item)
            rect = QRectF(self._selection_start_scene, self._selection_start_scene)
            self._selection_rect_item = QGraphicsRectItem(rect)
            pen = QPen(QColor("#2563eb"), 1.2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._selection_rect_item.setPen(pen)
            self._selection_rect_item.setBrush(QBrush(QColor(37, 99, 235, 36)))
            self._selection_rect_item.setZValue(9_000)
            self._scene.addItem(self._selection_rect_item)
            event.accept()
            return
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_start = QPointF(self._mouse_event_pos(event))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (
            self._overlay_drag_enabled
            and self._overlay_item is not None
            and event.button() == Qt.MouseButton.LeftButton
            and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self._overlay_dragging = True
            self._overlay_drag_last_scene = self.mapToScene(self._mouse_event_pos(event))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (
            self._editing_enabled
            and event.button() == Qt.MouseButton.RightButton
            and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            scene_pos = self.mapToScene(self._mouse_event_pos(event))
            pidx = self._find_point_near_click(scene_pos)
            if pidx is not None and self._delete_point_at(pidx):
                event.accept()
                return
        if (
            self._editing_enabled
            and event.button() == Qt.MouseButton.LeftButton
            and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            scene_pos = self.mapToScene(self._mouse_event_pos(event))
            pidx = self._find_point_near_click(scene_pos)
            if pidx is None:
                seg_i = self._find_segment_near_click(scene_pos)
                if seg_i is not None:
                    self._insert_point_and_start_drag(seg_i, scene_pos)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._selection_start_scene is not None and self._selection_rect_item is not None:
            now_scene = self.mapToScene(self._mouse_event_pos(event))
            self._selection_rect_item.setRect(QRectF(self._selection_start_scene, now_scene).normalized())
            event.accept()
            return
        if self._panning and self._pan_start is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            event_pos = QPointF(self._mouse_event_pos(event))
            delta = event_pos - self._pan_start
            self._pan_start = event_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        if (
            self._overlay_dragging
            and self._overlay_item is not None
            and self._overlay_drag_last_scene is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            now_scene = self.mapToScene(self._mouse_event_pos(event))
            delta = now_scene - self._overlay_drag_last_scene
            self._overlay_drag_last_scene = now_scene
            new_pos = self._overlay_item.pos() + delta
            self._overlay_item.setPos(new_pos)
            self._overlay_origin = (float(new_pos.x()), float(new_pos.y()))
            event.accept()
            return
        if self._inserting_idx is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            idx = self._inserting_idx
            if 0 <= idx < len(self._point_items):
                self._point_items[idx].setPos(self.mapToScene(self._mouse_event_pos(event)))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._selection_start_scene is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = QRectF(self._selection_start_scene, self.mapToScene(self._mouse_event_pos(event))).normalized()
            if self._selection_rect_item is not None:
                self._scene.removeItem(self._selection_rect_item)
                self._selection_rect_item = None
            self._selection_start_scene = None
            min_view_span = 3.0
            view_rect = QRectF(QPointF(self.mapFromScene(rect.topLeft())), QPointF(self.mapFromScene(rect.bottomRight()))).normalized()
            if view_rect.width() >= min_view_span or view_rect.height() >= min_view_span:
                self._selected_indices = {
                    idx
                    for idx, (x, y) in enumerate(self._pts)
                    if rect.contains(QPointF(float(x), float(y)))
                }
            else:
                self._selected_indices.clear()
            self._sync_selected_point_items()
            event.accept()
            return
        if self._panning and event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._pan_start = None
            if self._overlay_drag_enabled:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._overlay_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._overlay_dragging = False
            self._overlay_drag_last_scene = None
            if self._overlay_drag_enabled:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._inserting_idx is not None and event.button() == Qt.MouseButton.LeftButton:
            idx = self._inserting_idx
            self._inserting_idx = None
            if 0 <= idx < len(self._pts):
                px, py = self._pts[idx]
                self.pointDragFinished.emit(idx, px, -py)
            if self._drag_label is not None:
                self._drag_label.setVisible(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._drag_label is not None:
            self._drag_label.setVisible(False)
