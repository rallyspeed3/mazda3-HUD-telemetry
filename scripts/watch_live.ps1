<#
Connects to your board (Arduino Uno + MCP2515, or ESP32-S3) and shows a
live readout of every signal this toolkit knows (RPM, speed, throttle,
brake, steering, gear, wheel speeds) -- useful for sanity-checking your
wiring before you actually drive.

Flash can_live.ino (Arduino) or esp32_can_live.ino (ESP32) before
running this. Ctrl+C to stop. Nothing is saved -- use
scripts\start_logging.bat for that.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Confirm-PythonAvailable
$port = Resolve-BoardPort

Write-Host ""
Write-Host "Make sure can_live.ino (Arduino) or esp32_can_live.ino (ESP32) is already flashed." -ForegroundColor Yellow
Write-Host "Ctrl+C to stop.`n" -ForegroundColor Yellow

Push-Location $RepoRoot
try {
    python tools/live_dashboard.py --port $port
}
finally {
    Pop-Location
}
