<#
CPLAN preflight check for hand-copied files (no git pull available on corp).

Verifies that every critical file is present AND is the current version (each
file is identified by a marker string that only exists in its latest state),
purges stale Python bytecode caches, and proves that the Python interpreter
actually loads the new code. Prints a download URL for every outdated file.

This script is in its own manifest, and reports itself first: an outdated copy
answers with an outdated list of files, which is the one wrong answer nothing
else here can catch.

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

# This script's own version, and the one entry in the manifest that is about
# this script. Everything below checks other files; nothing checked this one,
# so an operator running a months-old check.ps1 got a confident "all files
# current" from a months-old manifest -- the failure the whole file exists to
# prevent, aimed at itself.
#
# Bump it in the same commit as ANY change to this file: the date, or the
# suffix when the date is already today's. `tests/test_check_manifest.py` fails
# until it is bumped, and says so.
$manifestVersion = "2026-08-11.3"

# file (repo-relative) = marker string that only the CURRENT version contains.
# Maintained together with the code: when a listed file changes upstream, its
# marker here is updated in the same commit.
$manifest = @(
    # First, because an outdated copy of this script answers every question
    # below with an outdated list, and does it in green.
    @{ Path = "check.ps1";                     Marker = '$manifestVersion = "2026-08-11.3"'; Why = "this script itself - an old copy checks a new repository against an old manifest and reports it fine" },
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
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "lookup into a time-zone list";  Why = "the time zone arrives as lookup JSON; unparsed it overflows varchar(64) and takes the whole daily refresh down with it, before one row is written" },
    # The width check for that same field. Listed so a machine without it is
    # told to fetch it: the answer it gives -- does any time zone in today's
    # export exceed the column -- is only available before the refresh, and
    # after the refresh it arrives as a psycopg traceback instead.
    @{ Path = "pipeline\scripts\check_time_zones.py"; Marker = "def column_limit";           Why = "names any time zone too long for the column, before the INSERT does it as a truncation error that ends the whole refresh" },
    @{ Path = "pipeline\scripts\check_time_zones.py"; Marker = "def report_context";         Why = "reads the export through the ETL's own transform() - an older copy re-implements the column matching and counts the lookup's row ids as time zones" },
    @{ Path = "pipeline\scripts\check_time_zones.py"; Marker = "def report_unmapped";        Why = "names a source zone TIME_ZONE_MAP does not translate - the one failure here that is otherwise silent" },
    # The two halves of one decision, and the half-copied state is worse than
    # either old one: the ETL writes IANA zones the studio's select cannot
    # offer, so a synced activity's drawer reads "Not set" for a field that is
    # filled, and the next save on that drawer clears it.
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "TIME_ZONE_MAP";                 Why = "the source's display names are translated to IANA zones; without it the studio stores 'Japan Standard Time - GMT+9:00' where a zone belongs" },
    @{ Path = "pipeline\studio\index.html";    Marker = "Asia/Ho_Chi_Minh";                  Why = "the time-zone select offers every zone the ETL now maps to - an older copy shows 'Not set' on a synced activity that has one" },
    @{ Path = "timezones.ps1";                 Marker = "check_time_zones";                  Why = "the launcher for that check - double-clickable via timezones.cmd" },
    @{ Path = "timezones.ps1";                 Marker = "Context";                           Why = "-Context reaches the per-zone region and lead-team breakdown; without it the switch is silently ignored" },
    @{ Path = "pipeline\scripts\check_tracking_ids.py"; Marker = "def find_hint";            Why = "says why a listed ID is missing - without it a wrong channel suffix and a never-created activity read identically" },
    @{ Path = "pipeline\scripts\check_tracking_ids.py"; Marker = "ACTIVITY_SOURCES";         Why = "searches the four activity exports and only those - an older copy can report a pack ID as a found activity" },
    @{ Path = "pipeline\scripts\check_tracking_ids.py"; Marker = "CSV_COLUMNS";              Why = "-Csv writes the result for a spreadsheet; an older copy accepts the switch and produces no file" },
    @{ Path = "trackids.ps1";                  Marker = "check_tracking_ids";                Why = "the launcher for that check - double-clickable via trackids.cmd" },
    @{ Path = "trackids.ps1";                  Marker = "GetFullPath";                       Why = "-Ids is resolved against the caller's folder; without it a relative list path is looked for in the repository root and reads as a missing file" },
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
    # The agent pack: the same report rendered for a retrieval index instead of
    # for a reader. Added as a second marker on report_calendar.py rather than
    # replacing the one above, so the file keeps both claims -- resolve_scope is
    # what makes the pack and the workbook two renderings of one report, and a
    # copy from before it cannot build the pack at all (ImportError), while an
    # older agentpack.ps1 would run against a report_calendar.py that has it.
    @{ Path = "pipeline\scripts\report_calendar.py"; Marker = "def resolve_scope";           Why = "the scope resolution the pack shares with the workbook - without it build_agent_pack.py fails to import" },
    @{ Path = "pipeline\scripts\report_calendar.py"; Marker = "differ, visibly";            Why = "the shared resolution is documented as period-only now that the pack widens the config it passes in - an older copy claims both hold the same figures, which is the one thing they no longer do" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def write_pack";                    Why = "the agent pack itself: values instead of formulas, long instead of wide, the layout rules written out as sentences" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "CHECKLIST_NAME";                    Why = "the answer key is written OUTSIDE the uploaded folder - inside it, an agent grounds on it and passes the test by reading the answers" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "whenever the image carries a total"; Why = "a chart stating a total must say what it counts - an older copy lets an image carry the wider figure with nothing on it accounting for the gap to the workbook in the reader's hand, and an image cannot be asked which total it meant" },
    # Both halves of what a first real run taught, and a copy missing either
    # one still produces a pack and a checklist that look right. The glossary
    # rule is what stops an agent reporting the previous year's quarter on an
    # in-scope activity as a data error; the derived grading is what stops the
    # checklist calling a question a count while the summary states its answer.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "overlap test, not a start-date test"; Why = "scope is an overlap test - without the sentence, an agent flags a Q4-2025 label inside a 2026 report as an anomaly worth reviewing" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "You might also ask";             Why = "every answer offers its own follow-ups - Copilot Studio has no follow-up chips, only starter prompts on the welcome page, so an older copy leaves each answer a dead end" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "TEAM_SIGNATURE";                 Why = "the agent is the fourth surface signed with the team name, and the footer carries it beside the data vintage on one line - an older copy omits the credit, and an operator adding it by hand makes it a second footer" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "ORGANISATION_PLACEHOLDER";       Why = "the full agent instructions ship organisation-neutral through a public repository - an older copy carries only the addendum and leaves the stale Excel and audience-reach lines in place" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def vintage";                    Why = "the pack states its own generation date and the instructions require it in every answer - it is rebuilt by hand, so without it a reader cannot tell a fresh figure from a month-old one" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "conversationNumber";             Why = "the evaluation set matches the template the product hands out - the documented format belongs to another harness, and a copy carrying it is rejected on import with a format error" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "INSTRUCTIONS_TEXT";              Why = "the agent-level instructions ship with the pack, outside the uploaded folder - a skill is selected when it fits, instructions apply to every turn, and without them nothing guards a turn the skill missed" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def _states";                       Why = "control vs counting question is derived from what the pack states, not asserted by hand - an older copy mis-grades a retrieved answer as a computed one" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "One red element per chart";        Why = "the visual rules are countable - hexes, a white-space ratio, a limit of one red element; an older copy names one colour and then asks for restraint, which is the judgement the agent is already getting wrong" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "Say each figure once";             Why = "summary, findings and charts divide the work instead of each restating the same number - an older copy produces an image whose tiles, bars and read-out say the same four figures three times over" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "BRAND_SKILL_TEXT";                Why = "the chart rules ship as a second, data-free skill and the instructions name it the way they name the report pack - an older copy carries them inline and pays for 160 lines of layout rules on every one-line question" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "Every turn carries it";           Why = "the vintage footer is owed on follow-up turns too - an older copy says only never omitted, and the line stops after the first answer because a later turn never re-opens the summary" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "Three, every time";               Why = "three follow-up questions, not two - an older copy says two is usually right, which reads as permission to stop at two and did" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "## Who is asking";                 Why = "persona priorities, the analysis steps and the question catalogue moved into the reporting skill - an older copy carries all three on every turn, including the ones that answer nothing from the pack" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "never reached for it";           Why = "the pack is no longer a knowledge source and the index-only workbook is gone - an older copy writes a seventh file for a reader that does not exist and describes the folder as something to upload" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "largest area in the image";  Why = "red is bounded by area and composition charts take a red-free sequence - an older copy bounds only the COUNT of red elements, which one donut segment satisfies while covering half the picture" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def pack_config";              Why = "the pack keeps the deprioritised bucket the workbook plans past, and every row says whether the workbook holds it - an older copy answers zero to a priority-4 question, and a newer pack beside an older agent_pack loses the in_report column that reconciles the two totals" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "copy the formatting";        Why = "the follow-up block is labelled as a shape to reproduce - an older copy hangs it off a colon, and the agent reads the block quote as the prompt quoting itself and answers with a plain list nobody spots" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "BREAKDOWN_NAME";             Why = "06-breakdowns.csv crosses two dimensions instead of one - an older copy has no such file, so a question crossing two blocks (which division binds the most executive attention) can only be answered by counting 05-activities.csv by hand" },
    # The sixth file named everywhere the other five already were: the README
    # inside the pack, the skill manifest, and the instructions. An older copy
    # writes 06-breakdowns.csv but never tells the agent it exists, so the file
    # ships and is never opened.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "Any figure crossing two dimensions"; Why = "06-breakdowns.csv is named in the skill's own file table, not only produced - an older copy writes the file and leaves every table of contents pointing at five" },
    # A final-review pass over the prose itself: the file count the skill text
    # states in words, the rule count the glossary claims, and which files
    # readme_text tells a reader to prefer, all had to move together with
    # 06-breakdowns.csv and none of them did on the first pass.
    #
    # Marker updated a second time, not added to: it is a quote of this exact
    # sentence, and the sentence legitimately changed again when 07-packs.csv
    # got its own routing row -- a marker that still said "five" here would
    # be stale by construction, watching text nothing shipped since Task 9
    # still contains. The Why below records why the count moved this time.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "six files shipped with"; Why = "the skill text counts the files in its own routing table, which gained a sixth row for 07-packs.csv - an older copy still says five, and a question the pack file uniquely answers routes to 03-data-quality.txt's counts instead" },
    # A third skill, in a file of its own rather than folded into the other two
    # entries above: the named board catalogue. agent_pack.py imports it at
    # module scope, so a copy that has the new agent_pack.py but not this new
    # file cannot even be imported, and a copy that has neither writes two
    # skills where a board-naming request now expects three.
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "def write_zip";              Why = "the board catalogue - a NEW file; without it agent_pack.py fails to import and no board archive is written" },
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "matters most here"; Why = "the board file defers the scope check to chart-standards instead of repeating it - a board is the artefact most forwarded and least questioned, so an older copy is where a silent disagreement with the workbook travels furthest" },
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "A Source line is not the footnote"; Why = "a board's Source citation and the printed source footnote are both called Source with nothing telling them apart - an older copy lets an agent footnote a panel with a pack filename and column names, breaching the no-filename rule chart-standards states two skills away" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "DASHBOARD_SKILL_ZIP_NAME";        Why = "the third skill archive is wired into write_pack beside the other two - an older copy imports fine but never writes the board catalogue" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "BRAND_SKILL_ZIP_NAME";      Why = "the run names the second skill archive and says it is uploaded once - an older copy writes it and the operator never learns it is there" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "third skill: the named boards"; Why = "the run also lists the third skill archive - an older copy writes it beside the pack and never tells the operator it exists" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "replace <ORGANISATION>";   Why = "the run says the instructions file needs one find-and-replace before it is pasted - an older copy calls it an addendum and the operator appends a full prompt to a full prompt" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "EVALUATION_NAME";          Why = "the run names the test set and says it is safe to import - an older copy writes it and leaves the operator guessing whether it may be uploaded" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "INSTRUCTIONS_NAME";        Why = "the run names all three artefacts and which one must not be uploaded - an older copy writes the instructions file but never tells the operator it is there" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "resolve_output_dir";         Why = "the pack is written into the OneDrive CPLAN folder so it can be uploaded from anywhere - an older copy leaves it inside the checkout, where it is unsynced and the operator uploads a stale one from the wrong machine" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "Nothing to upload";          Why = "the run no longer tells the operator to point a knowledge source at pack\ - an older copy does, which restores the second grounding path and with it two vintages of the same figure" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "wider than the workbook";  Why = "the pack is built without the priority and objectives filters and the run says so - an older copy builds the workbook scope, and a question about deprioritised activities is answered with nothing" },
    # The second delivery, for Agent Builder. A copy without these entries has
    # no Agent Builder pack at all, and nothing above notices: every file it
    # does have is current, so the check passes in green.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "def write_builder_pack";       Why = "the Agent Builder delivery - a NEW file; without it the run writes only the Studio pack and the test users have nothing to install" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "INSTRUCTIONS_LIMIT";           Why = "the 8,000-character limit is asserted rather than assumed - an older copy can hold a prompt the field silently truncates, and truncation takes the footer and the follow-ups first because they are last" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "CHART_STANDARDS_NAME";         Why = "the chart geometry ships as a knowledge file because this surface has no skills - an older copy leaves the agent holding the palette with no guidance on which chart to draw" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "BOARD_FILE_NAMES";             Why = "the three boards ship as their own knowledge files here, not one catalogue - an older copy has no board files at all, and Agent Builder has no skill package to fall back on" },
    # A knowledge file cannot announce itself. Added as a second marker: the
    # three board names now live in the instructions prompt too, and an older
    # copy leaves the agent with boards it can only find if a user already
    # knows to ask for one by name.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "Draw a board only from its own file"; Why = "the prompt itself names the boards and says to ask which one - an older copy answers a bare 'give me a dashboard' by drawing from no board file at all" },
    # A board's own Footnote line is a different line from the vintage footer,
    # and the read-out is bounded to the figures its own Source line names.
    # An older copy of the repeated block leaves an agent that reads one board
    # file free to print no panel caveats at all, and free to state any figure
    # it likes in the read-out rather than only the ones the board cites.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "Neither line stands in for the other"; Why = "distinguishes each panel's own Footnote line, which prints, from the vintage footer that closes the board - an older copy reads as if only the vintage line is ever printed, so a caveat like `never measured reach` goes unstated" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "resolve_builder_output_dir"; Why = "the Agent Builder delivery lands in OneDrive Output beside the pack's Input - an older copy writes it into the checkout, unsynced, and the operator uploads a stale one from the wrong machine" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "write_builder_pack";        Why = "the run actually writes the second delivery, not merely resolve a folder for it - a copy with the resolver and not the call reports a path it never wrote to" },
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "ONEDRIVE_OUTPUT_DIR";         Why = "the Output folder constant - without it build_agent_pack.py fails to import and NO pack is written at all, not merely the second one" },
    @{ Path = "agentpack.ps1";                 Marker = "cplan-skill.zip";                   Why = "the pack launcher, and the one place that says which of the artefacts must NOT be uploaded" },
    @{ Path = "agentpack.ps1";                 Marker = "resolve_output_dir";               Why = "the launcher asks the builder where it wrote instead of carrying its own copy of the rule - an older copy opens pipeline\output\agent-pack while the run wrote to OneDrive, and the operator uploads whatever was there before" },
    @{ Path = "agentpack.ps1";                 Marker = "NOT a";                            Why = "the header says the pack folder is not a knowledge source - an older copy tells the operator to upload it, which restores the second grounding path and with it two vintages of the same figure" },
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
    @{ Path = "setup.ps1";                     Marker = "means the packages are missing (run check.cmd)"; Why = "a missing package is reported as such, not as 'is the database reachable?'" },
    # The GEB member list reads as a workbook as well as a CSV. Added, not
    # substituted: the markers above still hold, and a copy predating the
    # workbook reader answers "current" on their strength alone -- while
    # silently ignoring the .xlsx the operator put next to report.cmd, which
    # is the one symptom this pair has to be able to tell apart.
    @{ Path = "pipeline\report\membership.py"; Marker = "def _read_xlsx";                  Why = "the workbook reader -- without it a geb-members.xlsx is ignored and the report runs unsplit, saying nothing" },
    @{ Path = "pipeline\scripts\report_calendar.py"; Marker = "membership.default_path";   Why = "the default search finds either format, and refuses to guess when both are present" },
    # A project publishes pictures from one declared directory, and the logo on
    # its tile is one of them. Five files move together here, and two of them
    # were never listed at all: resources.py holds the resolution, pages.py
    # serves the file, and app.py imports the first to fill a field the tile
    # reads. A copy with the new app.py and an old resources.py does not render
    # a logo-less tile -- it fails to import, and the portal does not start.
    @{ Path = "pipeline\portal\resources.py";  Marker = "def assets_dir";                    Why = "the project's picture directory is declared once, at the top of its manifest - without this the portal cannot start, because app.py imports it" },
    @{ Path = "pipeline\portal\pages.py";      Marker = "named_file(assets_dir";             Why = "the gated asset route serves every picture a project publishes, not the manual's alone" },
    @{ Path = "pipeline\portal\app.py";        Marker = "def _project_summary";              Why = "a project tile carries its logo - an older copy sends no such field and every tile stays unmarked" },
    @{ Path = "pipeline\portal\static\js\home.js"; Marker = "tile-logo";                     Why = "the tile renders the mark the API sends, and nothing when there is none" },
    @{ Path = "pipeline\portal\static\styles.css"; Marker = ".tile-logo {";                  Why = "the logo is capped in height and width - unstyled, one large PNG blows up the tile grid" },
    # A home tile leads to the project page, not straight to the workspace. The
    # stale copy here is invisible rather than broken: it opens the studio in a
    # new tab and works, while the manual, the technical documentation, data,
    # the changelog, access and the reports stay unreachable -- exactly the
    # "everything is fine" report the manifest exists to prevent.
    @{ Path = "pipeline\portal\static\js\home.js"; Marker = 'href="/project/';               Why = "a project tile opens the project's own page - an older copy jumps to the workspace and hides the six resource tiles behind a URL nobody is told" },
    @{ Path = "pipeline\portal\static\index.html"; Marker = "Select one to see everything it holds"; Why = "the tile heading describes where a tile now leads; an older copy still promises a new tab" },
    # What the workbook no longer says. All three removals only take away, so a
    # stale copy still produces a workbook that opens and looks right -- it just
    # prints the column, the filenames and the wording that were withdrawn, to
    # the very audience they were withdrawn from. Nothing about the output
    # reveals which version built it, so the markers have to.
    @{ Path = "pipeline\report\table_sheets.py"; Marker = "deliberately no quarter-to-quarter"; Why = "the Mix crosstabs lost the quarter delta; an old copy still prints a settled quarter against one still being planned, and every row reads as a collapse" },
    @{ Path = "pipeline\report\table_sheets.py"; Marker = 'No "Source: <file>" rows';            Why = "the Executive Summary no longer names the operator's export files to recipients who have never seen that directory" },
    @{ Path = "pipeline\scripts\report_calendar.py"; Marker = "Source: {key} = {path.name}";     Why = "the source filenames moved to the console, so an old copy drops them entirely instead of relocating them" },
    # Two blocks a board has to name that neither the workbook nor the pack
    # carried before: priority and lead team, widened in the same place the
    # pack already widens past the workbook. An old copy answers a
    # priority-level or lead-team question by counting 05-activities.csv by
    # hand, which the instructions refuse.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "PARTITION_BREAKDOWN_FIELDS"; Why = "priority and lead team join the breakdown blocks and are marked as a partition, not overlapping -- an old copy has no such blocks at all, and a newer pack beside an older agent_pack loses the short_notice measure the same change adds" },
    # The partition claim above was a label, not a guard: `_split_for` uses
    # the same comma/semicolon splitter as the genuinely multi-valued fields,
    # so a priority label or team name that happens to contain one silently
    # broke the sum `overlaps=no` promises. An old copy ships a priority or
    # lead-team total that quietly disagrees with the portfolio instead of
    # refusing to build.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "is declared in PARTITION_BREAKDOWN_FIELDS, which"; Why = "a partitioning field that splits into more than one value now raises, naming the field and the activity's tracking ID - an old copy writes the wrong total silently instead" },
    # "Activities in scope: 1,380" mixes what is already behind the pack's own
    # generation date with what is still ahead of it, and states neither. An
    # old copy has no HORIZON section, so the split a reader actually needs --
    # what has already happened vs. what is coming in the next 30 days -- is
    # left to be summed out of forty rows of the calendar by hand.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "Planned to date"; Why = "the HORIZON section splits the portfolio at the pack's own generation date instead of leaving it to be summed out of the calendar" },
    # Portfolio overview answered "is the plan plausible" with an inventory
    # that never changed what anyone did. An old copy still ships
    # board-portfolio-overview.md and points the routing table at it, so an
    # agent asked where to intervene opens a board that cannot answer.
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "HEAD_OF_COMMUNICATIONS_OVERVIEW"; Why = "the general portfolio board is replaced by one built for a head of communications - an older copy still routes to board-portfolio-overview.md, which this version no longer produces" },
    # Agent Builder has no skill package, so its own file names and its own
    # prompt have to follow the same rename separately -- neither is read by
    # the other. An old copy still asks `write_builder_pack` for
    # board-portfolio-overview.md, which raises KeyError against the renamed
    # `dashboard_skill.BOARDS`, and its prompt still tells the agent to expect
    # a board this version no longer ships.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "board-head-of-communications-overview.md"; Why = "the Agent Builder file names and prompt follow the board rename - an older copy raises KeyError building the upload folder and, short of that, still points an agent at a board that no longer exists" },
    # The checklist graded a question a counting one by searching only the two
    # prose files, from before 06-breakdowns.csv existed. Once lead_team
    # became a breakdown block, its top-team total was stated there outright,
    # and an old copy still called reading it a computation -- a checklist
    # result that passed for a reason it did not claim.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def _csv_text"; Why = "the checklist's haystack now includes 06-breakdowns.csv - an older copy grades a question a control's own answer as a counting question because it only ever searched the two prose files" },
    # A final review pass over the head-of-communications board. The priority
    # donut used to group by raw source text -- two vocabularies live in that
    # one column at once, so it plausibly drew six to ten alphabetised slices
    # against the chart rules' own five-segment cap. An old copy of any file
    # below still builds and still looks like a working board; it just draws
    # that wider donut, or lets a three-week-old pack claim its "next 30 days"
    # tile describes today, or leaves panel 2's Chart line silent about the
    # split, divider and peak marker its own footnote already promises.
    @{ Path = "pipeline\report\derive.py"; Marker = "def priority_level"; Why = "collapses both priority vocabularies onto the four levels the board's donut groups by, reusing priority_rank rather than a second mapping" },
    @{ Path = "pipeline\report\calendar_sheet.py"; Marker = "PRIORITY_LEVELS"; Why = "the priority block now sorts by urgency, not alphabetically -- an older copy interleaves Critical and Low" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "derive.priority_level(name)"; Why = "the pack's priority block groups by the four shared urgency levels instead of raw source text -- an older copy ships a donut over the chart rules' own five-segment cap" },
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "Next 30 days from the data date"; Why = "the tile names its own anchor so a stale pack cannot be misread as describing today; panel 2's Chart line also states the solid/dashed split, the vintage divider and the peak marker its footnote already promised" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "let one activity count twice"; Why = "the overlap rule now says a partitioning block sums to the portfolio too, not only block=TOTAL" },

    # A lead team named after two disciplines carries a comma inside its own
    # name. The generic splitter read it as two teams, filed the activity under
    # both, and the guard then refused the whole pack rather than ship a block
    # that no longer sums to the portfolio -- a real run stopped on exactly
    # this. An old copy of any file below either refuses that run again or,
    # worse, splits the name and ships the wider total.
    @{ Path = "pipeline\report\derive.py"; Marker = "def split_semicolon"; Why = "the separator for every field whose one value may itself carry a comma - an older copy has no such splitter, so the fields below fall back to the comma-splitting one" },
    @{ Path = "pipeline\report\calendar_sheet.py"; Marker = "PARTITION_BREAKDOWN_FIELDS"; Why = "the partition claim and the separator that makes it true now live in one place - an older copy still splits a lead team's own comma and leaves agent_pack.py importing a name it does not have" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "a semicolon separates two values here"; Why = "the guard now fires on a real second value, not on punctuation, and its message says which character actually separates - an older copy sends the operator to edit a team name that was correct" },

    # The GEB member list reaches the agent pack. The blocks were already
    # split by the shared scope resolution -- what was missing is that every
    # prose file went on telling the agent no such split exists, and an agent
    # believes the prose over the data, because that is what the prose is for.
    # An old copy of any file below ships a pack whose figures and whose rules
    # contradict each other, which is worse than either state alone.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "GEB_RULE_SPLIT"; Why = "the leadership rule follows the run: with a member list the pack says the blocks separate the levels and names the list as the source, without one it keeps today's never-name-a-GEB-member wording - an older copy prints the second beside an executives_geb block and tells the agent the data in front of it cannot exist" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "a subset of GEB/GEB-1 involvement"; Why = "the summary states the GEB count as a named subset instead of an indented sub-row - an older copy leaves the pack without the figure the workbook prints, and indentation is exactly what a chunked read drops" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "GEB list entries never matched"; Why = "the pack reports how many list entries matched nothing, as the Data Quality sheet does - without it a typo in the list and a genuine GEB-1 person look identical, and both quietly land under GEB-1" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "never add the two"; Why = "the second delivery's prompt carries the same conditional rule as the first - an older copy hands Agent Builder a pack with split blocks and a rule forbidding their use, and the two deliveries then disagree about the same field" },
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "a member list was supplied"; Why = "the boards stop asserting that nothing can separate the levels, while still labelling their own panels GEB/GEB-1 because those panels count the combined field - an older copy contradicts the pack it is drawn from" },
    @{ Path = "agentpack.ps1";                 Marker = ".\agentpack.ps1 -GebMembers"; Why = "the pack launcher documents the member-list flag it has always forwarded - an older copy leaves the operator with no way to learn that the agent pack can split the levels at all" },

    # The 2026-08-10 render of the overview drew one panel's heading, question,
    # donut and legend straight across the bar labels of the panel beside it,
    # left its own rectangle empty, and closed by routing the reader to a board
    # that does not exist. Both failures were instruction-shaped rather than
    # code-shaped: the layout rules were written to be checked by looking at
    # the finished image, on surfaces where the agent never sees it. An old
    # copy of any file below draws that image again and reports nothing wrong.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "Cut the canvas into panel rectangles"; Why = "the layout rules are written as construction rules, and a panel's parts are placed against its own rectangle - an older copy states only that nothing may overlap, which is a property the agent cannot verify without seeing what it drew" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "Cut the canvas into panel rectangles"; Why = "the same geometry on the surface with no skills - an older copy leaves this delivery with the check-it-afterwards wording the other one has already dropped" },
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "naming one board, and only one"; Why = "the overview routes to one of the three boards that exist - an older copy sends a head of communications to `Planning discipline`, which is deferred and undrawable, and invites a read-out that lists every route and so chooses none" },

    # The scope footnote reached the Studio prompt eighteen minutes after the
    # Agent Builder prompt was cut from it, and eight later edits to that file
    # never picked it up. An old copy draws a board whose headline total is
    # larger than the workbook in the reader's hand, with nothing on the image
    # saying which of the two it is.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "includes M the report excludes"; Why = "an image stating a total prints its scope, on the surface where the checklist asking for it is a retrieved file rather than a loaded one - an older copy asks the question in `09-chart-standards.txt` and states the answer nowhere at all" },

    # The follow-up block is justified by a surface, not by the agent, and it
    # was copied here without the justification being asked again.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "Agent Builder offers its own"; Why = "this prompt does not ask for three follow-up questions, because the surface already puts them under every answer - an older copy produces two competing sets on one turn, the model's and the surface's, and nothing says which the agent stands behind" },

    # The activity rows have carried communication_pack_cpid, the bare pack
    # number, since the pack was first exported -- communication_pack, the
    # name beside it, was mapped and lookup-parsed the whole time and simply
    # never written out. An old copy still shows only CP-100 in both
    # 05-activities.csv and the workbook's Activities sheet.
    @{ Path = "pipeline\report\table_sheets.py"; Marker = "The name beside the number"; Why = "the activity rows gain a Pack column stating the pack's name, not only its CP-100 identifier - an older copy leaves a reader unable to ask about a pack by the name it actually has" },

    # The column-matching loop transform_packs renamed by was copied a second
    # time into check_pack_link.py's diagnostic, and the copy silently
    # disagreed with the original: it did not drop a lookup's #Id companion
    # and did not stop a second column from claiming an already-matched
    # label, so it reported both as "mapped" when transform_packs drops both.
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "resolve_pack_columns"; Why = "the pack column-matching rule, factored out of transform_packs so the pack-link diagnostic calls the ETL's own rule instead of a second copy that can drift from it - an older copy has no such function and the diagnostic reimplements the rule instead" },

    # The scoring half of the pack-link diagnostic, and the launcher an
    # operator runs it from without a terminal. An older copy prints only the
    # raw pack-column inventory and has no verdict, no exit-code contract and
    # no double-clickable entry point.
    @{ Path = "pipeline\scripts\check_pack_link.py"; Marker = "PACK_LINK_CANDIDATES"; Why = "the three columns scored against the pack list and the score() function that measures each - an older copy only lists the pack export's raw columns and cannot say which one is the real link" },
    @{ Path = "pipeline\scripts\check_pack_link.py"; Marker = "MIN_LINK_RATE"; Why = "the 80% floor a candidate must clear before the check exits 0 - an older copy has no floor and always exits 0 once the pack export is found, so a broken link would report as fine" },
    @{ Path = "packlink.ps1";                  Marker = "check_pack_link";                Why = "the launcher for that check - double-clickable via packlink.cmd" },

    # PACKS_COLUMN_MAP carried none of the pack form's own identity fields --
    # a pack could be sized and linked but never named. An old copy maps
    # `Name of communication pack`, `Tracking cluster`, `Category` and `End
    # date` to nothing, so the harmonised pack frame has no pack_name,
    # tracking_cluster, category or end_date column for a pack file to read.
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "The pack's own identity"; Why = "PACKS_COLUMN_MAP widened to map the pack's name, tracking cluster, category and end date - an older copy leaves all four unmapped, so the pack file cannot say what a pack is" },

    # load_packs() is the loader report_calendar.resolve_scope calls: it reads
    # the pack export through transform_packs, de-duplicates on cpid the same
    # way load_activities de-duplicates on tracking_id, and returns None (not
    # an empty frame, not an exception) when a machine has no pack export at
    # all. An old copy has no such function, so nothing can load the pack list
    # for the report path.
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "class PackLoad"; Why = "the pack loader load_packs() and its PackLoad return type - an older copy cannot load the pack export at all, so the report path has no pack list to build a scope from" },

    # Task 6 joins the pack list to the activities: build_scope now takes a
    # pack_load, marks each row's pack_known (Yes/No/blank) and carries the
    # pre-filter per-pack counts the pack file needs. An old copy has no
    # `packs`, `pack_link` or `pack_counts_all` on Scope, so nothing
    # downstream can read a link rate or a pack's activity count.
    @{ Path = "pipeline\report\data.py";       Marker = "pack_counts_all";              Why = "Scope carries the pack frame, the link result and the pre-filter per-pack counts - an older copy has none of the three, so a pack file cannot be built from the scope alone" },

    # The link rate is measured on the same rows the floor was set against.
    # An old copy computes it on the filtered frame at one of the two Scope
    # construction sites and on the unfiltered frame at the other, then
    # compares either to MIN_LINK_RATE - a warning that stays silent through
    # a real breakage whenever the filters keep the well-linked rows.
    @{ Path = "pipeline\report\data.py";       Marker = "for the same reason the floor"; Why = "pack_link is measured on the pre-filter frame, the population check_pack_link.py scores and MIN_LINK_RATE was established over - an older copy measures the normal path on in-scope rows only and compares that to the same floor" },

    # resolve_scope now loads the pack export itself and logs how well the
    # link column resolved, warning below the 80% floor. An old copy never
    # calls load_packs, so build_scope always receives pack_load=None and the
    # workbook run never reports a broken link even when one exists.
    @{ Path = "pipeline\scripts\report_calendar.py"; Marker = "No pack export found"; Why = "resolve_scope loads the pack export and logs the link rate - an older copy never calls load_packs, so a broken pack link is never reported" },

    # 07-packs.csv: one row per pack in the list, including CP-200, the one
    # nothing points at. An old copy has no pack_rows() and never writes the
    # file, so "which packs have nothing planned" cannot be answered from the
    # pack at all -- the row would simply be missing rather than showing zero.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def pack_rows"; Why = "07-packs.csv gets one row per pack, with an activities_in_scope and an activities_total that can legitimately differ - an older copy has no pack file, so a pack with nothing planned is absent rather than a visible zero" },

    # The Copilot Studio skill archive now carries 07-packs.csv too, guarded
    # the same way the Agent Builder copy loop already is. An old copy writes
    # a hardcoded six-name tuple with zipfile.ZipFile.write, which raises
    # FileNotFoundError the moment a run has no pack export -- turning a
    # supported situation into a crash on exactly the machines that lack one.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "included only when"; Why = "the skill archive includes 07-packs.csv only when pack_dir actually has it - an older copy writes a fixed six-name tuple with zipfile.ZipFile.write, which raises FileNotFoundError for any run with no pack export" },

    # 08-reading-guide.txt, 09-chart-standards.txt, boards renumbered to
    # 10-12, and UPLOAD_DATA_FILES gaining agent_pack.PACKS_CSV_NAME so the
    # pack file sorts ahead of the rule documents in the uploaded folder.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "turn a missing optional input into a crash in"; Why = "the copy loop skips 07-packs.csv when no pack export was synced instead of crashing on a missing source file - an older copy has UPLOAD_DATA_FILES without the pack file at all, and the rule documents numbered one lower" },

    # 03-data-quality.txt's existing PACK COVERAGE section gains two figures
    # only a pack list can supply, once one exists. An old copy answers
    # neither question without opening 07-packs.csv and counting by hand.
    # Corrected from this line's first version, which put a second section
    # of the same name in 01-summary.txt -- a chunked read of either file
    # then saw an identical header and a shared "Distinct packs" row with no
    # way to tell which file it came from.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "Packs with no activity in scope"; Why = "the data-quality file states how many listed packs nothing was planned against and how many activities point at a pack the list does not have - an older copy answers neither question without opening 07-packs.csv and counting by hand" },

    # Same fix, its own marker: distinguishes this version from the one that
    # briefly duplicated PACK COVERAGE into 01-summary.txt instead of
    # extending the section data_quality_text already had.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "is not restated here"; Why = "the two new pack-list figures sit in data_quality_text's own PACK COVERAGE section, beside Distinct packs, rather than in a second section of that name in the summary - two sections sharing a name and a first row would leave a chunked read unable to tell them apart" },

    # The glossary's Packs entry described a limitation the pack file removed
    # (no grouping dimension) rather than what a pack is. An old copy still
    # points a reader at "the Data Quality sheet" for pack coverage, which
    # is no longer where that reader would look first.
    @{ Path = "pipeline\report\table_sheets.py"; Marker = "activities grouped around one"; Why = "the Packs glossary entry says what a pack is instead of naming a limitation the pack file already removed - an older copy sends a reader to the Data Quality sheet for coverage that 03-data-quality.txt and 07-packs.csv now state directly" },

    # A knowledge file cannot announce itself: retrieval answers a question,
    # it does not tell the agent which questions have a file waiting. Agent
    # Builder's prompt now points at 07-packs.csv in its own file list, and
    # its reading guide says how to join an activity row to that file. An
    # older copy ships the pack file but never tells the agent it is there.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "including packs with nothing planned"; Why = "the prompt's file list names 07-packs.csv - an older copy is silent about the pack file even though it already ships in the upload folder, so the agent never retrieves it" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "worth reporting when it is common"; Why = "the reading guide explains the Pack ID join and that activities_in_scope = 0 is an answer, not a defect - an older copy has no Packs section, so an agent asked a pack's lead or objective has no file it knows to open" },

    # Same pointer, mirrored into the Studio skill with the fuller wording
    # this surface can afford - it has no character limit, unlike the prompt
    # above.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "how many activities sit in it"; Why = "SKILL.md's own file table names 07-packs.csv - an older copy ships the file in the skill archive but never mentions it in the skill text, so the agent never retrieves it" },

    # 00-README.txt is the human-readable table of contents, and it stopped at
    # 05-activities.csv one release after 06-breakdowns.csv taught exactly this
    # lesson: the files readme_text tells a reader to prefer had to move with
    # the new file, and none of them did on the first pass. Same miss, same
    # file, one entity later.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "including the ones with nothing planned against them"; Why = "the pack's own 00-README.txt lists 07-packs.csv, conditionally on the file being written - an older copy stops the table of contents at 05-activities.csv, so the one file that answers `which packs have nothing planned` is delivered and never mentioned to the reader" },

    # pack_known was put on the frame by packs.mark and carried out of it by
    # nothing, while the reading guide told the agent to treat pack_known = No
    # as a finding worth reporting. An old copy instructs the agent to filter
    # on a column no delivered file contains, which is answered from whatever
    # column does exist rather than reported as impossible.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "show_pack_known"; Why = "05-activities.csv carries pack_known wherever a pack list was joined - an older copy leaves the column in the frame only, so the agent is told to read a column no file it holds contains" },

    # SKILL.md is rendered for the archive being written rather than for the
    # packed case alone. An old copy ships one routing table on every machine:
    # on one with no pack export it names 07-packs.csv, which is not in the
    # archive, and counts six files where five shipped.
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def skill_text"; Why = "the skill archive's SKILL.md follows the archive - an older copy routes a pack question to 07-packs.csv on a machine that has no pack export, and the agent answers the miss from whichever file looked closest" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "guard covers the pack file and nothing else"; Why = "only the optional pack file is guarded by exists() - an older copy guards all seven names, so a required file that failed to write produces a silently incomplete archive instead of an error" },

    # The same two corrections on the surface with no skills: the reading
    # guide follows the upload folder, the copy loop guards only the optional
    # name, and the pasted prompt - which cannot follow anything - says the
    # pack file is there only sometimes.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "def reading_guide_text"; Why = "08-reading-guide.txt drops its Packs section where no pack export was synced - an older copy explains 07-packs.csv and the pack_known column to an agent whose upload folder holds neither" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "Present only where a pack list was synced"; Why = "the pasted prompt describes both states of the pack file - an older copy asserts it unconditionally, and a prompt is pasted once and left while the pack is rebuilt underneath it" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "Only that one name is guarded"; Why = "the copy loop guards 07-packs.csv alone - an older copy guards all seven, so a required file that failed to write leaves an upload folder that is quietly one file short and is uploaded whole anyway" }
)

Write-Host ""
Write-Host "=== CPLAN file check (manifest $manifestVersion) ===" -ForegroundColor Cyan
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
