<#
Recover a wedged embedded CPLAN database. Use this when a start hangs or fails
with "Timeout starting server" / "database system was interrupted" after an
unclean shutdown (a console window closed while postgres was connected).

It stops the database cleanly (clearing any half-crashed postmaster and stale
postmaster.pid), then starts it once - giving crash recovery all the time it
needs - so the next setup.cmd / start.cmd finds a healthy server.

Usage (or double-click fix-db.cmd):
  .\fix-db.ps1
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Same interpreter resolution as the other launchers.
$config = @{}
$configPath = Join-Path $root "cplan.config"
if (Test-Path $configPath) {
    foreach ($line in Get-Content $configPath) {
        $t = $line.Trim()
        if ($t -and -not $t.StartsWith("#") -and $t.Contains("=")) {
            $i = $t.IndexOf("="); $config[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
        }
    }
}
function Resolve-Python {
    if ($config.ContainsKey("PYTHON") -and $config["PYTHON"] -and (Test-Path $config["PYTHON"])) { return $config["PYTHON"] }
    if ($env:CPLAN_PYTHON -and (Test-Path $env:CPLAN_PYTHON)) { return $env:CPLAN_PYTHON }
    if ($env:VIRTUAL_ENV) { $p = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"; if (Test-Path $p) { return $p } }
    $p = Join-Path $root ".venv\Scripts\python.exe"; if (Test-Path $p) { return $p }
    return $null
}
$python = Resolve-Python
if (-not $python) { Write-Host "No Python environment found (set PYTHON in cplan.config or CPLAN_PYTHON)." -ForegroundColor Red; exit 1 }
Write-Host "Using Python: $python" -ForegroundColor DarkGray

Push-Location $root
$env:PYTHONPATH = "."
try {
    Write-Host "First: close any open studio/portal/setup windows so nothing is holding the database." -ForegroundColor Yellow
    Write-Host ""

    Write-Host "[1/2] Stopping the database cleanly (clears a half-crashed server and stale pid)..." -ForegroundColor Cyan
    & $python -m pipeline.scripts.cplan_db --stop
    # A non-zero exit here usually just means it was not running - that is fine.

    Write-Host "[2/2] Starting it once and letting crash recovery finish (this can take a minute)..." -ForegroundColor Cyan
    & $python -m pipeline.scripts.cplan_db --start
    if ($LASTEXITCODE -ne 0) { throw "the database did not come up (exit $LASTEXITCODE)" }

    Write-Host "`nDatabase is healthy again." -ForegroundColor Green
    Write-Host "Next: double-click setup.cmd (if setup never finished) or start.cmd." -ForegroundColor Green
}
catch {
    Write-Host "`nRecovery failed: $_" -ForegroundColor Red
    Write-Host "If it keeps failing: make sure no python.exe / postgres.exe is still running" -ForegroundColor Yellow
    Write-Host "(Task Manager), then run this again. Data directory:" -ForegroundColor Yellow
    Write-Host "  $env:LOCALAPPDATA\CPLAN\postgres" -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
