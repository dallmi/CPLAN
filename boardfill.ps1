<#
CPLAN board fill check - does each board panel have something to draw?

The pack tests prove every board citation resolves: the line it names exists.
This asks the next question, which seed data can never answer: does it resolve
to a figure worth a chart. A panel citing a line that reads 0 for every
division passes that test and still reaches the reader as four empty bars.

A measure that is zero everywhere has four causes, and they need four
different people to do four different things:

  carried, and genuinely zero  -> good news. Say it in words, do not plot it.
  carried, never filled        -> a source-data gap. Chase the owners.
  not carried by the export    -> not a finding. The board must not imply the
                                  plan is empty when only the column is.
  pack older than the board    -> rebuild the pack.

Only the third is invisible in the breakdown file, because a column the export
never had and a column nobody fills produce the same zero there. So this reads
the field-completeness table too and crosses them.

Read-only. Touches nothing but the pack files it reads, and the -Csv if asked.

Reads the pack the agent actually reads: the mirrored upload set first, then
the folder the build writes to, and the folder inside the checkout last. That
order matters -- the checkout folder still holds whatever the last local build
left there, and a months-old pack parses exactly like today's, so a report
against it looks entirely healthy while describing nothing anybody uses.

The mirror is found the same way agentpack.ps1 finds it. Where it sits
somewhere this cannot guess, name it once with the variable that command
already uses:

  setx CPLAN_AGENT_DIR "<the folder holding 01-summary.txt>"

then open a NEW window. The header of every run says which folder was read.

Usage (from the repo root, or just double-click boardfill.cmd):
  .\boardfill.ps1
  .\boardfill.ps1 -Pack "C:\path\to\pack"
  .\boardfill.ps1 -Csv ".\board-fill.csv"

Exit code 0 only when every panel of every board has a figure to draw.
#>
param(
    [string]$Pack,
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
# meant by it - the folder they typed it in, not the repository root.
if ($Csv) { $csvPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Csv)) }
if ($Pack) { $packPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Pack)) }

Push-Location $root
$env:PYTHONPATH = "."
try {
    $pyArgs = @("-m", "pipeline.scripts.check_board_fill")
    if ($packPath) { $pyArgs += @("--pack", $packPath) }
    if ($csvPath) { $pyArgs += @("--csv", $csvPath) }

    & $python @pyArgs
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "Every board panel has a figure to draw." -ForegroundColor Green
    }
    elseif ($code -eq 2) {
        Write-Host "No pack to read. Build one first (agentpack.cmd), pass -Pack," -ForegroundColor Yellow
        Write-Host "or set CPLAN_AGENT_DIR to the folder the refresh copies the pack into." -ForegroundColor Yellow
    }
    else {
        # Not thrown: the check did its job, and the report above is the
        # answer. A traceback here would bury it.
        Write-Host "Read the report above - each line says which of the four causes it is." -ForegroundColor Yellow
    }
    exit $code
}
finally {
    Pop-Location
}
