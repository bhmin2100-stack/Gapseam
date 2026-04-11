# GapSim

## Build / Packaging Entry Point (SSOT)

이 저장소의 **공식 빌드 진입점은 루트 `pyproject.toml`** 입니다.

- 패키지 설치(개발): `pip install -e .`
- 배포 빌드: `python -m build`
- `gapsim/pyproject.toml`는 더 이상 사용하지 않으며 제거되었습니다.

CI 또는 로컬 스크립트에서 pyproject 경로를 참조할 때는 항상 루트 기준(`./pyproject.toml`)으로 통일합니다.

## Runtime Dependencies (code-usage based)

루트 `pyproject.toml`의 런타임 의존성은 실제 코드 import/사용 기준으로 유지합니다.

- `PySide6`: Qt UI (`src/gapsim/ui_qt/*`)
- `pillow` (`PIL`): 이미지 로드/내보내기 (`src/gapsim/engine/viz.py`, `src/gapsim/ui_qt/main_window.py`)
- `pyclipper`: 증착/오프셋 지오메트리 계산 (`src/gapsim/engine/deposition_pipeline.py`)

`matplotlib`는 현재 코드 경로에서 사용되지 않아 의존성 정의에서 제외합니다.
