# Executive dashboard boards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three named executive boards as a third skill archive, backed by one new pack file that states the cross-dimension figures the calendar cannot.

**Architecture:** `pipeline/report/agent_pack.py` gains `breakdown_rows`, which iterates the existing `iter_blocks` and trades the week dimension for six measures, writing `06-breakdowns.csv`. A new module `pipeline/report/dashboard_skill.py` holds the board catalogue — an index plus three board files — and builds `cplan-dashboards-skill.zip`. `tests/test_agent_pack.py` gains the test that holds the two together: every `Source:` citation in every board file must resolve against the pack generated in the same run.

**Tech Stack:** Python 3.13, pandas, pytest. No new dependencies. The board text is static Python string constants, like `BRAND_SKILL_TEXT` — nothing is read from disk at build time.

**Spec:** `docs/superpowers/specs/2026-08-07-executive-dashboard-boards-design.md`

## Global Constraints

- **No organisation name anywhere in the repository.** Not in code, comments, docs, test data or commit messages. Use `<ORGANISATION>` where the operator fills one in, or generic wording ("the organisation", "internal platform"). `tests/test_agent_pack.py` already enforces this for the instructions; Task 5 extends it to the board files.
- **Board text is data-free.** No figure, no period, no generation date. Like `BRAND_SKILL_TEXT` and unlike the pack, it is rebuilt identically every run.
- **Prose pack files are `.txt`, never `.md`.** `.md` is not on the crawled-extension list. The new pack file is `.csv`, so this does not bite, but do not "improve" it into Markdown.
- **Values, never formulas. Long, never wide.** Every figure in the pack is computed in Python and written as a literal. One row per block × value × measure; no matrix.
- **Commit message style:** a sentence in the imperative, no `feat:`/`fix:` prefix, a body explaining *why*, and the trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. Match the existing log.
- **Run tests with** `PYTHONPATH=. .venv/bin/python -m pytest` from the repository root.

---

### Task 1: `06-breakdowns.csv`

The pack file that states cross-dimension figures. `04-calendar.csv` carries one dimension against the weeks; nothing carries two dimensions against each other, so "which division binds the most executive attention" is unanswerable from a stated figure today.

**Files:**
- Modify: `pipeline/report/agent_pack.py` (constants near `CALENDAR_HEADER`; new functions after `calendar_rows`; `write_pack`; `_write_skill_zip`)
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: `iter_blocks(scope, config)` yielding `(block, value, overlaps, subset)`; `metrics.pack_stats(frame) -> dict`; `LARGE_AUDIENCE_BANDS`, `BAND_UNKNOWN` from `pipeline.report.config`.
- Produces: `agent_pack.BREAKDOWN_NAME = "06-breakdowns.csv"`, `agent_pack.BREAKDOWN_HEADER`, `agent_pack.BREAKDOWN_MEASURES` (tuple of the six measure names in written order), `agent_pack.TAUTOLOGICAL_MEASURES` (dict block -> tuple of suppressed measures), `agent_pack.breakdown_rows(scope, config) -> list[tuple]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_pack.py`, after `test_breakdown_blocks_are_marked_as_overlapping`. Add the reader helper beside `_calendar`:

```python
def _breakdowns(pack_dir):
    with (pack_dir / agent_pack.BREAKDOWN_NAME).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _figure(rows, block, value, measure):
    """The one figure for a block/value/measure, or None."""
    for row in rows:
        if (row["block"], row["value"], row["measure"]) == (block, value, measure):
            return int(row["figure"])
    return None
```

```python
# ---------------------------------------------------------------------------
# The breakdowns file: the crosses the calendar cannot make
# ---------------------------------------------------------------------------

def test_breakdown_totals_match_the_frame(tmp_path):
    """The TOTAL block restates the portfolio, measure by measure.

    Not a tautology: these six figures are the ones every other block's rows
    are computed the same way, so an error in `_measures` shows up here first
    and against a number the summary already states independently.
    """
    pack_dir, _, scope, _ = _pack(tmp_path)
    rows = _breakdowns(pack_dir)
    frame = scope.frame

    assert _figure(rows, "TOTAL", "all activities", "activities") == len(frame)
    assert _figure(rows, "TOTAL", "all activities", "with_executives") == int(
        frame["has_executives"].sum())
    assert _figure(rows, "TOTAL", "all activities", "unknown_audience") == int(
        (frame["audience_band"] == "Unknown").sum())
    assert _figure(rows, "TOTAL", "all activities", "without_pack") == (
        metrics.pack_stats(frame)["without_pack"])
    assert _figure(rows, "TOTAL", "all activities", "median_completeness") == int(
        frame["completeness"].median())


def test_breakdown_activities_agree_with_the_calendar(tmp_path):
    """Same blocks, same values, same counts -- the week dimension is all that differs.

    Both files come from `iter_blocks`, and this is the assertion that keeps
    them from being two implementations of "what is a block".
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    weekly = {}
    for row in _calendar(pack_dir):
        key = (row["block"], row["value"])
        weekly[key] = weekly.get(key, 0) + int(row["count"])

    for row in _breakdowns(pack_dir):
        if row["measure"] != "activities":
            continue
        key = (row["block"], row["value"])
        assert key in weekly, f"{key} is in the breakdowns and not in the calendar"
        assert int(row["figure"]) == weekly[key], f"{key} disagrees with the calendar"


def test_breakdown_carries_the_same_overlap_warning(tmp_path):
    """A block that overlaps in the calendar overlaps here, and says so.

    The column is the only thing standing between a reader and a sum larger
    than the portfolio, and the two files must not disagree about which blocks
    need it.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    calendar = {(r["block"], r["value"]): r["overlaps"] for r in _calendar(pack_dir)}
    for row in _breakdowns(pack_dir):
        key = (row["block"], row["value"])
        assert row["overlaps"] == calendar[key], f"{key} overlaps differently"


def test_a_measure_that_restates_its_block_is_not_written(tmp_path):
    """A row that cannot be wrong cannot inform either, and still costs retrieval.

    `unknown_audience` under the audience bands is the row's own definition;
    `with_executives` under an executive block is every row in it. The calendar
    already leaves out rows that say nothing -- empty week/value pairs -- for
    exactly this reason.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    rows = _breakdowns(pack_dir)
    assert rows, "the fixture wrote no breakdown rows at all"

    for row in rows:
        suppressed = agent_pack.TAUTOLOGICAL_MEASURES.get(row["block"], ())
        assert row["measure"] not in suppressed, (
            f"{row['block']}/{row['measure']} restates its own block")

    # And the suppression is narrow: the bands still carry the measures that
    # genuinely vary inside them.
    bands = [r for r in rows if r["block"] == "audience_band"]
    assert any(r["measure"] == "with_executives" for r in bands), (
        "suppression removed a measure that varies within the block")


def test_the_reporting_skill_ships_the_breakdowns_file(tmp_path):
    """A table of contents naming a file the archive does not hold is worse than
    no table of contents: the agent looks, fails, and answers from somewhere else.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        assert agent_pack.BREAKDOWN_NAME in archive.namelist()
```

