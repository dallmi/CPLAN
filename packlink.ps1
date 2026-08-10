<#
CPLAN pack-link check - which activity column actually links to the pack list?

Three activity columns could carry the pack's identifier -- communication_
pack_cpid, campaign_ltid, and the tracking_pack_id split out of the tracking
ID -- and the exports do not say which one the pack list answers to. Choosing
by reasoning would put an unverified assumption under 07-packs.csv, where a
wrong join does not look wrong: it looks like a pack file with plausible
numbers in it.

So it is measured. This reads the same exports a refresh reads, read-only, and
reports which columns of the pack export the ETL does not map, and how each
candidate column scores against the pack list.

Read-only. Touches nothing but the CSVs it reads, and the -Csv file if asked.

Usage (from the repo root, or just double-click packlink.cmd):
  .\packlink.ps1
  .\packlink.ps1 -InputDir "C:\path\to\Input"
  .\packlink.ps1 -Csv ".\result.csv"

Exit code 0 only when exactly one candidate matches at least 80% of the
activities that carry any pack reference at all.
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
    $args = @("-m", "pipeline.scripts.check_pack_link")
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
