@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

set "APP_NAME=GFE"
set "APP_MODULE=gapsim.emulation.trench_depo_ui"
set "PYTHON_EXE=%cd%\.venv\Scripts\python.exe"
if defined LOCALAPPDATA (
  set "LOG_DIR=%LOCALAPPDATA%\Gapseam\logs"
) else (
  set "LOG_DIR=%TEMP%\Gapseam\logs"
)
set "LOG_FILE=%LOG_DIR%\run_gfe_last.log"
set "REBUILT_VENV=0"
set "FAIL_REASON=Unknown startup failure"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
if not exist "%LOG_DIR%" (
  set "LOG_DIR=%cd%"
  set "LOG_FILE=%cd%\run_gfe_last.log"
)
> "%LOG_FILE%" (
  echo ==== %date% %time% ====
  echo Project: %cd%
  echo Log file: %LOG_FILE%
)

call :RUN_APP
exit /b %errorlevel%

:RUN_APP
echo.
echo Starting %APP_NAME%...

if not exist "src\gapsim" (
  echo.
  echo This file must be run from the GFE repository folder.
  set "FAIL_REASON=run_gfe.bat was not launched from the GFE repository folder"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  goto FAIL
)

if defined PYTHONPATH (
  set "PYTHONPATH=%cd%\src;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%cd%\src"
)
echo PYTHONPATH=%PYTHONPATH%>> "%LOG_FILE%"

call :ENSURE_VENV
if errorlevel 1 (
  if "%FAIL_REASON%"=="Unknown startup failure" set "FAIL_REASON=Python virtual environment setup failed"
  goto FAIL
)

call :ENSURE_DEPS
if errorlevel 1 (
  if "%REBUILT_VENV%"=="0" (
    echo.
    echo Existing Python environment looks broken. Rebuilding .venv...
    echo Dependency check failed; rebuilding .venv.>> "%LOG_FILE%"
    call :RESET_VENV
    if errorlevel 1 (
      if "%FAIL_REASON%"=="Unknown startup failure" set "FAIL_REASON=Dependency check failed and .venv rebuild failed"
      goto FAIL
    )
    call :ENSURE_DEPS
    if errorlevel 1 (
      if "%FAIL_REASON%"=="Unknown startup failure" set "FAIL_REASON=Python dependency installation/import failed"
      goto FAIL
    )
  ) else (
    if "%FAIL_REASON%"=="Unknown startup failure" set "FAIL_REASON=Python dependency installation/import failed"
    goto FAIL
  )
)

echo.
echo Launching %APP_NAME%...
echo Launching %APP_NAME% with %PYTHON_EXE%>> "%LOG_FILE%"
"%PYTHON_EXE%" -m %APP_MODULE% >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=GFE Python module exited with an error"
  goto FAIL
)

endlocal
exit /b 0

:ENSURE_VENV
if not exist "%PYTHON_EXE%" (
  call :CREATE_VENV
  exit /b %errorlevel%
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo.
  echo Local Python environment is invalid or too old. Rebuilding .venv...
  echo Existing .venv failed version check.>> "%LOG_FILE%"
  call :RESET_VENV
  exit /b %errorlevel%
)
exit /b 0

:CREATE_VENV
echo.
echo Creating local Python virtual environment...
echo Creating .venv>> "%LOG_FILE%"
set "REBUILT_VENV=1"
call :FIND_BASE_PYTHON
if errorlevel 1 exit /b 1
echo Base Python: %BASE_PYTHON%>> "%LOG_FILE%"
%BASE_PYTHON% -m venv ".venv" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=Failed to create .venv with %BASE_PYTHON%"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  echo Failed to create .venv. See log: %LOG_FILE%
  exit /b 1
)
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=Python 3.10 or newer is required"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  echo Python 3.10 or newer is required to run from source.
  echo Install Python 3.10+, or use the portable Windows ZIP with GFE.exe.
  exit /b 1
)
exit /b 0

:RESET_VENV
if exist ".venv" (
  rmdir /s /q ".venv" >> "%LOG_FILE%" 2>&1
  if exist ".venv" (
    set "FAIL_REASON=Failed to remove the old .venv folder"
    echo Failed to remove the old .venv folder.
    echo Close any running Python/GFE window and retry.
    echo Failed to remove .venv.>> "%LOG_FILE%"
    exit /b 1
  )
)
call :CREATE_VENV
exit /b %errorlevel%

:FIND_BASE_PYTHON
set "BASE_PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if not errorlevel 1 (
    set "BASE_PYTHON=py -3.11"
    exit /b 0
  )
  py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if not errorlevel 1 (
    set "BASE_PYTHON=py -3.10"
    exit /b 0
  )
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if not errorlevel 1 (
    set "BASE_PYTHON=py -3"
    exit /b 0
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    set "FAIL_REASON=python command is older than 3.10"
    echo python command is older than 3.10.>> "%LOG_FILE%"
    exit /b 1
  )
  set "BASE_PYTHON=python"
  exit /b 0
)

set "FAIL_REASON=No usable Python 3.10+ found"
echo Python 3.10 or newer is required to run from source.
echo Install Python 3.10+, or use the portable Windows ZIP with GFE.exe.
echo No usable Python 3.10+ found.>> "%LOG_FILE%"
exit /b 1

:ENSURE_DEPS
"%PYTHON_EXE%" -c "import PySide6, pyclipper, PIL, openpyxl; import gapsim.emulation.trench_depo_ui" >> "%LOG_FILE%" 2>&1
if not errorlevel 1 exit /b 0

echo.
echo Installing Python dependencies...
echo Installing Python dependencies>> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=Failed to upgrade pip"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  echo Failed to upgrade pip. See log: %LOG_FILE%
  exit /b 1
)
"%PYTHON_EXE%" -m pip install -e . >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=Failed to install Python dependencies"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  echo Failed to install dependencies. See log: %LOG_FILE%
  exit /b 1
)
"%PYTHON_EXE%" -c "import PySide6, pyclipper, PIL, openpyxl; import gapsim.emulation.trench_depo_ui" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=Failed to import installed Python dependencies"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
)
exit /b %errorlevel%

:FAIL
echo.
echo %APP_NAME% failed to start.
echo Reason: %FAIL_REASON%
echo Last log: %LOG_FILE%
echo.
echo ---- Last log lines ----
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '%LOG_FILE%') { Get-Content -LiteralPath '%LOG_FILE%' -Tail 80 } else { Write-Host 'Log file was not created.' }" 2>nul
if errorlevel 1 (
  if exist "%LOG_FILE%" type "%LOG_FILE%"
)
echo ---- End log ----
if "%GFE_NO_PAUSE%"=="" pause
endlocal
exit /b 1