Add the import the tests need at the top of `tests/test_agent_pack.py`, beside the existing `from pipeline.report import agent_pack`:

```python
from pipeline.report import agent_pack, metrics
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k breakdown -v`
Expected: FAIL — `AttributeError: module 'pipeline.report.agent_pack' has no attribute 'BREAKDOWN_NAME'`

- [ ] **Step 3: Add the constants**

In `pipeline/report/agent_pack.py`, beside `CALENDAR_HEADER` (near line 104):

```python
BREAKDOWN_HEADER = ("block", "value", "overlaps", "measure", "figure")

# `figure`, not `count`: five of the six measures are counts and one is a
# median, and a column named `count` holding a median is a lie in the header
# row of a file whose whole point is that a machine reads it.
BREAKDOWN_MEASURES = ("activities", "with_executives", "large_audience",
                      "without_pack", "unknown_audience", "median_completeness")

# Measures that restate the block they sit in. `large_audience` and
# `unknown_audience` under the audience bands are the band's own definition;
# `with_executives` under an executive block is every row in it.
#
# Left out for the reason `calendar_rows` leaves out empty week/value pairs: a
# row that cannot be wrong cannot inform either, and it competes for the same
# retrieval budget as one that can.
TAUTOLOGICAL_MEASURES = {
    "audience_band": ("large_audience", "unknown_audience"),
    "executives": ("with_executives",),
    "executives_geb": ("with_executives",),
    "executives_geb1": ("with_executives",),
}
```

And add `BREAKDOWN_NAME = "06-breakdowns.csv"` to the file-name block beside `ACTIVITIES_CSV_NAME` (near line 95):

```python
BREAKDOWN_NAME = "06-breakdowns.csv"
```

Extend the config import at the top of the module to carry `BAND_UNKNOWN`:

```python
from pipeline.report.config import (
    AUDIENCE_BAND_ORDER,
    BAND_UNKNOWN,
    FIELD_TITLES,
    LARGE_AUDIENCE_BANDS,
    SHORT_NOTICE_DAYS,
)
```

- [ ] **Step 4: Write `breakdown_rows`**

In `pipeline/report/agent_pack.py`, directly after `calendar_rows`:

```python
def _measures(subset):
    """The six figures a breakdown value carries, in written order."""
    return (
        ("activities", len(subset)),
        ("with_executives", int(subset["has_executives"].sum())),
        ("large_audience",
         int(subset["audience_band"].isin(LARGE_AUDIENCE_BANDS).sum())),
        ("without_pack", metrics.pack_stats(subset)["without_pack"]),
        ("unknown_audience", int((subset["audience_band"] == BAND_UNKNOWN).sum())),
        ("median_completeness", int(subset["completeness"].median())),
    )


def breakdown_rows(scope, config):
    """One row per block x value x measure -- the crosses the calendar cannot make.

    `04-calendar.csv` carries one dimension at a time against the weeks, so a
    question crossing two of them -- "which division binds the most executive
    attention" -- can only be answered by counting `05-activities.csv` by hand,
    which the instructions rightly discourage. These are the same blocks, from
    the same `iter_blocks`, with the week dimension traded for a few measures.

    Empty subsets are skipped rather than written as zeros. An empty scope
    yields the TOTAL block over an empty frame, and a median over no rows is
    not a figure at all.
    """
    rows = []
    for block, value, overlaps, subset in iter_blocks(scope, config):
        if subset.empty:
            continue
        suppressed = TAUTOLOGICAL_MEASURES.get(block, ())
        for measure, figure in _measures(subset):
            if measure in suppressed:
                continue
            rows.append((block, value, "yes" if overlaps else "no", measure, figure))
    return rows
```

- [ ] **Step 5: Wire it into the pack and the reporting skill**

In `write_pack`, beside the other `_write_csv` calls:

```python
    _write_csv(pack_dir / BREAKDOWN_NAME, BREAKDOWN_HEADER,
               breakdown_rows(scope, config))
```

In `_write_skill_zip`, add it to the tuple of shipped names:

```python
        for name in (GLOSSARY_NAME, SUMMARY_NAME, QUALITY_NAME,
                     CALENDAR_NAME, BREAKDOWN_NAME, ACTIVITIES_CSV_NAME):
```

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -v`
Expected: PASS, including the pre-existing tests. `test_the_pack_is_rewritten_in_place` and `test_an_empty_scope_still_writes_a_readable_pack` exercise the new file for free.

- [ ] **Step 7: Commit**

```bash
git add pipeline/report/agent_pack.py tests/test_agent_pack.py
git commit -m "$(cat <<'EOF'
Cross two dimensions in a file, since the calendar crosses none

The calendar carries one dimension at a time against the weeks. Which
division binds the most executive attention is a cross of two blocks, and
no file states it -- so the only route to it is counting the activities
file by hand, which the instructions discourage for good reason.

Same blocks, from the same iter_blocks the calendar already iterates, with
the week dimension traded for six measures. The overlaps column carries
the same warning, because a reader adding a division block up gets a
number larger than the portfolio either way.

