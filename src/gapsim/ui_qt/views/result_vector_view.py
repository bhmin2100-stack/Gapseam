from __future__ import annotations

import math
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

Point = Tuple[float, float]  # USER coords (x, y_user)


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


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _film_color(idx: int, total: int) -> QColor:
    if total <= 1:
        t = 1.0
    else:
        t = idx / float(total - 1)
    t = max(0.0, min(1.0, float(t)))
    c0 = (205, 236, 255)
    c1 = (42, 117, 196)
    return QColor(_lerp(c0[0], c1[0], t), _lerp(c0[1], c1[1], t), _lerp(c0[2], c1[2], t), 255)


def _film_color_warm(idx: int, total: int) -> QColor:
    if total <= 1:
        t = 1.0
    else:
        t = idx / float(total - 1)
    t = max(0.0, min(1.0, float(t)))
    c0 = (255, 228, 196)
    c1 = (224, 126, 33)
    return QColor(_lerp(c0[0], c1[0], t), _lerp(c0[1], c1[1], t), _lerp(c0[2], c1[2], t), 255)


def _film_color_stage(stage_id: int, idx: int, total: int) -> QColor:
    if int(stage_id) <= 1:
        return _film_color(idx, total)
    palettes = [
        ((255, 228, 196), (224, 126, 33)),   # orange
        ((214, 242, 206), (79, 160, 91)),    # green
        ((235, 224, 255), (142, 105, 209)),  # violet
        ((255, 224, 239), (204, 92, 134)),   # rose
    ]
    pidx = (int(stage_id) - 2) % len(palettes)
    c0, c1 = palettes[pidx]
    if total <= 1:
        t = 1.0
    else:
        t = idx / float(total - 1)
    t = max(0.0, min(1.0, float(t)))
    return QColor(_lerp(c0[0], c1[0], t), _lerp(c0[1], c1[1], t), _lerp(c0[2], c1[2], t), 255)


def _profile_to_scene(profile: Sequence[Point]) -> List[QPointF]:
    return [QPointF(float(x), -float(y)) for x, y in profile]


def _decimate_profile(profile: Sequence[Point], stride: int) -> List[Point]:
    if stride <= 1 or len(profile) <= 2:
        return [(float(x), float(y)) for x, y in profile]
    out: List[Point] = [(float(profile[0][0]), float(profile[0][1]))]
    for i in range(1, len(profile) - 1):
        if i % stride == 0:
            out.append((float(profile[i][0]), float(profile[i][1])))
    out.append((float(profile[-1][0]), float(profile[-1][1])))
    if len(out) < 2:
        return [(float(x), float(y)) for x, y in profile]
    return out


