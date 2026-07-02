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
set "PYTHON_INSTALL_ATTEMPTED=0"
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
call :LOG_PYTHON_DISCOVERY

:FIND_BASE_PYTHON_SCAN
where py >nul 2>nul
if not errorlevel 1 (
  py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if not errorlevel 1 (
    set "BASE_PYTHON=py -3.13"
    exit /b 0
  )
  py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if not errorlevel 1 (
    set "BASE_PYTHON=py -3.12"
    exit /b 0
  )
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
  if not errorlevel 1 (
    set "BASE_PYTHON=python"
    exit /b 0
  )
  echo python command is missing or older than 3.10.>> "%LOG_FILE%"
)

where python3 >nul 2>nul
if not errorlevel 1 (
  python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if not errorlevel 1 (
    set "BASE_PYTHON=python3"
    exit /b 0
  )
  echo python3 command is missing or older than 3.10.>> "%LOG_FILE%"
)

call :TRY_PYTHON_EXE "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not errorlevel 1 exit /b 0
call :TRY_PYTHON_EXE "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not errorlevel 1 exit /b 0
call :TRY_PYTHON_EXE "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not errorlevel 1 exit /b 0
call :TRY_PYTHON_EXE "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not errorlevel 1 exit /b 0
call :TRY_PYTHON_EXE "%ProgramFiles%\Python313\python.exe"
if not errorlevel 1 exit /b 0
call :TRY_PYTHON_EXE "%ProgramFiles%\Python312\python.exe"
if not errorlevel 1 exit /b 0
call :TRY_PYTHON_EXE "%ProgramFiles%\Python311\python.exe"
if not errorlevel 1 exit /b 0
call :TRY_PYTHON_EXE "%ProgramFiles%\Python310\python.exe"
if not errorlevel 1 exit /b 0

if "%PYTHON_INSTALL_ATTEMPTED%"=="0" (
  call :OFFER_PYTHON_INSTALL
  if not errorlevel 1 (
    echo Rescanning for Python after winget install...>> "%LOG_FILE%"
    goto FIND_BASE_PYTHON_SCAN
  )
)

set "FAIL_REASON=No usable Python 3.10+ found"
echo Python 3.10 or newer is required to run from source.
echo Install Python 3.10+, allow the winget install prompt, or use the portable Windows ZIP with GFE.exe.
echo No usable Python 3.10+ found.>> "%LOG_FILE%"
exit /b 1

:TRY_PYTHON_EXE
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
set BASE_PYTHON="%~1"
exit /b 0

:LOG_PYTHON_DISCOVERY
>> "%LOG_FILE%" echo ---- Python discovery ----
where py >> "%LOG_FILE%" 2>&1
where python >> "%LOG_FILE%" 2>&1
where python3 >> "%LOG_FILE%" 2>&1
py -0p >> "%LOG_FILE%" 2>&1
python --version >> "%LOG_FILE%" 2>&1
python3 --version >> "%LOG_FILE%" 2>&1
where winget >> "%LOG_FILE%" 2>&1
>> "%LOG_FILE%" echo ---- End Python discovery ----
exit /b 0

:OFFER_PYTHON_INSTALL
set "PYTHON_INSTALL_ATTEMPTED=1"
where winget >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3.10+ was not found, and winget is not available on this PC.
  echo Install Python 3.10+ manually, or use the portable Windows ZIP with GFE.exe.
  echo winget is not available.>> "%LOG_FILE%"
  exit /b 1
)
echo.
echo Python 3.10+ was not found.
echo This source ZIP needs Python to create .venv and install dependencies.
echo If this company PC blocks software installation, use the portable Windows ZIP instead.
if /I not "%GFE_AUTO_INSTALL_PYTHON%"=="1" (
  choice /C YN /N /M "Install Python 3.11 with winget now? [Y/N] "
  if errorlevel 2 (
    echo User declined winget Python install.>> "%LOG_FILE%"
    exit /b 1
  )
)
echo.
echo Installing Python 3.11 with winget...
echo Installing Python 3.11 with winget.>> "%LOG_FILE%"
winget install --id Python.Python.3.11 -e --scope user --accept-package-agreements --accept-source-agreements >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=winget failed to install Python 3.11"
  echo Failed to install Python with winget.
  echo This is usually blocked by company policy, proxy, or Microsoft Store/App Installer settings.
  echo Use the portable Windows ZIP with GFE.exe if Python installation is blocked.
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  exit /b 1
)
echo Python installer finished. Checking Python again...
exit /b 0

:ENSURE_DEPS
"%PYTHON_EXE%" -c "import PySide6, pyclipper, PIL, openpyxl; import gapsim.emulation.trench_depo_ui" >> "%LOG_FILE%" 2>&1
if not errorlevel 1 exit /b 0

echo.
echo Installing Python dependencies...
echo Installing Python dependencies>> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip --version >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo pip is missing; repairing pip with ensurepip...
  echo pip is missing; running ensurepip.>> "%LOG_FILE%"
  "%PYTHON_EXE%" -m ensurepip --upgrade >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    set "FAIL_REASON=Python is installed, but pip is missing and ensurepip failed"
    echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
    call :DIAGNOSE_PIP_FAILURE
    exit /b 1
  )
)
"%PYTHON_EXE%" -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=Failed to upgrade pip"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  echo Failed to upgrade pip. See log: %LOG_FILE%
  call :DIAGNOSE_PIP_FAILURE
  exit /b 1
)
"%PYTHON_EXE%" -m pip install -e . >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo Dependency install failed; retrying without pip cache.>> "%LOG_FILE%"
  "%PYTHON_EXE%" -m pip install --no-cache-dir -e . >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    set "FAIL_REASON=Failed to install Python dependencies"
    echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
    echo Failed to install dependencies. See log: %LOG_FILE%
    call :DIAGNOSE_PIP_FAILURE
    exit /b 1
  )
)
"%PYTHON_EXE%" -c "import PySide6, pyclipper, PIL, openpyxl; import gapsim.emulation.trench_depo_ui" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  set "FAIL_REASON=Failed to import installed Python dependencies"
  echo Failure: %FAIL_REASON%>> "%LOG_FILE%"
  call :DIAGNOSE_PIP_FAILURE
)
exit /b %errorlevel%

:DIAGNOSE_PIP_FAILURE
echo.
echo Dependency installation diagnostics:
echo - Python was found, but package installation or import failed.
echo - Common causes: company proxy/security blocks pip, no internet, damaged pip cache, or locked .venv files.
echo - If the log says BadZipFile or File is not a zip file, delete %%LOCALAPPDATA%%\pip\Cache and retry.
echo - On locked company PCs, use the portable Windows ZIP with GFE.exe instead of the source ZIP.
>> "%LOG_FILE%" echo ---- pip diagnostics ----
"%PYTHON_EXE%" --version >> "%LOG_FILE%" 2>&1
"%PYTHON_EXE%" -m pip --version >> "%LOG_FILE%" 2>&1
"%PYTHON_EXE%" -m pip config list -v >> "%LOG_FILE%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'https://pypi.org/simple/pip/' -TimeoutSec 10; Write-Host ('pypi.org reachable: HTTP ' + [int]$r.StatusCode) } catch { Write-Host ('pypi.org check failed: ' + $_.Exception.Message) }" >> "%LOG_FILE%" 2>&1
>> "%LOG_FILE%" echo ---- End pip diagnostics ----
exit /b 0

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