Measures that restate their own block are left out, the way empty
week/value pairs already are: a row that cannot be wrong cannot inform,
and it costs the same retrieval budget as one that can.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The `cplan-dashboards` skill archive

The board catalogue: an index that routes a request to a board, and three board files. Its own module because `agent_pack.py` is already ~1350 lines and this adds four documents' worth of text; the boards are also the part most likely to be edited on its own.

**Files:**
- Create: `pipeline/report/dashboard_skill.py`
- Modify: `pipeline/report/agent_pack.py` (`write_pack`, and one constant)
- Modify: `pipeline/scripts/build_agent_pack.py:129-131`
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime — the board text names `06-breakdowns.csv` as a literal, and Task 3 is what proves the two agree.
- Produces: `dashboard_skill.SKILL_NAME = "cplan-dashboards"`, `dashboard_skill.SKILL_TEXT` (the index, becomes `SKILL.md`), `dashboard_skill.BOARDS` (a `dict[str, str]` of archive filename -> file text, keys `board-portfolio-overview.md`, `board-leadership-attention.md`, `board-plan-trust.md`), `dashboard_skill.write_zip(zip_path) -> None`, and `agent_pack.DASHBOARD_SKILL_ZIP_NAME = "cplan-dashboards-skill.zip"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_pack.py`, after `test_the_chart_rules_ship_as_their_own_skill`:

```python
def test_the_boards_ship_as_their_own_skill(tmp_path):
    """A third archive: which panels make a board, beside how to draw and what
    the numbers are.

    Not folded into `chart-standards`, which is deliberately free of both data
    and organisation and is reusable by anything that draws. A board names pack
    files and column values, so merging the two would weld the reusable half to
    the project-specific half and force a re-upload of the visual standards
    every time a board changed.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.DASHBOARD_SKILL_ZIP_NAME) as archive:
        names = archive.namelist()
        skill = archive.read("SKILL.md").decode("utf-8")
        boards = {name: archive.read(name).decode("utf-8")
                  for name in names if name != "SKILL.md"}

    assert skill.startswith("---\nname: cplan-dashboards\n")
    assert sorted(boards) == ["board-leadership-attention.md",
                              "board-plan-trust.md",
                              "board-portfolio-overview.md"]

    description = next(line for line in skill.splitlines()
                       if line.startswith("description:"))
    assert len(description) <= 1024 + len("description: "), "description over the cap"
    for trigger in ("dashboard", "board", "executive"):
        assert trigger in description, f"nothing routes {trigger!r} to this skill"

    # The index routes; it does not hold the panels.
    for name in boards:
        assert name in skill, f"{name} is in the archive and not in the index"


def test_each_board_spends_the_red_budget_exactly_once(tmp_path):
    """The instructions permit two red elements in an image; a board permits one.

    Stricter than the rule it implements, and deliberately: "at most two" is a
    budget an improvising agent spends without noticing -- the 2026-08-06 test
    render put red on five charts and five tile numbers -- while "this panel,
    no other" is a property of the board that can be checked before drawing.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.DASHBOARD_SKILL_ZIP_NAME) as archive:
        for name in archive.namelist():
            if name == "SKILL.md":
                continue
            text = archive.read(name).decode("utf-8")
            highlights = [line for line in text.splitlines()
                          if line.strip().startswith("Highlight:")]
            assert highlights, f"{name} declares no highlight at all"
            chosen = [line for line in highlights if line.strip() == "Highlight: yes"]
            assert len(chosen) == 1, (
                f"{name} spends the red budget {len(chosen)} times, not once")


def test_every_panel_carries_the_whole_contract(tmp_path):
    """Five fields, each doing one job. A panel missing one is a panel the agent
    improvises, which is the failure the boards exist to remove.

    The executive read-out keeps all five rather than becoming an exception --
    its `Source:` line is the list of figures it is allowed to state, which is
    how "say each figure once" becomes checkable without rendering anything.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.DASHBOARD_SKILL_ZIP_NAME) as archive:
        for name in archive.namelist():
            if name == "SKILL.md":
                continue
            text = archive.read(name).decode("utf-8")
            panels = re.split(r"^### ", text, flags=re.M)[1:]
            assert panels, f"{name} defines no panels"
            for panel in panels:
                heading = panel.splitlines()[0]
                for field in ("Business question:", "Chart:", "Source:",
                              "Footnote:", "Highlight:"):
                    assert field in panel, f"{name} / {heading}: no {field}"


def test_the_boards_carry_no_organisation_name(tmp_path):
    """The archive is uploaded unmodified, so unlike the instructions file there
    is no placeholder here anyone could fill in.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.DASHBOARD_SKILL_ZIP_NAME) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8")
            assert agent_pack.ORGANISATION_PLACEHOLDER not in text, (
                f"{name} carries a placeholder nobody will replace")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k "boards or contract or red_budget" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'DASHBOARD_SKILL_ZIP_NAME'`

- [ ] **Step 3: Create the module with the index**

Create `pipeline/report/dashboard_skill.py`:

