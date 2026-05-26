# GFE

GFE(Gap Fill Emulator)는 Gap Fill 공정 아이디어를 빠르게 실험하기 위한 **미니 에뮬레이터 중심** 앱입니다.
이 브랜치에서는 기존 GapSim 풀 UI를 기본 제품/패키징 대상에서 제외하고, 트렌치 Depo 에뮬레이터를 기본 실행 대상으로 둡니다.

내부 Python 패키지 경로는 호환성을 위해 아직 `gapsim`을 유지합니다.

## Repository Status

- **현재 메인 제품/실행 대상:** GFE 미니 에뮬레이터 (`gfe`, `run_gfe.*`, `GFE.spec`)
- **공식 패키징 대상:** `dist/GFE` / `GFE_portable_*.zip` / `GFE.app`
- **레거시 GapSim 풀 UI:** `src/gapsim/ui_qt/main_window.py`, `launcher_window.py` 등은 과거 구현 이력 조회와 호환 검증용으로 보존합니다.
- **레거시 alias:** `run_gapsim.*`, `run_simulator.bat`, `run_emulator.*`, `build_gfs_*`는 기존 사용자를 위해 남겨둔 alias이며 내부적으로 GFE를 실행/빌드합니다.

새 기능과 배포 스크립트는 GFE 기준으로 추가하고, 예전 GapSim 흐름은 필요한 경우에만 이력 확인용으로 참고합니다. 자세한 구분은 [`LEGACY_GAPSIM.md`](LEGACY_GAPSIM.md)를 봅니다.

## 연속 Depo 실행

결과 탭의 **다음 Depo** 버튼은 마지막 stage뿐 아니라 선택한 stage 완료 시점에서도 이어달리기를 시작할 수 있습니다.

- 1차 실행 후 `다음 Depo: 2차`
- 2차 결과에서 다시 `다음 Depo: 3차`
- 같은 방식으로 4차, 5차 이상 계속 진행 가능

각 run의 `profiles.json`에는 이전 stage 이력이 함께 저장되어, 나중에 3차/4차 run 폴더만 다시 열어도 앞선 Depo 이력을 복원할 수 있습니다.

## Build / Packaging Entry Point (SSOT)

이 저장소의 **공식 빌드 진입점은 루트 `pyproject.toml`** 입니다.

- 패키지 설치(개발): `pip install -e .`
- 기본 CLI 실행: `gfe`
- 모듈 직접 실행: `python -m gapsim.emulation.trench_depo_ui`
- `gapsim`, `gapsim-emulator` CLI 이름은 기존 사용자용 호환 alias입니다.

CI 또는 로컬 스크립트에서 pyproject 경로를 참조할 때는 항상 루트 기준(`./pyproject.toml`)으로 통일합니다.

## Windows 실행

### 회사 배포용 실행 파일 사용

회사 PC처럼 Python 설치 없이 실행하려면 GitHub Actions가 만든 Windows portable zip을 사용합니다.

1. GitHub 저장소의 **Actions** 탭으로 이동합니다.
2. **Build GFE Windows Portable EXE** 워크플로를 엽니다.
3. 최신 `main` 실행 결과를 선택합니다.
4. 페이지 하단 **Artifacts**에서 `GFE-windows-portable`을 다운로드합니다.
5. ZIP 압축을 풀고 `GFE\GFE.exe`를 실행합니다.

배포할 때는 ZIP 안의 `GFE` 폴더 전체를 전달합니다. Qt DLL과 내부 Python 런타임 파일이 함께 있어야 하므로 `GFE.exe`만 따로 복사하면 실행되지 않을 수 있습니다.

최신 portable zip이 없거나 다시 만들고 싶으면 GitHub의 **Actions → Build GFE Windows Portable EXE → Run workflow**에서 `main` 브랜치를 선택해 수동 실행합니다.

### 소스 ZIP으로 실행

개발자나 Python이 설치된 PC에서는 GitHub의 **Code → Download ZIP**으로 소스를 받은 뒤 압축을 풀고 루트의 아래 파일을 더블클릭합니다.

- `run_gfe.bat`: GFE 미니 에뮬레이터 실행
- `run_emulator.bat`: 기존 호환용 alias
- `run_gapsim.bat`, `run_simulator.bat`: 기존 호환용 alias이며 이제 GFE를 실행합니다.

첫 실행 때 `.venv` 가상환경과 Python 의존성을 자동으로 준비합니다. 소스 폴더에서 실행할 때는 Python 3.10 이상이 필요합니다.

