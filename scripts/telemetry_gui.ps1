<#
Launches the Tkinter telemetry GUI (render HUD overlay videos, export VBO
for lap-analysis tools).
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
