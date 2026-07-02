from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter

WATERMARK_TEXT = "GFE from Flash 공정개발팀 CVD 민병헌"


def draw_viewport_watermark(
    painter: QPainter,
    viewport_rect: QRect,
    *,
    text: str = WATERMARK_TEXT,
) -> None:
    if not text:
        return
    if viewport_rect.width() <= 0 or viewport_rect.height() <= 0:
        return

    painter.save()
    try:
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        font = QFont(painter.font())
        font.setPointSize(max(8, min(11, font.pointSize() if font.pointSize() > 0 else 10)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(35, 35, 35, 88))

        margin = 10
        text_rect = viewport_rect.adjusted(margin, margin, -margin, -margin)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, text)
    finally:
        painter.restore()
