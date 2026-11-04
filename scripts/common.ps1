# Shared helpers, dot-sourced by the other scripts in this folder.
# You don't run this one directly.

function Resolve-BoardPort {
    # Works for either board: Arduino Uno shows up as "Arduino" or
    # "CH340"; the ESP32-S3's native USB shows up as "USB Serial Device".
    Write-Host "Looking for your board..." -ForegroundColor Cyan

    $candidates = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match 'COM\d+' -and (
                $_.Name -match 'Arduino' -or
                $_.Name -match 'CH340' -or
                $_.Name -match 'USB-SERIAL' -or
                $_.Name -match 'USB Serial' -or
                $_.Name -match 'ESP32'
            )
        })

    if ($candidates.Count -eq 1) {
        $port = [regex]::Match($candidates[0].Name, 'COM\d+').Value
        Write-Host "Found it: $port ($($candidates[0].Name))" -ForegroundColor Green
        return $port
    }

    if ($candidates.Count -gt 1) {
        Write-Host "Found more than one possible device:"
        for ($i = 0; $i -lt $candidates.Count; $i++) {
            $p = [regex]::Match($candidates[$i].Name, 'COM\d+').Value
            Write-Host "  $($i + 1)) $p -- $($candidates[$i].Name)"
        }
        while ($true) {
            $choice = Read-Host "Which one is your board? (type the number)"
            $index = 0
            if ([int]::TryParse($choice, [ref]$index) -and $index -ge 1 -and $index -le $candidates.Count) {
                return [regex]::Match($candidates[$index - 1].Name, 'COM\d+').Value
            }
            Write-Host "Type one of the numbers listed above." -ForegroundColor Yellow
        }
    }

    Write-Host "Couldn't auto-detect it." -ForegroundColor Yellow
    Write-Host "Open Device Manager -> Ports (COM & LPT) to find it -- look for" -ForegroundColor Yellow
    Write-Host "something like 'USB-SERIAL CH340 (COM6)', 'Arduino Uno (COM6)'," -ForegroundColor Yellow
    Write-Host "or 'USB Serial Device (COM6)' (ESP32-S3)." -ForegroundColor Yellow
    return (Read-Host "Type the COM port (e.g. COM6)").Trim()
}

function Confirm-PythonAvailable {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "Python wasn't found on your PATH." -ForegroundColor Red
        Write-Host "Install it from https://www.python.org/downloads/" -ForegroundColor Red
        Write-Host "(check 'Add python.exe to PATH' during setup), then run:" -ForegroundColor Red
        Write-Host "  pip install -r requirements.txt" -ForegroundColor Red
        exit 1
    }
}

function Find-FfmpegBinFolder {
    param([string]$RepoRoot)

    # Look for a portable ffmpeg.exe someone already downloaded/unzipped
    # near this project, so you don't have to fiddle with PATH yourself.
    $searchRoots = @(
        $RepoRoot,
        (Split-Path -Parent $RepoRoot),
        "C:\ffmpeg",
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"),
        (Join-Path ${env:ProgramFiles} "ffmpeg")
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

    foreach ($root in $searchRoots) {
        $found = Get-ChildItem -Path $root -Filter "ffmpeg.exe" -Recurse -Depth 5 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) {
            return $found.DirectoryName
        }
    }
    return $null
}

function Confirm-FfmpegAvailable {
    param([string]$RepoRoot)

    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        return
    }

    Write-Host "ffmpeg isn't on your PATH -- checking for a copy on this PC..." -ForegroundColor Yellow
    $binDir = Find-FfmpegBinFolder -RepoRoot $RepoRoot
    if ($binDir) {
        Write-Host "Found it: $binDir" -ForegroundColor Green
        $env:PATH = "$binDir;$env:PATH"
        return
    }

    Write-Host "ffmpeg wasn't found anywhere on this PC (needed to render video)." -ForegroundColor Red
    Write-Host "Download it from https://ffmpeg.org/download.html, unzip it anywhere" -ForegroundColor Red
    Write-Host "(even inside this project folder) -- this script will find it next" -ForegroundColor Red
    Write-Host "time without any extra setup." -ForegroundColor Red
    exit 1
}
