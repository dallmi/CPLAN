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
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Virtualenv not found at $python" -ForegroundColor Red
    Write-Host "Set it up once with:" -ForegroundColor Yellow
    Write-Host "  py -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install -r pipeline\api\requirements.txt"
    Write-Host "  .venv\Scripts\python -m pip install pandas duckdb"
    exit 1
}

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
        Write-Host "Starting studio at http://127.0.0.1:8780/  (Ctrl+C to stop)" -ForegroundColor Green
        Start-Process "http://127.0.0.1:8780/"
        & $python (Join-Path $root "pipeline\scripts\start_cplan.py")
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
