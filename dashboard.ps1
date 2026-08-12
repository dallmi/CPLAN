<#
CPLAN executive boards - one standalone HTML page.

Renders a frozen template in pipeline\dashboard\ from a data file. No model
sits in this path: same data in, byte-identical page out. That is the point of
the freeze, and dashboard.ps1 -Check is what proves it still holds.

Usage (from the repo root, or just double-click dashboard.cmd):
  .\dashboard.ps1                      # the campaign activity board, then open it
  .\dashboard.ps1 -Board leadership-attention
  .\dashboard.ps1 -Data C:\tmp\q4.json # a quarter of your own
  .\dashboard.ps1 -Out C:\tmp\page.html
  .\dashboard.ps1 -NoOpen              # write it, leave it closed
  .\dashboard.ps1 -Check               # compare against the golden file
  .\dashboard.ps1 -Strict              # exit non-zero if the figures do not add up

Boards:
  campaign-activity     the communications portfolio, for a management audience
  leadership-attention  where executive time goes, and where it is missing

The thresholds - planning horizon, lead time, the short-notice limit, the
leadership target - are not switches. They are the organisation's targets, they
change roughly never, and they live in THRESHOLDS at the top of
pipeline\report\dashboard_render.py so that a page can never disagree with the
filter behind it. Until this launcher existed they were prose inside the markup,
which is how a regenerated dashboard came to re-invent them every run.
#>
param(
    [ValidateSet("campaign-activity", "leadership-attention")]
    [string]$Board = "campaign-activity",
    [string]$Data,
    [string]$Out,
    [switch]$NoOpen,
    [switch]$Check,
    [switch]$UpdateGolden,
    [switch]$Strict
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
    exit 1
}
Write-Host "Using Python: $python" -ForegroundColor DarkGray

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("pipeline\scripts\report_dashboard.py", "--board", $Board)
    if ($Data) { $args += @("--data", $Data) }
    if ($Out) { $args += @("--out", $Out) }
    if ($Check) { $args += "--check" }
    if ($UpdateGolden) { $args += "--update-golden" }
    if ($Strict) { $args += "--strict" }

    # The script says where it wrote, so the launcher reads that rather than
    # guessing from a file glob. Each board writes its own name pattern, and a
    # glob would have to learn every one of them to stay right.
    & $python @args 2>&1 | Tee-Object -Variable captured | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw "report_dashboard failed (exit code $LASTEXITCODE)" }

    # -Check and -UpdateGolden write nothing the user wants opened.
    if (-not $NoOpen -and -not $Check -and -not $UpdateGolden) {
        $written = $captured |
            Where-Object { $_ -match '^Wrote (.+)$' } |
            ForEach-Object { $Matches[1] } |
            Select-Object -Last 1
        if ($written -and (Test-Path $written)) {
            Write-Host "Opening $written" -ForegroundColor Green
            Start-Process $written
        }
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    Write-Host "If it says 'differs from <board>.golden.html', the template, the" -ForegroundColor Yellow
    Write-Host "renderer or the sample data changed the page. That is meant to be a" -ForegroundColor Yellow
    Write-Host "deliberate act: check the diff, then rerun with -UpdateGolden and commit" -ForegroundColor Yellow
    Write-Host "the new golden file alongside the change that caused it." -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
