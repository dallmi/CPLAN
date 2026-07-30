<#
Cleanly stop CPLAN: first the two servers (studio 8780, portal 8781), then the
embedded database (pg_ctl -m fast). Run this when you are done for the day: a
clean stop means the next start needs no crash recovery.

Closing a server window is not enough - the python.exe inside it often survives
and keeps holding its port. The next start.cmd then dies with
"[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8780)",
and because uvicorn runs the app's startup BEFORE it binds the socket, that
window even prints "Application startup complete." first. This script closes
that gap, so start.ps1's promise ("stop them with stop.cmd") actually holds.

Usage (or double-click stop.cmd):
  .\stop.ps1
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Same interpreter resolution as the other launchers.
$config = @{}
$configPath = Join-Path $root "cplan.config"
if (Test-Path $configPath) {
    foreach ($line in Get-Content $configPath) {
        $t = $line.Trim()
        if ($t -and -not $t.StartsWith("#") -and $t.Contains("=")) {
            $i = $t.IndexOf("="); $config[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
        }
    }
}
function Resolve-Python {
    if ($config.ContainsKey("PYTHON") -and $config["PYTHON"] -and (Test-Path $config["PYTHON"])) { return $config["PYTHON"] }
    if ($env:CPLAN_PYTHON -and (Test-Path $env:CPLAN_PYTHON)) { return $env:CPLAN_PYTHON }
    if ($env:VIRTUAL_ENV) { $p = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"; if (Test-Path $p) { return $p } }
    $p = Join-Path $root ".venv\Scripts\python.exe"; if (Test-Path $p) { return $p }
    return $null
}
$python = Resolve-Python
if (-not $python) { Write-Host "No Python environment found (set PYTHON in cplan.config or CPLAN_PYTHON)." -ForegroundColor Red; exit 1 }

# The ports the two servers listen on. Kept in sync with start.ps1 and the
# --port defaults in pipeline\scripts\start_cplan.py / start_portal.py.
$serverPorts = @(
    @{ Port = 8780; Label = "studio" },
    @{ Port = 8781; Label = "portal" }
)

# Which process is listening on a port. Get-NetTCPConnection is the clean route;
# it throws when nothing listens there, which is the normal case, so an empty
# list is a perfectly good answer. netstat covers hosts without the NetTCPIP
# module. Needs no admin rights either way.
function Get-ListenerProcessIds([int]$port) {
    try {
        return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    catch [System.Management.Automation.CommandNotFoundException] {
        # A listener is the row whose foreign address is 0.0.0.0:0. Matching that
        # rather than the word "LISTENING" keeps this working on a non-English
        # Windows, where netstat translates the state column.
        $pattern = "\s127\.0\.0\.1:{0}\s+0\.0\.0\.0:0\s+\S+\s+(\d+)\s*$" -f $port
        return @(netstat -ano -p TCP |
            Select-String -Pattern $pattern |
            ForEach-Object { [int]$_.Matches[0].Groups[1].Value } |
            Select-Object -Unique)
    }
    catch { return @() }
}

# Stop OUR server on a port - a python.exe running one of the two launcher
# scripts. Anything else holding the port belongs to someone else (another dev
# tool, a proxy): name it and leave it alone rather than killing blind. Same
# scoping idea as fix-db.ps1 uses for orphaned postgres.exe.
function Stop-CplanServerOnPort([int]$port, [string]$label) {
    $found = $false
    foreach ($processId in (Get-ListenerProcessIds $port)) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        $found = $true
        if ($proc.CommandLine -match "start_cplan\.py|start_portal\.py") {
            Write-Host ("  {0,-6} port {1}: stopping PID {2}" -f $label, $port, $processId) -ForegroundColor Cyan
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        else {
            Write-Host ("  {0,-6} port {1}: held by {2} (PID {3}) - not a CPLAN server, left running" -f $label, $port, $proc.Name, $processId) -ForegroundColor Yellow
        }
    }
    if (-not $found) {
        Write-Host ("  {0,-6} port {1}: nothing listening" -f $label, $port) -ForegroundColor DarkGray
    }
}

Push-Location $root
$env:PYTHONPATH = "."
try {
    # Servers first: they hold open database connections, so stopping them
    # before the database is what makes the -m fast shutdown quick and clean.
    Write-Host "Stopping the CPLAN servers..." -ForegroundColor Cyan
    foreach ($server in $serverPorts) { Stop-CplanServerOnPort $server.Port $server.Label }
    Start-Sleep -Seconds 1  # let the sockets actually close before the database goes

    Write-Host "Stopping the embedded CPLAN database cleanly..." -ForegroundColor Cyan
    & $python -m pipeline.scripts.cplan_db --stop

    Write-Host "`nCPLAN is stopped. Any leftover empty PowerShell windows are just the" -ForegroundColor Green
    Write-Host "host windows of the stopped servers - close them with the X." -ForegroundColor Green
}
finally {
    Pop-Location
}
