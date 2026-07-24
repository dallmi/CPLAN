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
    exit 1
}
Write-Host "Using Python: $python" -ForegroundColor DarkGray

if ([string]::IsNullOrEmpty($env:CPLAN_AUTH_SECRET)) {
    Write-Host "CPLAN_AUTH_SECRET is not set - the portal will refuse to start." -ForegroundColor Red
    Write-Host "Set it once (then open a NEW window so it takes effect):" -ForegroundColor Yellow
    Write-Host '  setx CPLAN_AUTH_SECRET (python -c "import secrets;print(secrets.token_urlsafe(48))")'
    exit 1
}

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

Push-Location $root
$env:PYTHONPATH = "."
try {
    Write-Host "Starting portal  -> http://127.0.0.1:8781/  (own window; stop via stop.cmd)" -ForegroundColor Green
    Start-Process -FilePath $python -ArgumentList "pipeline\scripts\start_portal.py" -WorkingDirectory $root
    Write-Host "Waiting for the server to come up" -NoNewline
    if (Wait-ForUrl "http://127.0.0.1:8781/" 420) {
        Write-Host " ready." -ForegroundColor Green
        Start-Process "http://127.0.0.1:8781/"
    }
    else {
        Write-Host ""
        Write-Host "The server did not answer within 7 minutes - check the server window, then" -ForegroundColor Red
        Write-Host "open http://127.0.0.1:8781/ manually once it shows 'Uvicorn running'." -ForegroundColor Red
    }
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
