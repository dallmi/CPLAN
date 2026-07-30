# Studio Overview: Themed Collection Cards & Coming-Up Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the six flat KPI tiles on the studio Overview with four themed
collection cards, and rebuild the `Coming up` card as a scrollable
date-box list over a rolling seven-day window.

**Architecture:** All date arithmetic goes into `pipeline/studio/analytics.js`,
which is a real CommonJS module with a node test file. `pipeline/studio/app.js`
is a browser IIFE with no exports and can only be checked by asserting on its
source text, so it keeps only rendering. CSS goes into
`pipeline/studio/styles.css`; the two containers change class and attributes in
`pipeline/studio/index.html`.

**Tech Stack:** Vanilla ES5-flavoured JS (no build step, no framework, no
bundler), plain CSS with custom properties, `node:test` for module tests,
`unittest`/`pytest` for source-text regression guards.

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-30-overview-themed-cards-and-coming-up-design.md`. Read it before Task 1.
- **All user-facing strings are English.** The app has no German UI.
- **No brand name anywhere** — not in code, identifiers, CSS classes, comments,
  test data or commit messages. Generic terms only.
- **No absolute paths** in any committed file.
- **Colours come from the existing custom properties only** (`styles.css:9`):
  `--primary`, `--primary-dark`, `--grey-1` … `--grey-6`, `--bronze-1` …
  `--bronze-3`, `--surface`, `--surface-alt`, `--row-alt`, `--success`,
  `--warning`, `--danger`, `--info`, `--info-dark`. Do not invent tokens.
  `--bronze-tint` exists in the standalone dashboard and **not** here.
- **`analytics.js` names no user-facing copy** beyond the three day tokens
  introduced in Task 1 (`Today`, `Tomorrow`, weekday names). Every other label
  is written in `app.js`.
- **Run both suites before every commit:**
  - `node --test tests/analytics.test.js`
  - `python3 -m pytest tests/test_studio.py tests/test_studio_list.py -q`
  - Baseline before any change: 32 node tests pass, 40 + n python tests pass.
- **Commit style:** imperative sentence describing the change in plain
  language, no `feat:`/`fix:` prefixes — match the existing log
  (`git log --oneline -10`). End every commit message with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `pipeline/studio/analytics.js` | Testable date/portfolio logic, no copy | Add `comingUp`, `endingWithin`, `relativeDayLabel` |
| `tests/analytics.test.js` | Node unit tests for the above | Add 3 tests |
| `pipeline/studio/app.js` | Rendering only | Add `kpiGroup()`; rewrite the Overview KPI block and the upcoming block; delete the Overview comparison-window wiring |
| `pipeline/studio/index.html` | Overview markup | `#overview-kpis` class; `Coming up` card gains a subtitle, scroll attributes and a footer container |
| `pipeline/studio/styles.css` | Presentation | Add `.kpi-groups`, `.event-*`, `.scroll-y`, flex-column card rules; delete `.kpi-grid.five` and `.week-heading` |
| `tests/test_studio.py` | Source-text regression guards | Add a `OverviewCardsTests` class |

---

## Task 1: Rolling-window helpers in `analytics.js`

**Files:**
- Modify: `pipeline/studio/analytics.js` (add three functions before the
  `return {…}` export block at the end; add the three names to that block)
- Test: `tests/analytics.test.js` (append at end of file)

**Interfaces:**
- Consumes: the module-local `parseDate(value)` already defined at
  `analytics.js:125`, which returns a `Date` or `null`.
- Produces, all reachable from `app.js` as `A.<name>`:
  - `comingUp(rows, now, days) -> Array` — rows whose `start_date` falls in
    `[now, now + days]`, ascending by `start_date`. Rows with missing or
    unparseable `start_date` are dropped, never thrown on.
  - `endingWithin(rows, now, days) -> Array` — rows whose `end_date` falls in
    `[now, now + days]`. Unordered. Rows with no `end_date` are dropped.
  - `relativeDayLabel(date, now) -> string` — `'Today'`, `'Tomorrow'`, or the
    full weekday name (`'Wednesday'`). Returns `''` for an unparseable input.

- [ ] **Step 1: Write the failing tests**

Append to `tests/analytics.test.js`:

