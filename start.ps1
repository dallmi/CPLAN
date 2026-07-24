<#
Start CPLAN for daily work: launches the studio (port 8780) and — if
CPLAN_AUTH_SECRET is set — the portal (port 8781), each in its own window,
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
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Virtualenv not found at $python — run the one-time setup first (see README)." -ForegroundColor Red
    exit 1
}

Push-Location $root
$env:PYTHONPATH = "."
try {
    Write-Host "Starting studio  -> http://127.0.0.1:8780/" -ForegroundColor Green
    Start-Process -FilePath $python -ArgumentList "pipeline\scripts\start_cplan.py" -WorkingDirectory $root

    $hasSecret = -not [string]::IsNullOrEmpty($env:CPLAN_AUTH_SECRET)
    if (-not $StudioOnly -and $hasSecret) {
        Write-Host "Starting portal  -> http://127.0.0.1:8781/" -ForegroundColor Green
        Start-Process -FilePath $python -ArgumentList "pipeline\scripts\start_portal.py" -WorkingDirectory $root
        Start-Sleep -Seconds 2
        Start-Process "http://127.0.0.1:8781/"
    }
    else {
        if (-not $hasSecret) {
            Write-Host "CPLAN_AUTH_SECRET not set -> studio only (solo mode, no login/portal)." -ForegroundColor Yellow
            Write-Host 'Enable the portal once with: setx CPLAN_AUTH_SECRET (python -c "import secrets;print(secrets.token_urlsafe(48))")  then open a NEW window.' -ForegroundColor Yellow
        }
        Start-Sleep -Seconds 2
        Start-Process "http://127.0.0.1:8780/"
    }
}
finally {
    Pop-Location
}

Write-Host "`nServers run in their own windows. Close those windows (or Ctrl+C in them) to stop." -ForegroundColor Cyan
