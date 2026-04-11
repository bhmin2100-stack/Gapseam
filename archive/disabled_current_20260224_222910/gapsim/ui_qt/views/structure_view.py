from __future__ import annotations

import math
from typing import List, Tuple, Optional

from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsSimpleTextItem,
    QGraphicsItem,
)
from PySide6.QtGui import QPen, QBrush, QPainter, QColor, QPainterPath
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QPoint


# ---------------- Geometry utils (self-intersection check) ----------------
_EPS = 1e-9


def _orient(a: QPointF, b: QPointF, c: QPointF) -> float:
    return (b.x() - a.x()) * (c.y() - a.y()) - (b.y() - a.y()) * (c.x() - a.x())


def _on_segment(a: QPointF, b: QPointF, p: QPointF) -> bool:
    return (
        min(a.x(), b.x()) - _EPS <= p.x() <= max(a.x(), b.x()) + _EPS
        and min(a.y(), b.y()) - _EPS <= p.y() <= max(a.y(), b.y()) + _EPS
        and abs(_orient(a, b, p)) <= _EPS
    )


def _segments_intersect(a1: QPointF, a2: QPointF, b1: QPointF, b2: QPointF) -> bool:
    o1 = _orient(a1, a2, b1)
    o2 = _orient(a1, a2, b2)
    o3 = _orient(b1, b2, a1)
    o4 = _orient(b1, b2, a2)

    if (o1 > _EPS and o2 < -_EPS) or (o1 < -_EPS and o2 > _EPS):
        if (o3 > _EPS and o4 < -_EPS) or (o3 < -_EPS and o4 > _EPS):
            return True

    if abs(o1) <= _EPS and _on_segment(a1, a2, b1):
        return True
    if abs(o2) <= _EPS and _on_segment(a1, a2, b2):
        return True
    if abs(o3) <= _EPS and _on_segment(b1, b2, a1):
        return True
    if abs(o4) <= _EPS and _on_segment(b1, b2, a2):
        return True

    return False


def _has_self_intersection(points: List[QPointF]) -> bool:
    """
    Rule:
    - adjacent segments sharing endpoints are allowed.
    - everything else (cross/touch/overlap) is forbidden.
    """
    n = len(points)
    if n < 4:
        return False
    for i in range(n - 1):
        a1, a2 = points[i], points[i + 1]
        for j in range(i + 1, n - 1):
            if abs(i - j) <= 1:
                continue
            b1, b2 = points[j], points[j + 1]
            if _segments_intersect(a1, a2, b1, b2):
                return True
    return False


