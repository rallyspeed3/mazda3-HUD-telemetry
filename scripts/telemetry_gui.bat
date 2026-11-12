@echo off
REM Double-click this to open the HUD overlay renderer / telemetry GUI.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0telemetry_gui.ps1"
echo.
pause