```js
test('comingUp holds a rolling window, inclusive at both ends, sorted ascending', () => {
  const now = new Date('2026-08-01T12:00:00Z');
  const at = (id, start) => Object.assign({}, base, {id, start_date: start});
  const rows = [
    at('later', '2026-08-06T09:00:00Z'),
    at('starts-now', '2026-08-01T12:00:00Z'),
    at('past', '2026-07-31T09:00:00Z'),
    at('last-moment', '2026-08-08T12:00:00Z'),
    at('just-beyond', '2026-08-08T12:00:01Z'),
    at('unparseable', 'not a date'),
    at('missing', null)
  ];
  assert.deepEqual(
    analytics.comingUp(rows, now, 7).map(r => r.id),
    ['starts-now', 'later', 'last-moment']
  );
  // A window over nothing is an empty list, not a throw.
  assert.deepEqual(analytics.comingUp([], now, 7), []);
});

test('endingWithin finds what finishes in the window and ignores open-ended rows', () => {
  const now = new Date('2026-08-01T12:00:00Z');
  const at = (id, end) => Object.assign({}, base, {id, end_date: end});
  const rows = [
    at('ends-tomorrow', '2026-08-02T17:00:00Z'),
    at('ended-already', '2026-07-30T17:00:00Z'),
    at('ends-far-out', '2026-09-30T17:00:00Z'),
    at('open-ended', null)
  ];
  assert.deepEqual(
    analytics.endingWithin(rows, now, 7).map(r => r.id),
    ['ends-tomorrow']
  );
});

test('relativeDayLabel compares calendar days, not elapsed hours', () => {
  // Local-time constructors on purpose: the label is about the day a planner
  // sees on the wall, so the boundary that matters is local midnight.
  const now = new Date(2026, 7, 1, 12, 0, 0);            // Sat 1 Aug 2026, midday
  assert.equal(analytics.relativeDayLabel(new Date(2026, 7, 1, 23, 0, 0), now), 'Today');
  assert.equal(analytics.relativeDayLabel(new Date(2026, 7, 2, 1, 0, 0), now), 'Tomorrow');
  assert.equal(analytics.relativeDayLabel(new Date(2026, 7, 5, 9, 0, 0), now), 'Wednesday');
  // Across a month boundary it is still just a weekday — no special case.
  assert.equal(
    analytics.relativeDayLabel(new Date(2026, 8, 1, 9, 0, 0), new Date(2026, 7, 30, 12, 0, 0)),
    'Tuesday'
  );
  assert.equal(analytics.relativeDayLabel(null, now), '');
  assert.equal(analytics.relativeDayLabel('not a date', now), '');
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/analytics.test.js`
Expected: 3 failures, each `TypeError: analytics.<name> is not a function`.

- [ ] **Step 3: Write the implementation**

In `pipeline/studio/analytics.js`, insert directly **after** the
`parseDate` function (which ends at line 129) and **before**
`function fieldValueChanged`:

```js
  const DAY_MS = 86400000;

  // Rolling horizons for the Overview. app.js is a browser IIFE with no
  // exports and can only be checked by asserting on its source text, so the
  // date arithmetic lives here where a node test can actually run it.
  //
  // Rolling, not calendar: "this week" and "the next seven days" name the same
  // thing only on a Monday, and the Overview promises the seven-day reading.
  function comingUp(rows, now, days) {
    const end = new Date(now.getTime() + days * DAY_MS);
    return rows
      .filter(row => {
        const start = parseDate(row.start_date);
        return start && start >= now && start <= end;
      })
      .sort((a, b) => parseDate(a.start_date) - parseDate(b.start_date));
  }

  function endingWithin(rows, now, days) {
    const end = new Date(now.getTime() + days * DAY_MS);
    return rows.filter(row => {
      const finish = parseDate(row.end_date);
      return finish && finish >= now && finish <= end;
    });
  }

  const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  // Calendar days, not elapsed hours: an activity at 23:00 tonight is "Today"
  // and one at 01:00 tomorrow is "Tomorrow", which is how the date reads to
  // the person planning it. Comparing timestamps would call both of them
  // "Today" for two hours and then swap.
  //
  // The subtraction is between two local midnights and is rounded, so the
  // 23- or 25-hour day at a daylight-saving change still yields a whole
  // number of days.
  function relativeDayLabel(date, now) {
    const parsed = parseDate(date);
    if (!parsed) return '';
    const midnight = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const diff = Math.round((midnight(parsed) - midnight(now)) / DAY_MS);
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Tomorrow';
    return WEEKDAYS[parsed.getDay()];
  }
```

Then add the three names to the export object at the end of the file, after
`parseDate,`:

```js
    parseDate,
    comingUp,
    endingWithin,
    relativeDayLabel,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/analytics.test.js`
Expected: `# pass 35`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/studio/analytics.js tests/analytics.test.js
git commit -m "$(cat <<'MSG'
Put the Overview's rolling windows where a test can reach them

