<#
Connects to the Arduino and shows a live readout of every signal this
toolkit knows (RPM, speed, throttle, brake, steering, gear, wheel speeds)
-- useful for sanity-checking your wiring before you actually drive.

Flash firmware/can_live/can_live.ino to the Arduino before running this.
Ctrl+C to stop. Nothing is saved -- use scripts\start_logging.bat for that.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Confirm-PythonAvailable
$port = Resolve-ArduinoPort

Write-Host ""
Write-Host "Make sure firmware/can_live/can_live.ino is already flashed to the Arduino." -ForegroundColor Yellow
Write-Host "Ctrl+C to stop.`n" -ForegroundColor Yellow

Push-Location $RepoRoot
try {
    python tools/live_dashboard.py --port $port
}
finally {
    Pop-Location
}
