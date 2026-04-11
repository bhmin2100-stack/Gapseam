from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

Point = Tuple[float, float]
_ENDPOINT_X_MARGIN_A = 1.0


class PointsTableModel(QAbstractTableModel):
    pointEditRequested = Signal(int, float, float)  # row, x, y

    def __init__(self) -> None:
        super().__init__()
        self._pts: List[Point] = []

    @staticmethod
    def _enforce_endpoint_x_bounds(points: List[Point]) -> List[Point]:
        pts = [(float(x), float(y)) for x, y in points]
        if len(pts) < 3:
            return pts

        inner_xs = [float(x) for x, _y in pts[1:-1]]
        if not inner_xs:
            return pts
        inner_min = min(inner_xs)
        inner_max = max(inner_xs)
        margin = float(_ENDPOINT_X_MARGIN_A)
        descending = float(pts[0][0]) >= float(pts[-1][0])

        first_x, first_y = pts[0]
        if descending:
            first_x = max(first_x, inner_max + margin)
        else:
            first_x = min(first_x, inner_min - margin)
        pts[0] = (first_x, first_y)

        last_x, last_y = pts[-1]
        if descending:
            last_x = min(last_x, inner_min - margin)
        else:
            last_x = max(last_x, inner_max + margin)
        pts[-1] = (last_x, last_y)
        return pts

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._pts)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 2

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return ["X", "Y"][section]
        return str(section + 1)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r < 0 or r >= len(self._pts):
            return None
        x, y = self._pts[r]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return float(x) if c == 0 else float(y)
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or not index.isValid():
            return False
        r, c = index.row(), index.column()
        if r < 0 or r >= len(self._pts):
            return False
        try:
            v = float(value)
        except Exception:
            return False

        x, y = self._pts[r]
        nx, ny = ((v, y) if c == 0 else (x, v))
        if abs(nx - x) <= 1e-12 and abs(ny - y) <= 1e-12:
            return False

        self.pointEditRequested.emit(r, float(nx), float(ny))
        return True

    def set_points(self, pts: List[Point]) -> None:
        self.beginResetModel()
        self._pts = self._enforce_endpoint_x_bounds(list(pts))
        self.endResetModel()

    def get_points(self) -> List[Point]:
        return list(self._pts)

    def set_point(self, row: int, point: Point) -> bool:
        if row < 0 or row >= len(self._pts):
            return False
        nx, ny = float(point[0]), float(point[1])
        next_pts = list(self._pts)
        next_pts[row] = (nx, ny)
        next_pts = self._enforce_endpoint_x_bounds(next_pts)
        if next_pts == self._pts:
            return False
        self._pts = next_pts
        left = self.index(0, 0)
        right = self.index(len(self._pts) - 1, 1)
        self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.EditRole])
        return True

    def insert_point(self, row: int, point: Point) -> bool:
        if row < 0 or row > len(self._pts):
            return False
        p = (float(point[0]), float(point[1]))
        self.beginInsertRows(QModelIndex(), row, row)
        self._pts.insert(row, p)
        self._pts = self._enforce_endpoint_x_bounds(self._pts)
        self.endInsertRows()
        if self._pts:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._pts) - 1, 1), [Qt.DisplayRole, Qt.EditRole])
        return True

    def delete_point(self, row: int) -> Point | None:
        if len(self._pts) <= 2:
            return None
        if row <= 0 or row >= (len(self._pts) - 1):
            return None
        if row < 0 or row >= len(self._pts):
            return None
        removed = self._pts[row]
        self.beginRemoveRows(QModelIndex(), row, row)
        self._pts.pop(row)
        self._pts = self._enforce_endpoint_x_bounds(self._pts)
        self.endRemoveRows()
        if self._pts:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._pts) - 1, 1), [Qt.DisplayRole, Qt.EditRole])
        return removed
