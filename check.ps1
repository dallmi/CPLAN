<#
CPLAN preflight check for hand-copied files (no git pull available on corp).

Verifies that every critical file is present AND is the current version (each
file is identified by a marker string that only exists in its latest state),
purges stale Python bytecode caches, and proves that the Python interpreter
actually loads the new code. Prints a download URL for every outdated file.

Read-only apart from the __pycache__ cleanup. Safe to run any time.

Usage (or double-click check.cmd):
  .\check.ps1
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$rawBase = "https://raw.githubusercontent.com/dallmi/CPLAN/feature/cplan-v6-postgres"

# file (repo-relative) = marker string that only the CURRENT version contains.
# Maintained together with the code: when a listed file changes upstream, its
# marker here is updated in the same commit.
$manifest = @(
    @{ Path = "pipeline\api\database.py";      Marker = "_CREATE_NO_WINDOW";                 Why = "detached DB start, cache eviction, readiness probe" },
    @{ Path = "pipeline\api\database.py";      Marker = "_evict_cached_server_instance";     Why = "retry-poisoning fix" },
    @{ Path = "fix-db.ps1";                    Marker = "Win32_Process";                     Why = "orphaned postgres.exe killer" },
    @{ Path = "pipeline\api\setup_roles.py";   Marker = "DROP VIEW IF EXISTS v_change_log";  Why = "view-dependency fix for actor column" },
    @{ Path = "pipeline\api\ensure_db.py";     Marker = "def ensure_database";               Why = "schema creation before setup_roles - without it a first setup dies on 'relation activities does not exist'" },
    @{ Path = "pipeline\api\views.py";         Marker = "missing_business_division";         Why = "v_planning_completeness realigned to the unified variant-aware rule" },
    @{ Path = "pipeline\api\session.py";       Marker = "build_session_dependencies";        Why = "shared SET ROLE session module" },
    @{ Path = "pipeline\api\setup_portal.py";  Marker = "not accounts";                      Why = "disable guards + user list hides group roles" },
    @{ Path = "pipeline\portal\app.py";        Marker = "Refusing to start";                 Why = "portal fails closed without auth" },
    @{ Path = "pipeline\portal\static\app.js"; Marker = 'target="_blank"';                    Why = "tiles open in a new tab; server messages on row actions" },
    @{ Path = "pipeline\portal\static\index.html"; Marker = 'rel="icon"';                     Why = "portal landing page incl. favicon" },
    @{ Path = "pipeline\portal\static\styles.css"; Marker = "kit-pass";                      Why = "portal styling incl. sentence-case table headers" },
    @{ Path = "pipeline\studio\app.js";        Marker = "issueLabel";                       Why = "Issue column, queue context bar and drawer jump bar" },
    @{ Path = "pipeline\studio\styles.css";    Marker = "issue-chip";                       Why = "issue chips, queue bar, jump bar and the field pulse" },
    @{ Path = "pipeline\studio\index.html";    Marker = "activity-queue-bar";               Why = "queue context bar, drawer jump bar and the Issue column header" },
    @{ Path = "pipeline\studio\analytics.js";  Marker = "rowIssues";                        Why = "the issue rule app.js reads (A.rowIssues) - an old analytics.js breaks the Issue column and the drawer outright" },
    @{ Path = "pipeline\scripts\cplan_db.py";  Marker = "def stop";                          Why = "clean database stop" },
    @{ Path = "pipeline\scripts\start_portal.py"; Marker = "DEFAULT_PORT";                   Why = "portal launcher" },
    @{ Path = "setup.ps1";                     Marker = "pipeline.api.ensure_db";            Why = "config-driven one-time setup incl. the schema step before setup_roles" },
    @{ Path = "start.ps1";                     Marker = "Start-CplanServer";                 Why = "server windows stay open on a crash, so the traceback is readable" },
    @{ Path = "stop.ps1";                      Marker = "CPLAN_PYTHON";                      Why = "clean shutdown launcher" },
    @{ Path = "refresh.ps1";                   Marker = "-NoExit";                           Why = "daily refresh; studio window stays open on a crash" },
    @{ Path = "portal.ps1";                    Marker = "Start-CplanServer";                 Why = "portal launcher; server window stays open on a crash" }
)

Write-Host ""
Write-Host "=== CPLAN file check ===" -ForegroundColor Cyan
$stale = @()
$missingPackages = ""
$checkedPaths = @{}
foreach ($entry in $manifest) {
    $full = Join-Path $root $entry.Path
    $label = $entry.Path
    if (-not (Test-Path $full)) {
        if (-not $checkedPaths.ContainsKey($entry.Path)) {
            Write-Host ("  MISSING  {0}" -f $label) -ForegroundColor Red
            $stale += $entry.Path
            $checkedPaths[$entry.Path] = $true
        }
        continue
    }
    $hit = Select-String -Path $full -Pattern ([regex]::Escape($entry.Marker)) -Quiet
    if ($hit) {
        if (-not $checkedPaths.ContainsKey($entry.Path)) {
            Write-Host ("  OK       {0}" -f $label) -ForegroundColor Green
        }
    }
    else {
        Write-Host ("  STALE    {0}  (missing marker: {1} - {2})" -f $label, $entry.Marker, $entry.Why) -ForegroundColor Red
        if ($stale -notcontains $entry.Path) { $stale += $entry.Path }
    }
    $checkedPaths[$entry.Path] = $true
}

