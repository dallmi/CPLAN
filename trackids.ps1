<#
CPLAN tracking-ID check - are the IDs on this list actually in the export?

Takes a list of tracking IDs and says which of them the source activity CSVs
contain. A match is exact; an ID that does not match is reported with the
nearest thing found - the same activity on another channel, the pack it should
have been in, or an ID one character away - because "never created" and
"spelled wrong" lead somewhere completely different.

The list is an .xlsx with a "Tracking ID" column, or a text file with one ID
per line. The workbook may carry columns of its own - a campaign, a note,
whoever asked - and they travel through to the result file, so it can go
straight back to whoever sent the list.

Every run writes a result file. Without -Out that is a workbook under
pipeline\output\reports, named for the day.

Usage (from the repo root, or just double-click trackids.cmd):
  .\trackids.ps1 -Ids ".\ids.xlsx"
  .\trackids.ps1 -Ids ".\ids.xlsx" -Sheet "Q4"     # a sheet other than the first
  .\trackids.ps1 -Ids ".\ids.xlsx" -Open           # open the result when it is done
  .\trackids.ps1 -Ids ".\ids.txt" -All             # also list the ones that were found
  .\trackids.ps1 -Ids ".\ids.txt" -Out ".\result.csv"   # .xlsx or .csv, you pick
  .\trackids.ps1 -Ids ".\ids.txt" -InputDir "C:\path\to\Input"

Exit code 0 only when every listed ID was found.
#>
param(
    [Parameter(Mandatory = $true)][string]$Ids,
    [string]$InputDir,
    [string]$Sheet,
    [string]$Out,
    [string]$Csv,
    [switch]$All,
    [switch]$Open
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
if ($Out) { $outPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Out)) }
if ($Csv) { $csvPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Csv)) }

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("-m", "pipeline.scripts.check_tracking_ids", "--ids", $idsPath)
    if ($InputDir) { $args += @("--input", $InputDir) }
    if ($Sheet) { $args += @("--sheet", $Sheet) }
    if ($outPath) { $args += @("--out", $outPath) }
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

    # The check prints the path it wrote; find it again the same way it names
    # it, so -Open works with and without an explicit -Out. Unlike report.ps1
    # this is opt-in: the answer is already on screen above, and a check run
    # three times in a row should not open Excel three times.
    if ($Open) {
        $written = if ($outPath) { $outPath }
                   elseif ($csvPath) { $csvPath }
                   else {
                       Get-ChildItem (Join-Path $root "pipeline\output\reports") `
                           -Filter "CPLAN_trackids_*.xlsx" -ErrorAction SilentlyContinue |
                           Sort-Object LastWriteTime -Descending |
                           Select-Object -First 1 -ExpandProperty FullName
                   }
        if ($written -and (Test-Path $written)) { Invoke-Item $written }
    }
    exit $code
}
finally {
    Pop-Location
}
