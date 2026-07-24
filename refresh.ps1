<#
CPLAN daily refresh - one command for the whole load:
  SharePoint CSVs (already synced into OneDrive by Power Automate)
    -> process_cplan  (CSV -> parquet)
    -> sync_snapshot  (parquet -> PostgreSQL)
  and then, unless -NoStudio, start the studio and open it in the browser.

Usage (from the repo root, or just double-click refresh.cmd):
  .\refresh.ps1              # full refresh + start studio
  .\refresh.ps1 -SyncOnly    # skip the CSV step, only re-sync the existing parquet
  .\refresh.ps1 -NoStudio    # refresh only, don't start the server
#>
param(
    [switch]$SyncOnly,
    [switch]$NoStudio
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
# Resolve the Python interpreter: CPLAN_PYTHON override, then an active venv,
# then a repo-local .venv. Set CPLAN_PYTHON once (setx) to use a venv you set
# up elsewhere, without moving it into the repo.
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
    Write-Host "  .venv\Scripts\python -m pip install -r pipeline\api\requirements.txt"
    Write-Host "  .venv\Scripts\python -m pip install pandas duckdb"
    exit 1
}
Write-Host "Using Python: $python" -ForegroundColor DarkGray

Push-Location $root
$env:PYTHONPATH = "."
try {
    $args = @("-m", "pipeline.scripts.daily_refresh")
    if ($SyncOnly) { $args += "--skip-pipeline" }

    Write-Host "== CPLAN refresh: CSV -> parquet -> PostgreSQL ==" -ForegroundColor Cyan
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "daily_refresh failed (exit code $LASTEXITCODE)" }
    Write-Host "`nRefresh complete." -ForegroundColor Green

    if (-not $NoStudio) {
        # Poll until the server answers so the browser never opens onto a
        # connection-refused page; any HTTP response proves it is up.
        function Wait-ForUrl([string]$url, [int]$timeoutSeconds) {
            $ProgressPreference = "SilentlyContinue"
            $deadline = (Get-Date).AddSeconds($timeoutSeconds)
            while ((Get-Date) -lt $deadline) {
                try {
                    Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 | Out-Null
                    return $true
                }
                catch {
                    if ($_.Exception.Response) { return $true }
                    Write-Host "." -NoNewline
                    Start-Sleep -Seconds 2
                }
            }
            return $false
        }
        Write-Host "Starting studio  -> http://127.0.0.1:8780/  (own window; stop via stop.cmd)" -ForegroundColor Green
        Start-Process -FilePath $python -ArgumentList "pipeline\scripts\start_cplan.py" -WorkingDirectory $root
        Write-Host "Waiting for the server to come up" -NoNewline
        if (Wait-ForUrl "http://127.0.0.1:8780/" 420) {
            Write-Host " ready." -ForegroundColor Green
            Start-Process "http://127.0.0.1:8780/"
        }
        else {
            Write-Host ""
            Write-Host "The server did not answer within 7 minutes - check the server window, then" -ForegroundColor Red
            Write-Host "open http://127.0.0.1:8780/ manually once it shows 'Uvicorn running'." -ForegroundColor Red
        }
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    Write-Host "If it says 'No input files found', the Power Automate export hasn't landed in" -ForegroundColor Yellow
    Write-Host "OneDrive yet, or the files are still cloud-only placeholders (right-click the" -ForegroundColor Yellow
    Write-Host "Input folder -> 'Always keep on this device')." -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
