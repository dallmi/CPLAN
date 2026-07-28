# Review-List Issue Context & Field Jump — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Activities workbench state which finding put a row in a review list, and let a click on that finding land the cursor in the field that fixes it.

**Architecture:** One presentation-free rule, `rowIssues(row)`, moves into `analytics.js` next to `planningCompleteness`, together with the two date predicates that are currently inlined at three call sites in `app.js`. `app.js` consumes it in three places — the Issue table column (replacing Readiness), a queue context bar above the table, and a jump bar in the drawer — and owns all user-facing wording via `issueLabel()`. `focusField` gains scroll-into-view and a one-shot highlight so a jump is visible in the dense form.

**Tech Stack:** Vanilla ES2020 browser JS (no build step), `analytics.js` as a UMD-ish CommonJS/global module, `node:test` for behavioural tests, Python `unittest` for source-level guards, FastAPI + SQLite for the local studio, chrome-devtools MCP for the click-through.

**Spec:** `docs/superpowers/specs/2026-07-28-review-list-issue-context-design.md`

## Global Constraints

- All user-facing copy is **English**. The app has no German UI.
- `analytics.js` stays **presentation-free** — it returns descriptors, never labels. Every user-facing string lives in `app.js`.
- Colours come only from the corporate palette already declared in `styles.css` `:root`. No new hex values.
- Red (`--danger`) is reserved for the one genuine error (`invalid-date`). Missing fields are Bronze, short notice is Amber.
- `border-radius` is `var(--radius)` (2px). No rounded chips.
- No emojis in UI. Lucide SVG only, where an icon is needed at all.
- The issue order is **fixed, never queue-aware**: `invalid-date` → `short-notice` → `missing` (in required-set order).
- `planningCompleteness` remains the sole owner of the completeness rule. Nothing re-implements it.

## Local verification environment

Already provisioned; recreate only if missing.

```bash
SCRATCH=/private/tmp/claude-501/-Users-micha-Documents-Arbeit-CPLAN/d4755d41-9992-4119-874a-3e2416507424/scratchpad
python3 -m venv $SCRATCH/venv
$SCRATCH/venv/bin/pip install -q fastapi uvicorn sqlalchemy 'pydantic>=2' python-multipart itsdangerous duckdb pandas
```

Start the studio (background) against the 40-row snapshot:

```bash
$SCRATCH/venv/bin/python pipeline/scripts/start_cplan.py \
  --settings data/cplan-settings.json --port 8781
```

Serves the studio at `http://127.0.0.1:8781/`. `data/cplan-settings.json` already
points at `data/cplan.sqlite3` with an absolute path.

Test commands used throughout:

```bash
node --test tests/analytics.test.js
python3 -m unittest tests.test_studio_list -v
python3 -m unittest tests.test_studio tests.test_studio_list tests.test_studio_drawer tests.test_studio_flows tests.test_studio_pack
```

Note: `python3 -m unittest discover -s tests` reports 19 import errors on macOS
for backend modules (`sqlalchemy`, `psycopg`) that are not installed in the
system interpreter. Those are unrelated to this work — use the five studio
modules above as the gate.

---

### Task 1: The issue rule in `analytics.js`

**Files:**
- Modify: `pipeline/studio/analytics.js:15-51` (add predicates + `rowIssues`), and the export block at the end of the file
- Test: `tests/analytics.test.js`

**Interfaces:**
- Consumes: existing `planningCompleteness(row)`, `parseDate(value)` in the same module
- Produces:
  - `isShortNotice(row) -> boolean`
  - `hasInvalidDates(row) -> boolean`
  - `rowIssues(row) -> Array<{kind: 'invalid-date'|'short-notice'|'missing', field: string, leadDays?: number}>`

  All three exported on the module object (`analytics.rowIssues`, and
  `window.CplanAnalytics.rowIssues` in the browser).

- [ ] **Step 1: Write the failing tests**

Append to `tests/analytics.test.js`. The `base` fixture at the top of that file
is `source_type: 'internal'` and is missing `region`, `time_zone`, `audience`
and `business_division` — verified: `planningCompleteness(base)` returns
`{score: 71, missing: ['region','time_zone','audience','business_division']}`.