```python
"""The board catalogue: which panels make up a named executive board.

Three skills reach the agent, split by what each is about. `cplan-reporting`
says what the numbers are. `chart-standards` says how anything is drawn, and is
free of both data and organisation so it can be lifted elsewhere unchanged.
This one says which panels, in which order, from which pack line, make up a
board somebody asked for by name.

The split is not tidiness. Asked for "an executive dashboard" with no board
named, the agent decides every panel afresh, and a fresh decision is where a
rule gets dropped: a test render on 2026-08-06 put five tile numbers in Accent
red, a heading in capitals, and red on all five charts, against instructions
that forbid each in plain words. Naming the board fixes the panel list before
the drawing starts, so the rules apply to a known set.

Data-free, like `chart-standards` and unlike the pack: no figure, no period, no
generation date. It is rebuilt identically every run and re-uploaded only when
a board changes. What it does carry is a citation per panel -- file, block,
label -- and `tests/test_agent_pack.py` resolves every one of them against the
pack generated in the same run, so renaming a summary row breaks the build
rather than leaving a board pointing at a line that no longer exists.
"""

import zipfile

SKILL_NAME = "cplan-dashboards"

SKILL_TEXT = """---
name: cplan-dashboards
description: The named executive boards this agent can draw - which panels make up each one, in what order, and which pack line every figure comes from. Load whenever a dashboard, a board, an executive overview or a one-page summary is asked for, whenever a request names one of the three boards, and before drawing any image holding more than one chart.
---

# CPLAN executive boards

Three boards. Each answers one decision, and a board that tried to answer all
three would answer none — which is what an unnamed "executive dashboard"
becomes.

| Board | The decision it serves | File |
|---|---|---|
| Portfolio overview | Is the plan as a whole plausible? | `board-portfolio-overview.md` |
| Leadership attention | Where is executive time going, and where is it missing? | `board-leadership-attention.md` |
| Plan trust | What can I not yet rely on? | `board-plan-trust.md` |

Open the file for the board being asked for and draw exactly the panels it
lists, in the order it lists them. If the request names no board, say which
three exist and what each decides, and ask which one — do not blend them.

You still need the other two skills: `cplan-reporting` for the pack itself, and
`chart-standards` for how anything is drawn. This file says only which panels.

## How to read a panel

Every panel carries five fields, and each does one job.

- **Business question** — printed on the panel, under its heading.
- **Chart** — fixed. Not a choice to make again per run.
- **Source** — where the figure comes from. Read it; do not compute it.
- **Footnote** — the caveat this figure carries, printed under the panel.
- **Highlight** — whether this is the panel that gets the one red element.

## Reading a Source line

A citation names a file, then a block, then a label:

    01-summary.txt · LOAD · Activities in the peak week

Some name a file and a block only, when the panel plots the whole block:

    03-data-quality.txt · RECORD ANOMALIES

For `06-breakdowns.csv` the block form carries the measure, since a block there
holds several measures and a panel plots one:

    06-breakdowns.csv · block=region_group · measure=activities

Several citations on one line are separated by `;` and each stands alone.

A percentage of two cited figures is fine, and say both. `01-summary.txt`
prints a share only beside its VOLUME rows, so "39% record leadership
involvement" is one division between two audited counts. That is not the same
as deriving a figure from `05-activities.csv`, which remains the thing not to
do.

## The rules that hold across all three boards

**One red element per board, on the panel marked `Highlight: yes`.** Every
other panel is grey throughout — bars, lines, markers, numbers. Your
instructions allow two in an image; a board allows one. Tile numbers are black,
always: there is no board on which a red number is right.

**A number tile is only for a figure with no chart on the board.** A tile
restating the tallest bar beside it is a tile to delete. This is why no board
carries a peak-week tile next to its volume chart.

**The read-out states only the figures its own `Source:` line names.** Anything
else on the board has already been said better by the panel that plots it.

**Sentence case everywhere**, including the board title and every panel
heading. `Executive read-out`, never `EXECUTIVE READ-OUT`.

**Every board footer is the one your instructions require** — the data vintage
and the team signature, on one line, drawn as ordinary footnote text.

## Before you send a board

On top of the checklist in `chart-standards`:

1. Is exactly one panel red, and is it the one the board file marks?
2. Is every number tile black?
3. Does the board carry a panel the file does not list, or miss one it does?
4. Does any figure appear in two panels?
5. Does every panel print its business question and its footnote?

A board failing one of these is redrawn, not explained.
"""
```

- [ ] **Step 4: Add the three board texts and the zip builder**

Append to `pipeline/report/dashboard_skill.py`:

