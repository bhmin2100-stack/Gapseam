"""Display-only result navigation and recorded reference-plane deposition dose."""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QWidget

from gapsim.emulation.trench_depo import TrenchDepoConfig, TrenchDepoResult


DOSE_TOOLTIP = (
    "선택한 결과 시점까지의 기준 평면 증착량입니다. ALD는 GPC × 사이클, CVD는 D/R × 시간입니다.\n"
    "저장된 결과의 값을 사용하며, 실행 후 입력값을 바꿔도 변하지 않습니다.\n"
    "식각 전 성장 기준에서는 식각 전 증착량, 순성장 기준에서는 기준 평면의 순성장량입니다.\n"
    "트렌치 내부의 위치별 실제 막 두께와는 다릅니다."
)


def _finite_nonnegative(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


def frame_deposition_label(result: TrenchDepoResult, config: TrenchDepoConfig, index: int) -> str:
    """Prefer stored dose; never infer historical stages from the last stage's GPC."""
    count = len(result.frame_profiles)
    if not 0 <= index < count:
        return "누적 증착량 —"
    meta = result.meta

    def at(key: str) -> Optional[float]:
        values = meta.get(key)
        if isinstance(values, (list, tuple)) and len(values) == count:
            return _finite_nonnegative(values[index])
        return None

    amount = at("frame_doses_a")
    if amount is not None:
        return f"누적 증착량 {amount:,.3f} Å"

    # Mixed growth bases cannot be summed. Old continued files may lack dose
    # history entirely. In either case avoid applying the final recipe backwards.
    stages = meta.get("frame_stage_progress")
    if isinstance(stages, list) and len(stages) == count:
        stage = stages[index]
        amount = _finite_nonnegative(stage.get("dose_a")) if isinstance(stage, dict) else None
        if amount is not None:
            return f"현재 단계 증착량 {amount:,.3f} Å · 누적 정보 없음"
        return "누적 증착량 — (기록 없음)"
    if meta.get("history_self_contained") or int(meta.get("stage_count", 1) or 1) > 1:
        return "누적 증착량 — (기록 없음)"

    process = meta.get("process_type", config.process_type)
    if process == "cvd":
        progress = at("frame_times_s")
        rate = _finite_nonnegative(meta.get("cvd_rate_a_per_s", config.cvd_rate_a_per_s))
    else:
        progress = at("frame_cycle_counts")
        if progress is None and len(result.frame_steps) == count:
            progress = _finite_nonnegative(result.frame_steps[index])
        rate = _finite_nonnegative(meta.get("angstrom_per_cycle", config.angstrom_per_cycle))
    amount = _finite_nonnegative(progress * rate) if progress is not None and rate is not None else None
    return f"누적 증착량 {amount:,.3f} Å" if amount is not None else "누적 증착량 — (기록 없음)"


class ResultFrameNavigation(QWidget):
    """One interval for buttons, slider keyboard/page steps, and playback."""

    manualNavigation = Signal()

    def __init__(self, slider: QSlider, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.slider = slider
        # Dragging selects a destination without synchronously rendering every
        # intermediate frame. Keyboard/buttons/playback still update immediately.
        self.slider.setTracking(False)
        self.previous = QPushButton("◀ 이전")
        self.next = QPushButton("다음 ▶")
        self.interval = QSpinBox()
        self.interval.setAccessibleName("결과 이동 간격")
        self.interval.setRange(1, 2_147_483_647)
        self.interval.setValue(1)
        self.interval.setSuffix("장")
        self.interval.setKeyboardTracking(False)
        self.setToolTip(
            "이전·다음, 슬라이더 방향키, 자동재생에 적용할 이미지 간격입니다.\n"
            "슬라이더를 드래그한 뒤 놓으면 선택한 개별 이미지를 표시합니다.\n"
            "처음·마지막 이미지는 간격과 관계없이 확인할 수 있습니다. 계산 결과는 바뀌지 않습니다."
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("이동 간격"))
        layout.addWidget(self.interval)
        layout.addWidget(self.previous)
        layout.addWidget(self.next)
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        self.interval.valueChanged.connect(self._apply_interval)
        self.slider.actionTriggered.connect(lambda _action: self.manualNavigation.emit())
        self.slider.sliderPressed.connect(self.manualNavigation.emit)
        self.slider.valueChanged.connect(self._update_buttons)
        self.slider.rangeChanged.connect(self._update_buttons)
        self._apply_interval()

    def step(self) -> int:
        return self.interval.value()

    def set_available(self, available: bool) -> None:
        self.setEnabled(available)
        # Loading replaces the slider range/value with its signals blocked.
        self._update_buttons()

    def next_index(self, *, loop: bool = False) -> int:
        if loop and self.slider.value() >= self.slider.maximum():
            return self.slider.minimum()
        return min(self.slider.maximum(), self.slider.value() + self.step())

    def move(self, direction: int) -> None:
        self.manualNavigation.emit()
        value = self.slider.value() + direction * self.step()
        self.slider.setValue(max(self.slider.minimum(), min(value, self.slider.maximum())))

    def _apply_interval(self, _index: int = 0) -> None:
        self.slider.setSingleStep(self.step())
        self.slider.setPageStep(self.step())
        self._update_buttons()

    def _update_buttons(self, *_args: int) -> None:
        self.previous.setEnabled(self.slider.value() > self.slider.minimum())
        self.next.setEnabled(self.slider.value() < self.slider.maximum())