```javascript
// --- Issue rule (rowIssues + the two date predicates) ---

const complete = {
  ...base,
  region: 'EMEA',
  time_zone: 'Europe/Zurich',
  audience: '1000',
  business_division: 'GWM'
};

test('a fully complete, well-dated, long-notice row has no issues', () => {
  assert.deepEqual(analytics.rowIssues(complete), []);
});

test('isShortNotice is true below seven days and false at seven and above', () => {
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 0}), true);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 6}), true);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 7}), false);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 22}), false);
});

test('isShortNotice ignores absent and negative lead times', () => {
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: null}), false);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: ''}), false);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: -3}), false);
});

test('hasInvalidDates is true only when the end precedes the start', () => {
  assert.equal(analytics.hasInvalidDates(complete), false);
  assert.equal(analytics.hasInvalidDates({
    ...complete,
    start_date: '2026-08-01T09:00:00+02:00',
    end_date: '2026-07-31T09:00:00+02:00'
  }), true);
  assert.equal(analytics.hasInvalidDates({...complete, end_date: ''}), false);
});

test('rowIssues puts the date error first, then short notice, then missing fields', () => {
  const row = {
    ...base,
    start_date: '2026-08-01T09:00:00+02:00',
    end_date: '2026-07-31T09:00:00+02:00',
    planning_lead_days: 2
  };
  const issues = analytics.rowIssues(row);

  assert.deepEqual(issues[0], {kind: 'invalid-date', field: 'end_date'});
  assert.deepEqual(issues[1], {kind: 'short-notice', field: 'start_date', leadDays: 2});
  assert.deepEqual(issues.slice(2), [
    {kind: 'missing', field: 'region'},
    {kind: 'missing', field: 'time_zone'},
    {kind: 'missing', field: 'audience'},
    {kind: 'missing', field: 'business_division'}
  ]);
});

test('rowIssues follows the variant split for missing fields', () => {
  assert.deepEqual(analytics.rowIssues({...base, planning_lead_days: 22}), [
    {kind: 'missing', field: 'region'},
    {kind: 'missing', field: 'time_zone'},
    {kind: 'missing', field: 'audience'},
    {kind: 'missing', field: 'business_division'}
  ]);
  assert.deepEqual(analytics.rowIssues({...base, source_type: 'external', planning_lead_days: 22}), [
    {kind: 'missing', field: 'region'},
    {kind: 'missing', field: 'time_zone'}
  ]);
});

test('rowIssues reports both a date finding and completeness gaps on the same row', () => {
  const issues = analytics.rowIssues({...base, planning_lead_days: 3});
  assert.equal(issues.filter(i => i.kind === 'short-notice').length, 1);
  assert.equal(issues.filter(i => i.kind === 'missing').length, 4);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/analytics.test.js`
Expected: FAIL — `TypeError: analytics.rowIssues is not a function`

- [ ] **Step 3: Implement the rule**

Insert into `pipeline/studio/analytics.js` immediately after `planningCompleteness`
(which currently ends at line 51):

```javascript
  // A row lands in a review list for reasons that have nothing to do with
  // completeness: an end date before its start, or under a week of lead time.
  // Both predicates were inlined at three call sites in app.js; they live here
  // so the overview queue, the workbench filter and rowIssues cannot drift.
  const SHORT_NOTICE_DAYS = 7;

  function isShortNotice(row) {
    const lead = Number(row && row.planning_lead_days);
    return Number.isFinite(lead) && lead >= 0 && lead < SHORT_NOTICE_DAYS;
  }

  function hasInvalidDates(row) {
    const start = parseDate(row && row.start_date);
    const end = parseDate(row && row.end_date);
    return Boolean(start && end && end < start);
  }

  // Every reason this row is flagged, in one fixed order: hard date error,
  // then short notice, then missing fields in required-set order. The order is
  // deliberately NOT queue-aware -- a row must read the same wherever it
  // appears or the Issue column cannot be learned. Descriptors carry no
  // user-facing copy; app.js owns the wording.
  function rowIssues(row) {
    const issues = [];
    if (hasInvalidDates(row)) issues.push({kind: 'invalid-date', field: 'end_date'});
    if (isShortNotice(row)) {
      issues.push({kind: 'short-notice', field: 'start_date', leadDays: Number(row.planning_lead_days)});
    }
    planningCompleteness(row).missing.forEach(field => issues.push({kind: 'missing', field}));
    return issues;
  }
```

Note `Number(row && row.planning_lead_days)`: `Number(null)` is `0` and
`Number('')` is `0`, so the `Number.isFinite` check alone would wrongly accept
both. `parseDate` already returns `null` for empty input, so `hasInvalidDates`
needs no extra emptiness guard.

Then extend the export block at the end of the file — add the three names after
`requiredFor`:

```javascript
    requiredFor,
    rowIssues,
    isShortNotice,
    hasInvalidDates
  };
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/analytics.test.js`
Expected: PASS, `# fail 0`

- [ ] **Step 5: Commit**

```bash
git add pipeline/studio/analytics.js tests/analytics.test.js
git commit -m "Give analytics.js one rule for why a row is flagged

rowIssues() returns presentation-free descriptors for every finding on a
row -- date error, short notice, missing fields -- in one fixed order.
The two date predicates were inlined at three call sites in app.js and
move here alongside the completeness rule they belong with, so the
overview queue, the workbench filter and the new Issue column cannot
drift apart."
```

---

