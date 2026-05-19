# Legacy GapSim Notes

이 저장소의 현재 기준 제품은 **GFE(Gap Fill Emulator)** 입니다.
아래 항목들은 삭제하지 않고 남겨두지만, 새 개발의 중심이 아니라 과거 구현/이력 조회용으로 취급합니다.

## GFE 메인 경로

- 실행: `gfe`, `python -m gapsim.emulation.trench_depo_ui`
- macOS 실행: `run_gfe.command`
- Windows 실행: `run_gfe.bat`
- Windows portable 빌드: `build_gfe_portable.bat`
- macOS 앱 빌드: `build_gfe_macos.sh`
- PyInstaller spec: `GFE.spec`
- 핵심 UI/모델: `src/gapsim/emulation/`

## 레거시/호환 경로

| 경로 | 현재 역할 |
| --- | --- |
| `run_gapsim.*`, `run_simulator.bat`, `run_emulator.*` | 기존 사용자용 alias. GFE 실행으로 연결 |
| `build_gfs_*` | 기존 빌드명 호환 alias. GFE 빌드로 연결 |
| `src/gapsim/ui_qt/main_window.py` | 과거 GapSim 풀 UI 구현 이력/호환 테스트 참조 |
| `src/gapsim/ui_qt/launcher_window.py` | 과거 MDI 런처 이력/호환 참조 |
| `GapSim.spec` | 예전 이름으로 남은 GFE spec alias |
| `emulator_research/`, `reports/` | 실험/보고서 이력 자료 |
| `exports/`, `gapsim/sources_dump.txt` | 과거 코드 export 이력 자료 |

## 정리 원칙

1. 새 기능은 GFE 경로(`src/gapsim/emulation`, `run_gfe.*`, `GFE.spec`)를 기준으로 추가한다.
2. 레거시 파일은 기존 결과를 다시 보거나 구현 히스토리를 확인해야 할 때만 수정한다.
3. 호환 alias는 사용자가 기존 파일명을 더블클릭해도 GFE가 열리도록 유지한다.
4. 빌드/배포 문서와 CI는 GFE 이름을 우선 사용한다.
