from __future__ import annotations

import re
from typing import List, Tuple

from PySide6.QtWidgets import QTableView, QApplication
from PySide6.QtGui import QKeySequence
from PySide6.QtCore import Qt

from gapsim.ui_qt.models.points_table import PointsTableModel


def _parse_clipboard(text: str) -> List[Tuple[float, float]]:
    rows: List[Tuple[float, float]] = []
    for line in text.strip().splitlines():
        parts = re.split(r"[\t, ]+", line.strip())
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except Exception:
            continue
        rows.append((x, y))
    return rows


class PointsTableView(QTableView):
    def __init__(self):
        super().__init__()
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectItems)
        self.setSelectionMode(QTableView.ExtendedSelection)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self._paste_xy()
            return
        if event.matches(QKeySequence.Copy):
            self._copy_selection()
            return

        # Delete/Backspace: delete selected rows (except endpoints)
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_selected_rows()
            return

        super().keyPressEvent(event)

    def _paste_xy(self) -> None:
        model = self.model()
        if not isinstance(model, PointsTableModel):
            return

        text = QApplication.clipboard().text()
        pts = _parse_clipboard(text)
        if not pts:
            return

        idx = self.currentIndex()
        start_row = idx.row() if idx.isValid() else 0

        need = start_row + len(pts) - model.rowCount()
        if need > 0:
            model.insertRows(model.rowCount(), need)

        for i, (x, y) in enumerate(pts):
            r = start_row + i
            model.setData(model.index(r, 0), x, Qt.EditRole)
            model.setData(model.index(r, 1), y, Qt.EditRole)

    def _copy_selection(self) -> None:
        model = self.model()
        if not isinstance(model, PointsTableModel):
            return

        sel = self.selectionModel().selectedIndexes()
        if not sel:
            return

        rows = [i.row() for i in sel]
        cols = [i.column() for i in sel]
        r0, r1 = min(rows), max(rows)
        c0, c1 = min(cols), max(cols)

        out_lines = []
        for r in range(r0, r1 + 1):
            line = []
            for c in range(c0, c1 + 1):
                v = model.data(model.index(r, c), Qt.EditRole)
                line.append("" if v is None else str(v))
            out_lines.append("\t".join(line))

        QApplication.clipboard().setText("\n".join(out_lines))

    def _delete_selected_rows(self) -> None:
        model = self.model()
        if not isinstance(model, PointsTableModel):
            return

        sel = self.selectionModel().selectedIndexes()
        if not sel:
            return

        rows = sorted({i.row() for i in sel}, reverse=True)
        if not rows:
            return

        # delete in reverse order, protect endpoints dynamically
        for r in rows:
            last = model.rowCount() - 1
            if r <= 0 or r >= last:
                continue  # endpoints protected
            model.removeRows(r, 1)
