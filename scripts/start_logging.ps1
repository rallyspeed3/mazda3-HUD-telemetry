<#
Connects to the Arduino and starts recording a drive to a timestamped
CSV file in the "recordings" folder.

Flash firmware/can_live/can_live.ino to the Arduino before running this.
Press Ctrl+C when you're done driving -- the file is saved automatically.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Confirm-PythonAvailable
$port = Resolve-ArduinoPort

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
Write-Host "Make sure firmware/can_live/can_live.ino is already flashed to the Arduino." -ForegroundColor Yellow
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
