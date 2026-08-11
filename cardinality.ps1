<#
CPLAN cardinality check - what each breakdown dimension costs, and what it is worth.

The pack's aggregate files are sized by their blocks: a dimension's distinct
values times every week in 04-calendar.csv, every measure in 06-breakdowns.csv,
and every year and quarter in 08-periods.csv. This measures all of it against a
real export instead of estimating, and reports coverage and concentration
beside the cost so the two can be weighed against each other.

Usage (from the repo root, or just double-click cardinality.cmd):
  .\cardinality.ps1
  .\cardinality.ps1 -InputDir C:\path\to\Input
  .\cardinality.ps1 -Csv cardinality.csv

Reads only. Always exits 0: there is no pass or fail here, only figures.
#>
param(
    [string]$InputDir,
    [string]$Csv
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

# Resolved before the Push-Location, so a relative path means what the caller
# meant by it - the folder they typed it in, not the repository root. Without
# this, ".\result.csv" is written beside the launcher instead of the folder
# the caller typed it from, with no error to say so.
if ($Csv) { $csvPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Csv)) }

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("-m", "pipeline.scripts.check_cardinality")
    if ($InputDir) { $args += @("--input", $InputDir) }
    if ($csvPath) { $args += @("--csv", $csvPath) }

    & $python @args
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "Exactly one candidate column links to the pack list." -ForegroundColor Green
    }
    else {
        # Not thrown: the check did its job, and the report above is the answer.
        # A traceback here would bury it.
        Write-Host "Read the report above - no single candidate column was chosen." -ForegroundColor Yellow
    }
    exit $code
}
finally {
    Pop-Location
}
