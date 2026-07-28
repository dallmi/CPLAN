<#
CPLAN one-time setup. Idempotent: safe to re-run, it skips whatever is already
in place. Does everything the portal needs:
  1. configure the database backend (if not configured yet)
  2. generate and persist CPLAN_AUTH_SECRET (if not set yet)
  3. create the database schema (tables, indexes, analysis views)
  4. apply roles + RLS and create the first admin user
  5. apply the portal schema and user-management functions

Reads optional cplan.config (key=value) in the repo root:
  PYTHON=C:\path\to\python.exe      interpreter (else CPLAN_PYTHON / active venv / .venv)
  ADMIN_USER=a.admin                first admin login name
  BACKEND=postgres-embedded         postgres-embedded | postgresql | sqlite

On first run it writes cplan.config from your current environment, so later
runs are fully config-driven. The only thing you type is the admin password.

Usage (or double-click setup.cmd):
  .\setup.ps1
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# ---- read cplan.config ----------------------------------------------------
$config = @{}
$configPath = Join-Path $root "cplan.config"
if (Test-Path $configPath) {
    foreach ($line in Get-Content $configPath) {
        $t = $line.Trim()
        if ($t -and -not $t.StartsWith("#") -and $t.Contains("=")) {
            $i = $t.IndexOf("=")
            $config[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
        }
    }
}

# ---- resolve interpreter: config PYTHON -> CPLAN_PYTHON -> active venv -> .venv
function Resolve-Python {
    if ($config.ContainsKey("PYTHON") -and $config["PYTHON"] -and (Test-Path $config["PYTHON"])) { return $config["PYTHON"] }
    if ($env:CPLAN_PYTHON -and (Test-Path $env:CPLAN_PYTHON)) { return $env:CPLAN_PYTHON }
    if ($env:VIRTUAL_ENV) { $p = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"; if (Test-Path $p) { return $p } }
    $p = Join-Path $root ".venv\Scripts\python.exe"; if (Test-Path $p) { return $p }
    return $null
}
$python = Resolve-Python
if (-not $python) {
    Write-Host "No Python environment found." -ForegroundColor Red
    Write-Host "Set PYTHON in cplan.config, or set CPLAN_PYTHON, then re-run. Example:" -ForegroundColor Yellow
    Write-Host '  setx CPLAN_PYTHON "C:\path\to\your\venv\Scripts\python.exe"'
    exit 1
}
Write-Host "Using Python: $python" -ForegroundColor DarkGray

$adminUser = if ($config.ContainsKey("ADMIN_USER") -and $config["ADMIN_USER"]) { $config["ADMIN_USER"] } else { "a.admin" }
$backend   = if ($config.ContainsKey("BACKEND")   -and $config["BACKEND"])   { $config["BACKEND"]   } else { "postgres-embedded" }

# ---- write cplan.config on first run so future runs are config-driven -----
if (-not (Test-Path $configPath)) {
    @(
        "# CPLAN local setup configuration (gitignored). Edit and re-run setup.cmd.",
        "PYTHON=$python",
        "ADMIN_USER=$adminUser",
        "BACKEND=$backend"
    ) | Set-Content -Path $configPath -Encoding ASCII
    Write-Host "Wrote cplan.config - edit it later to change these values." -ForegroundColor DarkGray
}

Push-Location $root
$env:PYTHONPATH = "."
try {
    # Keep the double-click launchers on the same interpreter.
    setx CPLAN_PYTHON "$python" | Out-Null

    # 1) backend ------------------------------------------------------------
    $cplanHome = if ($env:CPLAN_HOME) { $env:CPLAN_HOME } else { Join-Path $root "pipeline\data" }
    $settingsFile = Join-Path $cplanHome "cplan-settings.json"
    if (Test-Path $settingsFile) {
        Write-Host "[1/5] Backend already configured ($backend)." -ForegroundColor Green
    }
    else {
        Write-Host "[1/5] Configuring backend: $backend" -ForegroundColor Cyan
        & $python -m pipeline.api.setup_backend --backend $backend
        if ($LASTEXITCODE -ne 0) { throw "setup_backend failed (exit $LASTEXITCODE)" }
    }

    # 2) auth secret --------------------------------------------------------
    if (-not [string]::IsNullOrEmpty($env:CPLAN_AUTH_SECRET)) {
        Write-Host "[2/5] Auth secret already set - keeping it." -ForegroundColor Green
    }
    else {
        Write-Host "[2/5] Generating and persisting CPLAN_AUTH_SECRET" -ForegroundColor Cyan
        $secret = (& $python -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
        if (-not $secret) { throw "secret generation returned empty output" }
        setx CPLAN_AUTH_SECRET "$secret" | Out-Null
        $env:CPLAN_AUTH_SECRET = $secret
        Write-Host "      Secret set (takes effect in new windows)." -ForegroundColor DarkGray
    }

    # 3) schema --------------------------------------------------------------
    # Must run before setup_roles: apply_roles hardens activities.created_by with
    # ALTER TABLE, which fails with "relation activities does not exist" on a
    # database nothing has created the schema in yet. Idempotent on an existing one.
    Write-Host "[3/5] Creating the database schema (first run can take a minute)" -ForegroundColor Cyan
    & $python -m pipeline.api.ensure_db
    if ($LASTEXITCODE -ne 0) { throw "ensure_db failed (exit $LASTEXITCODE) - 'No module named ...' above means the packages are missing (run check.cmd); otherwise the database is unreachable" }

    # 4) roles + first admin ------------------------------------------------
    Write-Host "[4/5] Applying roles and row-level security" -ForegroundColor Cyan
    & $python -m pipeline.api.setup_roles
    if ($LASTEXITCODE -ne 0) { throw "setup_roles (apply) failed (exit $LASTEXITCODE) - is the database reachable?" }

    Write-Host "      Creating admin '$adminUser' - you will be asked for a password (this is your login):" -ForegroundColor Cyan
    & $python -m pipeline.api.setup_roles --create-user $adminUser --role admin
    if ($LASTEXITCODE -ne 0) {
        Write-Host "      '$adminUser' was not created - it most likely already exists. Skipping." -ForegroundColor Yellow
        Write-Host "      (Manage users later in the portal, or set a different ADMIN_USER in cplan.config.)" -ForegroundColor Yellow
    }

    # 5) portal schema ------------------------------------------------------
    Write-Host "[5/5] Applying portal schema and user-management functions" -ForegroundColor Cyan
    & $python -m pipeline.api.setup_portal
    if ($LASTEXITCODE -ne 0) { throw "setup_portal failed (exit $LASTEXITCODE)" }

    Write-Host "`nSetup complete." -ForegroundColor Green
    Write-Host "Next: close this window, open a NEW one, and double-click start.cmd." -ForegroundColor Green
    Write-Host "Then log in to the portal at http://127.0.0.1:8781/ as '$adminUser'." -ForegroundColor Green
}
catch {
    Write-Host "`nSetup failed: $_" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
