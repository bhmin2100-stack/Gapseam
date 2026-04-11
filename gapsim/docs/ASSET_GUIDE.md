# Asset Guide

## 목적
런타임에 필요한 자산과 예제/개발용 자산을 구분해, 배포물과 저장소 루트를 단순화한다.

## 디렉터리 구조 분류

### 1) 런타임 필수 (required)
- `presets/run_presets.json`
  - 앱 실행 시 `MainWindow._run_preset_store_path()`가 기본 저장소로 읽고/쓴다.
  - 파일이 없어도 런타임에서 생성 가능하지만, 기본 배포에서는 초기 프리셋 제공을 위해 포함한다.

### 2) 런타임 선택 (optional)
- `sample/sample.json`
  - 수동 로드용 최소 예제 레시피.
  - 기능 검증/온보딩을 위한 샘플이며 앱 실행 필수 파일은 아니다.

### 3) 개발/레거시 (development only)
- `usg.json` (삭제됨)
  - 과거 실험 데이터 덤프 용도였으며 현재 코드 경로에서 참조하지 않는다.
  - 저장소 경량화와 예제 단순화를 위해 제거했다.

## 이번 정리 내역
- 오탈자 파일명 `sample/smaple.json` -> `sample/sample.json`으로 정정.
- 미사용 샘플 `sample/z.json` 삭제.
- 미사용 레거시 JSON `usg.json` 삭제.
- `presets/run_presets.json`은 중복 프리셋(`gfs`, `zzz`)을 제거하고 최소 기본 프리셋(`default`) 1개만 유지.
