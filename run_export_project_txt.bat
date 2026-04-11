@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" export_project_txt.py
) else if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" export_project_txt.py
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 export_project_txt.py
  ) else (
    python export_project_txt.py
  )
)

if errorlevel 1 (
  echo.
  echo Export failed. Exit code: %errorlevel%
)

if "%GAPSIM_NO_PAUSE%"=="" pause
endlocal