```python
PORTFOLIO_OVERVIEW = """# Board — Portfolio overview

**The decision:** is the plan as a whole plausible? This is the quarterly
read-out: volume, distribution, and the risks visible from the portfolio level.

Five panels. Panel 1 is a tile row across the top, panels 2–4 sit in a row
beneath it, panel 5 closes the board.

### Panel 1 — Number tiles

Business question: What is in the plan?
Chart: number tiles, one row, aligned on the baseline of the numbers
Source: 01-summary.txt · VOLUME · Activities in scope; 01-summary.txt · VOLUME · Internal; 01-summary.txt · VOLUME · External; 01-summary.txt · PLANNING DISCIPLINE · Median lead time (days); 01-summary.txt · LOAD · Share in the five busiest weeks
Footnote: Every figure is a count of activities within the period named at the top of the summary.
Highlight: no

### Panel 2 — Volume by start week

Business question: Where is planned communication volume concentrated?
Chart: line chart, one point per ISO week, the peak week marked
Source: 04-calendar.csv · block=TOTAL
Footnote: Each activity counts once, in the week it starts. A six-week campaign is one point, not six.
Highlight: yes

### Panel 3 — Planned audience size

Business question: What scale of audience is planned?
Chart: horizontal bar, in band order — not sorted by value
Source: 06-breakdowns.csv · block=audience_band · measure=activities
Footnote: A planning estimate, never measured reach. The bands partition the portfolio; Unknown is one of them.
Highlight: no

### Panel 4 — Regional distribution

Business question: Where are activities planned?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=region_group · measure=activities
Footnote: An activity naming several regions appears under each; the bars do not sum to the portfolio.
Highlight: no

### Panel 5 — Executive read-out

Business question: What should a reader take away?
Chart: none (prose), four to five sentences
Source: 01-summary.txt · LOAD · Median activities per week; 01-summary.txt · LOAD · Weeks with no activity; 01-summary.txt · LOAD · Longest run of empty weeks; 01-summary.txt · LEADERSHIP AND AUDIENCE · Large audience (top two bands)
Footnote: none
Highlight: no

## What this board does not do

No peak-week tile: panel 2 says it, and better. No restating the five-busiest-
weeks share in the read-out; it is already a tile. No channel panel — channels
have their own reading rules and are not on an executive board yet.

Forward planning thins towards the end of the horizon, so the last weeks in
scope read as a collapse when they are merely not yet written. Say that in the
read-out rather than reporting a decline.
"""


LEADERSHIP_ATTENTION = """# Board — Leadership attention

**The decision:** where is executive time going, and where is it missing from
communication that would warrant it?

Five panels. Panel 1 is a tile row, panels 2–4 sit in a row beneath it, panel 5
closes the board.

### Panel 1 — Number tiles

Business question: How much of the plan records leadership involvement?
Chart: number tiles, one row
Source: 01-summary.txt · LEADERSHIP AND AUDIENCE · With GEB/GEB-1 involvement; 01-summary.txt · VOLUME · Activities in scope
Footnote: The share is the first figure over the second. The source field holds both levels and cannot separate them.
Highlight: no

### Panel 2 — Leadership share by division

Business question: Which divisions bind the most executive attention?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=business_division · measure=with_executives
Footnote: An activity naming several divisions appears under each; the bars do not sum to the portfolio.
Highlight: yes

### Panel 3 — Leadership by audience size

Business question: Does leadership involvement follow audience size?
Chart: horizontal bar, in band order — not sorted by value
Source: 06-breakdowns.csv · block=audience_band · measure=with_executives
Footnote: A planning estimate, never measured reach. Read this beside the band totals, not as a share of anything stated here.
Highlight: no

### Panel 4 — Leadership by region

Business question: Where is leadership involvement recorded?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=region_group · measure=with_executives
Footnote: An activity naming several regions appears under each; the bars do not sum to the portfolio.
Highlight: no

### Panel 5 — Executive read-out

Business question: What should a reader take away?
Chart: none (prose), four to five sentences
Source: 01-summary.txt · LEADERSHIP AND AUDIENCE · Large audience (top two bands); 06-breakdowns.csv · block=business_division · measure=activities
Footnote: none
Highlight: no

## What this board does not do

Never say "the GEB". One field holds both GEB and GEB-1 with nothing in the
data separating them, so every label on this board reads GEB/GEB-1, and no
person is ever named — not in a bar, not in a footnote, not in the read-out.

Never present an audience band as reach. Panel 3 compares planning estimates.

Leadership involvement over time is not on this board: no pack file crosses the
executive dimension with the weeks, and a line drawn from the activities file
has not been through the report's rules.
"""


PLAN_TRUST = """# Board — Plan trust

**The decision:** what can a reader not yet rely on, and what is worth chasing
before the plan is used to decide anything?

Five panels. Panel 1 leads at full width, panels 2–4 sit in a row beneath it,
panel 5 closes the board.

### Panel 1 — Field completeness

Business question: Which fields are missing often enough to matter?
Chart: horizontal bar of missing counts, sorted by value
Source: 03-data-quality.txt · FIELD COMPLETENESS
Footnote: A field absent from the export is listed in the glossary as not counted, rather than counted as missing.
Highlight: yes

### Panel 2 — Activities without a pack link, by division

Business question: Where is pack membership not being recorded?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=business_division · measure=without_pack
Footnote: A standalone activity is complete without a pack, which is why planning completeness excludes pack linkage and this is tracked separately.
Highlight: no

### Panel 3 — Median planning completeness by division

Business question: Which divisions fill in the fields they control?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=business_division · measure=median_completeness
Footnote: A median per division; medians never combine, so these bars are read against each other and never added.
Highlight: no

### Panel 4 — Record anomalies

Business question: What is wrong with the records themselves?
Chart: horizontal bar, sorted by value
Source: 03-data-quality.txt · RECORD ANOMALIES
Footnote: Duplicates are counted before de-duplication; the rows the pack holds are already unique.
Highlight: no

### Panel 5 — Executive read-out

Business question: What is the most expensive gap, and what does it cost?
Chart: none (prose), four to five sentences
Source: 01-summary.txt · VOLUME · Unknown; 01-summary.txt · REPORT · Rows read
Footnote: none
Highlight: no

## What this board does not do

A missing pack link is not bad planning. Neither is an archived activity —
archiving is a list-size workaround in the source system, not a relevance
signal — and neither is a quarter or ISO week labelled with the year before the
period, because scope is an overlap test and those columns label the start.

Panels 2 and 3 are both division bars, and that is the point: one counts a
hole, the other measures a fill rate, and a division can be bad at one and fine
at the other. Do not merge them.
"""


BOARDS = {
    "board-portfolio-overview.md": PORTFOLIO_OVERVIEW,
    "board-leadership-attention.md": LEADERSHIP_ATTENTION,
    "board-plan-trust.md": PLAN_TRUST,
}


def write_zip(zip_path):
    """The board catalogue, alone in an archive with no data beside it.

    Nothing here is derived from a run, so it is rebuilt identically every time
    and only needs re-uploading when a board changes -- the same bargain
    `chart-standards` makes, while the report pack beside it goes stale weekly.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SKILL_TEXT)
        for name, text in BOARDS.items():
            archive.writestr(name, text)
```

- [ ] **Step 5: Wire it into `write_pack` and the operator's listing**

In `pipeline/report/agent_pack.py`, add the import beside the other `pipeline.report` imports:

```python
from pipeline.report import dashboard_skill, metrics
```

Add the constant beside `BRAND_SKILL_ZIP_NAME`:

```python
# A third skill: which panels make up a named board. Its own archive for the
# reason the chart rules have one -- the three load independently, and a
# request for a board needs all three while a one-line factual answer needs
# none of them.
DASHBOARD_SKILL_ZIP_NAME = "cplan-dashboards-skill.zip"
```

In `write_pack`, beside `_write_brand_skill_zip`:

```python
    dashboard_skill.write_zip(out_dir / DASHBOARD_SKILL_ZIP_NAME)
```

In `pipeline/scripts/build_agent_pack.py`, add to the tuple at line 129:

```python
            (agent_pack.DASHBOARD_SKILL_ZIP_NAME, "third skill: the named boards -- upload once, re-upload only when a board changes"),
```

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pipeline/report/dashboard_skill.py pipeline/report/agent_pack.py \
        pipeline/scripts/build_agent_pack.py tests/test_agent_pack.py
git commit -m "$(cat <<'EOF'
Give the agent three boards to draw instead of a blank page

