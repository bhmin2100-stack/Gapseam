# 2026-05-06 redepo performance tuning

- 병목 확인:
  - `compute_redeposition()` 내부의 `PathLOS.visible_indices()`가 대부분의 시간을 사용한다.
  - 그 아래에서는 segment intersection과 LOS candidate segment traversal이 지배적이다.
- 최적화:
  - source bin 기본값을 64로 제한했다.
  - source별 LOS target 후보를 rough lobe weight 기준 상위/누적 99% 후보로 제한하고 기본 cap을 256으로 설정했다.
  - Model4 내부 substep 기준 이동량을 16 A 이상으로 완화해 기본 `Depo 10 A / Etch 12 A` 조건은 1 substep으로 계산한다.
- 측정:
  - `cycles=1`, `Depo 10 A`, `Etch 12 A`, `Redepo 25%`: 약 1.6 s.
  - 같은 조건 `cycles=5`: 약 7.5 s.
  - capture ratio는 목표 efficiency와 거의 동일하게 유지된다.
