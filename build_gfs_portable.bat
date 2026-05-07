@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/6] Creating local Python virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv ".venv"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo Failed to find Python. Install Python 3.10+ and retry.
      exit /b 1
    )
    python -m venv ".venv"
  )
  if errorlevel 1 (
    echo Failed to create .venv. Install Python 3.10+ and retry.
    exit /b 1
  )
) else (
  echo [1/6] Reusing local Python virtual environment...
)

set "PYTHON_EXE=%cd%\.venv\Scripts\python.exe"

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Python 3.10 or newer is required to build GFS.
  exit /b 1
)

echo [2/6] Installing build dependencies...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" -m pip install -e . pyinstaller openpyxl
if errorlevel 1 exit /b 1

echo [3/6] Cleaning old build artifacts...
if exist "build\GapSim" rmdir /s /q "build\GapSim"
if exist "build\GFS" rmdir /s /q "build\GFS"
if exist "dist\GFS" rmdir /s /q "dist\GFS"
del /q "dist\GFS_portable_*.zip" >nul 2>nul

echo [4/6] Building GFS and mini emulator with PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --noconfirm "GapSim.spec"
if errorlevel 1 exit /b 1

if not exist "dist\GFS\GFS.exe" (
  echo dist\GFS\GFS.exe was not created
  exit /b 1
)

if not exist "dist\GFS\GFS_Emulator.exe" (
  echo dist\GFS\GFS_Emulator.exe was not created
  exit /b 1
)

echo [5/6] Copying runtime data...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$root = (Get-Location).Path;" ^
  "$dest = Join-Path $root 'dist\GFS';" ^
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
  "$zip = Join-Path (Join-Path $root 'dist') ('GFS_portable_' + (Get-Date -Format yyyyMMdd_HHmmss) + '.zip');" ^
  "if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force };" ^
  "Compress-Archive -Path (Join-Path $root 'dist\GFS') -DestinationPath $zip -Force;" ^
  "Write-Host $zip"
if errorlevel 1 exit /b 1

echo Done.
echo Run dist\GFS\GFS.exe for the main app or dist\GFS\GFS_Emulator.exe for the mini emulator.
echo Send the generated dist\GFS_portable_*.zip.
endlocal