app.js cannot be unit-tested, so the seven-day window and the
Today/Tomorrow label move to analytics.js. The label compares local
midnights rather than timestamps, or an activity at 23:00 reads as
tomorrow for the last hour of today.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Task 2: Themed collection cards replace the Overview tiles

**Files:**
- Modify: `pipeline/studio/app.js` — add `kpiGroup()` after `kpi()` (ends line
  541); rewrite the KPI block in `renderOverview`; delete the comparison-window
  wiring
- Modify: `pipeline/studio/index.html:75`
- Modify: `pipeline/studio/styles.css` — add `.kpi-groups` block, delete
  `.kpi-grid.five`
- Test: `tests/test_studio.py`

**Interfaces:**
- Consumes from Task 1: `A.endingWithin(rows, now, days)`.
- Consumes, already present in `renderOverview`: `rows`, `now`, `internal`,
  `external`, `active`, `upcoming`, `quality`, `lead`, `highPriority`,
  `incompleteRows`.
- Produces: `kpiGroup(title, cls, rows)` where `rows` is
  `[{v: string, l: string, derived?: boolean}]`, returning one
  `<div class="kpi-group {cls}">`.

- [ ] **Step 1: Write the failing tests**

`tests/test_studio.py` has no `_slice` helper — it lives in
`tests/test_studio_list.py:10` and is not importable across those files. Add it
to `tests/test_studio.py` directly below the `DASHBOARD = …` line, verbatim:

```python
def _slice(source: str, start_marker: str, end_marker: str) -> str:
    """Source between two verbatim markers; fails loudly if either is missing."""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]
```

Then append a new class to `tests/test_studio.py`:

```python
class OverviewCardsTests(unittest.TestCase):
    """The Overview KPI row is four themed collection cards, display only.

    Reverses the six-flat-tiles decision recorded in app.js. These guards pin
    the parts that a well-meaning refactor would quietly undo: that the cards
    carry no navigation and no deltas, and that the comparison window is gone
    from the Overview but still live on Health.
    """

    def setUp(self):
        self.app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        self.html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        self.css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    def _overview_kpi_block(self) -> str:
        return _slice(self.app, "const cardsHtml = [", "document.getElementById('overview-kpis')")

    def test_overview_renders_four_named_collection_cards(self):
        self.assertIn('class="kpi-groups" id="overview-kpis"', self.html)
        self.assertNotIn('kpi-grid five', self.html)
        block = self._overview_kpi_block()
        for title in ("Portfolio", "In flight", "Readiness", "Lead time"):
            self.assertIn(f"'{title}'", block)

    def test_collection_cards_carry_no_route_and_no_delta(self):
        block = self._overview_kpi_block()
        self.assertNotIn("data-goto", block)
        self.assertNotIn("kpi-trend", block)
        self.assertNotIn("trend(", block)

    def test_seven_day_rows_do_not_claim_to_be_a_calendar_week(self):
        block = self._overview_kpi_block()
        self.assertIn("Starts within 7 days", block)
        self.assertIn("Ends within 7 days", block)
        self.assertNotIn("this week", block.lower())

    def test_empty_portfolio_shows_a_dash_not_a_zero_percent(self):
        block = self._overview_kpi_block()
        # Both rates go through dash(value, guard). Without the guard an empty
        # filter reports "0% complete", which is false: nothing is incomplete
        # when nothing exists.
        self.assertEqual(block.count("dash("), 2)
        self.assertIn("const dash = (value, guard)", self.app)

    def test_comparison_window_leaves_the_overview_but_stays_on_health(self):
        overview = _slice(self.app, "function renderOverview(", "function renderTrend(")
        self.assertNotIn("comparisonWindow", overview)
        self.assertNotIn("renderMovements", self.app)
        self.assertNotIn("windowNoun", self.app)
        # Still wired where it earns its keep.
        self.assertIn("A.comparisonWindow", self.app)

    def test_readiness_accent_is_conditional_not_permanently_amber(self):
        block = self._overview_kpi_block()
        self.assertIn("readinessTone", block)

    def test_five_column_kpi_grid_is_gone(self):
        self.assertNotIn(".kpi-grid.five", self.css)
        self.assertIn(".kpi-groups{", self.css)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_studio.py::OverviewCardsTests -q`
Expected: 7 failures. The first is a `ValueError: substring not found` from
`_slice`, because `const cardsHtml = [` still ends at a different marker —
that is the intended red state.

- [ ] **Step 3: Add the `kpiGroup` helper**

In `pipeline/studio/app.js`, insert directly after the closing brace of
`function kpi(...)` (line 541):