### Task 2: Issue column replaces Readiness

**Files:**
- Modify: `pipeline/studio/app.js` — add `issueLabel`/`issueChips` near `missingLabels` (line 438); rewire `renderOverview` (lines 464-465), `matchesQueueFilter` (lines 645-646) and the table render in `applyActivityFilters` (lines 661-667)
- Modify: `pipeline/studio/index.html:148` — table header cell
- Modify: `pipeline/studio/styles.css:147-149` — replace the orphaned `.missing-chip` rules
- Test: `tests/test_studio_list.py`

**Interfaces:**
- Consumes: `A.rowIssues`, `A.isShortNotice`, `A.hasInvalidDates` from Task 1; existing `FIELD_LABELS`, `esc`
- Produces:
  - `issueLabel(issue) -> string`
  - `issueChips(id, issues) -> string` (HTML)
  - `ISSUE_CHIPS_SHOWN = 2`

  Task 4 reuses `issueLabel`.

- [ ] **Step 1: Write the failing test**

Replace `test_readiness_badge_uses_the_pastel_dot_contract` in
`tests/test_studio_list.py` (lines 61-77) with the Issue-chip contract, and add
the call-site guard:

```python
    def test_issue_column_renders_chips_that_carry_a_fix_target(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # Every chip is a real button carrying the row id and the field it
        # fixes, so the existing delegated [data-fix-id] handler drives it
        # with no extra wiring.
        self.assertIn('class="issue-chip ${esc(issue.kind)}"', app)
        self.assertIn('data-fix-id="${esc(id||\'\')}"', app)
        self.assertIn('data-fix-field="${esc(issue.field)}"', app)
        # Overflow chip still points at a field rather than being inert.
        self.assertIn("if (rest.length) shown.push(chip(rest[0], `+${rest.length}`", app)
        # Clean rows keep the quiet em dash.
        self.assertIn('<span class="readiness-ok">—</span>', app)
        # The cell opts out of the table's nowrap so two chips plus overflow
        # are not clipped by the td ellipsis.
        self.assertIn('<td class="issue-cell">${issueCell}</td>', app)

        # Retired: the count-only badge and its tooltip-as-only-detail.
        self.assertNotIn("${ready.missing.length} missing</button>", app)
        # Retired class from the pre-kit-pass markup.
        self.assertNotIn('class="missing-chip"', app)

    def test_issue_wording_lives_in_app_js_not_analytics(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        analytics = (DASHBOARD / "analytics.js").read_text(encoding="utf-8")

        # analytics.js returns descriptors only -- all copy is app.js's.
        self.assertIn("'End before start'", app)
        self.assertIn("${issue.leadDays}d lead", app)
        self.assertNotIn("End before start", analytics)
        # Match the interpolation, not the bare words: analytics.js:42 already
        # contains "and lead" in a prose comment, so a plain "d lead" needle
        # would fire on that.
        self.assertNotIn("}d lead", analytics)

    def test_date_predicates_are_called_not_reinlined(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # One rule, three call sites: overview queue groups and the workbench
        # queue filter both defer to analytics.js.
        self.assertIn("rows.filter(A.isShortNotice)", app)
        self.assertIn("rows.filter(A.hasInvalidDates)", app)
        self.assertIn("if (state.queueFilter==='short-notice') return A.isShortNotice(row);", app)
        self.assertIn("if (state.queueFilter==='invalid-date') return A.hasInvalidDates(row);", app)
        # The old inline copies are gone.
        self.assertNotIn("const l=Number(row.planning_lead_days);return Number.isFinite(l)", app)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_studio_list -v`
Expected: FAIL on `test_issue_column_renders_chips_that_carry_a_fix_target` —
`'class="issue-chip ${esc(issue.kind)}"' not found`

- [ ] **Step 3: Add the label and chip helpers**

In `pipeline/studio/app.js`, directly after `missingLabels` (line 438):

```javascript
  // analytics.js keeps the issue rule free of copy; the wording for each
  // descriptor lives here with the rest of the user-facing strings.
  const issueLabel = issue => {
    if (issue.kind === 'invalid-date') return 'End before start';
    if (issue.kind === 'short-notice') return `${issue.leadDays}d lead`;
    return FIELD_LABELS[issue.field] || issue.field;
  };

  // Two chips inline, the remainder folded into one overflow chip that still
  // carries a fix target -- a row with nine gaps must not blow up the column.
  const ISSUE_CHIPS_SHOWN = 2;
  function issueChips(id, issues) {
    const chip = (issue, text, title) =>
      `<button type="button" class="issue-chip ${esc(issue.kind)}" data-fix-id="${esc(id||'')}" data-fix-field="${esc(issue.field)}"${title?` title="${esc(title)}"`:''}>${esc(text)}</button>`;
    const shown = issues.slice(0, ISSUE_CHIPS_SHOWN).map(issue => chip(issue, issueLabel(issue)));
    const rest = issues.slice(ISSUE_CHIPS_SHOWN);
    if (rest.length) shown.push(chip(rest[0], `+${rest.length}`, rest.map(issueLabel).join(', ')));
    return shown.join('');
  }
```

