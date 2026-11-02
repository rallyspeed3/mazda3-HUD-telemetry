@echo off
REM Double-click this to connect to the Arduino and start logging a drive.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_logging.ps1"
echo.
pause
