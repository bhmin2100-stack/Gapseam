# 2026-05-06 GapSim-style binned-lobe redeposition

- 사용자가 원본 GapSim simulator의 redeposition 형태가 더 깔끔하다고 지적했다.
- 원본 `SputterRedepositionFluxModel._compute_redeposition_flux()`를 재확인했다.
- 핵심 차이:
  - 원본은 모든 유효 sputter source를 그대로 사용한다.
  - 원본은 source별 target을 상위 일부로 자르지 않는다.
  - 원본은 거리 power, same-depth penalty, 후처리 smoothing/cap을 쓰지 않는다.
  - 원본은 반사축 Gaussian lobe, target-facing, PathLOS만으로 분배한다.
- 에뮬레이터 4의 `compute_redeposition()`을 `gapsim_binned_lobe_los`로 바꿨다.
- 원본 full source 계산은 에뮬레이터 기본 해상도에서 너무 느려서, source만 depth/side bin으로 줄인다.
- target 분배는 원본처럼 전체 target 후보를 평가하고, target cap이나 거리 power는 쓰지 않는다.
- 기존 UI/config의 `emit_power`는 일단 lobe sigma로 매핑한다. `emit_power=1.0`이면 sigma 24 deg, 값이 커질수록 lobe가 좁아진다.
- 기존 `distance_power`, `lateral_spread_a`, `max_redepo_to_etch_ratio`, `max_redepo_distance`는 원본 GapSim 형태 보존을 위해 transport weight에는 쓰지 않는다.
