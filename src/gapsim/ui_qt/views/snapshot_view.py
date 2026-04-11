from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class SnapshotView(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pix_item)

        self._panning = False
        self._pan_start = QPoint()

        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

    def clear_snapshot(self) -> None:
        self._pix_item.setPixmap(QPixmap())
        self._scene.setSceneRect(0, 0, 1, 1)
        self.resetTransform()

    def set_snapshot(self, path: Path, *, fit: bool = False) -> bool:
        px = QPixmap(str(path))
        if px.isNull():
            return False
        self._pix_item.setPixmap(px)
        self._scene.setSceneRect(self._pix_item.boundingRect())
        if fit:
            self.fit_snapshot()
        return True

    def fit_snapshot(self) -> None:
        if self._pix_item.pixmap().isNull():
            return
        self.resetTransform()
        self.fitInView(self._pix_item, Qt.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.0015 ** angle
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and (event.modifiers() & Qt.ControlModifier):
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() == Qt.LeftButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
