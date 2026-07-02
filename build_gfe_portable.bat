@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

set "PYTHON_EXE=%cd%\.venv\Scripts\python.exe"
set "LOG_DIR=%cd%\runs\trench_depo_emulation"
set "LOG_FILE=%LOG_DIR%\build_gfe_last.log"
set "PYTHON_INSTALL_ATTEMPTED=0"
set "BASE_PYTHON="

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
> "%LOG_FILE%" (
  echo ==== %date% %time% ====
  echo Project: %cd%
)

if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo [1/6] Existing local Python virtual environment is invalid. Rebuilding...
    rmdir /s /q ".venv" >> "%LOG_FILE%" 2>&1
    if exist ".venv" (
      echo Failed to remove .venv. Close running Python/GFE windows and retry.
      echo See log: %LOG_FILE%
      exit /b 1
    )
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/6] Creating local Python virtual environment...
  call :FIND_BASE_PYTHON
  if errorlevel 1 (
    echo Failed to find Python 3.10+. Install Python 3.10+ and retry.
    echo See log: %LOG_FILE%
    exit /b 1
  )
  echo Base Python: %BASE_PYTHON%>> "%LOG_FILE%"
  %BASE_PYTHON% -m venv ".venv" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo Failed to create .venv. Install Python 3.10+ and retry.
    echo See log: %LOG_FILE%
    exit /b 1
  )
) else (
  echo [1/6] Reusing local Python virtual environment...
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo Python 3.10 or newer is required to build GFE.
  echo See log: %LOG_FILE%
  exit /b 1
)

echo [2/6] Installing build dependencies...
"%PYTHON_EXE%" -m pip --version >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo pip is missing; repairing pip with ensurepip...
  echo pip is missing; running ensurepip.>> "%LOG_FILE%"
  "%PYTHON_EXE%" -m ensurepip --upgrade >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo Python is installed, but pip is missing and ensurepip failed.
    call :DIAGNOSE_PIP_FAILURE
    echo See log: %LOG_FILE%
    exit /b 1
  )
)
"%PYTHON_EXE%" -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo Failed to upgrade pip.
  call :DIAGNOSE_PIP_FAILURE
  echo See log: %LOG_FILE%
  exit /b 1
)
"%PYTHON_EXE%" -m pip install -e . pyinstaller openpyxl >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo Build dependency install failed; retrying without pip cache.>> "%LOG_FILE%"
  "%PYTHON_EXE%" -m pip install --no-cache-dir -e . pyinstaller openpyxl >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo Failed to install build dependencies.
    call :DIAGNOSE_PIP_FAILURE
    echo See log: %LOG_FILE%
    exit /b 1
  )
)

echo [3/6] Cleaning old build artifacts...
if exist "build\GFE" rmdir /s /q "build\GFE"
if exist "dist\GFE" rmdir /s /q "dist\GFE"
del /q "dist\GFE_portable_*.zip" >nul 2>nul

echo [4/6] Building GFE mini emulator with PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --noconfirm "GFE.spec" >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1

if not exist "dist\GFE\GFE.exe" (
  echo dist\GFE\GFE.exe was not created
  exit /b 1
)

echo [5/6] Copying runtime data...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$root = (Get-Location).Path;" ^
  "$dest = Join-Path $root 'dist\GFE';" ^
  "foreach ($name in @('presets', 'sample', 'emulator_research')) {" ^
  "  $source = Join-Path $root $name;" ^
  "  if (Test-Path -LiteralPath $source) {" ^
  "    $target = Join-Path $dest $name;" ^
  "    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }" ^
  "    Copy-Item -LiteralPath $source -Destination $target -Recurse -Force;" ^
  "  }" ^
  "}"
if errorlevel 1 exit /b 1

echo [6/6] Creating portable zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$root = (Get-Location).Path;" ^
  "$zip = Join-Path (Join-Path $root 'dist') ('GFE_portable_' + (Get-Date -Format yyyyMMdd_HHmmss) + '.zip');" ^
  "if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force };" ^
  "Compress-Archive -Path (Join-Path $root 'dist\GFE') -DestinationPath $zip -Force;" ^
  "Write-Host $zip"
if errorlevel 1 exit /b 1

echo Done.
echo Run dist\GFE\GFE.exe for the mini emulator.
echo Send the generated dist\GFE_portable_*.zip.
endlocal
exit /b 0

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
  echo Python 3.10+ was not found, and winget is not available on this PC.
  echo Install Python 3.10+ manually, or use the portable Windows ZIP with GFE.exe.
  echo winget is not available.>> "%LOG_FILE%"
  exit /b 1
)
echo.
echo Python 3.10+ was not found.
echo This build script needs Python to create .venv and build the portable package.
echo If this company PC blocks software installation, use the GitHub Actions portable ZIP instead.
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
  echo Failed to install Python with winget.
  echo This is usually blocked by company policy, proxy, or Microsoft Store/App Installer settings.
  echo Use the GitHub Actions portable ZIP if Python installation is blocked.
  echo winget failed to install Python 3.11.>> "%LOG_FILE%"
  exit /b 1
)
echo Python installer finished. Checking Python again...
exit /b 0

:DIAGNOSE_PIP_FAILURE
echo.
echo Dependency installation diagnostics:
echo - Python was found, but package installation failed.
echo - Common causes: company proxy/security blocks pip, no internet, damaged pip cache, or locked .venv files.
echo - If the log says BadZipFile or File is not a zip file, delete %%LOCALAPPDATA%%\pip\Cache and retry.
echo - On locked company PCs, use the GitHub Actions portable ZIP instead of building locally.
>> "%LOG_FILE%" echo ---- pip diagnostics ----
"%PYTHON_EXE%" --version >> "%LOG_FILE%" 2>&1
"%PYTHON_EXE%" -m pip --version >> "%LOG_FILE%" 2>&1
"%PYTHON_EXE%" -m pip config list -v >> "%LOG_FILE%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'https://pypi.org/simple/pip/' -TimeoutSec 10; Write-Host ('pypi.org reachable: HTTP ' + [int]$r.StatusCode) } catch { Write-Host ('pypi.org check failed: ' + $_.Exception.Message) }" >> "%LOG_FILE%" 2>&1
>> "%LOG_FILE%" echo ---- End pip diagnostics ----
exit /b 0
