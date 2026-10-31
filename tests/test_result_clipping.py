import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from gapsim.ui_qt.views.result_vector_view import ResultVectorView


def legacy_clipping(view):
    for item in view._layer_items + view._etch_ghost_items:
        if item is not None:
            item.setParentItem(None)
    view._mixed_layer_clip.hide()
    view._mixed_ghost_clip.hide()
    view._mixed_layer_clip = None
    view._mixed_ghost_clip = None


def render(view):
    image = QImage(400, 400, QImage.Format.Format_RGBA8888)
    image.fill(0xffffffff)
    painter = QPainter(image)
    view.scene().render(painter, QRectF(0, 0, 400, 400), QRectF(-20, -12, 40, 42))
    painter.end()
    return np.frombuffer(image.constBits(), dtype=np.uint8).copy().reshape(400, 400, 4)


def test_long_mixed_history_masks_match_original_clipping_forward_and_backward():
    app = QApplication.instance() or QApplication([])
    frames = [[(-12-i*.025, -i*.02), (-5+i*.025, -18+i*.035),
               (5-i*.015, -18+i*.035), (12-i*.035, -i*.02)] for i in range(70)]
    views = [ResultVectorView(), ResultVectorView()]
    for view in views:
        view.set_frames(frames, history_mode='mixed_etch', dynamic_substrate_fill=True,
                        stage_ids=[1]*35+[2]*35, initial_index=0)
    legacy_clipping(views[1])
    for index in (0, 35, 69, 20, 0):
        for view in views:
            view.show_frame(index)
        assert views[0]._boundary_item.path() == views[1]._boundary_item.path()
        a, b = map(render, views)
        # Raster clipping can differ at antialiased cut edges, never in film areas.
        changed = np.any(np.abs(a.astype(int)-b.astype(int)) > 8, axis=2)
        assert changed.mean() < .005
    for view in views:
        view.clear_data()
        view.set_frames(frames[:2], history_mode='mixed_etch')
        view.show_frame(0)
        view.close()