```js
  // Themed collection card: one heading, a stack of figures. Taken from the
  // campaign analytics dashboard, which groups its measures the same way.
  //
  // Display only — no route, no delta. That is the deliberate difference from
  // kpi() above, which is still what the Timeline, Health and Packs pages use.
  function kpiGroup(title, cls, rows) {
    const body = rows.map(r =>
      `<div class="kpi-row${r.derived ? ' derived' : ''}"><span class="v">${esc(r.v)}</span><span class="l">${esc(r.l)}</span></div>`
    ).join('');
    return `<div class="kpi-group ${cls}"><div class="kpi-group-title">${esc(title)}</div>${body}</div>`;
  }
```

- [ ] **Step 4: Delete the comparison-window wiring from `renderOverview`**

Delete these declarations. They are contiguous blocks; delete the explanatory
comments above them too, since the code they explain is going.

1. `app.js:663-696` — everything from `const previous30 = new Date(now);`
   through `const windowNoun = rangeActive ? 'In selected range' : 'Next 30 days';`,
   including the long comment block that opens with
   `// The comparison window follows the range filter.`
2. `app.js:777` — `const share = n => …`
3. `app.js:790` — `const isHigh = row => …`
4. `app.js:795-826` — the `// Only the movements worth looking at get a chip.`
   comment, `const movements = []`, `const trend = …`, `const renderMovements = …`
5. `app.js:827` — `const leadNow = …, leadBefore = …;`
6. `app.js:841-843` — `const highNow …`, `const shortNow …`, `const tone = …`

Leave `A.comparisonWindow` in `analytics.js` and its call at `app.js:1469`
untouched. Leave the `.kpi-trend` rules in `styles.css` untouched — Health
still renders them.

- [ ] **Step 5: Replace the KPI block**

Replace the whole `const cardsHtml = [ … ].join('');` array (`app.js:844-870`,
including every comment inside it) and the render line that follows it with:

```js
    // Four themed collection cards, sixteen figures.
    //
    // This screen carried exactly these four cards once before, and they were
    // replaced by six flat tiles on the argument that sixteen figures cannot
    // rank themselves and the daily planner needs "what do I do next" instead.
    // They are back on request: the reader who asked for them wants the whole
    // portfolio in one scan, and the ranking job the tiles were doing is done
    // one card lower by "Needs you first", which groups findings by type and
    // carries an action per group.
    //
    // What went with the tiles: the routes and the movement chips. Three of the
    // four routes pointed at findings the queue below already lists. The fourth,
    // median lead time to Health, is now two clicks instead of one — accepted.
    //
    // Display only, with one exception: Readiness takes its accent from whether
    // anything is actually open. A permanently amber card is a false alarm on a
    // clean portfolio, which is why .priority-card.danger works the same way.
    // "In flight" counts a rolling seven days, matching "Coming up" below, and
    // its two rows say "within 7 days" rather than naming a calendar week. On a
    // Thursday the two readings share barely a day, and the code computes the
    // rolling one.
    const dash = (value, guard) => (guard ? value : '—');
    const readinessFindings = incompleteRows.length + quality.invalidDateRanges;
    const readinessTone = readinessFindings ? 'readiness' : 'clean';
    const cardsHtml = [
      kpiGroup('Portfolio', 'portfolio', [
        {v: fmtNum(rows.length), l: 'Total activities'},
        {v: fmtNum(internal), l: 'Internal'},
        {v: fmtNum(external), l: 'External'},
        {v: fmtNum(highPriority.length), l: 'Critical and high'}
      ]),
      kpiGroup('In flight', 'inflight', [
        {v: fmtNum(active.length), l: 'Active now'},
        {v: fmtNum(A.comingUp(rows, now, 7).length), l: 'Starts within 7 days'},
        {v: fmtNum(A.endingWithin(rows, now, 7).length), l: 'Ends within 7 days'},
        {v: fmtNum(upcoming.length), l: 'Next 30 days'}
      ]),
      kpiGroup('Readiness', readinessTone, [
        {v: fmtNum(incompleteRows.length), l: 'Incomplete'},
        {v: dash(`${quality.completenessRate}%`, rows.length), l: 'Complete', derived: true},
        {v: fmtNum(quality.missingPackIds), l: 'No pack'},
        {v: fmtNum(quality.invalidDateRanges), l: 'Invalid dates'}
      ]),
      kpiGroup('Lead time', 'leadtime', [
        {v: lead.median === null ? '—' : `${fmtNum(lead.median)}d`, l: 'Median lead'},
        {v: fmtNum(lead.shortNotice), l: 'On short notice'},
        {v: dash(`${lead.shortNoticeRate}%`, rows.length), l: 'Short-notice rate', derived: true},
        {v: fmtNum(lead.excluded), l: 'Excluded'}
      ])
    ].join('');
    document.getElementById('overview-kpis').innerHTML = cardsHtml;
```

