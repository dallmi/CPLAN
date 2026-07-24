<#
Start the CPLAN portal (landing page + browser-based user administration) at
http://127.0.0.1:8781/ and open it in the browser. Separate long-running server
from the studio (start_cplan.py / refresh.cmd, port 8780).

The portal REQUIRES authentication: it refuses to start unless CPLAN_AUTH_SECRET
is set and the backend is PostgreSQL. Set the secret once, persistently:
  setx CPLAN_AUTH_SECRET (python -c "import secrets;print(secrets.token_urlsafe(48))")
then open a NEW shell (setx only affects new processes).

Usage (or just double-click portal.cmd):
  .\portal.ps1
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Virtualenv not found at $python" -ForegroundColor Red
    Write-Host "Set it up once with:" -ForegroundColor Yellow
    Write-Host "  py -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install -r pipeline\api\requirements.txt"
    exit 1
}

if ([string]::IsNullOrEmpty($env:CPLAN_AUTH_SECRET)) {
    Write-Host "CPLAN_AUTH_SECRET is not set — the portal will refuse to start." -ForegroundColor Red
    Write-Host "Set it once (then open a NEW window so it takes effect):" -ForegroundColor Yellow
    Write-Host '  setx CPLAN_AUTH_SECRET (python -c "import secrets;print(secrets.token_urlsafe(48))")'
    exit 1
}

Push-Location $root
$env:PYTHONPATH = "."
try {
    Write-Host "Starting portal at http://127.0.0.1:8781/  (Ctrl+C to stop)" -ForegroundColor Green
    Start-Process "http://127.0.0.1:8781/"
    & $python (Join-Path $root "pipeline\scripts\start_portal.py")
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    Write-Host "First run only: apply roles and the portal schema, and create the first admin:" -ForegroundColor Yellow
    Write-Host "  .venv\Scripts\python -m pipeline.api.setup_roles --create-user a.admin --role admin"
    Write-Host "  .venv\Scripts\python -m pipeline.api.setup_portal"
    exit 1
}
finally {
    Pop-Location
}
