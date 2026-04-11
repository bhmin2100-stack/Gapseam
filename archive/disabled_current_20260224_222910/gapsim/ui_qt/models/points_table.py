from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

Point = Tuple[float, float]  # (x, y_user)


class PointsTableModel(QAbstractTableModel):
    """
    2-column (X, Y) editable table model.
    - pointEdited signal is emitted on user edit so controller can update the view.
    """
    pointEdited = Signal(int, float, float)  # idx, x, y

    def __init__(self, points: List[Point] | None = None):
        super().__init__()
        self._points: List[Point] = list(points) if points else []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._points)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 2

    def headerData(self, section: int, orientation: Qt.Orientation, role: int):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return "X" if section == 0 else "Y"
        return str(section + 1)

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def data(self, index: QModelIndex, role: int):
        if not index.isValid():
            return None

        x, y = self._points[index.row()]
        v = x if index.column() == 0 else y

        if role == Qt.DisplayRole:
            return f"{v:.3f}"
        if role == Qt.EditRole:
            return v
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.EditRole or not index.isValid():
            return False

        row, col = index.row(), index.column()
        try:
            v = float(value)
        except Exception:
            return False

        x, y = self._points[row]
        if col == 0:
            x = v
        else:
            y = v

        self._points[row] = (x, y)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        self.pointEdited.emit(row, x, y)
        return True

    # ----- helpers (controller/view sync) -----
    def set_points(self, pts: List[Point]) -> None:
        self.beginResetModel()
        self._points = list(pts)
        self.endResetModel()

    def get_points(self) -> List[Point]:
        return list(self._points)

    def set_point(self, idx: int, x: float, y: float) -> None:
        if idx < 0 or idx >= len(self._points):
            return
        self._points[idx] = (x, y)
        left = self.index(idx, 0)
        right = self.index(idx, 1)
        self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.EditRole])

    def insertRows(self, row: int, count: int, parent=QModelIndex()) -> bool:
        row = max(0, min(row, len(self._points)))
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        for _ in range(count):
            self._points.insert(row, (0.0, 0.0))
        self.endInsertRows()
        return True

    def removeRows(self, row: int, count: int, parent=QModelIndex()) -> bool:
        if row < 0 or row >= len(self._points):
            return False
        end = min(row + count - 1, len(self._points) - 1)
        self.beginRemoveRows(QModelIndex(), row, end)
        del self._points[row : end + 1]
        self.endRemoveRows()
        return True
