# GFE

GFE(Gap Fill Emulator)는 Gap Fill 공정 아이디어를 빠르게 실험하기 위한 Windows/macOS용 미니 에뮬레이터입니다.

## Windows에서 바로 실행

회사 PC에서 소스 ZIP으로 확인할 때는 아래 순서만 따르면 됩니다.

1. GitHub 저장소 첫 화면에서 **Code** 버튼을 누릅니다.
2. **Download ZIP**을 누릅니다.
3. ZIP 압축을 풉니다.
4. 압축을 푼 폴더 안의 `run_gfe.bat`를 더블클릭합니다.

처음 실행하면 `.venv` 가상환경과 필요한 Python 패키지를 자동으로 준비합니다. 소스 ZIP 방식은 PC에 Python 3.10 이상이 설치되어 있어야 합니다. Python이 없으면 `run_gfe.bat`가 설치 상태를 진단하고, Windows `winget`이 사용 가능한 PC에서는 Python 3.11 설치를 물어본 뒤 시도합니다. 회사 보안 정책이 소프트웨어 설치나 pip 접속을 막는 PC에서는 아래의 portable ZIP 방식을 쓰는 편이 안정적입니다.

`run_gfe.bat`는 기존 `.venv`가 깨졌거나 Python 경로가 바뀐 경우 자동으로 `.venv`를 다시 만들고 재시도합니다. pip 캐시 문제를 줄이기 위해 dependency 설치 실패 시 캐시 없이 한 번 더 재시도합니다. 그래도 실행이 실패하면 아래 파일에 마지막 실행 로그와 Python/pip 진단 내용이 남습니다.

```text
%LOCALAPPDATA%\Gapseam\logs\run_gfe_last.log
```

실패 화면에는 마지막 로그 80줄도 같이 표시됩니다. `Failed to install Python dependencies`가 보이면 Python 자체는 잡혔지만 회사 proxy/security가 pip 다운로드를 막았거나, 인터넷 연결이 없거나, pip cache가 손상된 경우가 많습니다. `BadZipFile` 또는 `File is not a zip file`이 보이면 데이터 폴더의 `emulator_research\structures.xlsx`가 손상됐거나, pip가 받은 wheel/cache 파일이 손상된 경우입니다.

구조 저장 Excel은 프로그램 폴더가 아니라 처음 선택한 GFE 데이터 폴더의 `emulator_research\structures.xlsx`에 저장됩니다. 구조를 저장할 때는 임시 `.xlsx` 파일을 먼저 만들고 열기 검증 후 원본을 교체하므로 저장 중 실패해도 기존 파일이 최대한 보존됩니다. 기존 `structures.xlsx`가 이미 손상된 경우에는 `structures.invalid_YYYYMMDD_HHMMSS.xlsx`로 백업하고 새 구조 워크북을 만듭니다.

`.venv` 삭제가 실패했다는 메시지가 나오면 열려 있는 GFE/Python 창을 모두 닫고 `run_gfe.bat`를 다시 실행하세요.

## Python 없이 실행하는 배포 ZIP

Python 설치가 없는 PC에 배포하려면 GitHub Actions가 만든 portable ZIP을 사용합니다.

1. GitHub 저장소의 **Actions** 탭으로 이동합니다.
2. **Build GFE Windows Portable EXE** 워크플로를 엽니다.
3. 최신 `main` 실행 결과를 선택합니다.
4. 페이지 하단 **Artifacts**에서 `GFE-windows-portable`을 다운로드합니다.
5. ZIP 압축을 풀고 `GFE\GFE.exe`를 실행합니다.

배포할 때는 ZIP 안의 `GFE` 폴더 전체를 전달합니다. `GFE.exe`만 따로 복사하면 Qt DLL과 내부 Python 런타임이 빠져 실행되지 않을 수 있습니다.

## Windows 배포 ZIP 직접 만들기

Windows PC에서 직접 portable ZIP을 만들려면 루트 폴더에서 아래 파일을 실행합니다.

```text
build_gfe_portable.bat
```

빌드가 끝나면 `dist/GFE_portable_*.zip`이 생성됩니다.

이 빌드 방식도 Python 3.10 이상과 pip 다운로드가 필요합니다. Python이 없으면 `build_gfe_portable.bat`도 `winget` 설치를 물어본 뒤 시도하지만, 회사 PC에서 막히면 GitHub Actions가 만든 `GFE-windows-portable` artifact를 사용하는 것이 좋습니다.

## Addon 폴더

GFE는 시작할 때 루트의 `addons/` 폴더를 자동으로 확인합니다. addon 하나는 폴더 하나로 관리합니다.

```text
addons/
  my-addon/
    addon.json
    addon.py
```

`addon.json` 예시:

```json
{
  "id": "my-addon",
  "name": "My Addon",
  "version": "0.1.0",
  "description": "Adds a custom panel.",
  "entrypoint": "addon.py",
  "extension_points": ["progress.panel"]
}
```

`addon.py`에는 `register(context)` 함수를 둡니다. 처음 발견된 addon은 기본 ON으로 표시되고, GFE의 **애드온** 목록에서 체크/해제할 수 있습니다.

```python
from PySide6.QtWidgets import QLabel


def register(context):
    context.add_progress_widget(QLabel("Addon loaded"), title="My Addon")
```

체크 상태는 `addons/addons_state.json`에 저장됩니다. 외부 addon은 로컬 Python 코드로 실행되므로 신뢰할 수 있는 폴더만 넣으세요.

## macOS 실행

macOS에서는 루트 폴더의 아래 파일을 실행합니다.

```text
run_gfe.command
```

터미널에서 실행할 경우:

```sh
chmod +x run_gfe.command
./run_gfe.command
```

macOS 앱 번들을 만들려면:

```sh
chmod +x build_gfe_macos.sh
./build_gfe_macos.sh
```

빌드 결과는 `dist/GFE.app`입니다.

## 개발자 실행

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
gfe
```

모듈 직접 실행:

```sh
python -m gapsim.emulation.trench_depo_ui
```

## 주요 파일

- `run_gfe.bat`: Windows 소스 ZIP 실행 파일
- `run_gfe.command`: macOS 소스 실행 파일
- `build_gfe_portable.bat`: Windows portable ZIP 빌드
- `build_gfe_macos.sh`: macOS 앱 번들 빌드
- `GFE.spec`: PyInstaller 빌드 설정
- `pyproject.toml`: Python 패키지/의존성 설정
- `addons/`: GFE 시작 시 자동 인식되는 addon 폴더

## 연속 Depo 실행

결과 탭의 **다음 Depo** 버튼으로 선택한 stage 완료 시점부터 다음 Depo를 이어서 실행할 수 있습니다.

- 1차 실행 후 `다음 Depo: 2차`
- 2차 결과에서 다시 `다음 Depo: 3차`
- 같은 방식으로 4차, 5차 이상 계속 진행 가능

각 run의 `profiles.json`에는 이전 stage 이력이 함께 저장되어, 나중에 3차/4차 run 폴더만 다시 열어도 앞선 Depo 이력을 복원할 수 있습니다.

## 런타임 의존성

- `PySide6`: Qt 기반 UI
- `openpyxl`: Excel 구조/파라미터 라이브러리
- `pillow`: 결과 이미지 내보내기
- `pyclipper`: 형상 계산 경로
