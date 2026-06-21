@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

set "PYTHON_EXE=%cd%\.venv\Scripts\python.exe"
set "LOG_DIR=%cd%\runs\trench_depo_emulation"
set "LOG_FILE=%LOG_DIR%\build_gfe_last.log"

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
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv ".venv" >> "%LOG_FILE%" 2>&1
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo Failed to find Python. Install Python 3.10+ and retry.
      echo See log: %LOG_FILE%
      exit /b 1
    )
    python -m venv ".venv" >> "%LOG_FILE%" 2>&1
  )
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
"%PYTHON_EXE%" -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" -m pip install -e . pyinstaller openpyxl >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1

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
