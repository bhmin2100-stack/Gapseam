@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

rem Legacy alias: GFE is now the emulator-first portable package.
call "%~dp0build_gfe_portable.bat"
set "EXIT_CODE=%errorlevel%"

endlocal
exit /b %EXIT_CODE%
