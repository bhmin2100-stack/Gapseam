# GFE

GFE(Gap Fill Emulator)는 Gap Fill 공정 아이디어를 빠르게 실험하기 위한 Windows/macOS용 미니 에뮬레이터입니다.

## Windows에서 바로 실행

회사 PC에서 소스 ZIP으로 확인할 때는 아래 순서만 따르면 됩니다.

1. GitHub 저장소 첫 화면에서 **Code** 버튼을 누릅니다.
2. **Download ZIP**을 누릅니다.
3. ZIP 압축을 풉니다.
4. 압축을 푼 폴더 안의 `run_gfe.bat`를 더블클릭합니다.

처음 실행하면 `.venv` 가상환경과 필요한 Python 패키지를 자동으로 준비합니다. 소스 ZIP 방식은 PC에 Python 3.10 이상이 설치되어 있어야 합니다.

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
