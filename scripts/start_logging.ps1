<#
Connects to your board (Arduino Uno + MCP2515, or ESP32-S3) and starts
recording a drive to a timestamped CSV file in the "recordings" folder.

Flash can_live.ino (Arduino) or esp32_can_live.ino (ESP32) before
running this. Press Ctrl+C when you're done driving -- the file is
saved automatically.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Confirm-PythonAvailable
$port = Resolve-BoardPort

$recordingsDir = Join-Path $RepoRoot "recordings"
if (-not (Test-Path $recordingsDir)) {
    New-Item -ItemType Directory -Path $recordingsDir | Out-Null
}
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$outFile = Join-Path $recordingsDir "drive_$timestamp.csv"

Write-Host ""
Write-Host "Port:      $port" -ForegroundColor Cyan
Write-Host "Saving to: $outFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "Make sure can_live.ino (Arduino) or esp32_can_live.ino (ESP32) is already flashed." -ForegroundColor Yellow
Read-Host "Press Enter to start logging (Ctrl+C anytime to stop and save)"

Push-Location $RepoRoot
try {
    python tools/record_drive.py --port $port --rate 20 --out "$outFile"
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Saved: $outFile" -ForegroundColor Green
Write-Host "Turn it into a video with scripts\render_video.bat" -ForegroundColor DarkGray
