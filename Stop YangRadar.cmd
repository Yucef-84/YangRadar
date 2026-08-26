@echo off
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-yangradar.ps1"
if errorlevel 1 (
  echo.
  echo Shutdown failed. Check the message above.
)
pause

