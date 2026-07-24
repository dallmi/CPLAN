<#
Start CPLAN for daily work: launches the studio (port 8780) and - if
CPLAN_AUTH_SECRET is set - the portal (port 8781), each in its own window,
then opens the browser. Data loading is separate (refresh.cmd).

  studio  http://127.0.0.1:8780/   activities, planning, analytics
  portal  http://127.0.0.1:8781/   login, project tiles, user administration

The two are separate servers sharing one database and one login cookie; the
portal's CPLAN tile links to the studio, so both must run for the link to work.

Usage (or double-click start.cmd):
  .\start.ps1                # studio + portal (portal only if the secret is set)
  .\start.ps1 -StudioOnly    # studio only
#>
param([switch]$StudioOnly)

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

# Poll a URL until the server actually answers, so the browser never opens
# onto a connection-refused page while the database is still starting.
# Any HTTP response (including 401/404) proves the server is up.
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
    Write-Host "Starting studio  -> http://127.0.0.1:8780/" -ForegroundColor Green
    Start-Process -FilePath $python -ArgumentList "pipeline\scripts\start_cplan.py" -WorkingDirectory $root

    $hasSecret = -not [string]::IsNullOrEmpty($env:CPLAN_AUTH_SECRET)
    $openUrl = "http://127.0.0.1:8780/"
    if (-not $StudioOnly -and $hasSecret) {
        Write-Host "Starting portal  -> http://127.0.0.1:8781/" -ForegroundColor Green
        Start-Process -FilePath $python -ArgumentList "pipeline\scripts\start_portal.py" -WorkingDirectory $root
        $openUrl = "http://127.0.0.1:8781/"
    }
    elseif (-not $hasSecret) {
        Write-Host "CPLAN_AUTH_SECRET not set -> studio only (solo mode, no login/portal)." -ForegroundColor Yellow
        Write-Host 'Enable the portal once with: setx CPLAN_AUTH_SECRET (python -c "import secrets;print(secrets.token_urlsafe(48))")  then open a NEW window.' -ForegroundColor Yellow
    }

    Write-Host "Waiting for the server to come up (after an unclean shutdown the database can need a few minutes)" -NoNewline
    if (Wait-ForUrl $openUrl 420) {
        Write-Host " ready." -ForegroundColor Green
        Start-Process $openUrl
    }
    else {
        Write-Host ""
        Write-Host "The server did not answer within 7 minutes - check the server window for errors," -ForegroundColor Red
        Write-Host "then open $openUrl manually once it shows 'Uvicorn running'." -ForegroundColor Red
    }
}
finally {
    Pop-Location
}

Write-Host "`nServers run in their own windows. Stop them with stop.cmd (or Ctrl+C in their windows)." -ForegroundColor Cyan
