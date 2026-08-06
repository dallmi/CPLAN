<#
CPLAN agent pack - the calendar report in a shape a retrieval agent can read.

Reads the same SharePoint CSV exports from the same OneDrive sync folder as
report.ps1, through the same scope resolution, and writes the same figures as
plain text and CSV instead of as a styled workbook. Run it with the same period
flags as the report and the two are guaranteed to agree; run it with different
ones and they are two different reports that happen to sit side by side.

Usage (from the repo root, or just double-click agentpack.cmd):
  .\agentpack.ps1                       # the period set in CONFIG, then open the folder
  .\agentpack.ps1 -All                  # every dated activity, whatever CONFIG says
  .\agentpack.ps1 -Year 2026            # one calendar year
  .\agentpack.ps1 -From 2026-01-01 -To 2026-06-30
  .\agentpack.ps1 -NoOpen               # write it, leave the folder closed
  .\agentpack.ps1 -Out C:\tmp\pack      # somewhere else
  .\agentpack.ps1 -InputDir C:\tmp\csv  # read from here instead of OneDrive

Three things come out, and only two of them are for uploading:

  pack\             the folder to point a Copilot knowledge source at
  cplan-skill.zip   the same content as a Copilot Studio skill package
  checklist.md      the answer key. Do NOT upload it: an agent that can read
                    the answers passes the test without computing anything.
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
    $args = @("pipeline\scripts\build_agent_pack.py")
    # -Year is [int], so an omitted switch arrives as 0 rather than $null.
    if ($All) { $args += "--all" }
    if ($Year -gt 0) { $args += @("--year", $Year) }
    if ($From) { $args += @("--from", $From) }
    if ($To) { $args += @("--to", $To) }
    if ($Out) { $args += @("--out", $Out) }
    if ($InputDir) { $args += @("--input-dir", $InputDir) }
    if ($GebMembers) { $args += @("--geb-members", $GebMembers) }

    Write-Host "== CPLAN agent pack: CSV -> .txt + .csv ==" -ForegroundColor Cyan
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "build_agent_pack failed (exit code $LASTEXITCODE)" }

    # Open the folder that holds all three artefacts, not the pack subfolder:
    # the skill package and the checklist are the two a reader has to decide
    # about, and neither is visible from inside pack\.
    if (-not $NoOpen) {
        $written = if ($Out) { $Out } else { Join-Path $root "pipeline\output\agent-pack" }
        if (Test-Path $written) {
            Write-Host "Opening $written" -ForegroundColor Green
            Start-Process $written
        }
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    Write-Host "If it says 'no input files found', the Power Automate export hasn't landed in" -ForegroundColor Yellow
    Write-Host "OneDrive yet, or the files are still cloud-only placeholders (right-click the" -ForegroundColor Yellow
    Write-Host "Input folder -> 'Always keep on this device'). You can also point it at a" -ForegroundColor Yellow
    Write-Host "folder of CSVs directly:  .\agentpack.ps1 -InputDir C:\path\to\csv" -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
