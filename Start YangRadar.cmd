@echo off
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-yangradar.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Check the message above.
  pause
)

