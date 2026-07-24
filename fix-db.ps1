<#
Reset a wedged embedded CPLAN database to a clean, stopped state. Use this when
a start hangs or fails with "Timeout starting server" / "database system was
interrupted" / an AssertionError after an unclean shutdown.

It ONLY stops the database cleanly (clearing a half-crashed postmaster and any
stale postmaster.pid). It deliberately does NOT start it: a short-lived window
that starts the embedded server would kill it again the moment the window
closes, leaving the next step to trip over a dying server. After this, the
next setup.cmd / start.cmd cold-starts a fresh, healthy server itself.

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

    Write-Host "Stopping the database cleanly (clears a half-crashed server and stale pid)..." -ForegroundColor Cyan
    & $python -m pipeline.scripts.cplan_db --stop
    # A non-zero exit here usually just means it was not running - that is fine.

    # Kill any orphaned CPLAN postgres.exe left behind by an unclean shutdown.
    # These keep the data directory's files locked ("sharing violation on ./log"),
    # which blocks the next start. Scoped by command line to the CPLAN data
    # directory so no unrelated PostgreSQL is touched. Needs no admin rights.
    $pgdata = Join-Path $env:LOCALAPPDATA "CPLAN\postgres"
    $orphans = Get-CimInstance Win32_Process -Filter "Name = 'postgres.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*CPLAN*postgres*" }
    if ($orphans) {
        Write-Host "Killing $($orphans.Count) orphaned postgres.exe process(es) holding the data directory..." -ForegroundColor Cyan
        foreach ($p in $orphans) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
    }

    Write-Host "`nDatabase reset to a clean, stopped state." -ForegroundColor Green
    Write-Host "Next: double-click setup.cmd (if setup never finished) or start.cmd -" -ForegroundColor Green
    Write-Host "it will cold-start a fresh server itself. Do NOT run any other CPLAN" -ForegroundColor Green
    Write-Host "window at the same time." -ForegroundColor Green
}
catch {
    Write-Host "`nClean stop failed: $_" -ForegroundColor Red
    Write-Host "Make sure no python.exe / postgres.exe is still running (Task Manager)," -ForegroundColor Yellow
    Write-Host "then run this again. Data directory:" -ForegroundColor Yellow
    Write-Host "  $env:LOCALAPPDATA\CPLAN\postgres" -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
