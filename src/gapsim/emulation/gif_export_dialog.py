"""Explicit, bounded GIF export settings; unrelated to simulation accuracy."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout

from .trench_depo_export import GIF_MAX_FRAMES, gif_frame_indices, minimum_gif_interval


class GifExportDialog(QDialog):
    def __init__(self, frame_count: int, interval: int = 1, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GIF 저장 설정")
        self.setMinimumWidth(390)
        self.frame_count = frame_count
        minimum = minimum_gif_interval(frame_count)
        self.interval = QSpinBox()
        self.interval.setAccessibleName("GIF 이미지 간격")
        self.interval.setRange(minimum, max(minimum, frame_count - 1))
        self.interval.setValue(max(minimum, interval))
        self.interval.setSuffix("장마다")
        self.interval.setToolTip("저장된 결과 이미지 중 몇 장마다 GIF에 넣을지 정합니다. 계산 조건이나 원본 결과는 바뀌지 않습니다.")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        description = QLabel(
            f"전체 결과 {frame_count:,}장 · GIF 최대 {GIF_MAX_FRAMES}장\n"
            f"처음과 마지막 결과는 항상 포함합니다.\n"
            f"100장 제한을 지키려면 최소 {minimum:,}장 간격이 필요합니다."
        )
        description.setWordWrap(True)
        form = QFormLayout()
        form.addRow("이미지 간격", self.interval)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장 위치 선택…")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(description)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(buttons)
        self.interval.valueChanged.connect(self._update_summary)
        self._update_summary()

    def _update_summary(self):
        count = len(gif_frame_indices(self.frame_count, self.interval.value()))
        self.summary.setText(f"저장될 GIF: {count}장 / 최대 {GIF_MAX_FRAMES}장")
