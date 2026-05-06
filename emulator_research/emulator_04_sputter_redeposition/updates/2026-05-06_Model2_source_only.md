# 2026-05-06 Model2 source only

- 4번 redeposition의 source model 선택지를 제거하고 `model2` ion transmission source만 사용하도록 고정했다.
- 예전 run/config에 `redepo_source_model="model1"`이 들어와도 실행 단계에서 `model2`로 정규화한다.
- UI의 Source 콤보박스에는 `Model2 ion source` 하나만 남겼고, 4번 설명 문구도 `2번 source + 4번 redepo` 기준으로 바꿨다.
- Model4 redepo가 active일 때 결과 meta의 ion transmission model은 source 경로가 실제로 사용된 것으로 표시한다.
- 회귀 테스트:
  - 기존 `model1` config가 `model2`로 흡수되는지 확인
  - zero-efficiency redepo가 direct sputter와 동일한지 확인
  - UI에서 Source 선택지가 하나만 남는지 확인
