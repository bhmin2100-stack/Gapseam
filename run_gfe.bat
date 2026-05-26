@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

set "APP_NAME=GFE"
set "APP_MODULE=gapsim.emulation.trench_depo_ui"

call :RUN_APP
exit /b %errorlevel%

:RUN_APP
echo.
echo Starting %APP_NAME%...

if not exist "src\gapsim" (
  echo.
  echo This file must be run from the GFE repository folder.
  goto FAIL
)

if defined PYTHONPATH (
  set "PYTHONPATH=%cd%\src;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%cd%\src"
)

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Creating local Python virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv ".venv"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo Python 3.10 or newer is required to run from source.
      echo Install Python, or use the portable Windows ZIP with GFE.exe.
      goto FAIL
    )
    python -m venv ".venv"
  )
  if errorlevel 1 goto FAIL
)

".venv\Scripts\python.exe" -c "import PySide6, pyclipper, PIL, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Installing Python dependencies...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto FAIL
  ".venv\Scripts\python.exe" -m pip install -e . openpyxl
  if errorlevel 1 goto FAIL
)

echo.
echo Launching %APP_NAME%...
".venv\Scripts\python.exe" -m %APP_MODULE%
if errorlevel 1 goto FAIL

endlocal
exit /b 0

:FAIL
echo.
echo %APP_NAME% failed to start.
if "%GFE_NO_PAUSE%"=="" pause
endlocal
exit /b 1