Asked for an executive dashboard with no board named, the agent decides
every panel afresh, and a fresh decision is where a rule gets dropped:
yesterday's render put five tile numbers in red, a heading in capitals and
red on all five charts, against instructions forbidding each in plain
words. Naming the board fixes the panel list before the drawing starts.

Three boards, one decision each. Its own module because the catalogue is
four documents of text and agent_pack.py is long enough, and its own
archive because chart-standards is deliberately free of data and
organisation while a board names pack files and column values.

Each board spends the red budget once, on the panel it names. That is
stricter than the two the instructions allow, because "at most two" is a
budget an improvising agent spends without noticing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The citation test

The one that holds the boards to the pack. Without it a board is prose that happens to name a file, and renaming a summary row leaves it pointing at a line that no longer exists — silently, because nothing reads a board except the agent.

**Files:**
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: `dashboard_skill.BOARDS` (filename -> text); the `_breakdowns(pack_dir)` helper added in Task 1; `agent_pack.BREAKDOWN_NAME`, `BREAKDOWN_MEASURES` and `TAUTOLOGICAL_MEASURES`; the generated `01-summary.txt`, `03-data-quality.txt`, `04-calendar.csv`, `06-breakdowns.csv`.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_pack.py`. Extend the import line Task 1 already widened, so there is one import from this package rather than two:

```python
from pipeline.report import agent_pack, dashboard_skill, metrics
```

Then the helpers and the test:

```python
def _prose_sections(text):
    """`TITLE -> [line, ...]` for the underlined sections of a prose pack file.

    Both prose files write a title and then a rule of dashes exactly as long,
    which is what makes the shape detectable without a parser per file.
    """
    lines = text.splitlines()
    sections, current = {}, None
    for index, line in enumerate(lines):
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if line.strip() and following and set(following) == {"-"}:
            current = line.strip()
            sections[current] = []
        elif current is not None and set(line.strip()) != {"-"}:
            sections[current].append(line)
    return sections


def _citations(text):
    """Every `Source:` citation in a board file, one per returned string."""
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("Source:"):
            continue
        body = stripped[len("Source:"):].strip()
        if body == "none":
            continue
        found += [part.strip() for part in body.split(";") if part.strip()]
    return found


def _resolve(citation, pack_dir):
    """Fail with the citation in the message if the pack does not state it."""
    parts = [part.strip() for part in citation.split("·")]
    name, rest = parts[0], parts[1:]
    path = pack_dir / name
    assert path.exists(), f"{citation}: the pack has no file {name}"
    assert rest, f"{citation}: names a file and nothing in it"

    if name.endswith(".csv"):
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        wanted = dict(part.split("=", 1) for part in rest)
        assert any(all(row.get(key) == value for key, value in wanted.items())
                   for row in rows), f"{citation}: no row in {name} matches"
        return

    sections = _prose_sections(path.read_text(encoding="utf-8"))
    section = rest[0]
    assert section in sections, f"{citation}: {name} has no section {section!r}"
    if len(rest) == 1:
        return
    label = rest[1]
    assert any(line.strip().startswith(f"{label}:")
               or line.strip().startswith(f"{label} |")
               for line in sections[section]), (
        f"{citation}: {section} states no {label!r}")


def test_every_board_citation_resolves_against_the_pack(tmp_path):
    """A board reads its figures; it does not compute them. This is what makes
    that claim true rather than stated.

    It is also the anti-drift test. Rename a summary row and the build fails
    here, instead of a board quietly pointing at a line that no longer exists
    -- which nothing but the agent would ever read. It covers labels carrying
    an interpolated value too, such as `Planned at under 7 days' notice`, which
    moves with SHORT_NOTICE_DAYS.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    checked = 0
    for name, text in dashboard_skill.BOARDS.items():
        citations = _citations(text)
        assert citations, f"{name} cites nothing"
        for citation in citations:
            try:
                _resolve(citation, pack_dir)
            except AssertionError as error:
                raise AssertionError(f"{name}: {error}") from None
            checked += 1
    assert checked >= 20, f"only {checked} citations checked; a board lost its sources"


def test_boards_cite_only_measures_the_breakdowns_file_writes(tmp_path):
    """A measure name is a string in two places, and a typo in the board is
    invisible until an agent looks for a row that was never written.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    written = {row["measure"] for row in _breakdowns(pack_dir)}
    assert written <= set(agent_pack.BREAKDOWN_MEASURES)

    for name, text in dashboard_skill.BOARDS.items():
        for citation in _citations(text):
            if agent_pack.BREAKDOWN_NAME not in citation:
                continue
            parts = dict(part.strip().split("=", 1)
                         for part in citation.split("·")[1:])
            measure, block = parts["measure"], parts["block"]
            assert measure in written, f"{name} cites unwritten measure {measure!r}"
            suppressed = agent_pack.TAUTOLOGICAL_MEASURES.get(block, ())
            assert measure not in suppressed, (
                f"{name} cites {measure!r} under {block!r}, where it is suppressed")
```

- [ ] **Step 2: Run the test to verify it passes for the right reason**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k citation -v`
Expected: PASS. If it fails, the board text from Task 2 has a citation the pack does not state — fix the board, not the test.

- [ ] **Step 3: Prove the test can fail**

Temporarily change one citation in `pipeline/report/dashboard_skill.py` — in `PORTFOLIO_OVERVIEW`, `Activities in scope` to `Activities in scopes`.

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k citation -v`
Expected: FAIL with `01-summary.txt · VOLUME · Activities in scopes: VOLUME states no 'Activities in scopes'`

Revert the change and re-run. Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_pack.py
git commit -m "$(cat <<'EOF'
Hold every board citation to the pack built in the same run

A board claims it reads its figures rather than computing them. Nothing
made that true: a citation is prose naming a file, and the only reader is
the agent, so a renamed summary row would leave a board pointing at a line
that no longer exists and nobody would find out.

Every Source line is now resolved against the generated pack -- a section
and a label for the prose files, a matching row for the CSVs. Renaming a
row breaks the build instead. It covers the labels carrying an
interpolated value too, which is where a hand-written copy goes stale
first.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Tell the rest of the pack that a sixth file exists

Six places enumerate the pack files. A file the table of contents omits is a file the agent does not open.

**Files:**
- Modify: `pipeline/report/agent_pack.py` (`SKILL_TEXT`, `readme_text`, `glossary_text`, `INSTRUCTIONS_TEXT`)
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: `agent_pack.BREAKDOWN_NAME` and `dashboard_skill.SKILL_NAME` from Tasks 1 and 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_pack.py`:

