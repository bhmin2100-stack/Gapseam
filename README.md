# GapSim

## Build / Packaging Entry Point (SSOT)

이 저장소의 **공식 빌드 진입점은 루트 `pyproject.toml`** 입니다.

- 패키지 설치(개발): `pip install -e .`
- 배포 빌드: `python -m build`
- `gapsim/pyproject.toml`는 더 이상 사용하지 않으며 제거되었습니다.

CI 또는 로컬 스크립트에서 pyproject 경로를 참조할 때는 항상 루트 기준(`./pyproject.toml`)으로 통일합니다.

## Windows 실행

Python이 설치된 개발 PC에서는 루트의 `run_gapsim.bat`를 실행하면 됩니다.
GitHub Desktop으로 clone한 소스 폴더에서는 아래 파일을 더블클릭해 각각 실행할 수 있습니다.

- `run_simulator.bat`: GapSim 메인 시뮬레이터
- `run_emulator.bat`: 미니 에뮬레이터

첫 실행 때 `.venv` 가상환경과 Python 의존성을 자동으로 준비합니다. 소스 폴더에서 실행할 때는 Python 3.10 이상이 필요합니다.

회사 PC처럼 Python 설치 없이 실행하려면 Windows 빌드 산출물인 `GFS_portable_*.zip`을 내려받아 압축을 풀고 아래 파일 중 필요한 것을 실행합니다.

- `GFS\GFS.exe`: GapSim 메인 앱
- `GFS\GFS_Emulator.exe`: 미니 에뮬레이터

두 실행파일은 Qt DLL과 내부 Python 런타임 파일이 함께 있어야 하므로 exe만 따로 빼지 말고 `GFS` 폴더 전체를 유지해야 합니다.


## 전체 코드 TXT 내보내기 (Windows)

윈도우에서 모든 소스/설정/문서 텍스트를 한 파일로 모으려면 루트의 아래 파일을 더블클릭합니다.

- `export_all_code_txt_windows.bat`: 최신 `exports/YYYYMMDD_HHMMSS/gfs_code_export.txt` 생성 후 `exports` 폴더 열기
- `run_export_project_txt.bat`: 동일한 TXT 내보내기를 수행하는 기존 호환용 실행 파일

생성된 TXT는 바이너리/빌드/실행 결과 폴더(`.git`, `.venv`, `dist`, `runs`, `exports` 등)를 제외하고 코드 중심 텍스트 파일만 합칩니다.

## Windows 실행파일 빌드

로컬 Windows PC에서 portable zip을 만들려면 아래 파일을 실행합니다.

`build_gfs_portable.bat`

스크립트는 `.venv` 생성, 의존성 설치, PyInstaller 빌드, `GFS.exe`와 `GFS_Emulator.exe` 검증, `dist/GFS_portable_*.zip` 생성까지 처리합니다.

GitHub에서는 `.github/workflows/windows-build.yml` 워크플로가 `main` 또는 `codex/**` 브랜치 push 때 Windows 러너에서 테스트 후 같은 portable zip artifact를 생성합니다.

## macOS 실행

맥에서는 Windows용 `run_gapsim.bat` 대신 아래 방법 중 하나를 사용합니다.

1. 가상환경 생성 및 설치
   `python3 -m venv .venv`
   `source .venv/bin/activate`
   `pip install -e .`
2. 실행
   `gapsim`

설치 없이 바로 실행하려면 루트의 `run_gapsim.command`를 실행해도 됩니다.
Finder에서 더블클릭 실행도 가능하며, 터미널에서는 `chmod +x run_gapsim.command` 후 `./run_gapsim.command`로 실행할 수 있습니다.

코드 내 실행 진입점은 공통으로 `python -m gapsim.ui_qt.main_window` 입니다.

## macOS 실행파일(.app) 빌드

터미널 명령 없이 Finder에서 바로 실행할 앱 번들은 `dist/GFS.app`로 생성됩니다.

빌드:
`chmod +x build_gfs_macos.sh`
`./build_gfs_macos.sh`

빌드가 끝나면 `dist/GFS.app`를 더블클릭해서 실행할 수 있습니다.

## Runtime Dependencies (code-usage based)

루트 `pyproject.toml`의 런타임 의존성은 실제 코드 import/사용 기준으로 유지합니다.

- `PySide6`: Qt UI (`src/gapsim/ui_qt/*`)
- `pillow` (`PIL`): 이미지 로드/내보내기 (`src/gapsim/engine/viz.py`, `src/gapsim/ui_qt/main_window.py`)
- `pyclipper`: 증착/오프셋 지오메트리 계산 (`src/gapsim/engine/deposition_pipeline.py`)

`matplotlib`는 현재 코드 경로에서 사용되지 않아 의존성 정의에서 제외합니다.
