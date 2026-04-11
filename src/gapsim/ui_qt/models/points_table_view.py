from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QTableView

Point = Tuple[float, float]


class PointsTableView(QTableView):
    deleteRowsRequested = Signal(list)  # row indices
    replacePointsRequested = Signal(list)  # List[Point]

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            return
        if event.matches(QKeySequence.Paste):
            self.paste_tsv()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_rows()
            return
        super().keyPressEvent(event)

    def copy_selection(self) -> None:
        model = self.model()
        if model is None:
            return
        sel = self.selectionModel().selectedRows()
        if not sel:
            return
        lines = []
        for rindex in sel:
            r = rindex.row()
            x = model.data(model.index(r, 0), Qt.DisplayRole)
            y = model.data(model.index(r, 1), Qt.DisplayRole)
            lines.append(f"{x}\t{y}")
        QApplication.clipboard().setText("\n".join(lines))

    def _parse_clipboard_points(self) -> List[Point]:
        text = QApplication.clipboard().text()
        if not text.strip():
            return []
        out: List[Point] = []
        for line in text.replace("\r\n", "\n").split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            try:
                x = float(parts[0].strip())
                y = float(parts[1].strip())
            except Exception:
                continue
            out.append((x, y))
        return out

    def paste_tsv(self) -> None:
        rows = self._parse_clipboard_points()
        if not rows:
            return
        self.replacePointsRequested.emit(rows)

    def delete_selected_rows(self) -> None:
        sel = self.selectionModel().selectedRows()
        if not sel:
            return
        rows = sorted(set(i.row() for i in sel))
        self.deleteRowsRequested.emit(rows)
