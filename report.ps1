<#
CPLAN calendar report - the planning year as one .xlsx.

Reads the SharePoint CSV exports straight from the OneDrive sync folder. No
database, no API process, no sync run has to be up first - which is why this
launcher does far less than refresh.ps1: there is nothing to start and nothing
to wait for.

Usage (from the repo root, or just double-click report.cmd):
  .\report.ps1                        # the period set in CONFIG (2026), then open it
  .\report.ps1 -All                   # every dated activity, whatever CONFIG says
  .\report.ps1 -Year 2026             # one calendar year
  .\report.ps1 -From 2025-01-01 -To 2026-12-31   # two years in one workbook
  .\report.ps1 -NoOpen                # write it, leave it closed
  .\report.ps1 -Out C:\tmp\plan.xlsx  # somewhere else
  .\report.ps1 -InputDir C:\tmp\csv   # read from here instead of OneDrive
  .\report.ps1 -GebMembers C:\tmp\geb-members.csv  # split GEB / GEB-1

The period is the one criterion with a switch here, because it is the one that
changes from run to run. The rest - senior-executive involvement, audience
bands - live in the CONFIG block at the top of
pipeline\scripts\report_calendar.py. A switch costs nothing in traceability:
every workbook prints its own period on the Executive Summary and carries it in
its filename, so a run is still readable months later from the file alone.
#>
param(
    [switch]$All,
    [int]$Year,
    [string]$From,
    [string]$To,
    [switch]$NoOpen,
    [string]$Out,
    [string]$InputDir,
    [string]$GebMembers
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
    Write-Host "Or create a repo venv:" -ForegroundColor Yellow
    Write-Host "  py -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install pandas openpyxl"
    exit 1
}
Write-Host "Using Python: $python" -ForegroundColor DarkGray

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("pipeline\scripts\report_calendar.py")
    # -Year is [int], so an omitted switch arrives as 0 rather than $null.
    if ($All) { $args += "--all" }
    if ($Year -gt 0) { $args += @("--year", $Year) }
    if ($From) { $args += @("--from", $From) }
    if ($To) { $args += @("--to", $To) }
    if ($Out) { $args += @("--out", $Out) }
    if ($InputDir) { $args += @("--input-dir", $InputDir) }
    if ($GebMembers) { $args += @("--geb-members", $GebMembers) }

    Write-Host "== CPLAN calendar report: CSV -> .xlsx ==" -ForegroundColor Cyan
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "report_calendar failed (exit code $LASTEXITCODE)" }

    # The script prints the path it wrote; find it again the same way it names
    # it, so -NoOpen and a custom -Out both behave.
    if (-not $NoOpen) {
        if ($Out) {
            $written = $Out
        }
        else {
            $written = Get-ChildItem (Join-Path $root "pipeline\output\reports") -Filter "CPLAN_calendar_*.xlsx" |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
        }
        if ($written -and (Test-Path $written)) {
            Write-Host "Opening $written" -ForegroundColor Green
            Start-Process $written
        }
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    Write-Host "If it says 'no input files found', the Power Automate export hasn't landed in" -ForegroundColor Yellow
    Write-Host "OneDrive yet, or the files are still cloud-only placeholders (right-click the" -ForegroundColor Yellow
    Write-Host "Input folder -> 'Always keep on this device'). You can also point the report at" -ForegroundColor Yellow
    Write-Host "a folder of CSVs directly:  .\report.ps1 -InputDir C:\path\to\csv" -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