Note `internal` and `external` are already counts, not arrays
(`app.js:643-644`), so they take no `.length`.

- [ ] **Step 6: Update the markup**

In `pipeline/studio/index.html:75`, replace:

```html
        <div class="kpi-grid five" id="overview-kpis"></div>
```

with:

```html
        <div class="kpi-groups" id="overview-kpis"></div>
```

- [ ] **Step 7: Update the stylesheet**

In `pipeline/studio/styles.css`, delete the four-line comment beginning
`/* Overview measures: six figures in one row` together with the
`.kpi-grid.five{…}` rule that follows it (lines 344-348), and put this in its
place:

```css
/* Overview measures: four themed collection cards of four figures each. These
   were here before, were replaced by six flat tiles, and are back by request —
   see the note in app.js's renderOverview for why it went both ways. Display
   only: the routes and the movement chips live one card lower now, in "Needs
   you first". */
.kpi-groups{display:grid;grid-template-columns:repeat(4,minmax(210px,1fr));gap:14px;margin-bottom:16px}
.kpi-group{background:var(--white);border:1px solid var(--surface);border-left:3px solid var(--grey-1);padding:14px 16px}
.kpi-group-title{font-size:10px;font-weight:700;letter-spacing:.02em;color:var(--grey-5);margin-bottom:8px}
.kpi-group .kpi-row{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:5px 0;font-size:12px}
.kpi-group .kpi-row .v{font-size:19px;font-weight:300;line-height:1.2}
.kpi-group .kpi-row .l{color:var(--grey-5);text-align:right}
/* A derived figure is read off the ones above it, not counted from the data.
   Dimming it stops the reader treating a rate as a fifth measurement. */
.kpi-group .kpi-row.derived .v,.kpi-group .kpi-row.derived .l{color:var(--grey-4)}
.kpi-group.portfolio{border-left-color:var(--primary)}
.kpi-group.inflight{border-left-color:var(--grey-6)}
.kpi-group.leadtime{border-left-color:var(--bronze-1)}
/* Amber only while something is open — the same rule .priority-card.danger
   follows. A card that is always amber stops meaning anything. */
.kpi-group.readiness{border-left-color:var(--warning)}
.kpi-group.clean{border-left-color:var(--grey-1)}
```

Then add the four-column collapse to the two existing media queries in
`styles.css:68-69`. In the `max-width:1000px` query, change
`.kpi-grid{grid-template-columns:repeat(2,1fr)}` to
`.kpi-grid,.kpi-groups{grid-template-columns:repeat(2,1fr)}`. In the
`max-width:700px` query, change `.kpi-grid{grid-template-columns:1fr 1fr}` to
`.kpi-grid,.kpi-groups{grid-template-columns:1fr 1fr}`.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_studio.py -q`
Expected: 47 passed.

Run: `node --test tests/analytics.test.js`
Expected: `# pass 35`, `# fail 0`.

- [ ] **Step 9: Check the screen in a browser**

Start the studio the way the project already documents it (`README.md`), open
the Overview and confirm by eye:

1. Four cards in one row, each with a coloured left edge and four figures.
2. `Complete` and `Short-notice rate` are visibly dimmer than the rest.
3. No chevrons, no `→`, no green/red delta chips anywhere in the card row.
4. Set the time filter to a range with no activities: `Complete` and
   `Median lead` read `—`, not `0%` and not `0d`.
5. Below 1000px the row becomes two columns and nothing overflows.

- [ ] **Step 10: Commit**

