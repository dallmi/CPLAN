<#
CPLAN standalone studio - the whole planning studio as one read-only HTML file.

Exports the current database into a single file that opens by double-click, with
no web server and no internet. Everything the studio can show, it can show:
all four pages, every analytic, filters, search, the read-only drawer, and both
the CSV and Excel exports.

What it cannot do is write. Creating, editing, deleting and per-activity change
history stay in the studio (start.ps1).

Read this before sending the file to anyone: it carries the complete plan in
cleartext, with no login and no expiry. Whoever receives it receives all of it,
and can forward it further.

Usage (from the repo root, or just double-click snapshot.cmd):
  .\snapshot.ps1                        # export, then open it
  .\snapshot.ps1 -NoOpen                # write it, leave it closed
  .\snapshot.ps1 -Out C:\tmp\plan.html  # somewhere else

The database has to be reachable - this reads it directly, and deliberately does
not fall back to the parquet snapshot: activities created in the studio never
reach the parquet, so a fallback would quietly ship an incomplete plan.
#>
param(
    [switch]$NoOpen,
    [string]$Out
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
# Same resolution order as the other launchers: CPLAN_PYTHON override, then an
# active venv, then a repo-local .venv.
function Resolve-CplanPython {
    if ($env:CPLAN_PYTHON -and (Test-Path $env:CPLAN_PYTHON)) { return $env:CPLAN_PYTHON }
    if ($env:VIRTUAL_ENV) {
        $p = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path $p) { return $p }
    }
    $p = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $p) { return $p }
    return $null
}

$python = Resolve-CplanPython
if (-not $python) {
    Write-Host "No Python environment found for CPLAN." -ForegroundColor Red
    Write-Host "Point the launcher at your existing venv once, then open a NEW window:" -ForegroundColor Yellow
    Write-Host '  setx CPLAN_PYTHON "C:\path\to\your\venv\Scripts\python.exe"'
    exit 1
}
Write-Host "Using Python: $python" -ForegroundColor DarkGray

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("-m", "pipeline.scripts.build_studio_standalone")
    if ($Out) { $args += @("--out", $Out) }

    Write-Host "== CPLAN standalone studio: database -> one read-only HTML file ==" -ForegroundColor Cyan
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "build_studio_standalone failed (exit code $LASTEXITCODE)" }

    if (-not $NoOpen) {
        $written = if ($Out) { $Out } else { Join-Path $root "pipeline\output\cplan_studio_standalone.html" }
        if (Test-Path $written) {
            Write-Host "Opening $written" -ForegroundColor Green
            Start-Process $written
        }
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    Write-Host "This reads the database directly. If it cannot connect, run setup.ps1 once," -ForegroundColor Yellow
    Write-Host "or start the database with:  .venv\Scripts\python pipeline\scripts\cplan_db.py --status" -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
