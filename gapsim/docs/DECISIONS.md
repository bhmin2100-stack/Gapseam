# GapSim Decisions (SSOT)

## D1. Recipe SSOT
- Recipe JSON의 정식 스키마는 `gapsim.domain.recipe.Recipe`이다.
- 저장/로드는 `gapsim.io.recipe_io.save_recipe/load_recipe`만 사용한다.
- UI 내부 dict는 존재할 수 있으나 파일 포맷으로는 사용하지 않는다.

## D2. Walls
- View wall(표시/클리핑)과 physics boundary(계산 경계조건)는 분리한다.
- Physics boundary 위치는 엔진 preprocess 규칙에 의해 결정적(deterministic)으로 산출한다.
- sealed_mode 같은 경계조건 옵션은 wall 자체가 아니라 step params 또는 meta로 저장한다.

## D3. Phase2 -> Step
- Phase2(점 이동 성장)는 runner 하드코딩이 아니라 Step으로 구현한다.
- runner는 steps 실행 + snapshot/metrics/events 기록 + cancel/progress만 담당한다.