"""Estimate spatial work before a run; change spacing only on user selection."""
from dataclasses import dataclass
import math

from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout,
)

from gapsim.engine.deposition_pipeline import normalize_surface_order


POINT_WARNING_THRESHOLD = 10_000
MAX_SPACING_A = 200.0  # Same supported range as the main calculation control.


@dataclass(frozen=True)
class ResolutionEstimate:
    input_points: int
    depth_a: float
    arc_length_a: float

    def points_at(self, spacing_a: float) -> int:
        if not math.isfinite(spacing_a) or spacing_a <= 0:
            raise ValueError("표면 점 간격은 0보다 커야 합니다.")
        if self.input_points < 2 or self.arc_length_a <= 1e-9:
            return self.input_points
        return max(2, math.ceil(self.arc_length_a / spacing_a) + 1)


def estimate_resolution(points) -> ResolutionEstimate:
    raw = [(float(x), float(y)) for x, y in points]
    if any(not math.isfinite(v) for p in raw for v in p):
        raise ValueError("구조 좌표는 유한한 숫자여야 합니다.")
    pts = normalize_surface_order(raw)
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    ys = [p[1] for p in pts]
    depth = max(ys) - min(ys) if ys else 0.0
    return ResolutionEstimate(len(raw), depth, length)


def _spacing_for_budget(estimate, current, budget):
    required = max(current, estimate.arc_length_a / (budget - 1))
    # Familiar choices, rounded upward so the predicted count meets the budget.
    candidates = [m * 10.0 ** e for e in range(-1, 3) for m in (1, 2, 4, 5)]
    return min(MAX_SPACING_A, next((v for v in candidates if v >= required), MAX_SPACING_A))


def resolution_choices(estimate, current):
    choices = [("현재 유지", float(current))]
    for label, budget in (("권장", 6000), ("더 빠르게", 3000)):
        spacing = _spacing_for_budget(estimate, current, budget)
        if spacing > choices[-1][1]:
            choices.append((label, spacing))
    return choices


class ResolutionDialog(QDialog):
    def __init__(self, estimate, current_spacing_a, parent=None, *, split=False):
        super().__init__(parent)
        self.setWindowTitle("계산 해상도 선택")
        self.setMinimumWidth(540)
        self.setMaximumWidth(680)
        self.setModal(True)
        self.choices = resolution_choices(estimate, current_spacing_a)
        self.group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel("구조가 크거나 세밀해서 계산이 오래 걸릴 수 있습니다.")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600; font-size: 15px;")
        layout.addWidget(title)
        summary = QLabel(
            f"구조 깊이 {estimate.depth_a / 10:,.1f} nm · 입력 점 {estimate.input_points:,}개\n"
            f"현재 간격으로 예상되는 내부 점: 약 {estimate.points_at(current_spacing_a):,}개"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.radios = []
        for index, (name, spacing) in enumerate(self.choices):
            radio = QRadioButton(
                f"{name}  ·  {spacing:g} Å ({spacing / 10:g} nm)  ·  약 {estimate.points_at(spacing):,}개"
            )
            radio.setAccessibleName(f"{name} 표면 점 간격 {spacing:g} Å")
            self.group.addButton(radio, index)
            self.radios.append(radio)
            layout.addWidget(radio)
        self.radios[1 if len(self.radios) > 1 else 0].setChecked(True)
        note = QLabel(
            "점 간격이 커지면 계산량은 줄지만 팁·목 폭·모서리 모양이 달라질 수 있습니다. "
            "최종 형상 비교는 현재 간격에서도 확인하세요.\n\n"
            "점 수는 표면 길이로 추정한 값이며, 계산 중 변할 수 있습니다. "
            "실행 시간이나 정확도를 보장하는 값은 아닙니다.\n"
            + ("선택한 간격을 이번 Split의 모든 조건에 적용합니다. " if split else "선택한 간격을 실행 조건에 반영합니다. ")
            + "저장된 프리셋은 그대로 유지됩니다."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555; background: #f3f5f7; padding: 12px; border-radius: 6px;")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("선택한 간격으로 실행")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_spacing_a(self):
        return self.choices[self.group.checkedId()][1]