# ---------------- Draggable point item ----------------
class _PointItem(QGraphicsEllipseItem):
    def __init__(self, idx: int, center: QPointF, radius_px: float, view: "StructureView"):
        super().__init__(-radius_px, -radius_px, 2 * radius_px, 2 * radius_px)
        self._idx = idx
        self._view = view
        self.setPos(center)

        self.setZValue(10)
        self.setPen(QPen(Qt.blue, 0))
        self.setBrush(QBrush(Qt.blue))

        # keep size constant in screen pixels when zooming
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptedMouseButtons(Qt.LeftButton)

    @property
    def idx(self) -> int:
        return self._idx

    def set_radius_px(self, r: float) -> None:
        self.setRect(-r, -r, 2 * r, 2 * r)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            new_pos: QPointF = value
            return self._view._propose_point_pos(self._idx, new_pos, self.pos())
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._view._on_point_moved(self._idx, self.pos())
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            event.ignore()
            return
        self._view._begin_user_edit()
        self._view._show_coord_label(self.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            event.ignore()
            return
        self._view._update_coord_label(self.pos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            event.ignore()
            return
        self._view._hide_coord_label()
        self._view._end_user_edit()
        super().mouseReleaseEvent(event)


# ---------------- Main View ----------------
class StructureView(QGraphicsView):
    """
    External coords rule:
    - USER coords: (x, y_user) where depth is negative.
    - Scene coords: (x, y_scene) where down is positive -> y_scene = -y_user

    UX:
    - Drag points (snap + intersection guard)
    - Insert: left click on a segment (not on point)
    - Delete: right click on internal point, or Delete key handled in table view
    - Pan: Ctrl + left drag
    - Zoom: Ctrl + wheel
    """
    editBegan = Signal(object)                 # List[(x,y_user)]
    pointMoved = Signal(int, float, float)     # idx, x, y_user
    pointInserted = Signal(int, float, float)  # insert_idx, x, y_user
    pointDeleted = Signal(int)                 # deleted_idx

    def __init__(self) -> None:
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        # display unit
        self._unit_name = "Å"
        self._unit_scale = 1.0

        # point radius (screen px)
        self._point_radius_px = 4

        # panning (Ctrl + left drag)
        self._panning = False
        self._pan_start_view_pos = None
        self._pan_start_center_scene = None

        # grid density
        self._minor_grid_target_lines = 20

        # snap: minor grid / divisor
        self._snap_divisor = 5

        # suppress emit for programmatic updates
        self._suppress_emit = False

        # undo snapshot guard
        self._edit_active = False

        # insertion drag state
        self._inserting_idx: Optional[int] = None

        # geometry items (scene coords)
        self._points: List[QPointF] = []
        self._point_items: List[_PointItem] = []
        self._line_items: List[QGraphicsLineItem] = []

        # "walls" (scene coords) - computed dynamically (view-only wall)
        self._wall_x_left: Optional[float] = None
        self._wall_x_right: Optional[float] = None

        # coord bubble (pixel-size fixed)
        self._coord_label = QGraphicsSimpleTextItem()
        self._coord_label.setZValue(100)
        self._coord_label.setBrush(QBrush(Qt.black))
        self._coord_label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self._coord_label.hide()
        self.scene.addItem(self._coord_label)

        # default points
        self.set_points_xy([
            (200.0, 0.0),
            (100.0, 0.0),
            (50.0, -400.0),
            (-50.0, -400.0),
            (-100.0, 0.0),
            (-200.0, 0.0),
        ])
        self._ensure_scene_margin()

    # ---------- public: point size ----------
    def set_point_radius_px(self, px: int) -> None:
        px = max(1, int(px))
        self._point_radius_px = px
        for it in self._point_items:
            it.set_radius_px(px)
        self.viewport().update()

    # ---------- public: walls info ----------
    def get_walls_x(self) -> Tuple[Optional[float], Optional[float]]:
        """
        wall x positions in USER coords(=scene x), None if no points.
        """
        return self._wall_x_left, self._wall_x_right

    def get_virtual_boundary_points_xy(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """
        Optional helper:
        Virtual endpoints that connect to walls (USER coords).
        - right wall point: (wall_x_right, y_first)
        - left wall point : (wall_x_left, y_last)
        """
        if not self._points or self._wall_x_left is None or self._wall_x_right is None:
            return None
        y_first = -self._points[0].y()
        y_last = -self._points[-1].y()
        return (self._wall_x_right, y_first), (self._wall_x_left, y_last)

    # ---------- External API (USER coords) ----------
    def set_points_xy(self, pts: List[Tuple[float, float]]) -> None:
        qpts = [QPointF(x, -y) for x, y in pts]
        self._set_points(qpts)

    def try_set_point_xy(self, idx: int, x: float, y: float) -> Tuple[float, float]:
        if idx < 0 or idx >= len(self._point_items):
            return x, y

        self._suppress_emit = True
        self._point_items[idx].setPos(QPointF(x, -y))
        self._suppress_emit = False

        pos = self._point_items[idx].pos()
        self._apply_point_pos(idx, pos, emit=False)
        return pos.x(), -pos.y()

    def get_points_xy(self) -> List[Tuple[float, float]]:
        return [(p.x(), -p.y()) for p in self._points]

    # ---------- Undo snapshot helpers ----------
    def _begin_user_edit(self) -> None:
        if not self._edit_active:
            self.editBegan.emit(self.get_points_xy())
            self._edit_active = True

    def _end_user_edit(self) -> None:
        self._edit_active = False

    # ---------- Core drawing ----------
    def _set_points(self, qpts: List[QPointF]) -> None:
        self._suppress_emit = True

        for it in self._line_items:
            self.scene.removeItem(it)
        for it in self._point_items:
            self.scene.removeItem(it)

        self._points = [QPointF(p) for p in qpts]
        self._point_items = []
        self._line_items = []

        pen_line = QPen(Qt.black, 0)
        pen_line.setStyle(Qt.SolidLine)

        for i in range(len(self._points) - 1):
            a, b = self._points[i], self._points[i + 1]
            li = self.scene.addLine(a.x(), a.y(), b.x(), b.y(), pen_line)
            li.setZValue(5)
            self._line_items.append(li)

        for i, p in enumerate(self._points):
            pi = _PointItem(i, p, self._point_radius_px, self)
            self.scene.addItem(pi)
            self._point_items.append(pi)

        self._ensure_scene_margin()
        self.viewport().update()
        self._suppress_emit = False

    # ---------- Grid ----------
    def _choose_grid_steps(self, visible_rect: QRectF) -> tuple[float, float]:
        span = max(visible_rect.width(), visible_rect.height())
        if span <= 0:
            return 10.0, 20.0
        target_minor = span / float(self._minor_grid_target_lines)
        k = math.floor(math.log10(max(target_minor, 1e-12) / 5.0))
        cand1 = 5.0 * (10.0**k)
        cand2 = 5.0 * (10.0 ** (k + 1))
        minor = cand1 if abs(cand1 - target_minor) <= abs(cand2 - target_minor) else cand2
        minor = max(minor, 1e-9)
        return minor, minor * 2.0

    def _update_walls_from_points(self, minor_step: float) -> None:
        if len(self._points) < 2:
            self._wall_x_left = None
            self._wall_x_right = None
            return
        xs = [p.x() for p in self._points]
        x_min = min(xs)
        x_max = max(xs)
        offset = max(minor_step * 2.0, minor_step)
        self._wall_x_left = x_min - offset
        self._wall_x_right = x_max + offset

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)

        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        minor_step, major_step = self._choose_grid_steps(visible)

        left, right = visible.left(), visible.right()
        top, bottom = visible.top(), visible.bottom()

        painter.save()

        # Si fill below boundary
        if len(self._points) >= 2:
            max_y = max(p.y() for p in self._points)
            pad = visible.height() * 0.5 + 200
            y_floor = max(bottom, max_y) + pad

            path = QPainterPath()
            path.moveTo(self._points[0])
            for p in self._points[1:]:
                path.lineTo(p)
            path.lineTo(self._points[-1].x(), y_floor)
            path.lineTo(self._points[0].x(), y_floor)
            path.closeSubpath()

            painter.fillPath(path, QBrush(QColor(220, 220, 220)))

        # view-only walls
        self._update_walls_from_points(minor_step)
        if self._wall_x_left is not None and self._wall_x_right is not None:
            pen_wall = QPen(QColor(80, 80, 80), 0, Qt.SolidLine)
            painter.setPen(pen_wall)
            painter.drawLine(self._wall_x_left, top, self._wall_x_left, bottom)
            painter.drawLine(self._wall_x_right, top, self._wall_x_right, bottom)

        # grid
        pen_minor = QPen(Qt.lightGray, 0, Qt.DotLine)
        pen_major = QPen(Qt.gray, 0, Qt.DotLine)

        def align_start(v: float, step: float) -> float:
            return math.floor(v / step) * step

        x0 = align_start(left, minor_step)
        y0 = align_start(top, minor_step)

        x = x0
        while x <= right:
            painter.setPen(pen_major if abs((x / major_step) - round(x / major_step)) < 1e-9 else pen_minor)
            painter.drawLine(x, top, x, bottom)
            x += minor_step

        y = y0
        while y <= bottom:
            painter.setPen(pen_major if abs((y / major_step) - round(y / major_step)) < 1e-9 else pen_minor)
            painter.drawLine(left, y, right, y)
            y += minor_step

        painter.restore()

    # ---------- Scene margin ----------
    def _ensure_scene_margin(self) -> None:
        items_rect = self.scene.itemsBoundingRect()
        if items_rect.isNull():
            items_rect = QRectF(0, 0, 100, 100)

        vp = self.viewport().rect()
        tl = self.mapToScene(vp.topLeft())
        br = self.mapToScene(vp.bottomRight())
        vp_w = abs(br.x() - tl.x())
        vp_h = abs(br.y() - tl.y())

        w = max(items_rect.width(), vp_w)
        h = max(items_rect.height(), vp_h)

        margin = max(w, h) * 1.5 + 200
        self.setSceneRect(items_rect.adjusted(-margin, -margin, margin, margin))

    # ---------- Snap + intersection guard ----------
    def _propose_point_pos(self, idx: int, new_pos: QPointF, old_pos: QPointF) -> QPointF:
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        minor_step, _ = self._choose_grid_steps(visible)
        snap_step = minor_step / float(self._snap_divisor)

        sx = round(new_pos.x() / snap_step) * snap_step
        sy = round(new_pos.y() / snap_step) * snap_step
        snapped = QPointF(sx, sy)

        tmp = [QPointF(p) for p in self._points]
        tmp[idx] = snapped
        if _has_self_intersection(tmp):
            return old_pos
        return snapped

    def _apply_point_pos(self, idx: int, pos: QPointF, emit: bool) -> None:
        self._points[idx] = QPointF(pos)

        if idx - 1 >= 0:
            a, b = self._points[idx - 1], self._points[idx]
            self._line_items[idx - 1].setLine(a.x(), a.y(), b.x(), b.y())
        if idx < len(self._points) - 1:
            a, b = self._points[idx], self._points[idx + 1]
            self._line_items[idx].setLine(a.x(), a.y(), b.x(), b.y())

        self._update_coord_label(pos)
        self.viewport().update()
        if emit:
            self.pointMoved.emit(idx, pos.x(), -pos.y())

    def _on_point_moved(self, idx: int, pos: QPointF) -> None:
        if self._suppress_emit:
            return
        self._apply_point_pos(idx, pos, emit=True)

    # ---------- Coord label ----------
    def _label_scene_pos(self, point_scene: QPointF) -> QPointF:
        v = self.mapFromScene(point_scene)
        v2 = v + QPoint(10, -20)
        return self.mapToScene(v2)

    def _show_coord_label(self, pos: QPointF) -> None:
        self._coord_label.show()
        self._update_coord_label(pos)

    def _update_coord_label(self, pos: QPointF) -> None:
        if not self._coord_label.isVisible():
            return
        self._coord_label.setText(f"({pos.x():.1f}, {-pos.y():.1f}){self._unit_name}")
        self._coord_label.setPos(self._label_scene_pos(pos))

    def _hide_coord_label(self) -> None:
        self._coord_label.hide()

    # ---------- helpers: hit-testing ----------
    def _dist_point_to_segment_px(self, p: QPointF, a: QPointF, b: QPointF) -> float:
        ax, ay = a.x(), a.y()
        bx, by = b.x(), b.y()
        px, py = p.x(), p.y()

        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay

        vv = vx * vx + vy * vy
        if vv <= 1e-12:
            return math.hypot(px - ax, py - ay)

        t = (wx * vx + wy * vy) / vv
        t = max(0.0, min(1.0, t))
        cx, cy = ax + t * vx, ay + t * vy
        return math.hypot(px - cx, py - cy)

    def _find_segment_near_click(self, scene_pos: QPointF, thresh_px: float = 8.0) -> Optional[int]:
        if len(self._points) < 2:
            return None
        pv = QPointF(self.mapFromScene(scene_pos))
        best_i = None
        best_d = 1e18
        for i in range(len(self._points) - 1):
            av = QPointF(self.mapFromScene(self._points[i]))
            bv = QPointF(self.mapFromScene(self._points[i + 1]))
            d = self._dist_point_to_segment_px(pv, av, bv)
            if d < best_d:
                best_d = d
                best_i = i
        if best_i is not None and best_d <= thresh_px:
            return best_i
        return None

    def _find_point_near_click(self, scene_pos: QPointF, thresh_px: float = 10.0) -> Optional[int]:
        if not self._points:
            return None
        pv = QPointF(self.mapFromScene(scene_pos))
        best_i = None
        best_d = 1e18
        for i, p in enumerate(self._points):
            qv = QPointF(self.mapFromScene(p))
            d = math.hypot(pv.x() - qv.x(), pv.y() - qv.y())
            if d < best_d:
                best_d = d
                best_i = i
        if best_i is not None and best_d <= thresh_px:
            return best_i
        return None

    # ---------- insert/delete logic ----------
    def _insert_point_and_start_drag(self, seg_i: int, scene_pos: QPointF) -> None:
        insert_idx = seg_i + 1
        new_points = [QPointF(p) for p in self._points]
        new_points.insert(insert_idx, QPointF(scene_pos))

        if _has_self_intersection(new_points):
            return

        self._set_points(new_points)
        self._inserting_idx = insert_idx
        self._show_coord_label(self._points[insert_idx])

        p = self._points[insert_idx]
        self.pointInserted.emit(insert_idx, p.x(), -p.y())

    def _delete_point(self, idx: int) -> None:
        if idx <= 0 or idx >= len(self._points) - 1:
            return
        new_points = [QPointF(p) for p in self._points]
        del new_points[idx]
        self._set_points(new_points)
        self.pointDeleted.emit(idx)

    # ---------- Zoom / Pan / Insert / Delete ----------
    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            zoom_factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(zoom_factor, zoom_factor)
            self._ensure_scene_margin()
            self.viewport().update()
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        if event.button() == Qt.LeftButton and (event.modifiers() & Qt.ControlModifier):
            self._panning = True
            self._pan_start_view_pos = event.pos()
            self._pan_start_center_scene = self.mapToScene(self.viewport().rect().center())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.RightButton:
            idx = self._find_point_near_click(scene_pos)
            if idx is not None and (0 < idx < len(self._points) - 1):
                self._begin_user_edit()
                self._delete_point(idx)
                self._end_user_edit()
                event.accept()
                return

        if event.button() == Qt.LeftButton and not (event.modifiers() & Qt.ControlModifier):
            pidx = self._find_point_near_click(scene_pos)
            if pidx is None:
                seg_i = self._find_segment_near_click(scene_pos)
                if seg_i is not None:
                    self._begin_user_edit()
                    self._insert_point_and_start_drag(seg_i, scene_pos)
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and (event.buttons() & Qt.LeftButton):
            delta_view = event.pos() - self._pan_start_view_pos
            p0 = self.mapToScene(0, 0)
            p1 = self.mapToScene(delta_view.x(), delta_view.y())
            delta_scene = p1 - p0
            self.centerOn(self._pan_start_center_scene - delta_scene)
            event.accept()
            return

        if self._inserting_idx is not None and (event.buttons() & Qt.LeftButton):
            idx = self._inserting_idx
            if 0 <= idx < len(self._point_items):
                self._point_items[idx].setPos(self.mapToScene(event.pos()))
                self._update_coord_label(self._point_items[idx].pos())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._panning:
            self._panning = False
            self._pan_start_view_pos = None
            self._pan_start_center_scene = None
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._inserting_idx is not None:
            self._inserting_idx = None
            self._hide_coord_label()
            self._end_user_edit()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ensure_scene_margin()
