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
    # The failed-sign-in throttle. These files ship together or not at all: the
    # portal and the studio import login_guard, login_guard needs the counters
    # setup_portal creates, and both need auth.py's three-way credential probe.
    # A machine that received some of them and not the others must be reported
    # as stale, not as "all files current" -- that half-copied state is a
    # portal that starts, serves its landing page, and then answers every
    # sign-in with an error.
    @{ Path = "pipeline\api\login_guard.py";   Marker = "MISSING_GUARD_MESSAGE";             Why = "the shared login rate limit - a NEW file; without it neither server starts" },
    @{ Path = "pipeline\api\auth.py";          Marker = "CredentialCheck";                   Why = "a database that could not answer is not counted as a password guess" },
    @{ Path = "pipeline\api\setup_portal.py";  Marker = "begin_login_attempt";               Why = "the login counters + --clear-login-block; re-run setup.cmd after copying this one" },
    @{ Path = "pipeline\api\app.py";           Marker = "too_many_attempts";                 Why = "the studio's login shares the portal's limit - otherwise it is bypassed by changing the port" },
    @{ Path = "pipeline\portal\app.py";        Marker = "too_many_attempts";                 Why = "the portal's login is throttled" },
    @{ Path = "pipeline\scripts\start_cplan.py";  Marker = "proxy_headers";                  Why = "studio refuses to start without the throttle, and never trusts X-Forwarded-For" },
    @{ Path = "pipeline\scripts\start_portal.py"; Marker = "proxy_headers";                  Why = "portal refuses to start without the throttle, and never trusts X-Forwarded-For" },
    # Passwords are hashed before they reach a SQL statement, so that the
    # cleartext can never be written to the server log. These four ship
    # together, and each half-copied combination breaks something different:
    #   - scram.py missing: setup_roles and the portal both import it at module
    #     scope, so setup.cmd's role step and start.cmd both die with
    #     ModuleNotFoundError - and setup.ps1 reports that as "is the database
    #     reachable?", which sends the operator to the wrong place entirely.
    #   - new setup_portal.py, old portal\app.py: the portal starts and serves
    #     normally, but its create_user/reset_password calls still send
    #     cleartext, which the new functions refuse - so every Invite and every
    #     Reset password answers 422 forever, an admin can create no accounts,
    #     and a locked-out user cannot be given a new password.
    #   - new portal\app.py, old setup_portal.py: the old functions take the
    #     verifier for a password and hash it again, and the account is created
    #     with a password nobody knows, silently and with no error anywhere.
    # None of that is visible from the outside, so it must be caught here.
    @{ Path = "pipeline\api\scram.py";         Marker = "def verifier_for";                  Why = "the SCRAM verifier builder - a NEW file; without it neither setup_roles nor the portal can even be imported" },
    @{ Path = "pipeline\api\setup_portal.py";  Marker = "p_verifier";                        Why = "create_user/reset_password refuse cleartext; re-run setup.cmd after copying this one" },
    @{ Path = "pipeline\portal\app.py";        Marker = "verifier_for";                      Why = "the portal hashes before it sends - an older copy sends cleartext and every Invite/Reset answers 422" },
    @{ Path = "pipeline\api\setup_roles.py";   Marker = "_verifier_literal";                 Why = "the --create-user/--reset-password CLI hashes too - otherwise the bootstrap admin's password lands in the log" },
    # static\app.js was split into static\js\*.js; the entry pointed at the old
    # path and so reported MISSING on every run, which trains an operator to
    # read a red result as normal -- exactly the habit the entries above rely
    # on not existing.
    @{ Path = "pipeline\portal\static\js\home.js"; Marker = 'target="_blank"';                Why = "tiles open in a new tab; server messages on row actions" },
    @{ Path = "pipeline\portal\static\index.html"; Marker = 'rel="icon"';                     Why = "portal landing page incl. favicon" },
    # Marker was "kit-pass", a class the design-system adoption deleted, so this
    # entry reported STALE forever -- same problem as the entry above it.
    @{ Path = "pipeline\portal\static\styles.css"; Marker = "--bordeaux-1";                  Why = "portal styling on the design-system tokens" },
    @{ Path = "pipeline\studio\app.js";        Marker = "bod_geb:'GEB/GEB-1'";           Why = "four-tab studio, pack drawer, Excel exports, the read-only snapshot switch, and the GEB/GEB-1 relabel" },
    @{ Path = "pipeline\studio\styles.css";    Marker = "channel-chip";                  Why = "channel colour, packs table, pack drawer, five-tile row" },
    @{ Path = "pipeline\studio\index.html";    Marker = "<label>GEB/GEB-1<input";        Why = "four-tab nav, view switcher, pack drawer, both Excel exports, snapshot script tag, and the GEB/GEB-1 relabel" },
    @{ Path = "pipeline\studio\snapshot.js";   Marker = "SnapshotPlanningRepository";     Why = "read-only repository for the standalone export -- without it the standalone build produces a page that cannot load data" },
    @{ Path = "pipeline\scripts\build_studio_standalone.py"; Marker = "__CPLAN_SNAPSHOT__"; Why = "standalone studio export (snapshot.ps1, and step 3 of the daily refresh)" },
    @{ Path = "pipeline\scripts\daily_refresh.py"; Marker = "run_standalone_step";        Why = "daily refresh exports the standalone studio as its third step" },
    @{ Path = "snapshot.ps1";                  Marker = "build_studio_standalone";       Why = "standalone studio launcher" },
    @{ Path = "pipeline\studio\xlsx.js";       Marker = "summaryBelow";                  Why = "the workbook writer -- without this file both exports refuse and say so" },
    @{ Path = "pipeline\studio\analytics.js";  Marker = "Deliberately NOT tracking_pack_id";                        Why = "missing campaign/pack no longer pinned to zero" },
    @{ Path = "pipeline\scripts\cplan_db.py";  Marker = "def stop";                          Why = "clean database stop" },
    @{ Path = "pipeline\scripts\start_portal.py"; Marker = "DEFAULT_PORT";                   Why = "portal launcher" },
    @{ Path = "setup.ps1";                     Marker = "pipeline.api.ensure_db";            Why = "config-driven one-time setup incl. the schema step before setup_roles" },
    @{ Path = "start.ps1";                     Marker = "Start-CplanServer";                 Why = "server windows stay open on a crash, so the traceback is readable" },
    @{ Path = "stop.ps1";                      Marker = "Stop-CplanServerOnPort";            Why = "clean shutdown launcher - without it the servers keep their ports and the next start dies with winerror 10048" },
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
    # Deliberately no longer "setup.cmd (or start.cmd)": setup.cmd is the only
    # branch that re-applies the database schema, and an update can add objects
    # the servers refuse to start without (the login throttle did). Taking the
    # start.cmd shortcut after copying new files is how an installation ends up
    # with new code on an old database.
    Write-Host "RESULT: all files current. Run fix-db.cmd, then setup.cmd (it re-applies the schema," -ForegroundColor Green
    Write-Host "        which an update can require), then start.cmd." -ForegroundColor Green
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
