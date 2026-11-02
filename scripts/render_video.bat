@echo off
REM Double-click this to turn a recorded CSV into a HUD overlay video.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0render_video.ps1"
echo.
pause
