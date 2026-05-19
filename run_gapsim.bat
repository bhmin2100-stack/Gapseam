@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

rem Legacy alias: GFE now starts the mini emulator by default.
call "%~dp0run_gfe.bat"
set "EXIT_CODE=%errorlevel%"

endlocal
exit /b %EXIT_CODE%
