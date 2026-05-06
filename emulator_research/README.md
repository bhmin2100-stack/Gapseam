# GapSim Mini Emulator Research Slots

이 폴더는 미니 에뮬레이터 연구를 0번부터 10번까지 분리해서 관리하기 위한 작업 공간이다.

- `emulator_00_conformal_depo_baseline`: 기본 선택값. etch 없는 conformal deposition 기준 모드
- `emulator_01_direct_angle_sputter_etch`: trench conformal deposition + direct angle sputter etch 연구
- `emulator_02_ion_transmission_shadowing`: 1번 direct sputter 출력에 ion transmission / geometric shadowing 계수만 곱하는 실험
- `emulator_03_reflected_ion_etch`: 폐기. 1번 direct sputter 위 reflected ion 항은 형상 차이 대비 실행 부담이 커서 채택하지 않음
- `emulator_04_sputter_redeposition`: 준비중. 1번 direct sputter 출력 위에 redeposition 항을 결합할 예정
- `emulator_05_unassigned` ~ `emulator_10_unassigned`: UI의 `New` 버튼으로 하나씩 생성해 붙일 대기 슬롯
- `presentations`: 에뮬레이터별 분리 PPTX 저장 위치

운영 규칙:

1. 각 에뮬레이터는 독립 연구 제목을 가진다.
2. 새 물리 요청이나 결과 정리가 생기면 해당 에뮬레이터 PPT에 슬라이드 1장을 추가한다.
3. 코드 변경 설명보다 물리적 요청, 관찰, 파라미터, 결과 해석을 우선 기록한다.
4. UI는 0번, 1번, 2번, 3번, 4번 토글로 시작하고, 새 에뮬레이터는 다음 빈 번호로 생성한다.
5. 1번 에뮬레이터는 `gapsim.emulation.trench_depo` 기반 direct angle sputter etch 작업을 담당한다.
6. 2번 에뮬레이터는 1번 direct sputter를 보존하고, sputter output에만 ion transmission 계수를 곱한다.
7. 3번 에뮬레이터는 1번 direct sputter를 black box로 보존하고 별도 reflected ion field를 더하는 실험이었으나, 성능 대비 효과가 작아 폐기한다.
8. 4번 에뮬레이터는 1번 direct sputter와만 섞어 redeposition 항을 검증하고, 비교창도 GapSim 대신 1번 baseline과 비교한다.
9. 관련 논문, 리뷰, 공식 문서가 있으면 제목/연도/출처를 기록하고 핵심 물리 그림 또는 데이터 형태를 슬라이드에 반영한다.
10. PPT는 텍스트 요약만 만들지 않고 실험 screenshot, run GIF, geometry 비교 이미지, 논문 figure를 기반으로 한 재구성 도식 등 시각 자료를 적극적으로 사용한다.
11. 외부 이미지나 논문 그림을 쓸 때는 출처를 남기고, 그대로 복제하기보다 필요한 경우 직접 재구성한 설명 그림으로 만든다.
