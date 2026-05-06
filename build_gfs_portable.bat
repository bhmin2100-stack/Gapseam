@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creating local Python virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv. Install Python 3.10+ and retry.
    exit /b 1
  )
) else (
  echo [1/5] Reusing local Python virtual environment...
)

echo [2/5] Installing build dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -e . pyinstaller
if errorlevel 1 exit /b 1

echo [3/5] Cleaning old build artifacts...
if exist "build\GapSim" rmdir /s /q "build\GapSim"
if exist "build\GFS" rmdir /s /q "build\GFS"
if exist "dist\GFS" rmdir /s /q "dist\GFS"
del /q "dist\GFS_portable_*.zip" >nul 2>nul

echo [4/5] Building GFS and mini emulator with PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm "GapSim.spec"
if errorlevel 1 exit /b 1

if not exist "dist\GFS\GFS.exe" (
  echo dist\GFS\GFS.exe was not created
  exit /b 1
)

if not exist "dist\GFS\GFS_Emulator.exe" (
  echo dist\GFS\GFS_Emulator.exe was not created
  exit /b 1
)

if exist "presets" (
  if exist "dist\GFS\presets" rmdir /s /q "dist\GFS\presets"
  xcopy "presets" "dist\GFS\presets" /E /I /Y >nul
)

if exist "sample" (
  if exist "dist\GFS\sample" rmdir /s /q "dist\GFS\sample"
  xcopy "sample" "dist\GFS\sample" /E /I /Y >nul
)

if exist "emulator_research" (
  if exist "dist\GFS\emulator_research" rmdir /s /q "dist\GFS\emulator_research"
  xcopy "emulator_research" "dist\GFS\emulator_research" /E /I /Y >nul
)

echo [5/5] Creating portable zip...
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%I
powershell -NoProfile -Command ^
  "$zip = Join-Path '%cd%\\dist' ('GFS_portable_' + '%TS%' + '.zip');" ^
  "if (Test-Path $zip) { Remove-Item $zip -Force };" ^
  "Compress-Archive -Path '%cd%\\dist\\GFS' -DestinationPath $zip -Force;" ^
  "Write-Host $zip"
if errorlevel 1 exit /b 1

echo Done.
echo Run dist\GFS\GFS.exe for the main app or dist\GFS\GFS_Emulator.exe for the mini emulator.
echo Send the generated dist\GFS_portable_*.zip.
endlocal
