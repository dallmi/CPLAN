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
# The branch every download URL below is built from. `feature/cplan-v6-postgres`
# was merged and deleted; every URL this script printed pointed at a ref that no
# longer exists, which is a 404 at the end of a correct STALE report -- the one
# moment the operator is actually following instructions.
$rawBase = "https://raw.githubusercontent.com/dallmi/CPLAN/main"

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
    # The rest of the split frontend. home.js above is one of nine ES modules
    # that import each other; naming only the one whose marker happened to
    # survive the split would report "all files current" for a copy missing any
    # of the other eight -- a portal that loads its shell and then dies on a
    # module it cannot resolve. The second index.html entry pins that the page
    # points at the split module at all, which the favicon marker cannot see.
    @{ Path = "pipeline\portal\static\index.html"; Marker = 'src="js/app.js"';                Why = "the landing page loads the split module, not the old single file" },
    @{ Path = "pipeline\portal\static\js\app.js"; Marker = "wireInvite";                      Why = "portal entry module -- imports the eight below, so a missing one breaks the page at load" },
    @{ Path = "pipeline\portal\static\js\api.js"; Marker = "revokeRole";                      Why = "portal server calls" },
    @{ Path = "pipeline\portal\static\js\state.js"; Marker = "accountsFromRows";              Why = "portal client state, role ranking and sign-in formatting" },
    @{ Path = "pipeline\portal\static\js\ui.js"; Marker = "generatePassword";                 Why = "portal shared rendering, toasts, layer stack and the initial-password generator" },
    @{ Path = "pipeline\portal\static\js\users.js"; Marker = "wireUsers";                     Why = "portal users table incl. search, filters and sorting" },
    @{ Path = "pipeline\portal\static\js\matrix.js"; Marker = "wireMatrix";                   Why = "portal user x project access matrix" },
    @{ Path = "pipeline\portal\static\js\drawer.js"; Marker = "wireDrawer";                   Why = "portal person drawer incl. the confirmed destructive actions" },
    @{ Path = "pipeline\portal\static\js\invite.js"; Marker = "wireInvite";                   Why = "portal invite flow" },
    @{ Path = "pipeline\portal\static\js\password-words.js"; Marker = "PASSWORD_WORDS";       Why = "word list behind the initial-password generator -- without it ui.js fails to resolve its import" },
    @{ Path = "pipeline\portal\static\project.html"; Marker = 'src="/project.js"';            Why = "portal project page" },
    @{ Path = "pipeline\portal\static\project.js"; Marker = "function loadUserChip";          Why = "portal project page behaviour" },
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
    # The calendar report, complete. Every module report_calendar.py reaches at
    # import time is listed: a hand-copy that misses any one of them turns every
    # report run into ModuleNotFoundError, and a manifest that covered only some
    # of them would report the rest "OK" and send the operator looking elsewhere.
    # Derived from the import closure of report_calendar.py, not from memory.
    @{ Path = "report.ps1";                    Marker = "GebMembers";                        Why = "report launcher incl. the GEB member list flag" },
    @{ Path = "pipeline\scripts\report_calendar.py"; Marker = "--geb-members";               Why = "the report entry point; loads the GEB member list and swaps the split breakdown fields in" },
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "parse_sp_person_emails";        Why = "the ETL every sheet is built from -- the plural parser keeps one email slot per person, which the singular one cannot do for a multi-person column" },
    @{ Path = "pipeline\report\membership.py"; Marker = "DEFAULT_FILENAME";                  Why = "GEB membership loader -- report_calendar.py imports it at module scope, so a missing copy turns every report run into ModuleNotFoundError" },
    @{ Path = "pipeline\report\config.py";     Marker = "EXECUTIVES_SPLIT";                  Why = "report criteria, audience bands, the reader-facing field titles, and the split column pair every other module reads" },
    @{ Path = "pipeline\report\data.py";       Marker = "_people_with_emails";               Why = "scope building and the GEB/GEB-1 split -- pairs each person with their own email, or drops all of them when the counts disagree" },
    @{ Path = "pipeline\report\derive.py";     Marker = "def split_people_aligned";          Why = "per-row derivations; the aligned splitter keeps empty email slots so person N keeps their own address" },
    @{ Path = "pipeline\report\calendar_sheet.py"; Marker = "SPLIT_FIELDS";                  Why = "the calendar sheet incl. the GEB and GEB-1 blocks and their header counts" },
    @{ Path = "pipeline\report\table_sheets.py"; Marker = "GEB_SPLIT_TERMS";                 Why = "summary, data quality, audience, mix, activities and glossary sheets" },
    @{ Path = "pipeline\report\grid.py";       Marker = "def build_grid";                    Why = "the calendar's week/month/quarter axis" },
    @{ Path = "pipeline\report\metrics.py";    Marker = "REPORTED_FIELDS";                   Why = "load, lead time, pack and completeness figures" },
    @{ Path = "pipeline\report\regions.py";    Marker = "GROUP_UNMAPPED";                    Why = "region grouping and the unmapped-value report" },
    @{ Path = "pipeline\report\style.py";      Marker = "NUM_FMT_PCT";                       Why = "every colour, number format and sheet-finishing helper the workbook is built from" },
    # The team signature. Added as second markers rather than replacing the
    # ones above, so each file keeps both claims. A brand is only a brand if it
    # is the same everywhere; a hand-copy carrying the old wording would report
    # "current" on the strength of a marker that predates the naming, which is
    # exactly the inconsistency this is meant to prevent.
    @{ Path = "pipeline\portal\app.py";        Marker = 'title="Insights Portal"';           Why = "the portal is named for what it holds, not for its first product" },
    @{ Path = "pipeline\portal\static\index.html"; Marker = "ECC Measurement &amp; Insights"; Why = "portal landing page carries the signature, and the sign-in copy no longer describes CPLAN alone" },
    @{ Path = "pipeline\portal\static\project.html"; Marker = "ECC Measurement &amp; Insights"; Why = "portal project page carries the signature" },
    @{ Path = "pipeline\portal\static\project.js"; Marker = "Insights Portal";                Why = "the project page's document title follows the portal name" },
    @{ Path = "pipeline\studio\index.html";    Marker = "ECC Measurement &amp; Insights"; Why = "the studio carries the signature too - a mark on one surface is not a brand" },
    @{ Path = "pipeline\report\table_sheets.py"; Marker = "Produced by ECC Measurement";     Why = "the workbook signs itself; it reaches people who never open either application" },
    @{ Path = "setup.ps1";                     Marker = "pipeline.api.ensure_db";            Why = "config-driven one-time setup incl. the schema step before setup_roles" },
    @{ Path = "start.ps1";                     Marker = "Start-CplanServer";                 Why = "server windows stay open on a crash, so the traceback is readable" },
    @{ Path = "stop.ps1";                      Marker = "Stop-CplanServerOnPort";            Why = "clean shutdown launcher - without it the servers keep their ports and the next start dies with winerror 10048" },
    @{ Path = "refresh.ps1";                   Marker = "-NoExit";                           Why = "daily refresh; studio window stays open on a crash" },
    @{ Path = "portal.ps1";                    Marker = "Start-CplanServer";                 Why = "portal launcher; server window stays open on a crash" },
    # Second markers for files that changed after their first marker was chosen.
    # Every one of the entries below names a string the file's *previous*
    # version did not contain; the marker above it, by then, named something
    # both versions had. Thirty of the fifty-five listed files were in that
    # state at once -- reported "current" on a machine holding the copy from
    # before the change, which is the one answer this script exists not to give.
    # Added rather than substituted, so each file keeps every claim already made
    # about it. `tests/test_check_manifest.py` now fails when a listed file
    # changes and no marker follows, so this cannot silently accumulate again.
    @{ Path = "pipeline\api\views.py";         Marker = "def drop_analysis_views";           Why = "the view teardown a whole-schema drop has to go through first" },
    @{ Path = "pipeline\api\session.py";       Marker = "role vanished (user deleted)";      Why = "the dead-session case on the SET ROLE 401 branch is named, not silent" },
    @{ Path = "pipeline\api\setup_portal.py";  Marker = "_NO_KEY_GIVEN";                     Why = "--clear-login-block tells 'no key given' apart from an empty key" },
    @{ Path = "pipeline\api\scram.py";         Marker = "def _bidi_ok(mapped: str) -> bool:"; Why = "saslprep checks the mapped string, in PostgreSQL's step order rather than the RFC's" },
    @{ Path = "pipeline\portal\app.py";        Marker = "Insights Portal service:";          Why = "the service names itself for what it holds; CPLAN_* env vars deliberately keep their names" },
    @{ Path = "pipeline\portal\static\styles.css"; Marker = "/* Insights Portal";            Why = "the stylesheet header follows the portal name" },
    @{ Path = "pipeline\portal\static\js\home.js"; Marker = "projectsLoadFailed";            Why = "a failed project read renders as an error state, not as a false empty result" },
    @{ Path = "pipeline\portal\static\js\app.js"; Marker = "!result.ok && result.message";   Why = "the sign-in form repeats which refusal it got - 401, 429 or 503" },
    @{ Path = "pipeline\portal\static\js\api.js"; Marker = "status === 429";                 Why = "the throttled answer is worded identically for every caller" },
    @{ Path = "pipeline\portal\static\js\state.js"; Marker = "projectsLoadFailed: false";    Why = "the load-failure flags home, users and matrix render from" },
    @{ Path = "pipeline\portal\static\js\ui.js"; Marker = "PASSWORD_WORDS";                  Why = "the initial password is four words from the shared list (~44 bits), not the old scheme" },
    @{ Path = "pipeline\portal\static\js\users.js"; Marker = "usersLoadFailed";              Why = "the users table distinguishes 'read failed' from 'no users'" },
    @{ Path = "pipeline\portal\static\js\matrix.js"; Marker = "popoverLayerToken";           Why = "closing the role popover returns focus to the cell that opened it" },
    @{ Path = "pipeline\portal\static\js\drawer.js"; Marker = "drawerLayerToken";            Why = "the drawer remembers its trigger across a reopen, so focus has somewhere to go back to" },
    @{ Path = "pipeline\portal\static\js\invite.js"; Marker = "inviteLayerToken";            Why = "the invite modal gives focus back on every close path" },
    @{ Path = "pipeline\studio\app.js";        Marker = "LOGIN_ERRORS";                      Why = "the studio's sign-in words 429 and 503 exactly as the portal does" },
    @{ Path = "pipeline\studio\styles.css";    Marker = "max(280px";                         Why = "the viewport cap keeps a floor, so a narrow window cannot clamp the list to zero height" },
    @{ Path = "pipeline\studio\xlsx.js";       Marker = 'xSplit="1"';                        Why = "the first column is frozen alongside the header row" },
    @{ Path = "pipeline\studio\analytics.js";  Marker = "function comingUp";                 Why = "the Overview's rolling windows live where a node test can run them" },
    @{ Path = "pipeline\scripts\cplan_db.py";  Marker = "def start(pgdata";                  Why = "--start brings the database up on its own, for pgAdmin after a reboot" },
    @{ Path = "pipeline\scripts\report_calendar.py"; Marker = "in this repository's root";   Why = "an unreadable member list is reported by name and path, not skipped" },
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "same filter to the same elements"; Why = "the email slots track parse_sp_lookup's dropped elements - otherwise every later address lands under the wrong name" },
    @{ Path = "pipeline\report\membership.py"; Marker = "DictReader stashes any field";      Why = "a row with an extra column is rejected instead of silently truncated" },
    @{ Path = "pipeline\report\config.py";     Marker = "two hardcoded copies would.";       Why = "the field titles have one home, which describe() and the sheets share" },
    @{ Path = "pipeline\report\data.py";       Marker = "def _people_with_emails(bod_geb, bod_geb_email)"; Why = "the split is derived from the two raw cells after every filter has run" },
    @{ Path = "pipeline\report\calendar_sheet.py"; Marker = "EXECUTIVES_SPLIT, FIELD_TITLES"; Why = "the calendar reads the titles from config.py instead of keeping its own copy" },
    @{ Path = "pipeline\report\grid.py";       Marker = "_by_monday";                        Why = "week lookup is a cached map - the scan it replaced crawled once the grid spanned years" },
    @{ Path = "pipeline\report\metrics.py";    Marker = '"bod_geb", "other_executives"';     Why = "both leadership fields are carried, not just the combined one" },
    @{ Path = "pipeline\report\style.py";      Marker = "_ILLEGAL";                          Why = "control characters are blanked, so one bad byte cannot cost the whole workbook" },
    @{ Path = "setup.ps1";                     Marker = "means the packages are missing (run check.cmd)"; Why = "a missing package is reported as such, not as 'is the database reachable?'" }
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