Write-Host ""
Write-Host "=== Python bytecode cache ===" -ForegroundColor Cyan
$caches = Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "*\.venv\*" }
if ($caches) {
    $caches | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ("  purged {0} __pycache__ folder(s) - stale bytecode cannot shadow the new files" -f $caches.Count) -ForegroundColor Green
}
else {
    Write-Host "  no __pycache__ folders found - nothing to purge" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Interpreter and environment ===" -ForegroundColor Cyan
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
$python = $null
if ($config.ContainsKey("PYTHON") -and $config["PYTHON"] -and (Test-Path $config["PYTHON"])) { $python = $config["PYTHON"] }
elseif ($env:CPLAN_PYTHON -and (Test-Path $env:CPLAN_PYTHON)) { $python = $env:CPLAN_PYTHON }
elseif ($env:VIRTUAL_ENV -and (Test-Path (Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"))) { $python = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe" }
elseif (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) { $python = Join-Path $root ".venv\Scripts\python.exe" }

if ($python) {
    Write-Host ("  OK       interpreter: {0}" -f $python) -ForegroundColor Green
    Push-Location $root
    $env:PYTHONPATH = "."
    try {
        $probe = & $python -c "import pipeline.api.database as d; print('NEW' if hasattr(d, '_CREATE_NO_WINDOW') else 'OLD')" 2>&1
        if ("$probe".Trim() -eq "NEW") {
            Write-Host "  OK       Python loads the CURRENT database code (not stale bytecode)" -ForegroundColor Green
        }
        elseif ("$probe".Trim() -eq "OLD") {
            Write-Host "  STALE    Python imports an OLD pipeline.api.database - wrong directory or stale copy elsewhere" -ForegroundColor Red
            $stale += "pipeline\api\database.py"
        }
        else {
            Write-Host ("  WARN     import check failed: {0}" -f "$probe".Trim()) -ForegroundColor Yellow
        }
        # Every runtime import in pipeline/api/requirements.txt, probed in one
        # call. A missing package is as blocking as a stale file: setup.cmd's
        # schema step imports fastapi (via pipeline.api.app) and start.cmd needs
        # uvicorn, so reporting "all files current" without this check sends the
        # user straight into "No module named fastapi".
        $probeDeps = "import importlib.util as u; " +
            "mods=['fastapi','uvicorn','sqlalchemy','psycopg','pyarrow','pgserver','psutil','itsdangerous']; " +
            "print(','.join(m for m in mods if u.find_spec(m) is None))"
        $probeOut = & $python -c $probeDeps 2>&1
        $missing = "$probeOut".Trim()
        if ($missing -eq "") {
            Write-Host "  OK       all required packages installed (fastapi, uvicorn, sqlalchemy, psycopg, pyarrow, pgserver, psutil, itsdangerous)" -ForegroundColor Green
        }
        else {
            Write-Host ("  MISSING  packages: {0}" -f $missing) -ForegroundColor Red
            Write-Host  "           install them into THIS interpreter, then re-run check.cmd:" -ForegroundColor Yellow
            Write-Host ('             "{0}" -m pip install -r pipeline\api\requirements.txt' -f $python) -ForegroundColor Yellow
            $missingPackages = $missing
        }
    }
    finally { Pop-Location }
}
else {
    Write-Host "  WARN     no Python interpreter found (set PYTHON in cplan.config or CPLAN_PYTHON)" -ForegroundColor Yellow
}
if ([string]::IsNullOrEmpty($env:CPLAN_AUTH_SECRET)) {
    Write-Host "  INFO     CPLAN_AUTH_SECRET not set in THIS window (portal needs it; setup.cmd creates it)" -ForegroundColor Yellow
}
else {
    Write-Host "  OK       CPLAN_AUTH_SECRET is set" -ForegroundColor Green
}

Write-Host ""
if ($stale.Count -eq 0 -and -not $missingPackages) {
    Write-Host "RESULT: all files current. Safe to run fix-db.cmd, then setup.cmd (or start.cmd)." -ForegroundColor Green
}
else {
    if ($stale.Count -gt 0) {
        Write-Host ("RESULT: {0} file(s) outdated or missing. Download them, then run this check again:" -f $stale.Count) -ForegroundColor Red
        foreach ($path in ($stale | Select-Object -Unique)) {
            $url = "$rawBase/" + ($path -replace "\\", "/")
            Write-Host ("  {0}" -f $url) -ForegroundColor Yellow
        }
    }
    if ($missingPackages) {
        Write-Host ("RESULT: missing Python packages ({0}) - setup.cmd and start.cmd cannot run until they are installed (command above)." -f $missingPackages) -ForegroundColor Red
    }
}
