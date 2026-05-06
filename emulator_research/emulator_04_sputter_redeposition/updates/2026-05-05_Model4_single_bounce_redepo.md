# 에뮬레이터 04 - single-bounce 리데포 1차 구현

- Model1 direct sputter 계산식은 수정하지 않았다.
- Model4는 wrapper로 동작하며, source model을 `model1` 또는 `model2`로 선택할 수 있다.
- 리데포 source는 hard-coded bottom이 아니라 실제 gross sputter etch amount에서 자동 산출한다.
- 리데포 방출축은 reflected-ion reflection axis가 아니라 surface air normal lobe를 사용한다.
- 이번 버전은 single-bounce LOS만 포함하며, multi-bounce, reflected ion, gas-phase backscattering, surface diffusion은 제외했다.

## 기본 UI

- 4번 에뮬레이터에서 `Source = Model1 / Model2` 선택 가능
- `Redepo %`, `Emit power`, `Dist power` 조절 가능
- 비교창은 GapSim이 아니라 Emulator 01 baseline과 비교

## 디버그 확인 항목

- `total_removed_mass`
- `total_redepo_mass`
- `redepo_capture_ratio`
- `active_source_count`
- `active_target_count`
- `top_source_mass`
- `upper_sidewall_source_mass`
- `mid_sidewall_source_mass`
- `bottom_source_mass`