```bash
git add pipeline/studio/app.js pipeline/studio/index.html pipeline/studio/styles.css tests/test_studio.py
git commit -m "$(cat <<'MSG'
Group the Overview figures by theme again

Four collection cards replace six flat tiles. The cards were here
before and lost to the argument that sixteen figures cannot rank
themselves; the ranking is now done a card lower by "Needs you first",
so they come back with the portfolio split and the running count the
tiles never carried.

The routes and the movement chips go with the tiles. Three of the four
routes pointed at findings the queue already lists. Readiness keeps a
conditional accent — a permanently amber card is a false alarm on a
clean portfolio.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Task 3: `Coming up` becomes a scrollable seven-day date-box list

**Files:**
- Modify: `pipeline/studio/app.js` — rewrite the upcoming block
  (currently lines 905-921)
- Modify: `pipeline/studio/index.html:103`
- Modify: `pipeline/studio/styles.css` — add `.event-*` and `.scroll-y` rules
  and the flex-column card rules; delete `.week-heading`
- Test: `tests/test_studio.py`

**Interfaces:**
- Consumes from Task 1: `A.comingUp(rows, now, days)`,
  `A.relativeDayLabel(date, now)`.
- Consumes, already present: `channelColor(channel)` (`app.js:572`),
  `emptyState(svgPath, title, subtext)` (`app.js:527`), `EMPTY_ICONS.calendar`
  (`app.js:520`), `upcoming` (the 30-day list, `app.js:642`), `fmtNum`, `esc`.
- Consumes from Task 2: the `_slice` helper added to `tests/test_studio.py`.
  Task 3's tests use it, so Task 2 must land first.
- Produces: nothing consumed by a later task. This is the last task.

- [ ] **Step 1: Write the failing tests**

Append a second class to `tests/test_studio.py`:

```python
class ComingUpCardTests(unittest.TestCase):
    """Coming up: a seven-day date-box list that scrolls inside its card.

    The eight-row cap it replaces existed only to bound the card's height. The
    scroll container bounds it directly, so these guards pin the parts that
    make the container actually work — and that a keyboard can reach it.
    """

    def setUp(self):
        self.app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        self.html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        self.css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    def _upcoming_block(self) -> str:
        return _slice(self.app, "// Upcoming: a rolling seven days", "document.getElementById('priority-donut')")

    def test_window_is_seven_rolling_days_and_the_row_cap_is_gone(self):
        block = self._upcoming_block()
        self.assertIn("A.comingUp(rows, now, 7)", block)
        self.assertNotIn("UPCOMING_SHOWN", self.app)
        self.assertNotIn("weekKey", self.app)
        self.assertNotIn("week-heading", self.app)
        self.assertNotIn(".week-heading{", self.css)

    def test_row_carries_a_channel_edge_and_a_source_tinted_date_box(self):
        block = self._upcoming_block()
        self.assertIn("event-channel-edge", block)
        self.assertIn("channelColor(row.channel)", block)
        self.assertIn("event-date-box", block)
        self.assertIn("relativeDayLabel", block)
        # The drawer route survives the redesign.
        self.assertIn("data-open-id", block)

    def test_scroll_region_is_reachable_by_keyboard(self):
        card = _slice(self.html, 'id="upcoming-list"', "</article>")
        opening = _slice(self.html, '<div class="card-body flush scroll-y" id="upcoming-list"', ">")
        self.assertIn('tabindex="0"', opening)
        self.assertIn('role="region"', opening)
        self.assertIn("aria-label=", opening)
        # The footer is a sibling of the scroll body, or it scrolls away.
        self.assertIn('id="upcoming-more"', card)

    def test_flex_column_card_can_actually_scroll(self):
        rule = _slice(self.css, "#view-list .grid.two>.card", ".event-row{")
        # min-height:0 is load-bearing: without it the flex child grows to its
        # content instead of scrolling, and the card silently returns to the
        # 988px problem the row cap was invented for.
        self.assertIn("min-height:0", rule)
        self.assertIn("overflow-y:auto", rule)
        # The floor stops the card collapsing when the queue beside it is empty.
        self.assertIn("min-height:360px", rule)
        # Only Coming up scrolls; the queue keeps its own height.
        self.assertIn(".scroll-y", rule)

    def test_empty_state_names_the_seven_day_window(self):
        block = self._upcoming_block()
        self.assertIn("No activities in the next 7 days", block)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_studio.py::ComingUpCardTests -q`
Expected: 5 failures, the first from `_slice` not finding
`// Upcoming: a rolling seven days`.

- [ ] **Step 3: Replace the upcoming render block**

In `pipeline/studio/app.js`, replace everything from the comment
`// Upcoming: grouped by week, channel chip per row.` down to and including the
line ending `'Check back later or widen the planning horizon.');` (lines
905-921) with:

```js
    // Upcoming: a rolling seven days, one date box per row.
    //
    // The eight-row cap this replaces existed only to bound the card's height —
    // sixteen rows made it 988px tall beside a 172px chart and the grid
    // stretched the neighbour to match. The card now scrolls, so the height is
    // bounded directly and there is no reason left to hide rows.
    //
    // The date box comes from the standalone dashboard, which is faster to scan
    // than a text date. The channel colour is the studio's own and stays: as a
    // 3px edge it reads at a glance without putting eight tinted blocks on the
    // screen. Both distinctions survive because they answer different questions
    // — the box says internal or external, the edge says which channel.
    const comingUpRows = A.comingUp(rows, now, 7);
    const beyondWeek = Math.max(0, upcoming.length - comingUpRows.length);
    document.getElementById('upcoming-list').innerHTML = comingUpRows.length
      ? comingUpRows.map(row => {
          const date = A.parseDate(row.start_date);
          const external = row.source_type === 'external';
          const month = date.toLocaleDateString('en-GB', {month: 'short'}).toUpperCase();
          const chip = row.channel
            ? `<span class="chip"><i class="channel-dot" style="background:${channelColor(row.channel)}" aria-hidden="true"></i>${esc(row.channel)}</span>`
            : '';
          return `<div class="event-row" data-open-id="${esc(row.id||'')}">`
            + `<span class="event-channel-edge" style="background:${channelColor(row.channel)}" aria-hidden="true"></span>`
            + `<div class="event-date-box${external?' external':''}"><span class="event-day">${date.getDate()}</span><span class="event-month">${esc(month)}</span></div>`
            + `<div class="event-details"><div class="event-title">${esc(row.activity_name||'Untitled')}</div>`
            + `<div class="event-meta">${esc(A.relativeDayLabel(date, now))} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div>`
            + chip
            + `</div>`;
        }).join('')
      : emptyState(EMPTY_ICONS.calendar, 'No activities in the next 7 days', 'The timeline shows the wider horizon.');
    // Outside the scroll container on purpose: a footer that scrolls away
    // cannot say how much was left off.
    document.getElementById('upcoming-more').innerHTML = beyondWeek
      ? `<div class="list-more">${fmtNum(beyondWeek)} more in the next 30 days · <button type="button" class="linklike" data-goto="overview:timeline">See them on the timeline →</button></div>`
      : '';
```

`.list-more` is reused rather than replaced by a new `.card-foot` class: the
declaration the spec asked for (`padding:11px 16px`, `border-top`, `11px`,
`--grey-5`) is character-for-character what `.list-more` already carries at
`styles.css:381`.

- [ ] **Step 4: Update the markup**

In `pipeline/studio/index.html:103`, replace:

```html
            <article class="card"><div class="card-head"><div><h3>Coming up</h3></div></div><div class="card-body flush" id="upcoming-list"></div></article>
```

with:

```html
            <article class="card"><div class="card-head"><div><h3>Coming up</h3><p>Next 7 days</p></div></div><div class="card-body flush scroll-y" id="upcoming-list" tabindex="0" role="region" aria-label="Coming up in the next 7 days"></div><div id="upcoming-more"></div></article>
```

- [ ] **Step 5: Update the stylesheet**

Delete the `.week-heading{…}` rule at `styles.css:140` — line 919 was its only
caller and it is gone.

Append to `pipeline/studio/styles.css`:

```css
/* Coming up and Needs you first share a grid row, so they share a height. The
   queue sets it and grows with its content; Coming up scrolls inside whatever
   it is given. That is what retired the eight-row cap: the height is bounded
   here now, not by hiding rows. */
#view-list .grid.two>.card{display:flex;flex-direction:column;min-height:360px;margin-bottom:0}
#view-list .grid.two>.card>.card-body{flex:1}
/* min-height:0 is load-bearing. A flex child defaults to min-height:auto and
   grows to its content, so without this line the card does not scroll — it
   just gets tall, which is the exact bug the row cap was invented for. */
#view-list .grid.two>.card>.card-body.scroll-y{min-height:0;overflow-y:auto}
/* The scroll boundary. The local layer scrolls with the content and covers the
   fixed shadow at the end of the list, so the hint disappears once there is
   nothing more to reach. */
.scroll-y{background:linear-gradient(rgba(255,255,255,0),var(--white) 70%) bottom/100% 22px no-repeat local,
          radial-gradient(farthest-side at 50% 100%,rgba(0,0,0,.12),rgba(0,0,0,0)) bottom/100% 9px no-repeat scroll}

/* Upcoming rows. Two colour signals doing two different jobs: the box says
   internal or external, the edge says which channel. Neither is decodable on
   its own — the source type is also in the drawer and the channel name is
   always beside its dot. */
.event-row{position:relative;display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding:11px 16px;border-bottom:1px solid var(--surface);cursor:pointer}
.event-row:last-child{border-bottom:0}
.event-row:hover{background:var(--row-alt)}
.event-channel-edge{position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--grey-1)}
.event-date-box{display:flex;flex-direction:column;align-items:center;justify-content:center;width:48px;height:48px;flex:none;border-radius:var(--radius);background:var(--surface);color:var(--grey-6)}
.event-date-box.external{background:var(--surface-alt);color:var(--bronze-3)}
.event-day{font-size:18px;font-weight:300;line-height:1}
.event-month{font-size:10px;font-weight:600;letter-spacing:.06em}
.event-details{min-width:0}
.event-title{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.event-meta{font-size:11px;color:var(--grey-5);margin-top:2px}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_studio.py tests/test_studio_list.py -q`
Expected: all pass, 52 in `test_studio.py`.