### 직접 만든 portable zip 실행

로컬 Windows PC에서 직접 빌드한 경우 `dist/GFE_portable_*.zip`을 압축 해제하고 아래 파일을 실행합니다.

- `GFE\GFE.exe`: GFE 미니 에뮬레이터

## 회사 배포 절차

권장 배포 방식은 `main` 브랜치 기준 GitHub Actions artifact를 사용하는 것입니다.

1. 변경사항을 `main`에 푸시합니다.
2. **Actions → Build GFE Windows Portable EXE**가 성공했는지 확인합니다.
3. artifact `GFE-windows-portable`을 다운로드합니다.
4. 다운로드한 ZIP을 회사 PC 또는 공유 위치에 배포합니다.
5. 사용자는 압축 해제 후 `GFE\GFE.exe`를 실행합니다.

소스 코드까지 같이 확인해야 하는 경우에는 GitHub의 **Code → Download ZIP**으로 받은 소스 ZIP을 함께 전달합니다. 단, 소스 ZIP 실행은 Python 3.10 이상 설치가 필요하고 첫 실행 때 의존성 설치 시간이 걸립니다.

## 전체 코드 TXT 내보내기 (Windows)

윈도우에서 모든 소스/설정/문서 텍스트를 한 파일로 모으려면 루트의 아래 파일을 더블클릭합니다.

- `export_all_code_txt_windows.bat`: 최신 `exports/YYYYMMDD_HHMMSS/gfs_code_export.txt` 생성 후 `exports` 폴더 열기
- `run_export_project_txt.bat`: 동일한 TXT 내보내기를 수행하는 기존 호환용 실행 파일

생성된 TXT는 바이너리/빌드/실행 결과 폴더(`.git`, `.venv`, `dist`, `runs`, `exports` 등)를 제외하고 코드 중심 텍스트 파일만 합칩니다.

## Windows 실행파일 빌드

로컬 Windows PC에서 portable zip을 만들려면 아래 파일을 실행합니다.

`build_gfe_portable.bat`

스크립트는 `.venv` 생성, 의존성 설치, PyInstaller 빌드, `GFE.exe` 검증, `dist/GFE_portable_*.zip` 생성까지 처리합니다.

기존 `build_gfs_portable.bat`는 호환용 alias로 남겨두었고, 내부적으로 `build_gfe_portable.bat`를 호출합니다.

GitHub에서는 `.github/workflows/windows-build.yml` 워크플로가 `main`, `GFE`, `codex/**` 브랜치 push 때 Windows 러너에서 테스트 후 같은 portable zip artifact를 생성합니다.

## macOS 실행

1. 가상환경 생성 및 설치
   `python3 -m venv .venv`
   `source .venv/bin/activate`
   `pip install -e .`
2. 실행
   `gfe`

설치 없이 바로 실행하려면 루트의 `run_gfe.command`를 실행해도 됩니다.
Finder에서 더블클릭 실행도 가능하며, 터미널에서는 `chmod +x run_gfe.command` 후 `./run_gfe.command`로 실행할 수 있습니다.

기존 `run_emulator.command`, `run_gapsim.command`는 호환용 alias이며 이제 GFE를 실행합니다.

## macOS 실행파일(.app) 빌드

터미널 명령 없이 Finder에서 바로 실행할 앱 번들은 `dist/GFE.app`로 생성됩니다.

빌드:
`chmod +x build_gfe_macos.sh`
`./build_gfe_macos.sh`

기존 `build_gfs_macos.sh`는 호환용 alias로 남겨두었고, 내부적으로 `build_gfe_macos.sh`를 호출합니다.

빌드가 끝나면 `dist/GFE.app`를 더블클릭해서 실행할 수 있습니다.

## Runtime Dependencies (code-usage based)

루트 `pyproject.toml`의 런타임 의존성은 실제 코드 import/사용 기준으로 유지합니다.

- `PySide6`: Qt 기반 GFE UI (`src/gapsim/emulation/trench_depo_ui.py`, 재사용 Qt 위젯)
- `openpyxl`: 구조/파라미터 Excel 라이브러리 (`src/gapsim/emulation/structure_library.py`)
- `pillow` (`PIL`): 에뮬레이터 결과 이미지 내보내기 (`src/gapsim/emulation/trench_depo_export.py`)
- `pyclipper`: 기존 엔진/비교 모델 호환 경로 (`src/gapsim/engine/deposition_pipeline.py`)

`matplotlib`는 현재 코드 경로에서 사용되지 않아 의존성 정의에서 제외합니다.
