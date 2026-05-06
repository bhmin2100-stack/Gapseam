@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

call "%~dp0run_simulator.bat"
set "EXIT_CODE=%errorlevel%"

endlocal
exit /b %EXIT_CODE%
