@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo .venv\Scripts\python.exe not found
  exit /b 1
)

echo [1/3] Cleaning old build artifacts...
if exist "build\GFS" rmdir /s /q "build\GFS"
if exist "dist\GFS" rmdir /s /q "dist\GFS"

echo [2/3] Building GFS with PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm "GapSim.spec"
if errorlevel 1 exit /b 1

echo [3/3] Creating portable zip...
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%I
powershell -NoProfile -Command ^
  "$zip = Join-Path '%cd%\\dist' ('GFS_portable_' + '%TS%' + '.zip');" ^
  "if (Test-Path $zip) { Remove-Item $zip -Force };" ^
  "Compress-Archive -Path '%cd%\\dist\\GFS' -DestinationPath $zip -Force;" ^
  "Write-Host $zip"
if errorlevel 1 exit /b 1

echo Done.
endlocal