- [ ] **Step 4: Rewire the three date-predicate call sites**

In `renderOverview`, replace lines 464-465:

```javascript
    const shortNoticeRows = rows.filter(A.isShortNotice);
    const invalidRows = rows.filter(A.hasInvalidDates);
```

In `matchesQueueFilter`, replace lines 645-646:

```javascript
    if (state.queueFilter==='short-notice') return A.isShortNotice(row);
    if (state.queueFilter==='invalid-date') return A.hasInvalidDates(row);
```

- [ ] **Step 5: Render the Issue cell**

In `applyActivityFilters`, replace the `const ready=...` / `const readiness=...`
block (lines 662-665) with:

```javascript
      const issues=A.rowIssues(row);
      const issueCell=issues.length
        ? issueChips(row.id,issues)
        : '<span class="readiness-ok">—</span>';
```

In the row template on line 667, replace `<td>${readiness}</td>` with:

```javascript
<td class="issue-cell">${issueCell}</td>
```

In `pipeline/studio/index.html:148`, rename the header cell —
`<th>Readiness</th>` becomes `<th>Issue</th>`.

- [ ] **Step 6: Style the chips**

In `pipeline/studio/styles.css`, replace lines 147-148 (the orphaned
`.missing-chip` rules) with:

```css
/* Issue column: one neutral chip surface; a 2px left bar carries the severity,
   so red stays reserved for the single finding that is a genuine error. */
.issue-chip{display:inline-block;max-width:150px;margin:0 4px 2px 0;padding:3px 7px;border:0;border-left:2px solid var(--bronze-1);border-radius:var(--radius);background:var(--surface);color:var(--bronze-3);font-size:10px;font-weight:700;vertical-align:middle;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
.issue-chip:hover{background:var(--grey-1);color:var(--black)}
.issue-chip.short-notice{border-left-color:var(--warning)}
.issue-chip.invalid-date{border-left-color:var(--danger);color:var(--danger)}
/* td is nowrap+ellipsis for every other column; the chips need to wrap. */
td.issue-cell{white-space:normal}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_studio_list -v`
Expected: PASS, all tests OK

Run: `python3 -m unittest tests.test_studio tests.test_studio_list tests.test_studio_drawer tests.test_studio_flows tests.test_studio_pack`
Expected: OK — no other studio guard regressed

- [ ] **Step 8: Commit**

```bash
git add pipeline/studio/app.js pipeline/studio/index.html pipeline/studio/styles.css tests/test_studio_list.py
git commit -m "Show the actual finding in the table instead of a completeness count

The Readiness column reported completeness regardless of why the row was
listed, so a row reached from \"activities on short notice\" showed
\"3 missing\" and jumped to activity_description -- a different issue than
the one clicked. The column is now Issue and renders the findings
themselves as chips, each carrying the field that fixes it."
```

---

### Task 3: Queue context bar

**Files:**
- Modify: `pipeline/studio/index.html:145-147` — new bar between `.filterbar` and the table card
- Modify: `pipeline/studio/app.js` — `renderQueueBar`, called from `applyActivityFilters`; shared filter-id list and clear handlers near lines 2183-2187
- Modify: `pipeline/studio/styles.css` — `.queue-bar` rules
- Test: `tests/test_studio_list.py`

