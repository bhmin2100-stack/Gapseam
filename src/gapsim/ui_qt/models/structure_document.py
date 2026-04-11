from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand

from gapsim.ui_qt.models.points_table import Point, PointsTableModel


class StructureDocument(QObject):
    pointsChanged = Signal()

    def __init__(self, model: PointsTableModel) -> None:
        super().__init__()
        self._model = model

    def get_points(self) -> List[Point]:
        return self._model.get_points()

    def set_points(self, points: List[Point]) -> None:
        self._model.set_points(points)
        self.pointsChanged.emit()

    def set_point(self, idx: int, point: Point) -> bool:
        ok = self._model.set_point(idx, point)
        if ok:
            self.pointsChanged.emit()
        return ok

    def insert_point(self, idx: int, point: Point) -> bool:
        ok = self._model.insert_point(idx, point)
        if ok:
            self.pointsChanged.emit()
        return ok

    def delete_point(self, idx: int) -> Optional[Point]:
        removed = self._model.delete_point(idx)
        if removed is not None:
            self.pointsChanged.emit()
        return removed


class MovePointCommand(QUndoCommand):
    def __init__(
        self,
        document: StructureDocument,
        idx: int,
        old_pos: Point,
        new_pos: Point,
        *,
        applied: bool = False,
        text: str = "Move point",
    ) -> None:
        super().__init__(text)
        self._doc = document
        self._idx = int(idx)
        self._old_pos = (float(old_pos[0]), float(old_pos[1]))
        self._new_pos = (float(new_pos[0]), float(new_pos[1]))
        self._skip_first_redo = bool(applied)

    def undo(self) -> None:
        self._doc.set_point(self._idx, self._old_pos)

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._doc.set_point(self._idx, self._new_pos)


class InsertPointCommand(QUndoCommand):
    def __init__(
        self,
        document: StructureDocument,
        idx: int,
        point: Point,
        *,
        applied: bool = False,
        text: str = "Insert point",
    ) -> None:
        super().__init__(text)
        self._doc = document
        self._idx = int(idx)
        self._point = (float(point[0]), float(point[1]))
        self._skip_first_redo = bool(applied)

    def undo(self) -> None:
        self._doc.delete_point(self._idx)

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._doc.insert_point(self._idx, self._point)


class DeletePointCommand(QUndoCommand):
    def __init__(
        self,
        document: StructureDocument,
        idx: int,
        point: Point,
        *,
        applied: bool = False,
        text: str = "Delete point",
    ) -> None:
        super().__init__(text)
        self._doc = document
        self._idx = int(idx)
        self._point = (float(point[0]), float(point[1]))
        self._skip_first_redo = bool(applied)

    def undo(self) -> None:
        self._doc.insert_point(self._idx, self._point)

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._doc.delete_point(self._idx)


class SetPointsCommand(QUndoCommand):
    def __init__(
        self,
        document: StructureDocument,
        old_points: List[Point],
        new_points: List[Point],
        *,
        applied: bool = False,
        text: str = "Set points",
    ) -> None:
        super().__init__(text)
        self._doc = document
        self._old_points = [(float(x), float(y)) for x, y in old_points]
        self._new_points = [(float(x), float(y)) for x, y in new_points]
        self._skip_first_redo = bool(applied)

    def undo(self) -> None:
        self._doc.set_points(self._old_points)

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._doc.set_points(self._new_points)