Run: `node --test tests/analytics.test.js`
Expected: `# pass 35`, `# fail 0`.

- [ ] **Step 7: Check the card in a browser**

Open the Overview and confirm:

1. Rows show a date box, a coloured left edge, and the channel chip on the
   right. Internal boxes are grey, external boxes warm.
2. The meta line reads `Today`, `Tomorrow` or a weekday — never a bare date.
3. With more rows than fit, the list scrolls and the footer stays put.
4. `Tab` reaches the list and the arrow keys scroll it.
5. Both cards in the row end at the same height.
6. Clear every finding so `Needs you first` shows its empty state: `Coming up`
   holds at 360px rather than collapsing with its neighbour.
7. Filter to a range with no upcoming activity: the empty state appears and the
   footer is absent.

- [ ] **Step 8: Full check and commit**

```bash
node --test tests/analytics.test.js
python3 -m pytest tests/ -q
```

Then run the brand-name guard exactly as the workspace instructions spell it
out — a case-insensitive whole-word `git grep` for the employer name across the
worktree, and the same word against `git log --oneline -30`. Both must print
nothing.

The literal is deliberately not written here: this file is committed, and a plan
that spells the name out would make the guard match itself on every future run
and report a hit that never clears.

Then:

```bash
git add pipeline/studio/app.js pipeline/studio/index.html pipeline/studio/styles.css tests/test_studio.py
git commit -m "$(cat <<'MSG'
Let Coming up scroll instead of stopping at eight rows

The cap was never about the eighth activity — it was the only way to
stop the card growing to 988px and stretching the queue beside it. A
scroll container bounds the height directly, so every activity in the
window is reachable again.

The window is a rolling seven days and the rows take the standalone
dashboard's date box, which scans faster than a text date. The channel
colour stays as a 3px edge: the box already says internal or external,
and eight tinted blocks would have been a lot of colour for a screen
that is mostly white.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Self-review notes

Checked against the spec section by section:

- Part 1 rows, sources, accents, layout, removals → Task 2, Steps 3-7.
- The `#range-banner` decision (no `kpi-footnote`) needs no work: the banner
  already exists and Task 2 adds nothing under the grid.
- Part 2 window, row, scroll, footer, accessibility, empty state, card head →
  Task 3, Steps 3-5.
- The three `analytics.js` helpers and their tests → Task 1.
- Every spec test-plan bullet appears in Task 2 Step 1 or Task 3 Step 1, except
  the two manual checks, which are Task 2 Step 9 item 4 and Task 3 Step 7 item 6.

Two deliberate deviations from the spec, both narrowing:

1. **`.card-foot` is not introduced.** `.list-more` already carries exactly the
   declaration the spec specified. Reused instead.
2. **The scroll rule is scoped to `.scroll-y`.** The spec's own out-of-scope
   section rules out giving `Needs you first` a scroll container, and an
   unscoped `> .card > .card-body` rule would have given it one.

Four errors found and fixed during this review, all of which would have failed
on the first run:

1. `tests/test_studio.py` has no `_slice` helper — it lives only in
   `tests/test_studio_list.py` and does not cross files. Task 2 Step 1 now adds
   it, and Task 3 records the dependency.
2. The empty-portfolio test counted `"rows.length ?"`, a string the
   implementation never produces once the `dash(value, guard)` helper is used.
   It now counts `dash(` and asserts the helper exists.
3. A comment inside the `cardsHtml` array contained the literal phrase
   `this week`, which the label-regression test forbids in that block. The
   comment moved above the array, where it still explains the choice.
4. The CSS slice ended at `.card-foot`, a marker deviation 1 removes. It now
   ends at `.event-row{`.

Names used across tasks and checked for consistency: `comingUp`,
`endingWithin`, `relativeDayLabel`, `kpiGroup`, `readinessTone`,
`comingUpRows`, `beyondWeek`, `#upcoming-more`, `.scroll-y`,
`.event-channel-edge`, `.event-date-box`, `.kpi-groups`.