**Interfaces:**
- Consumes: `state.queueFilter`, `QUEUE_FILTER_LABELS` (line 650), `A.planningCompleteness`, `FIELD_LABELS`, `fmtNum`
- Produces: `renderQueueBar(rows)`, `ACTIVITY_FILTER_IDS`, `clearActivityFilters()`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_studio_list.py`:

```python
    def test_queue_bar_is_gated_on_the_queue_filter(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # The bar exists only while the user is inside a review list; the
        # ordinary workbench is visually unchanged.
        self.assertIn("if(!state.queueFilter){bar.hidden=true;return;}", app)
        self.assertIn("renderQueueBar(rows);", app)
        # Counts describe what is on screen, not the whole dataset, so they
        # stay truthful when the queue is combined with a search or filter.
        self.assertIn("${fmtNum(rows.length)} in view", app)
        # The old inline suffix on the result count is retired.
        self.assertNotIn("— Clear to remove", app)

    def test_both_clear_controls_share_one_reset(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # The filter id list existed twice inline; one constant now, used by
        # the filter-change binding and by both clear buttons.
        self.assertIn("const ACTIVITY_FILTER_IDS=[", app)
        self.assertIn("function clearActivityFilters()", app)
        self.assertIn("document.getElementById('queue-bar-clear').onclick=", app)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_studio_list -v`
Expected: FAIL on `test_queue_bar_is_gated_on_the_queue_filter` —
`"if(!state.queueFilter){bar.hidden=true;return;}" not found`

- [ ] **Step 3: Add the markup**

In `pipeline/studio/index.html`, insert directly after the closing `</div>` of
`.filterbar` (after line 146) and before the `<article class="card">`:

```html
        <div class="queue-bar" id="activity-queue-bar" hidden>
          <span class="severity-line" id="queue-bar-severity"></span>
          <div>
            <div class="queue-bar-title" id="queue-bar-title"></div>
            <div class="queue-bar-meta" id="queue-bar-meta"></div>
          </div>
          <button class="btn secondary" type="button" id="queue-bar-clear">Clear</button>
        </div>
```

- [ ] **Step 4: Render the bar**

In `pipeline/studio/app.js`, add directly after `applyActivityFilters` closes:

```javascript
  // Names the review list the user arrived from. Everything it reports is
  // computed over the rows actually on screen, so combining the queue with a
  // search term does not leave a stale headline behind.
  function renderQueueBar(rows) {
    const bar=document.getElementById('activity-queue-bar');
    if(!state.queueFilter){bar.hidden=true;return;}
    let detail='';
    if(state.queueFilter==='incomplete'){
      const counts=new Map();
      rows.forEach(row=>A.planningCompleteness(row).missing.forEach(field=>counts.set(field,(counts.get(field)||0)+1)));
      const top=Array.from(counts.entries()).sort((a,b)=>b[1]-a[1])[0];
      if(top)detail=`Largest gap: ${FIELD_LABELS[top[0]]||top[0]} (${fmtNum(top[1])})`;
    } else if(state.queueFilter==='short-notice'){
      detail='Under 7 days lead time';
    } else if(state.queueFilter==='invalid-date'){
      detail='End date before start date';
    }
    document.getElementById('queue-bar-severity').className=`severity-line ${state.queueFilter==='incomplete'?'high':'critical'}`;
    document.getElementById('queue-bar-title').textContent=QUEUE_FILTER_LABELS[state.queueFilter]||state.queueFilter;
    document.getElementById('queue-bar-meta').textContent=`${fmtNum(rows.length)} in view${detail?` · ${detail}`:''}`;
    bar.hidden=false;
  }
```

In `applyActivityFilters`, replace the `queueNote` line (659) and the count line
(660) with:

```javascript
    document.getElementById('activity-result-count').textContent=`${fmtNum(rows.length)} of ${fmtNum(state.rows.length)}`;
    renderQueueBar(rows);
```

- [ ] **Step 5: Share one reset between both clear controls**

In `pipeline/studio/app.js`, add next to `QUEUE_FILTER_LABELS` (line 650):

```javascript
  const ACTIVITY_FILTER_IDS=['activity-search','activity-source','activity-channel','activity-priority','activity-campaign','activity-readiness'];
```

Replace the two inline copies in the binding block (lines 2186-2187) with:

```javascript
    ACTIVITY_FILTER_IDS.filter(id=>id!=='activity-search').forEach(id=>document.getElementById(id).addEventListener('change',runActivityFilters));
    function clearActivityFilters(){
      state.queueFilter=null;
      ACTIVITY_FILTER_IDS.forEach(id=>document.getElementById(id).value='');
      runActivityFilters();
    }
    document.getElementById('activity-clear').onclick=clearActivityFilters;
    // The bar's own Clear drops just the queue -- a user who narrowed the
    // review list with a search should not lose that search too.
    document.getElementById('queue-bar-clear').onclick=()=>{state.queueFilter=null;runActivityFilters();};
```

- [ ] **Step 6: Style the bar**

Append to `pipeline/studio/styles.css`:

```css
/* Queue context bar: says which review list the workbench is currently
   showing. Same three-column shape as .queue-group on the overview card. */
.queue-bar{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;margin-bottom:14px;padding:11px 14px;background:var(--surface-alt);border:1px solid var(--surface)}
.queue-bar-title{font-size:13px;font-weight:600}
.queue-bar-meta{margin-top:2px;font-size:11px;color:var(--grey-4)}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_studio_list -v`
Expected: PASS

Run: `python3 -m unittest tests.test_studio tests.test_studio_list tests.test_studio_drawer tests.test_studio_flows tests.test_studio_pack`
Expected: OK

- [ ] **Step 8: Commit**

```bash
git add pipeline/studio/app.js pipeline/studio/index.html pipeline/studio/styles.css tests/test_studio_list.py
git commit -m "Name the review list the workbench is showing

Arriving from a Review list left the page indistinguishable from the
normal workbench apart from a text suffix on the result count. A context
bar now carries the queue title, how many rows are in view and the
queue's own detail, and both clear controls share one reset."
```

---

### Task 4: Drawer jump bar and field highlight

**Files:**
- Modify: `pipeline/studio/index.html:191` — bar between `#conflict-banner` and `#detail-view`
- Modify: `pipeline/studio/app.js` — split `focusField` (lines 960-978), add `highlightField`/`renderIssueJump`, call from `setDrawerEditing` (line 1752) and `prepareCreateChrome` (line 1239), bind the click handler
- Modify: `pipeline/studio/styles.css` — `.issue-jump` and the pulse keyframe
- Test: `tests/test_studio_list.py`

**Interfaces:**
- Consumes: `issueLabel` from Task 2, `A.rowIssues` from Task 1, existing `focusField`, `msContainer`, `PACK_ROW_TOKEN_RE`, `form()`
- Produces: `fieldElement(name) -> Element|null`, `highlightField(el)`, `renderIssueJump(editing)`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_studio_list.py`:

```python
    def test_focus_field_scrolls_and_highlights(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # A bare .focus() ring is too quiet in a form this dense -- the target
        # is centred in the drawer and pulsed once.
        self.assertIn("function fieldElement(name)", app)
        self.assertIn("box.scrollIntoView({block:'center'})", app)
        self.assertIn("box.classList.add('pulse')", app)
        # Reflow between remove and add, or a second jump to the same field
        # never restarts the animation.
        self.assertIn("void box.offsetWidth;", app)

    def test_jump_bar_follows_the_edit_transition_not_just_open(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # setDrawerEditing is the single funnel for every view<->edit
        # transition, so a row opened read-only and then edited gets the bar
        # too. Rendering it from openDrawer alone would miss that path.
        self.assertIn("renderIssueJump(editing);", app)
        self.assertIn("function renderIssueJump(editing)", app)
        self.assertIn("A.rowIssues(state.selected)", app)
        # Create/duplicate sessions reuse the drawer DOM -- no stale list.
        self.assertIn("renderIssueJump(false);", app)
        # Same label vocabulary as the Issue column.
        self.assertIn("${esc(issueLabel(issue))}</button>", app)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_studio_list -v`
Expected: FAIL on `test_focus_field_scrolls_and_highlights` —
`"function fieldElement(name)" not found`

- [ ] **Step 3: Add the markup**

In `pipeline/studio/index.html`, insert after `#conflict-banner` (line 191) and
before `#detail-view`:

```html
      <div class="issue-jump" id="drawer-issue-jump" hidden></div>
```

- [ ] **Step 4: Split `focusField` and add the highlight**

Replace `focusField` in `pipeline/studio/app.js` (lines 960-978) entirely with:

```javascript
  // Resolving the target and acting on it are separate so the highlight is
  // applied once, at the end, for every branch.
  function fieldElement(name) {
    // T5: pack gap tokens land inside the pack UI -- a row token targets that
    // channel row's input, the channel token the first checkbox.
    const token=PACK_ROW_TOKEN_RE.exec(name||'');
    if(token){
      const rowEl=document.querySelector(`#pack-rows .pack-row[data-channel="${CSS.escape(token[1])}"]`);
      const input=rowEl&&rowEl.querySelector(`[data-pack-${token[2]}]`);
      if(input)return input;
    }
    if(name==='pack_channels')return document.querySelector('#pack-channels input');
    const container=msContainer(name);
    if(container)return container.querySelector('.ms-trigger');
    return form().elements[name]||null;
  }

  // Focus alone is too quiet in a form this dense: the field is centred in the
  // drawer and pulsed once so the jump is visible even mid-form.
  function highlightField(el) {
    const box=el.closest('.f-label,.ms-field,.pack-row')||el;
    box.scrollIntoView({block:'center'});
    box.classList.remove('pulse');
    // Force a reflow, or re-jumping to the same field never restarts the
    // animation -- the class would be removed and re-added within one frame.
    void box.offsetWidth;
    box.classList.add('pulse');
    box.addEventListener('animationend',()=>box.classList.remove('pulse'),{once:true});
  }

  function focusField(name) {
    const el=fieldElement(name);
    if(!el)return;
    if(typeof el.focus==='function')el.focus();
    highlightField(el);
  }
```

- [ ] **Step 5: Render the jump bar**

In `pipeline/studio/app.js`, add directly before `setDrawerEditing` (line 1752):

```javascript
  // Every open finding on the record, as jump targets. Rendered from the
  // edit transition rather than from openDrawer, so a row opened read-only
  // and then switched to edit gets the bar too.
  function renderIssueJump(editing) {
    const bar=document.getElementById('drawer-issue-jump');
    const issues=editing&&state.selected ? A.rowIssues(state.selected) : [];
    if(!issues.length){bar.hidden=true;bar.innerHTML='';return;}
    bar.innerHTML=`<span class="issue-jump-label">To fix:</span>`
      +issues.map(issue=>`<button type="button" class="link-inline" data-jump="${esc(issue.field)}">${esc(issueLabel(issue))}</button>`).join('');
    bar.hidden=false;
  }
```

Inside `setDrawerEditing`, add after `clearCreateAnotherButton();` (line 1761):

```javascript
    renderIssueJump(editing);
```

Inside `prepareCreateChrome`, add after `clearCreateAnotherButton();` (line 1245):

```javascript
    renderIssueJump(false);
```

Bind the clicks in the same block that binds the other drawer controls, next to
the `#drawer-edit` handler (line 2278):

```javascript
    document.getElementById('drawer-issue-jump').addEventListener('click',event=>{
      const btn=event.target.closest('[data-jump]');
      if(!btn)return;
      document.querySelectorAll('#drawer-issue-jump [data-jump]').forEach(el=>el.classList.remove('active'));
      btn.classList.add('active');
      focusField(btn.dataset.jump);
    });
```

- [ ] **Step 6: Style the bar and the pulse**

Append to `pipeline/studio/styles.css`:

```css
/* Drawer jump bar: every open finding on the record, as jump targets. */
.issue-jump{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:10px 22px;background:var(--surface-alt);border-bottom:1px solid var(--surface)}
.issue-jump-label{font-size:10px;font-weight:700;letter-spacing:.02em;color:var(--grey-4)}
.issue-jump .link-inline.active{color:var(--black);text-decoration:underline}
/* One-shot tint on the jumped-to field -- the native focus ring alone is too
   easy to lose in a form this long. */
@keyframes field-pulse{from{background:var(--surface-alt)}to{background:transparent}}
.f-label.pulse,.ms-field.pulse,.pack-row.pulse{animation:field-pulse 1.1s ease-out}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_studio_list -v`
Expected: PASS

Run: `python3 -m unittest tests.test_studio tests.test_studio_list tests.test_studio_drawer tests.test_studio_flows tests.test_studio_pack`
Expected: OK

- [ ] **Step 8: Commit**

```bash
git add pipeline/studio/app.js pipeline/studio/index.html pipeline/studio/styles.css tests/test_studio_list.py
git commit -m "Land the cursor on the field that fixes the issue

Jumping to a field called .focus() and nothing else, so in a form this
long the target was often off-screen behind an unremarkable ring. The
field is now centred and pulsed once, and the drawer carries a jump bar
listing every open finding so several gaps can be worked in sequence."
```

---

### Task 5: Preflight markers and end-to-end verification

**Files:**
- Modify: `check.ps1:34-37` — studio markers
- No test file: this task's deliverable is the click-through evidence

**Interfaces:**
- Consumes: everything from Tasks 1-4

- [ ] **Step 1: Update the preflight markers**

Michael copies files by hand onto the corp machine, and `check.ps1` flags a
stale copy by looking for a string that exists **only** in the current version.
All four studio markers currently match the pre-change files too, so a stale
copy would pass.

`check.ps1`'s own header says a marker is updated in the same commit as its
file. Tasks 1-4 deliberately defer that: the four studio files reach their
final shape only after Task 4, and a marker set at Task 1 would wrongly
accept a half-finished studio for the rest of the branch. The markers land
once here, over the finished set. Nothing between Tasks 1 and 4 is a
copyable state.

In `check.ps1`, replace lines 34-37 with:

```powershell
    @{ Path = "pipeline\studio\app.js";        Marker = "issueLabel";                       Why = "Issue column, queue context bar and drawer jump bar" },
    @{ Path = "pipeline\studio\styles.css";    Marker = "issue-chip";                       Why = "issue chips, queue bar, jump bar and the field pulse" },
    @{ Path = "pipeline\studio\index.html";    Marker = "activity-queue-bar";               Why = "queue context bar, drawer jump bar and the Issue column header" },
    @{ Path = "pipeline\studio\analytics.js";  Marker = "rowIssues";                        Why = "the issue rule app.js reads (A.rowIssues) - an old analytics.js breaks the Issue column and the drawer outright" },
```

`analytics.js` matters most: `app.js` calls `A.rowIssues`, so a stale
`analytics.js` beside a current `app.js` breaks the column and the drawer with
no visible warning.

- [ ] **Step 2: Verify the marker strings actually exist**

```bash
for m in issueLabel issue-chip activity-queue-bar rowIssues; do
  printf '%-22s ' "$m"
  grep -rq "$m" pipeline/studio/ && echo present || echo MISSING
done
```

Expected: all four `present`

- [ ] **Step 3: Run the full local gate**

```bash
node --test tests/analytics.test.js
python3 -m unittest tests.test_studio tests.test_studio_list tests.test_studio_drawer tests.test_studio_flows tests.test_studio_pack
```

Expected: `# fail 0` and `OK`

- [ ] **Step 4: Start the studio and walk the flow**

Start the server per the "Local verification environment" section above, open
`http://127.0.0.1:8781/` with chrome-devtools MCP, then run this in the page.
It asserts the two things the static tests cannot: that a chip opens the drawer,
and that the right field ends up focused.

```javascript
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = [];
  await sleep(1500);

  for (const queue of ['incomplete', 'short-notice', 'invalid-date']) {
    const link = document.querySelector(`[data-queue="${queue}"]`);
    if (!link) { out.push({queue, skipped: 'no findings in this snapshot'}); continue; }

    document.querySelector('.nav-item[data-page="overview"]').click();
    await sleep(300);
    link.click();
    await sleep(600);

    const bar = document.getElementById('activity-queue-bar');
    const chip = document.querySelector('#activity-table-body .issue-chip');
    const expectedField = chip && chip.dataset.fixField;
    chip.click();
    await sleep(600);

    out.push({
      queue,
      barVisible: !bar.hidden,
      barTitle: document.getElementById('queue-bar-title').textContent,
      barMeta: document.getElementById('queue-bar-meta').textContent,
      firstChip: chip.textContent.trim(),
      drawerOpen: document.getElementById('activity-drawer').classList.contains('open'),
      editing: !document.getElementById('activity-form').hidden,
      jumpTargets: [...document.querySelectorAll('#drawer-issue-jump [data-jump]')].map(b => b.textContent),
      expectedField,
      focusedField: document.activeElement && (document.activeElement.name
        || document.activeElement.closest('[data-multiselect]')?.dataset.multiselect
        || document.activeElement.tagName),
      focusMatches: document.activeElement
        && (document.activeElement.name === expectedField
          || Boolean(document.activeElement.closest(`[data-multiselect="${expectedField}"]`)))
    });

    document.querySelector('[data-close-drawer]').click();
    await sleep(300);
  }
  return out;
}
```

Expected for every queue with findings: `barVisible: true`, `barTitle` naming
that queue, `drawerOpen: true`, `editing: true`, a non-empty `jumpTargets`, and
`focusMatches: true`.

The multiselect branch is checked via `[data-multiselect="<field>"]`, the
attribute `msContainer` (app.js:800) actually queries — `region`,
`business_division` and `strategic_objectives` focus a `.ms-trigger` nested
inside that container, not a named form control, so `activeElement.name` is
empty for them and only the `closest()` arm matches.

In the local snapshot the `invalid-date` queue has no findings (all 40 rows
have an end date at or after their start), so that iteration reports
`skipped`. That is expected, not a failure — `incomplete` and `short-notice`
both carry all 40 rows and must pass.

- [ ] **Step 5: Confirm the short-notice regression is gone**

The original defect: arriving from *"activities on short notice"* the row
reported a completeness gap. Run in the page:

```javascript
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  document.querySelector('.nav-item[data-page="overview"]').click();
  await sleep(300);
  document.querySelector('[data-queue="short-notice"]').click();
  await sleep(600);
  const chip = document.querySelector('#activity-table-body .issue-chip');
  return {leadingChip: chip.textContent.trim(), kind: chip.className, target: chip.dataset.fixField};
}
```

Expected: `leadingChip` reads like `0d lead`, `kind` contains `short-notice`,
`target` is `start_date` — the finding the user clicked, not a completeness gap.

- [ ] **Step 6: Commit**

```bash
git add check.ps1
git commit -m "Point the studio preflight markers at the new files

All four studio markers still matched the pre-change files, so a stale
hand-copied studio would have passed the preflight. analytics.js is the
dangerous one: app.js calls A.rowIssues, so an old analytics.js beside a
current app.js breaks the Issue column and the drawer with no warning."
```

- [ ] **Step 7: Push**

```bash
git push origin feature/cplan-v6-postgres
```

---

## Handover note for the corp machine

Michael cannot `git pull` on the corp machine — files are copied by hand. After
this branch lands, the files to copy are:

| File | Raw URL path |
|---|---|
| `pipeline/studio/analytics.js` | `.../feature/cplan-v6-postgres/pipeline/studio/analytics.js` |
| `pipeline/studio/app.js` | `.../feature/cplan-v6-postgres/pipeline/studio/app.js` |
| `pipeline/studio/index.html` | `.../feature/cplan-v6-postgres/pipeline/studio/index.html` |
| `pipeline/studio/styles.css` | `.../feature/cplan-v6-postgres/pipeline/studio/styles.css` |
| `check.ps1` | `.../feature/cplan-v6-postgres/check.ps1` |

`analytics.js` and `app.js` must be copied **together** — `app.js` calls
`A.rowIssues`, which does not exist in the old `analytics.js`. Running
`check.cmd` afterwards reports any file that was missed.
