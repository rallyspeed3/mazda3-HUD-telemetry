<#
Renders a recorded drive CSV into a transparent HUD overlay video
(throttle/brake bars, steering wheel, gear indicator).
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Confirm-PythonAvailable
Confirm-FfmpegAvailable -RepoRoot $RepoRoot

$recordingsDir = Join-Path $RepoRoot "recordings"
$csvCandidates = @()
if (Test-Path $recordingsDir) {
    $csvCandidates = @(Get-ChildItem $recordingsDir -Filter *.csv -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
}

$csvPath = $null
if ($csvCandidates.Count -gt 0) {
    Write-Host "Which recording do you want to render?"
    for ($i = 0; $i -lt $csvCandidates.Count; $i++) {
        Write-Host "  $($i + 1)) $($csvCandidates[$i].Name)"
    }
    Write-Host "  0) type a different file path"
    while ($true) {
        $choice = Read-Host "Pick a number"
        if ($choice -eq "0") { break }
        $index = 0
        if ([int]::TryParse($choice, [ref]$index) -and $index -ge 1 -and $index -le $csvCandidates.Count) {
            $csvPath = $csvCandidates[$index - 1].FullName
            break
        }
        Write-Host "Type one of the numbers listed above." -ForegroundColor Yellow
    }
}

if (-not $csvPath) {
    $csvPath = (Read-Host "Full path to the CSV").Trim('"')
}
if (-not (Test-Path $csvPath)) {
    Write-Host "Can't find that file: $csvPath" -ForegroundColor Red
    exit 1
}

$orientation = Read-Host "Horizontal dash-cam video or vertical Reels/Stories? [h/v]"
if ($orientation -match '^[Vv]') {
    $config = "hud_overlay/configs/vertical_reels.json"
    $extraArgs = @("--width", "1080", "--height", "1920")
} else {
    $config = "hud_overlay/configs/horizontal_1080p.json"
    $extraArgs = @()
}

$baseName = [System.IO.Path]::GetFileNameWithoutExtension($csvPath)
$outDir = Split-Path -Parent $csvPath
$outFile = Join-Path $outDir "${baseName}_hud.mov"

Write-Host ""
Write-Host "Rendering -> $outFile" -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    python hud_overlay/render_overlay.py --csv "$csvPath" --config $config --out "$outFile" @extraArgs
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done: $outFile" -ForegroundColor Green
