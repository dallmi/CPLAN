<#
CPLAN tracking-ID check - are the IDs on this list actually in the export?

Takes a text file of tracking IDs, one per line, and says which of them the
source activity CSVs contain. A match is exact; an ID that does not match is
reported with the nearest thing found - the same activity on another channel,
the pack it should have been in, or an ID one character away - because "never
created" and "spelled wrong" lead somewhere completely different.

Read-only. Touches nothing but the CSVs it reads, and the -Csv file if asked.

Usage (from the repo root, or just double-click trackids.cmd):
  .\trackids.ps1 -Ids ".\ids.txt"
  .\trackids.ps1 -Ids ".\ids.txt" -All            # also list the ones that were found
  .\trackids.ps1 -Ids ".\ids.txt" -Csv ".\result.csv"
  .\trackids.ps1 -Ids ".\ids.txt" -InputDir "C:\path\to\Input"

Exit code 0 only when every listed ID was found.
#>
param(
    [Parameter(Mandatory = $true)][string]$Ids,
    [string]$InputDir,
    [string]$Csv,
    [switch]$All
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
# this, ".\ids.txt" is looked for beside the launcher and reads as a missing
# file, which is the one error message that sends you looking in the wrong place.
$idsPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Ids))
if ($Csv) { $csvPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Csv)) }

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("-m", "pipeline.scripts.check_tracking_ids", "--ids", $idsPath)
    if ($InputDir) { $args += @("--input", $InputDir) }
    if ($csvPath) { $args += @("--csv", $csvPath) }
    if ($All) { $args += "--all" }

    & $python @args
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "Every ID on the list is in the export." -ForegroundColor Green
    }
    else {
        # Not thrown: the check did its job, and the report above is the answer.
        # A traceback here would bury it.
        Write-Host "Read the report above - some IDs were not found." -ForegroundColor Yellow
    }
    exit $code
}
finally {
    Pop-Location
}