```python
def test_every_pack_file_is_named_by_the_things_that_index_it(tmp_path):
    """A file no table of contents names is a file the agent never opens.

    Four documents route the agent to the pack -- the README inside it, the
    skill manifest, the instructions, and the archive's own file list -- and
    each is maintained by hand.
    """
    pack_dir, out_dir, _, _ = _pack(tmp_path)
    readme = (pack_dir / agent_pack.README_NAME).read_text(encoding="utf-8")
    instructions = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        manifest = archive.read("SKILL.md").decode("utf-8")

    for name in (agent_pack.SUMMARY_NAME, agent_pack.GLOSSARY_NAME,
                 agent_pack.QUALITY_NAME, agent_pack.CALENDAR_NAME,
                 agent_pack.BREAKDOWN_NAME, agent_pack.ACTIVITIES_CSV_NAME):
        assert name in readme, f"the README does not list {name}"
        assert name in manifest, f"the skill manifest does not list {name}"
        assert name in instructions, f"the instructions do not list {name}"


def test_the_glossary_says_a_median_never_combines(tmp_path):
    """The overlap rule saves a reader from summing an overlapping block. It
    does not save them from summing a median, which is wrong on a partitioning
    block too -- a different mistake, needing its own sentence.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    glossary = (pack_dir / agent_pack.GLOSSARY_NAME).read_text(encoding="utf-8")
    assert "median" in glossary.lower()
    assert agent_pack.BREAKDOWN_NAME in glossary


def test_the_instructions_point_at_the_board_skill(tmp_path):
    """A skill loads when the orchestrator judges it relevant, so the
    instructions naming it is the whole retrieval mechanism -- the same
    phrasing that already makes `chart-standards` load.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    instructions = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert dashboard_skill.SKILL_NAME in instructions
    assert agent_pack.BRAND_SKILL_NAME in instructions
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k "index_it or median or board_skill" -v`
Expected: FAIL — the README does not list `06-breakdowns.csv`

- [ ] **Step 3: Update `readme_text`**

In `pipeline/report/agent_pack.py`, in the file list inside `readme_text`, between the calendar and activities lines:

```
  {BREAKDOWN_NAME}    one row per block x value x measure - the crosses the calendar cannot make
```

- [ ] **Step 4: Update `SKILL_TEXT`**

In the "Which file answers what" table, add a row after the calendar row:

```
| Any figure crossing two dimensions | `{BREAKDOWN_NAME}` |
```

And extend the sentence beneath it so the preference covers the new file:

```
Prefer `{SUMMARY_NAME}`, `{CALENDAR_NAME}` and `{BREAKDOWN_NAME}` for any
counting question. Those figures were computed by tested code. A number you
derive yourself from `{ACTIVITIES_CSV_NAME}` has not been through the report's
rules.
```

- [ ] **Step 5: Update `glossary_text`**

In the tuple of rules inside `glossary_text`, after the existing overlap rule:

```python
        f"Only counts answer \"how many\". In {BREAKDOWN_NAME}, "
        "measure=median_completeness is a median per value: it does not "
        "combine, on an overlapping block or a partitioning one. The overlap "
        "rule above is about a different mistake and does not cover this one.",
        f"{BREAKDOWN_NAME} states a measure only where it can vary. A measure "
        "that would restate its own block -- the unknown-audience count inside "
        "the Unknown band, executive involvement inside an executive block -- "
        "is not written. Its absence is not a zero.",
```

- [ ] **Step 6: Update `INSTRUCTIONS_TEXT`**

In the bulleted list of pack contents, after the calendar line:

```
- `06-breakdowns.csv` — one row per block × value × measure. The crosses `04-calendar.csv` cannot make: activities, leadership involvement, large audiences, missing pack links, unknown audience and median completeness, per division, region, country and audience band
```

In the sentence immediately below that list, extend the preference the same way `SKILL_TEXT` was extended.

And in the "Visualization Instructions" preamble, after the sentence requiring `chart-standards`:

```
When a dashboard, a board or a one-page executive overview is asked for, load the `cplan-dashboards` skill as well. It names the three boards this agent draws and fixes each one's panels, so the layout is not decided again per request. If no board is named, say which three exist and ask — a blended board answers none of the three decisions.
```

- [ ] **Step 7: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -v`
Expected: PASS. Watch `test_the_instructions_are_the_whole_prompt` and `test_a_figure_is_stated_once_rather_than_in_every_section` in particular — both read the instructions text and are the ones an edit here can break.

- [ ] **Step 8: Commit**

```bash
git add pipeline/report/agent_pack.py tests/test_agent_pack.py
git commit -m "$(cat <<'EOF'
Name the sixth file everywhere the other five are named

Four hand-maintained documents route the agent to the pack: the README
inside it, the skill manifest, the instructions, and the archive's file
list. A file none of them names is a file the agent never opens, so the
breakdowns file would have shipped unread.

The glossary gains the rule the overlap rule does not cover: a median is
per value and never combines, on a partitioning block as much as an
overlapping one. And the rule that a suppressed measure is an absence
rather than a zero, since a reader cannot tell those apart by looking.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The check.ps1 manifest

`check.ps1` is the only thing that tells an operator on a machine without git which files to hand-copy, and it decides current-vs-stale by one marker string per file. A new module with no entry is a file that can be half-copied without anything noticing.

**Files:**
- Modify: `check.ps1:35` (the version), `check.ps1:40-190` (the manifest array)
- Test: `tests/test_check_manifest.py` (no change — it reads the manifest out of the script)

