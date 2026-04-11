from __future__ import annotations

from typing import List, Tuple, Optional

from PySide6.QtCore import QObject, QModelIndex

from gapsim.ui_qt.models.points_table import PointsTableModel
from gapsim.ui_qt.views.structure_view import StructureView

Point = Tuple[float, float]


class StructureController(QObject):
    """
    Glue between:
      - StructureView (left graphics)
      - PointsTableModel (right table)
    Includes:
      - 1-step undo
      - insert/delete sync both directions
    """

    def __init__(self, view: StructureView, model: PointsTableModel):
        super().__init__()
        self.view = view
        self.model = model

        self._undo_snapshot: Optional[List[Point]] = None

        # when we mutate model because of view actions, don't "rebuild view"
        self._model_change_from_view = False

        # snapshot for undo (view-driven)
        self.view.editBegan.connect(self._on_edit_began)

        # View -> Model
        self.view.pointMoved.connect(self._on_view_point_moved)
        self.view.pointInserted.connect(self._on_view_point_inserted)
        self.view.pointDeleted.connect(self._on_view_point_deleted)

        # Model -> View (cell edit)
        self.model.pointEdited.connect(self._on_model_point_edited)

        # Model structural changes (table-driven insert/delete) -> rebuild view
        self.model.rowsAboutToBeRemoved.connect(self._on_model_rows_about_to_be_removed)
        self.model.rowsInserted.connect(self._on_model_rows_inserted)
        self.model.rowsRemoved.connect(self._on_model_rows_removed)

    def set_points(self, pts: List[Point]) -> None:
        self.model.set_points(pts)
        self.view.set_points_xy(pts)

    def undo(self) -> None:
        if not self._undo_snapshot:
            return
        pts = self._undo_snapshot
        self._undo_snapshot = None
        self.set_points(pts)

    # ---- view-driven undo snapshot ----
    def _on_edit_began(self, pts_before: List[Point]) -> None:
        self._undo_snapshot = list(pts_before)

    # ---- view -> model ----
    def _on_view_point_moved(self, idx: int, x: float, y: float) -> None:
        self.model.set_point(idx, x, y)

    def _on_view_point_inserted(self, insert_idx: int, x: float, y: float) -> None:
        self._model_change_from_view = True
        try:
            self.model.insertRows(insert_idx, 1)
            self.model.set_point(insert_idx, x, y)
        finally:
            self._model_change_from_view = False

    def _on_view_point_deleted(self, deleted_idx: int) -> None:
        self._model_change_from_view = True
        try:
            self.model.removeRows(deleted_idx, 1)
        finally:
            self._model_change_from_view = False

    # ---- model -> view (cell edits) ----
    def _on_model_point_edited(self, idx: int, x: float, y: float) -> None:
        ax, ay = self.view.try_set_point_xy(idx, x, y)
        if (ax != x) or (ay != y):
            self.model.set_point(idx, ax, ay)

    # ---- model structural changes (table-driven) ----
    def _on_model_rows_about_to_be_removed(self, parent: QModelIndex, first: int, last: int) -> None:
        if self._model_change_from_view:
            return
        # table-driven delete should be undoable too
        self._undo_snapshot = self.model.get_points()

    def _on_model_rows_inserted(self, parent: QModelIndex, first: int, last: int) -> None:
        if self._model_change_from_view:
            return
        # table-driven insert: rebuild view to have matching number of points
        self.view.set_points_xy(self.model.get_points())

    def _on_model_rows_removed(self, parent: QModelIndex, first: int, last: int) -> None:
        if self._model_change_from_view:
            return
        # table-driven delete: rebuild view
        self.view.set_points_xy(self.model.get_points())