class ResultVectorView(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._frame_profiles_raw: List[List[Point]] = []
        self._frame_voids_raw: List[List[List[Point]]] = []
        self._frame_stage_ids: List[int] = []
        self._profile_cache: "OrderedDict[int, List[QPointF]]" = OrderedDict()
        self._void_cache: "OrderedDict[int, List[List[QPointF]]]" = OrderedDict()
        self._cache_limit = 64
        self._void_mode = "legacy_cumulative"
        self._decimation_stride = 1
        self._x_window: Optional[Tuple[float, float]] = None
        self._content_rect: Optional[QRectF] = None
        self._floor_y: float = 100.0
        self._global_y_min_scene: float = 0.0
        self._current_index = -1
        self._color_total_layers = 1
        self._stage_layer_totals: Dict[int, int] = {}
        self._show_initial_points = True
        self._dynamic_substrate_fill = False
        self._layer_items: List[Optional[QGraphicsPathItem]] = []
        self._void_items_by_frame: List[List[QGraphicsPathItem]] = []
        self._initial_point_items: List[QGraphicsEllipseItem] = []
        self._substrate_item: Optional[QGraphicsPathItem] = None
        self._boundary_item: Optional[QGraphicsPathItem] = None
        self._last_draw_idx = -1

        self._panning = False
        self._pan_start: Optional[QPointF] = None

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)

        self._major_target_lines = 10
        self._minor_div = 5

    def _trim_cache(self, cache: "OrderedDict[int, object]") -> None:
        while len(cache) > self._cache_limit:
            cache.popitem(last=False)

    def set_decimation_stride(self, stride: int) -> None:
        stride = max(1, int(stride))
        if self._decimation_stride == stride:
            return
        self._decimation_stride = stride
        self._profile_cache.clear()
        self._void_cache.clear()
        if self._current_index >= 0 and self._frame_profiles_raw:
            cur_idx = self._current_index
            self._build_scene_items()
            self.show_frame(cur_idx, fit=False)

    def _cache_get_profile_scene(self, idx: int) -> List[QPointF]:
        cached = self._profile_cache.get(idx)
        if cached is not None:
            self._profile_cache.move_to_end(idx)
            return cached
        raw = self._frame_profiles_raw[idx]
        decimated = _decimate_profile(raw, self._decimation_stride)
        scene_pts = _profile_to_scene(decimated)
        self._profile_cache[idx] = scene_pts
        self._trim_cache(self._profile_cache)
        return scene_pts

    def _cache_get_voids_scene(self, idx: int) -> List[List[QPointF]]:
        cached = self._void_cache.get(idx)
        if cached is not None:
            self._void_cache.move_to_end(idx)
            return cached

        raw_voids = self._frame_voids_raw[idx]
        scene_voids: List[List[QPointF]] = []
        for poly in raw_voids:
            decimated = _decimate_profile(poly, self._decimation_stride)
            if len(decimated) < 3:
                decimated = [(float(x), float(y)) for x, y in poly]
            if len(decimated) >= 3:
                scene_voids.append(_profile_to_scene(decimated))

        self._void_cache[idx] = scene_voids
        self._trim_cache(self._void_cache)
        return scene_voids

    def clear_data(self) -> None:
        self._frame_profiles_raw = []
        self._frame_voids_raw = []
        self._frame_stage_ids = []
        self._profile_cache.clear()
        self._void_cache.clear()
        self._void_mode = "legacy_cumulative"
        self._x_window = None
        self._content_rect = None
        self._floor_y = 100.0
        self._global_y_min_scene = 0.0
        self._current_index = -1
        self._color_total_layers = 1
        self._stage_layer_totals = {}
        self._dynamic_substrate_fill = False
        self._layer_items = []
        self._void_items_by_frame = []
        self._initial_point_items = []
        self._substrate_item = None
        self._boundary_item = None
        self._last_draw_idx = -1
        self._scene.clear()
        self._scene.setSceneRect(-1000, -1000, 2000, 2000)
        self.resetTransform()

    def set_stage_visibility(self, *, show_stage1: bool, show_stage2: bool) -> None:
        # Backward compatibility: stage visibility toggles are no longer used.
        _ = show_stage1
        _ = show_stage2

    def set_dynamic_substrate_fill(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._dynamic_substrate_fill == enabled:
            return
        self._dynamic_substrate_fill = enabled
        if self._frame_profiles_raw:
            cur_idx = self._visible_index(self._current_index if self._current_index >= 0 else len(self._frame_profiles_raw) - 1)
            self._build_scene_items()
            self.show_frame(cur_idx, fit=False)

    def _stage_visible(self, stage_id: int) -> bool:
        _ = stage_id
        return True

    def _visible_index(self, idx: int) -> int:
        if not self._frame_profiles_raw:
            return 0
        return max(0, min(int(idx), len(self._frame_profiles_raw) - 1))

    def set_frames(
        self,
        frames: Sequence[Sequence[Point]],
        *,
        x_window: Optional[Tuple[float, float]] = None,
        voids: Optional[Sequence[Sequence[Sequence[Point]]]] = None,
        stage_ids: Optional[Sequence[int]] = None,
        void_mode: str = "legacy_cumulative",
        dynamic_substrate_fill: bool = False,
    ) -> None:
        self._frame_profiles_raw = []
        for f in frames:
            if len(f) < 2:
                continue
            self._frame_profiles_raw.append([(float(x), float(y)) for x, y in f])

        self._frame_voids_raw = []
        if voids is not None:
            for vf in voids[: len(self._frame_profiles_raw)]:
                polys_raw: List[List[Point]] = []
                for poly in vf:
                    if len(poly) >= 3:
                        polys_raw.append([(float(x), float(y)) for x, y in poly])
                self._frame_voids_raw.append(polys_raw)
        if len(self._frame_voids_raw) != len(self._frame_profiles_raw):
            self._frame_voids_raw = [[] for _ in self._frame_profiles_raw]

        self._frame_stage_ids = []
        if stage_ids is not None:
            for sid in stage_ids[: len(self._frame_profiles_raw)]:
                self._frame_stage_ids.append(max(1, int(sid)))
        if len(self._frame_stage_ids) != len(self._frame_profiles_raw):
            self._frame_stage_ids = [1 for _ in self._frame_profiles_raw]

        self._profile_cache.clear()
        self._void_cache.clear()
        self._void_mode = "current" if str(void_mode).lower() == "current" else "legacy_cumulative"
        self._dynamic_substrate_fill = bool(dynamic_substrate_fill)
        self._color_total_layers = max(1, len(self._frame_profiles_raw) - 1)
        stage_counts: Dict[int, int] = {}
        for i in range(1, len(self._frame_stage_ids)):
            sid = max(1, int(self._frame_stage_ids[i]))
            stage_counts[sid] = stage_counts.get(sid, 0) + 1
        self._stage_layer_totals = {sid: max(1, c) for sid, c in stage_counts.items()}
        self._x_window = x_window
        self._update_content_bounds()
        self._current_index = -1
        self._build_scene_items()
        if self._frame_profiles_raw:
            self.show_frame(len(self._frame_profiles_raw) - 1, fit=True)
        else:
            self._scene.setSceneRect(-1000, -1000, 2000, 2000)

    def frame_count(self) -> int:
        return len(self._frame_profiles_raw)

    def set_show_initial_points(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._show_initial_points == enabled:
            return
        self._show_initial_points = enabled
        for item in self._initial_point_items:
            item.setVisible(enabled)

    def _build_scene_items(self) -> None:
        self._scene.clear()
        self._layer_items = []
        self._void_items_by_frame = [[] for _ in self._frame_profiles_raw]
        self._initial_point_items = []
        self._substrate_item = None
        self._boundary_item = None
        self._last_draw_idx = -1

        if not self._frame_profiles_raw:
            return

        base = self._cache_get_profile_scene(0)
        if len(base) < 2:
            return

        y_min = self._global_y_min_scene
        floor_y = self._floor_y if self._floor_y > y_min else (y_min + 100.0)

        # Si substrate. For pure etch playback, track the remaining profile instead of
        # pinning the full frame-0 substrate in place.
        sub_item = QGraphicsPathItem()
        sub_item.setPen(QPen(Qt.PenStyle.NoPen))
        sub_item.setBrush(QBrush(QColor(220, 220, 220)))
        self._scene.addItem(sub_item)
        self._substrate_item = sub_item
        if not self._dynamic_substrate_fill:
            self._substrate_item.setPath(self._profile_fill_path(base, floor_y))

        # Deposited film layers (prebuilt once, toggled per frame)
        prev = base
        stage_seen: Dict[int, int] = {}
        for li in range(1, len(self._frame_profiles_raw)):
            cur = self._cache_get_profile_scene(li)
            item: Optional[QGraphicsPathItem] = None
            if len(prev) >= 2 and len(cur) >= 2:
                stage_id = self._frame_stage_ids[li] if li < len(self._frame_stage_ids) else 1
                stage_id = max(1, int(stage_id))
                stage_seen[stage_id] = stage_seen.get(stage_id, 0) + 1
                poly = prev + list(reversed(cur))
                path = QPainterPath()
                path.moveTo(poly[0])
                for p in poly[1:]:
                    path.lineTo(p)
                path.closeSubpath()

                if self._stage_visible(stage_id):
                    item = QGraphicsPathItem(path)
                    item.setPen(QPen(Qt.PenStyle.NoPen))
                    color = _film_color_stage(
                        stage_id,
                        stage_seen[stage_id] - 1,
                        self._stage_layer_totals.get(stage_id, 1),
                    )
                    item.setBrush(QBrush(color))
                    item.setVisible(False)
                    self._scene.addItem(item)
            self._layer_items.append(item)
            prev = cur

        # Trapped voids (prebuilt once, toggled per frame)
        for fi in range(len(self._frame_voids_raw)):
            frame_items: List[QGraphicsPathItem] = []
            for poly in self._cache_get_voids_scene(fi):
                if len(poly) < 3:
                    continue
                path = QPainterPath()
                path.moveTo(poly[0])
                for p in poly[1:]:
                    path.lineTo(p)
                path.closeSubpath()

                base_item = QGraphicsPathItem(path)
                hole_pen = QPen(QColor(180, 180, 180), 1.0)
                hole_pen.setCosmetic(True)
                base_item.setPen(hole_pen)
                base_item.setBrush(QBrush(QColor(255, 255, 255)))
                base_item.setZValue(6.0)
                base_item.setVisible(False)
                self._scene.addItem(base_item)
                frame_items.append(base_item)
            self._void_items_by_frame[fi] = frame_items

        # Current boundary line (updated per frame)
        boundary_item = QGraphicsPathItem()
        line_pen = QPen(QColor(0, 0, 0), 2.0)
        line_pen.setCosmetic(True)
        boundary_item.setPen(line_pen)
        boundary_item.setZValue(10.0)
        self._scene.addItem(boundary_item)
        self._boundary_item = boundary_item

        # Initial points (static visibility toggle)
        dot_brush = QBrush(QColor(120, 120, 120, 220))
        dot_pen = QPen(Qt.PenStyle.NoPen)
        for p in base:
            dot = QGraphicsEllipseItem(-2.0, -2.0, 4.0, 4.0)
            dot.setPos(p)
            dot.setPen(dot_pen)
            dot.setBrush(dot_brush)
            dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            dot.setZValue(20.0)
            dot.setVisible(self._show_initial_points)
            self._scene.addItem(dot)
            self._initial_point_items.append(dot)

    def _profile_fill_path(self, profile_scene: Sequence[QPointF], floor_y: float) -> QPainterPath:
        path = QPainterPath()
        if len(profile_scene) < 2:
            return path
        path.moveTo(profile_scene[0])
        for p in profile_scene[1:]:
            path.lineTo(p)
        path.lineTo(QPointF(profile_scene[-1].x(), floor_y))
        path.lineTo(QPointF(profile_scene[0].x(), floor_y))
        path.closeSubpath()
        return path

    def _set_layer_visible(self, layer_index: int, visible: bool) -> None:
        if layer_index < 1:
            return
        idx = layer_index - 1
        if idx < 0 or idx >= len(self._layer_items):
            return
        item = self._layer_items[idx]
        if item is not None:
            item.setVisible(bool(visible))

    def _set_void_frame_visible(self, frame_index: int, visible: bool) -> None:
        if frame_index < 0 or frame_index >= len(self._void_items_by_frame):
            return
        for item in self._void_items_by_frame[frame_index]:
            item.setVisible(bool(visible))

    def show_frame(self, index: int, *, fit: bool = False) -> bool:
        if not self._frame_profiles_raw:
            return False

        idx = max(0, min(index, len(self._frame_profiles_raw) - 1))
        self._current_index = idx
        draw_idx = self._visible_index(idx)
        curr = self._cache_get_profile_scene(draw_idx)
        if len(curr) < 2:
            return False
        if self._boundary_item is None:
            self._build_scene_items()
            if self._boundary_item is None:
                return False

        prev_draw = self._last_draw_idx
        if prev_draw < 0:
            for li in range(1, draw_idx + 1):
                self._set_layer_visible(li, True)
        elif draw_idx > prev_draw:
            for li in range(prev_draw + 1, draw_idx + 1):
                self._set_layer_visible(li, True)
        elif draw_idx < prev_draw:
            for li in range(draw_idx + 1, prev_draw + 1):
                self._set_layer_visible(li, False)

        if self._void_mode == "current":
            if prev_draw < 0:
                for vf_idx in range(0, draw_idx + 1):
                    self._set_void_frame_visible(vf_idx, True)
            elif draw_idx > prev_draw:
                for vf_idx in range(prev_draw + 1, draw_idx + 1):
                    self._set_void_frame_visible(vf_idx, True)
            elif draw_idx < prev_draw:
                for vf_idx in range(draw_idx + 1, prev_draw + 1):
                    self._set_void_frame_visible(vf_idx, False)
        else:
            if prev_draw >= 0:
                self._set_void_frame_visible(prev_draw, False)
            self._set_void_frame_visible(draw_idx, True)

        line_path = QPainterPath()
        line_path.moveTo(curr[0])
        for p in curr[1:]:
            line_path.lineTo(p)
        self._boundary_item.setPath(line_path)
        if self._dynamic_substrate_fill and self._substrate_item is not None:
            self._substrate_item.setPath(self._profile_fill_path(curr, self._floor_y))
        self._last_draw_idx = draw_idx

        if fit:
            self.fit_content()
        return True

    def fit_content(self) -> None:
        target = self._content_rect
        if target is None or target.isNull():
            target = self._scene.itemsBoundingRect()
        if target.isNull():
            return
        self.resetTransform()
        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)

    def _update_content_bounds(self) -> None:
        if not self._frame_profiles_raw:
            self._content_rect = None
            self._scene.setSceneRect(-1000, -1000, 2000, 2000)
            return

        xs: List[float] = []
        ys: List[float] = []
        for frame in self._frame_profiles_raw:
            for x, y_user in frame:
                xs.append(float(x))
                ys.append(-float(y_user))
        for frame_voids in self._frame_voids_raw:
            for poly in frame_voids:
                for x, y_user in poly:
                    xs.append(float(x))
                    ys.append(-float(y_user))

        if not xs:
            xs = [0.0]
        if not ys:
            ys = [0.0]

        y_min = min(ys)
        y_max = max(ys)
        self._global_y_min_scene = y_min
        y_span = max(abs(y_max - y_min), 1.0)
        self._floor_y = y_max + max(50.0, y_span * 0.5)

        x_left = min(xs)
        x_right = max(xs)
        if self._x_window is not None:
            xl, xr = self._x_window
            x_left = min(x_left, float(xl), float(xr))
            x_right = max(x_right, float(xl), float(xr))

        if x_right <= x_left:
            x_right = x_left + 1.0
        if self._floor_y <= y_min:
            self._floor_y = y_min + 100.0

        rect = QRectF(x_left, y_min, x_right - x_left, self._floor_y - y_min)
        self._content_rect = rect.adjusted(-50, -50, 50, 50)

        w = self._content_rect.width()
        h = self._content_rect.height()
        margin = max(w, h, 300.0) * 2.0
        self._scene.setSceneRect(self._content_rect.adjusted(-margin, -margin, margin, margin))

    def drawBackground(self, painter, rect) -> None:
        super().drawBackground(painter, rect)

        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        w = visible.width()
        if w <= 0:
            return
        major_step = _nice_step(w / self._major_target_lines)
        minor_step = major_step / self._minor_div

        minor_pen = QPen(QColor(235, 235, 235), 1, Qt.PenStyle.DotLine)
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

        major_pen = QPen(QColor(205, 205, 205), 1, Qt.PenStyle.DashLine)
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

    def drawForeground(self, painter, rect) -> None:
        super().drawForeground(painter, rect)
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        w = visible.width()
        if w <= 0:
            return
        major_step = _nice_step(w / self._major_target_lines)

        axis_pen = QPen(QColor(80, 80, 80), 2)
        axis_pen.setCosmetic(True)
        painter.setPen(axis_pen)
        # If world origin axes are outside the viewport, pin fallback axes to top/left.
        x_axis_visible = visible.top() <= 0.0 <= visible.bottom()
        y_axis_visible = visible.left() <= 0.0 <= visible.right()
        x_axis_scene_y = 0.0 if x_axis_visible else float(visible.top())
        y_axis_scene_x = 0.0 if y_axis_visible else float(visible.left())

        painter.drawLine(visible.left(), x_axis_scene_y, visible.right(), x_axis_scene_y)
        painter.drawLine(y_axis_scene_x, visible.top(), y_axis_scene_x, visible.bottom())
        self._draw_axis_labels(
            painter,
            visible,
            major_step,
            x_axis_scene_y=x_axis_scene_y,
            y_axis_scene_x=y_axis_scene_x,
        )

    def _draw_axis_labels(
        self,
        painter,
        rect,
        major_step: float,
        *,
        x_axis_scene_y: float,
        y_axis_scene_x: float,
    ) -> None:
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(70, 70, 70))

        vp_rect = self.viewport().rect()
        x_axis_v = self.mapFromScene(QPointF(0.0, float(x_axis_scene_y))).y()
        y_axis_v = self.mapFromScene(QPointF(float(y_axis_scene_x), 0.0)).x()

        x_label_y = min(max(x_axis_v + 14, 14), vp_rect.height() - 4)
        y_label_x = min(max(y_axis_v + 6, 4), vp_rect.width() - 40)

        x0 = math.floor(rect.left() / major_step) * major_step
        x = x0
        last_x_label = -1e18
        while x <= rect.right():
            p = self.mapFromScene(QPointF(x, float(x_axis_scene_y)))
            if 0 <= p.x() <= vp_rect.width() and (p.x() - last_x_label) >= 46:
                painter.drawText(p.x() + 2, x_label_y, _fmt_tick(x, major_step))
                last_x_label = p.x()
            x += major_step

        y0 = math.floor(rect.top() / major_step) * major_step
        y = y0
        last_y_label = -1e18
        while y <= rect.bottom():
            p = self.mapFromScene(QPointF(float(y_axis_scene_x), y))
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
        if event.button() == Qt.MouseButton.LeftButton and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._panning = True
            self._pan_start = QPointF(event.pos())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning and self._pan_start is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = QPointF(event.pos()) - self._pan_start
            self._pan_start = QPointF(event.pos())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
