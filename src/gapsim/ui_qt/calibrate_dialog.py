from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)


class _CalibrateView(QGraphicsView):
    lineMeasured = Signal(float)  # length in pixels

    def __init__(self, image_path: Path) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self._pixmap = QPixmap(str(image_path))
        self._pix_item = QGraphicsPixmapItem(self._pixmap)
        self._scene.addItem(self._pix_item)

        self._line_item: Optional[QGraphicsLineItem] = None
        self._start_scene: Optional[QPointF] = None

        self._scene.setSceneRect(self._pix_item.boundingRect())
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._start_scene = self.mapToScene(event.pos())
        if self._line_item is not None:
            self._scene.removeItem(self._line_item)
            self._line_item = None
        self._line_item = QGraphicsLineItem()
        pen = QPen(Qt.GlobalColor.red, 2.0)
        pen.setCosmetic(True)
        self._line_item.setPen(pen)
        self._scene.addItem(self._line_item)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._start_scene is None or self._line_item is None:
            super().mouseMoveEvent(event)
            return
        p = self.mapToScene(event.pos())
        self._line_item.setLine(self._start_scene.x(), self._start_scene.y(), p.x(), p.y())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._start_scene is None or self._line_item is None:
            super().mouseReleaseEvent(event)
            return
        p = self.mapToScene(event.pos())
        dx = float(p.x() - self._start_scene.x())
        dy = float(p.y() - self._start_scene.y())
        length_px = math.hypot(dx, dy)
        self._start_scene = None
        if length_px > 1e-9:
            self.lineMeasured.emit(length_px)
        event.accept()


class CalibrateDialog(QDialog):
    def __init__(self, image_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("캘리브레이션")
        self.resize(900, 650)

        self._scale_a_per_px: Optional[float] = None

        root = QVBoxLayout(self)
        hint = QLabel("이미지에서 기준 길이를 드래그로 1개 그린 뒤, 실제 길이(Å)를 입력하세요.")
        root.addWidget(hint)

        self._view = _CalibrateView(image_path)
        root.addWidget(self._view, 1)

        self._status = QLabel("선을 아직 그리지 않았습니다.")
        root.addWidget(self._status)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._view.lineMeasured.connect(self._on_line_measured)

    @property
    def scale_a_per_px(self) -> Optional[float]:
        return self._scale_a_per_px

    def _on_line_measured(self, length_px: float) -> None:
        value, ok = QInputDialog.getDouble(
            self,
            "기준 길이 입력",
            "이 선의 실제 길이 (Å):",
            100.0,
            1e-9,
            1e12,
            6,
        )
        if not ok:
            self._status.setText("입력이 취소되었습니다. 다시 선을 그려주세요.")
            return
        if value <= 0.0:
            QMessageBox.warning(self, "입력 오류", "길이는 0보다 커야 합니다.")
            return

        self._scale_a_per_px = float(value) / float(length_px)
        self._status.setText(
            f"캘리브레이션 완료: {self._scale_a_per_px:.8f} Å/px"
        )
        self.accept()
