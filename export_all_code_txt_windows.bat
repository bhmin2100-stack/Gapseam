@echo off
setlocal

rem One-click Windows exporter: collect project source/config/docs text into one TXT file.
cd /d "%~dp0"

echo [GFE] Creating one combined code TXT file...
echo.

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

set EXPORT_EXIT=%errorlevel%
if not "%EXPORT_EXIT%"=="0" (
  echo.
  echo [GFE] Export failed. Exit code: %EXPORT_EXIT%
  if "%GAPSIM_NO_PAUSE%"=="" pause
  exit /b %EXPORT_EXIT%
)

echo.
echo [GFE] Export complete. Check the newest folder under: exports
if exist "exports" start "" "%cd%\exports"

if "%GAPSIM_NO_PAUSE%"=="" pause
endlocal
