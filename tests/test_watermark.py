from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from gapsim.ui_qt.views.watermark import WATERMARK_TEXT, draw_viewport_watermark


class WatermarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_watermark_text_matches_requested_credit(self) -> None:
        self.assertEqual(WATERMARK_TEXT, "GFE from Flash 공정개발팀 CVD 민병헌")

    def test_draw_viewport_watermark_marks_bottom_right_viewport(self) -> None:
        image = QImage(320, 160, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))

        painter = QPainter(image)
        try:
            draw_viewport_watermark(painter, QRect(0, 0, 320, 160), text="GFE")
        finally:
            painter.end()

        changed = False
        for x in range(200, 310):
            for y in range(110, 150):
                if image.pixelColor(x, y) != QColor("white"):
                    changed = True
                    break
            if changed:
                break
        self.assertTrue(changed)


if __name__ == "__main__":
    unittest.main()
