@echo off
REM Double-click this to watch live CAN data without recording anything.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0watch_live.ps1"
echo.
pause
