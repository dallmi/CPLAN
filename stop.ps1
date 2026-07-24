<#
Cleanly stop the embedded CPLAN database (pg_ctl -m fast). Run this when you are
done for the day: a clean stop means the next start needs no crash recovery.

First close the studio/portal windows (Ctrl+C or the X), then run this.

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

Push-Location $root
$env:PYTHONPATH = "."
try {
    Write-Host "Stopping the embedded CPLAN database cleanly..." -ForegroundColor Cyan
    & $python -m pipeline.scripts.cplan_db --stop
}
finally {
    Pop-Location
}