**Interfaces:**
- Consumes: `pipeline/report/dashboard_skill.py` from Task 2, and the new marker strings introduced in Tasks 1 and 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Read the two rules the manifest test enforces**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_manifest.py -v`
Expected: PASS before any edit. The two rules are: every marker exists in the file it names, and no marker also exists in the *previous* committed version of that file — a marker that does cannot tell a pre-change copy from a post-change one.

This means every marker below must be a string introduced by Tasks 1–4.

- [ ] **Step 2: Bump the manifest version**

In `check.ps1`, line 35 and the matching marker on line 43. Today's date with the next suffix:

```powershell
$manifestVersion = "2026-08-07.9"
```

```powershell
    @{ Path = "check.ps1";                     Marker = '$manifestVersion = "2026-08-07.9"'; Why = "this script itself - an old copy checks a new repository against an old manifest and reports it fine" },
```

- [ ] **Step 3: Add the entries**

In the manifest array, beside the other `pipeline\report\agent_pack.py` entries:

```powershell
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "def breakdown_rows";              Why = "the file that crosses two dimensions - without it the calendar is the only breakdown, and every board question about leadership by division is answerable only by counting the activities file by hand" },
    @{ Path = "pipeline\report\agent_pack.py"; Marker = "TAUTOLOGICAL_MEASURES";           Why = "measures that restate their own block are left out - an older copy writes them, and a reader cannot tell a suppressed measure from a zero" },
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = 'SKILL_NAME = "cplan-dashboards"'; Why = "the named boards ship as the third skill - without it the agent draws a fresh dashboard per request, which is where the visual rules get dropped" },
    @{ Path = "pipeline\report\dashboard_skill.py"; Marker = "Highlight: yes";             Why = "each board spends the red budget once, on the panel it names - stricter than the two the instructions allow, because a budget is spent without noticing" },
```

The third marker is single-quoted, not double-quoted with backslashes: PowerShell has no `\"` escape, and a double-quoted marker containing quotes would not parse. The existing `$manifestVersion` entry uses the same single-quoted form.

- [ ] **Step 4: Run the manifest test**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_check_manifest.py -v`
Expected: PASS. A failure naming a marker means that string is also in the previous committed version of the file — choose a string the change actually introduced.

`dashboard_skill.py` is a new file, so its two entries have no previous version to be confused with. If the test errors rather than skipping on a file git has never seen, that is a gap in the test worth fixing there — not a reason to drop the entries.

- [ ] **Step 5: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add check.ps1
git commit -m "$(cat <<'EOF'
List the new module where an operator without git can see it

check.ps1 is the only thing telling an operator on a machine without git
which files to hand-copy, and it decides current-vs-stale by one marker
per file. A new module with no entry is a file that can be half-copied
with nothing noticing -- which is the failure the manifest exists for.

Four entries and a version bump: the breakdowns function, the suppression
table, the board skill's name, and the highlight line that is the whole
point of a board.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Build a real pack and read it

The tests run on a fixture of a few dozen synthetic rows. This is the step that puts the three archives in front of a person before anyone uploads them.

**Files:**
- No source changes expected. Any fix goes back into the task that owns the file.

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing.

- [ ] **Step 1: Build the pack**

Run: `PYTHONPATH=. .venv/bin/python pipeline/scripts/build_agent_pack.py`
Expected: the listing names three archives — `cplan-skill.zip`, `chart-standards-skill.zip`, `cplan-dashboards-skill.zip` — with the boards' size beside it, plus `06-breakdowns.csv` in the pack folder.

This needs the source CSV exports, which live on the operator's machine and not in `pipeline/input/` here. On a machine without them, build the fixture pack into a real directory instead — it exercises the same `write_pack` and produces the same three archives over synthetic rows:

```bash
PYTHONPATH=. .venv/bin/python -c "
from datetime import date
from pathlib import Path
from pipeline.report import agent_pack
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope

out = Path('/tmp/cplan-pack-review')
config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
scope = load_fixture_scope(out / 'csv', config)
print(agent_pack.write_pack(scope, config, out / 'out'))
"
```

- [ ] **Step 2: Read the breakdowns file**

Open `06-breakdowns.csv` in the output folder. Check by eye:

- the `TOTAL` block's `activities` figure equals `Activities in scope` in `01-summary.txt`;
- no row carries an empty `value`;
- no `median_completeness` figure is above 100 or below 0;
- the `audience_band` block carries no `unknown_audience` or `large_audience` row.

- [ ] **Step 3: Read the board archive**

Unzip `cplan-dashboards-skill.zip` and read the three board files end to end. Check that no panel heading is in capitals, no board names the organisation, and each board's `Highlight: yes` sits on the panel the spec assigns it.

- [ ] **Step 4: Commit nothing, or commit the fix**

If everything reads correctly there is nothing to commit — the pack output is not in git. If something is wrong, fix it in the module that owns it and amend the commit from the task that introduced it.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: `06-breakdowns.csv` and its measure table to Task 1; the skill package, the panel contract and the three boards to Task 2; the citation grammar and tests 1–3, 5 to Task 3; "What else has to move" to Task 4; the manifest consequence to Task 5. Tests 2, 4 and 6 from the spec's list sit in Task 2 (`highlight`, `contract`, `organisation name`) and Task 1 (`breakdown_rows` against metrics).

**Deliberate omissions**, each stated in the spec's "Out of scope": leadership involvement over time, the two planner boards, channel and coverage boards, evaluation cases, packs as first-class records. `checklist_text` is untouched by design — its haystack is the two prose files, and adding the breakdowns file would reclassify counting questions as reading ones.

**One thing to watch.** Task 4 edits `INSTRUCTIONS_TEXT`, which four existing tests read (`test_the_instructions_are_the_whole_prompt`, `test_a_figure_is_stated_once_rather_than_in_every_section`, `test_the_instructions_carry_no_organisation_name`, `test_the_ways_of_working_sit_in_the_skill_and_the_guards_in_the_prompt`). Run the full file after that task, not just the new tests.
