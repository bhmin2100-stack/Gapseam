# 에뮬레이터 02 업데이트: Ion transmission / geometric shadowing

## 목표

- 에뮬레이터 01 direct angle sputter 모델은 보존한다.
- 에뮬레이터 02는 01의 sputter output에 `ion_factor`만 곱한다.
- `conformal deposition`에는 `ion_factor`를 곱하지 않는다.
- reflected ion, redeposition, microtrenching, diffusion solver, full ray tracing은 02 범위에서 제외한다.

## 구현 선택

- 근사: `depth / local opening width` + shallow opening 기준 simple sky visibility.
- 계산 위치: direct sputter raw field 계산 직후.
- 결합:
  - `sputter_raw_field = model01_direct_sputter_output`
  - `ion_factor_field = depth_opening_width_sky_visibility(geometry)`
  - `sputter_effective_field = sputter_raw_field * ion_factor_field`
  - `net_growth_field = depo_field - sputter_effective_field`
- 관찰 geometry: 넓은 입구와 내부 계단/neck을 가진 `ION_TRANSMISSION_STEPPED_TRENCH_POINTS`.

## 보존 확인

- `ion_transmission_enabled=False`이면 01 direct sputter와 frame profile이 동일하다.
- `ion_transmission_override=1.0`이어도 01 direct sputter와 frame profile이 동일하다.
- `sputter_strength=0`이면 ion transmission이 켜져도 conformal-only와 동일하다.
- 에뮬레이터 02 기본 config에서는 `reflected_ion_active=False`, `reflected_ion_total_last=0`.

## 구동 결과

Run:

`runs/trench_depo_emulation/20260504_193424_트렌치증착_12사이클_10A_에뮬레이터02_계단식_넓은_트렌치_ion_transmission_shadowing_검증`

12 cycle, 10 A/cycle, sputter 8 A/cycle, stepped wide trench:

- model01 final points: 4592
- model02 final points: 4666
- ion factor top/mid/bottom: 0.733 / 0.133 / 0.058
- sputter raw top/bottom: 0.149 / 0.054 A/substep
- sputter effective top/bottom: 0.073 / 0.003 A/substep
- reflected ion active: false
- reflected ion total: 0.0

해석: 01의 angle-dependent sputter field는 유지되고, 02 transmission factor 때문에 깊은 bottom 쪽 실제 etch만 강하게 약해진다.

## 참고 문헌

- Huard et al., "Role of neutral transport in aspect ratio dependent plasma etching of three-dimensional features", JVST A 35, 05C301 (2017), DOI 10.1116/1.4973953.
- Gottscho, Jurgensen, Vitkavage, "Microscopic uniformity in plasma etching", JVST B 10, 2133 (1992), DOI 10.1116/1.586180.
- Dynamics of plasma-surface interactions and feature profile evolution during pulsed plasma etching, Thin Solid Films 374, 208-216 (2000), DOI 10.1016/S0040-6090(00)01152-4.
