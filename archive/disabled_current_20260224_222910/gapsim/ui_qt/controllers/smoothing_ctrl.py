from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional
import math

from PySide6.QtCore import QObject

from gapsim.ui_qt.views.structure_view import StructureView

Point = Tuple[float, float]  # (x, y_user)  y_user: depth is negative


def _resample_polyline_equal_arc(pts: List[Point], n_segments: int) -> List[Point]:
    """
    Resample polyline into n_segments equal arc-length segments.
    Output points count = n_segments + 1 (including endpoints).
    """
    if n_segments <= 0 or len(pts) < 2:
        return list(pts)

    seg_lens = []
    cum = [0.0]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        L = math.hypot(x1 - x0, y1 - y0)
        seg_lens.append(L)
        cum.append(cum[-1] + L)

    total = cum[-1]
    if total <= 1e-12:
        return [pts[0]] * (n_segments + 1)

    step = total / n_segments
    out: List[Point] = []

    j = 0
    for k in range(n_segments + 1):
        target = min(k * step, total)

        while j < len(seg_lens) - 1 and cum[j + 1] < target - 1e-12:
            j += 1

        x0, y0 = pts[j]
        x1, y1 = pts[j + 1]
        L = seg_lens[j]
        if L <= 1e-12:
            t = 0.0
        else:
            t = (target - cum[j]) / L
            t = max(0.0, min(1.0, t))

        out.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))

    out[0] = pts[0]
    out[-1] = pts[-1]
    return out


def _laplacian_smooth_midpoint(pts: List[Point], iters: int) -> List[Point]:
    """
    Each iteration: internal point i -> midpoint of (i-1, i+1).
    Endpoints fixed.
    """
    if iters <= 0 or len(pts) < 3:
        return list(pts)

    cur = list(pts)
    for _ in range(iters):
        nxt = list(cur)
        for i in range(1, len(cur) - 1):
            x_prev, y_prev = cur[i - 1]
            x_next, y_next = cur[i + 1]
            nxt[i] = ((x_prev + x_next) / 2.0, (y_prev + y_next) / 2.0)
        cur = nxt
    return cur


@dataclass
class SmoothingState:
    base_points: List[Point]
    segments: int = 200
    iterations: int = 5
    last_result: Optional[List[Point]] = None


class SmoothingController(QObject):
    """
    - base_points: points at the time entering smoothing (stored)
    - run(): resample -> smooth -> update view
    - revert(): restore view to base_points
    """
    def __init__(self, view: StructureView):
        super().__init__()
        self.view = view
        self.state = SmoothingState(base_points=[])

    def set_base_points(self, pts: List[Point]) -> None:
        self.state.base_points = list(pts)
        self.state.last_result = None

    def set_params(self, segments: int, iterations: int) -> None:
        self.state.segments = max(1, int(segments))
        self.state.iterations = max(0, int(iterations))

    def run(self) -> List[Point]:
        base = self.state.base_points
        if len(base) < 2:
            self.state.last_result = list(base)
            self.view.set_points_xy(base)
            return list(base)

        seg = max(1, self.state.segments)
        it = max(0, self.state.iterations)

        resampled = _resample_polyline_equal_arc(base, seg)
        smoothed = _laplacian_smooth_midpoint(resampled, it)

        self.state.last_result = smoothed
        self.view.set_points_xy(smoothed)
        return smoothed

    def revert(self) -> None:
        self.view.set_points_xy(self.state.base_points)

    def get_saved_payload(self) -> dict:
        """
        Payload for recipe/meta:
        - base_points: pre-smoothing points
        - segments/iterations: smoothing params
        """
        return {
            "base_points": list(self.state.base_points),
            "segments": int(self.state.segments),
            "iterations": int(self.state.iterations),
        }
