<#
CPLAN time-zone check - run this before a refresh when the export has changed.

Lists every time zone the export carries and names any value the database
cannot hold. The source column is a lookup into a list the organisation
maintains, so its values are display names ("Hong Kong, China, Taiwan Time -
GMT+8:00"), and `activities.time_zone` is a fixed-width column: one value
longer than it ends the daily refresh on the INSERT, before a single row is
written. Every activity then still reads as missing a time zone, which looks
like a mapping bug and is not one.

Read-only. Touches nothing but the CSVs it reads.

Usage (from the repo root, or just double-click timezones.cmd):
  .\timezones.ps1
  .\timezones.ps1 -Context                       # also: which regions and teams use each zone
  .\timezones.ps1 -InputDir "C:\path\to\Input"   # a folder other than the usual one

-Context answers a different question: the labels are inherited descriptions,
not places anyone typed, so a zone can be picked for its offset or by mistake.
Only its own rows say which -- a bucket whose activities all sit in one region
means what it says, one whose rows sit somewhere else is a mis-pick.

Exit code 0 only when the refresh cannot die on this field.
#>
param(
    [switch]$Context,
    [string]$InputDir
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
    $args = @("-m", "pipeline.scripts.check_time_zones")
    if ($InputDir) { $args += @("--input", $InputDir) }
    if ($Context) { $args += "--context" }

    & $python @args
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "Every time zone fits. A refresh will not fail on this field." -ForegroundColor Green
    }
    else {
        # Not thrown: the check did its job, and the report above is the answer.
        # A traceback here would bury it.
        Write-Host "Read the report above before running refresh.cmd." -ForegroundColor Yellow
    }
    exit $code
}
finally {
    Pop-Location
}
