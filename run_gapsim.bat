@echo off
setlocal

cd /d "%~dp0"

rem Ensure legacy src layout is importable without requiring pip install -e .
if defined PYTHONPATH (
  set "PYTHONPATH=%cd%\src;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%cd%\src"
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m gapsim.ui_qt.main_window
) else if exist "gapsim\.venv\Scripts\python.exe" (
  "gapsim\.venv\Scripts\python.exe" -m gapsim.ui_qt.main_window
) else if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" -m gapsim.ui_qt.main_window
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 -m gapsim.ui_qt.main_window
  ) else (
    python -m gapsim.ui_qt.main_window
  )
)

if errorlevel 1 (
  echo.
  echo GFS failed to start. Exit code: %errorlevel%
  if "%GAPSIM_NO_PAUSE%"=="" pause
)

endlocal
