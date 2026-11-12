<#
Launches the Tkinter GUI for rendering HUD overlay videos.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Confirm-PythonAvailable
Confirm-FfmpegAvailable -RepoRoot $RepoRoot

Push-Location $RepoRoot
try {
    python gui/app.py
}
finally {
    Pop-Location
}
