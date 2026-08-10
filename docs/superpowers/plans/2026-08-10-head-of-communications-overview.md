# Head of communications overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** replace the `Portfolio overview` board with a `Head of communications overview` designed for the role, on both delivery surfaces, and give the pack the four figures its panels need.

**Architecture:** `pack_config` appends `priority` and `lead_team` to the pack's breakdown fields, so both arrive as blocks in `04-calendar.csv` and `06-breakdowns.csv` through the same `iter_blocks` everything else runs on, and the distributed workbook is untouched. `_measures` gains `short_notice`. `_summary_sections` gains a `HORIZON` section. `dashboard_skill` swaps one board for another; `agent_builder` follows through its filename map and one line of the prompt.

**Tech Stack:** Python 3.13, pandas, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-10-head-of-communications-overview-design.md`

## Global Constraints

- **No organisation name anywhere in the repository.** Not in code, comments, docs, test data or commit messages. `<ORGANISATION>` is the operator's placeholder and appears only in `agent_builder.INSTRUCTIONS_TEXT` and `agent_pack.INSTRUCTIONS_TEXT`.
- **Board text is data-free.** No figure, no period, no generation date; the archive rebuilds identically every run.
- **Board panel text ships verbatim to both surfaces.** `agent_builder` composes its files as `BOARD_RULES_TEXT + dashboard_skill.BOARDS[key]` — never a second copy.
- **Every `Source:` citation must resolve** against the pack generated in the same run. `tests/test_agent_pack.py::test_every_board_citation_resolves_against_the_pack` enforces it; if a citation fails, fix the board, never the resolver.
- **`agent_builder.INSTRUCTIONS_TEXT` stays under 8,000 characters with at least 200 spare.** It is 7,775 today. Never raise `INSTRUCTIONS_LIMIT`, never lower the 200 floor.
- **`check.ps1` is manifest-controlled.** `tests/test_check_manifest.py` requires any manifest-listed file that changes to gain a NEW marker absent from the version it replaced, plus a `$manifestVersion` bump. Handle it in the same commit as the change.
- **Commit message style:** imperative sentence, no `feat:`/`fix:` prefix, a body explaining *why*, trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Run tests with** `PYTHONPATH=. .venv/bin/python -m pytest` from the repository root.

---

### Task 1: Priority and lead team as blocks, and a short-notice measure

**Files:**
- Modify: `pipeline/report/agent_pack.py` (`pack_config`, `BREAKDOWN_MEASURES`, `_measures`)
- Modify: `check.ps1`
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: `metrics.lead_time_stats(frame) -> {"counted", "median_days", "short_notice"}`; `iter_blocks(scope, config)`.
- Produces: blocks `priority` and `lead_team` in both `04-calendar.csv` and `06-breakdowns.csv`; the measure name `short_notice` in `BREAKDOWN_MEASURES`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_pack.py`, after the existing breakdown tests:

```python
def test_the_pack_breaks_down_by_priority_and_lead_team(tmp_path):
    """Two blocks the workbook does not carry, added where the pack already
    widens: `pack_config`. A board that names a team or a priority level has
    nowhere else to read it, and counting `05-activities.csv` by hand is the
    one thing the instructions refuse.
    """
    scope, config = _scope(tmp_path)
    packed = agent_pack.pack_config(config)
    assert "priority" in packed.breakdown_fields
    assert "lead_team" in packed.breakdown_fields
    # The workbook's own config is untouched: the pack is wider, as it already
    # is for priorities and objectives.
    assert "priority" not in config.breakdown_fields
    assert "lead_team" not in config.breakdown_fields

    pack_dir = agent_pack.write_pack(scope, packed, tmp_path / "out")
    blocks = {row["block"] for row in _breakdowns(pack_dir)}
    assert {"priority", "lead_team"} <= blocks
    calendar_blocks = {row["block"] for row in _calendar(pack_dir)}
    assert {"priority", "lead_team"} <= calendar_blocks


def test_priority_and_lead_team_do_not_overlap(tmp_path):
    """An activity has one priority and one lead team, so these blocks sum.

    The overlaps column is the only thing standing between a reader and a
    total larger than the portfolio; marking a partitioning block as
    overlapping would make an honest sum look untrustworthy.
    """
    scope, config = _scope(tmp_path)
    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config),
                                     tmp_path / "out")
    for row in _breakdowns(pack_dir):
        if row["block"] in ("priority", "lead_team"):
            assert row["overlaps"] == "no", f"{row['block']} claims to overlap"


def test_short_notice_is_a_measure_and_agrees_with_the_metrics(tmp_path):
    """The figure the board's red element rests on, computed by the same
    function the summary uses rather than a second implementation of it.
    """
    scope, config = _scope(tmp_path)
    packed = agent_pack.pack_config(config)
    pack_dir = agent_pack.write_pack(scope, packed, tmp_path / "out")
    assert "short_notice" in agent_pack.BREAKDOWN_MEASURES

    rows = _breakdowns(pack_dir)
    total = _figure(rows, "TOTAL", "all activities", "short_notice")
    assert total == metrics.lead_time_stats(scope.frame)["short_notice"]

    # And it decomposes: a partitioning block's rows add back up to it.
    by_team = sum(int(r["figure"]) for r in rows
                  if r["block"] == "lead_team" and r["measure"] == "short_notice")
    assert by_team == total
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k "priority_and_lead_team or short_notice" -v`
Expected: FAIL — `assert 'priority' in ('business_division', 'region_group', 'country', 'executives')`

- [ ] **Step 3: Widen the pack's config**

In `pipeline/report/agent_pack.py`, in `pack_config`, replace the return with:

```python
    # Two dimensions the workbook has no block for and the pack needs: a board
    # that names a team or a priority level has nowhere else to read one, and
    # deriving it from the activities file is the thing the instructions
    # refuse. Appended rather than substituted, and appended HERE rather than
    # in `ReportConfig`, for the reason the priority and objective filters are
    # dropped here: the workbook is a planning instrument and the pack answers
    # questions, and only the second one needs these.
    extra = tuple(field for field in ("priority", "lead_team")
                  if field not in config.breakdown_fields)
    return replace(config, exclude_priorities=(), exclude_objectives=(),
                   breakdown_fields=config.breakdown_fields + extra)
```

- [ ] **Step 4: Add the measure**

In `BREAKDOWN_MEASURES`, append `"short_notice"`:

```python
BREAKDOWN_MEASURES = ("activities", "with_executives", "large_audience",
                      "without_pack", "unknown_audience", "median_completeness",
                      "short_notice")
```

And in `_measures`, after `median_completeness`:

```python
        ("short_notice", metrics.lead_time_stats(subset)["short_notice"]),
```

`metrics.lead_time_stats` is already imported with the module and is what the summary's own short-notice figure comes from, so the two cannot drift.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -v`
Expected: PASS. Watch `test_breakdown_activities_agree_with_the_calendar` — it compares the two files block by block and will now cover the new blocks for free.

- [ ] **Step 6: Manifest and commit**

`pipeline/report/agent_pack.py` is manifest-listed. Add a new entry with a marker this change introduces and bump `$manifestVersion` to the next suffix.

```bash
git add pipeline/report/agent_pack.py tests/test_agent_pack.py check.ps1
git commit -m "$(cat <<'EOF'
Give the pack the two dimensions a board has to name

A board that says which team absorbs late work, or how much of the plan
is urgent, needs priority and lead team as blocks. Neither exists: the
only route to them is counting the activities file by hand, which the
instructions refuse for good reason.

Appended in pack_config, where the pack already widens past the workbook
for priorities and objectives, so the distributed workbook gains no
blocks it never asked for. Both partition, so both sum -- an activity has
one priority and one lead team.

short_notice joins the measures beside them, computed by the same
lead_time_stats the summary's own figure comes from rather than a second
implementation that could drift from it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The HORIZON section

Three stated figures, because a headline number a chunked retrieval could get wrong is worse than one that is missing.

**Files:**
- Modify: `pipeline/report/agent_pack.py` (`_summary_sections`, and the module's `datetime` import)
- Modify: `check.ps1`
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: `scope.frame["start_date"]` (pandas Timestamps), `generated` (a `date`).
- Produces: a `HORIZON` section in `01-summary.txt` with labels `Planned to date`, `Next 30 days`, `Rest of the period`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_summary_splits_the_portfolio_at_its_own_vintage(tmp_path):
    """"1,380 activities in scope" mixes what is behind the generation date
    with what is ahead of it and states neither.

    Stated rather than left to be summed out of the calendar: these are
    headline numbers, the pack files are retrieved in chunks on both
    surfaces, and a partial read of forty calendar rows produces a confident
    wrong figure — which costs more than a missing one.
    """
    pack_dir, _, scope, _ = _pack(tmp_path)
    pairs = _summary_pairs((pack_dir / agent_pack.SUMMARY_NAME)
                           .read_text(encoding="utf-8"))
    for label in ("Planned to date", "Next 30 days", "Rest of the period"):
        assert label in pairs, f"the summary does not state {label!r}"

    three = sum(int(pairs[label]) for label in
                ("Planned to date", "Next 30 days", "Rest of the period"))
    assert three == len(scope.frame), "the horizon does not partition the portfolio"


def test_the_horizon_splits_where_the_vintage_says(tmp_path):
    """The arithmetic a reader would do to check it is the arithmetic here.

    Every in-scope activity has a start date — "no start date" is its own
    exclusion reason — so the three counts are a partition and not a sample.
    """
    from datetime import date as _date, timedelta
    scope, config = _scope(tmp_path)
    generated = _date(2025, 6, 30)
    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "out",
                                     generated=generated)
    pairs = _summary_pairs((pack_dir / agent_pack.SUMMARY_NAME)
                           .read_text(encoding="utf-8"))
    starts = scope.frame["start_date"].dt.date
    assert int(pairs["Planned to date"]) == int((starts <= generated).sum())
    assert int(pairs["Next 30 days"]) == int(
        ((starts > generated) & (starts <= generated + timedelta(days=30))).sum())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k "vintage or horizon" -v`
Expected: FAIL — `the summary does not state 'Planned to date'`

- [ ] **Step 3: Add the section**

In `pipeline/report/agent_pack.py`, extend the datetime import at the top:

```python
from datetime import date, timedelta
```

In `_summary_sections`, after the `volume` list is built and before `stats = metrics.load_stats(scope)`:

```python
    # Where the plan stands relative to its own generation date. Stated rather
    # than left to be summed out of the calendar: these are headline figures,
    # the pack is retrieved in chunks on both delivery surfaces, and a partial
    # read of forty week rows yields a confident wrong number. A missing figure
    # costs less than a wrong one, and a stated figure costs neither.
    #
    # A partition, not a sample: "no start date" is its own exclusion reason,
    # so every in-scope activity has one and the three counts sum to the total.
    if total:
        starts = frame["start_date"].dt.date
        to_date = int((starts <= generated).sum())
        soon = int(((starts > generated)
                    & (starts <= generated + timedelta(days=30))).sum())
    else:
        to_date = soon = 0
    horizon = [
        ("Planned to date", to_date),
        ("Next 30 days", soon),
        ("Rest of the period", total - to_date - soon),
    ]
```

And add it to the returned list, between VOLUME and LOAD:

```python
        ("VOLUME", volume),
        ("HORIZON", horizon),
        ("LOAD", load),
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -v`
Expected: PASS. `test_summary_figures_match_the_workbook` compares labels the workbook also states — HORIZON is pack-only, so it must not appear there; if that test fails, read what it asserts before changing anything.

- [ ] **Step 5: Manifest and commit**

```bash
git add pipeline/report/agent_pack.py tests/test_agent_pack.py check.ps1
git commit -m "$(cat <<'EOF'
Say where the plan stands, instead of leaving it to be added up

"Activities in scope: 1,380" mixes what is behind the generation date
with what is ahead of it and states neither. On a real snapshot that is
1,153 elapsed against 66 in the coming month -- the second number is the
one somebody acts on this week, and no file said it.

Stated in the summary rather than summed out of the calendar. Both
delivery surfaces retrieve the pack in chunks, so adding up forty week
rows is a headline figure that a partial read gets confidently wrong, and
a wrong number costs more than a missing one.

A partition rather than a sample: no start date is its own exclusion
reason, so the three counts sum to the portfolio and the test says so.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The board itself

**Files:**
- Modify: `pipeline/report/dashboard_skill.py`
- Modify: `check.ps1`
- Test: `tests/test_agent_pack.py`

**Interfaces:**
- Consumes: the blocks and section from Tasks 1 and 2.
- Produces: `dashboard_skill.BOARDS` key `board-head-of-communications-overview.md` replacing `board-portfolio-overview.md`; the constant `PORTFOLIO_OVERVIEW` is removed and `HEAD_OF_COMMUNICATIONS_OVERVIEW` takes its place.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_overview_board_is_the_one_designed_for_the_role(tmp_path):
    """One overview, not two. Two general boards give the agent no criterion
    by which to pick, which is the case where it grabs blindly.
    """
    assert "board-head-of-communications-overview.md" in dashboard_skill.BOARDS
    assert "board-portfolio-overview.md" not in dashboard_skill.BOARDS
    assert len(dashboard_skill.BOARDS) == 3

    joined = dashboard_skill.SKILL_TEXT + "".join(dashboard_skill.BOARDS.values())
    assert "portfolio overview" not in joined.lower(), (
        "the replaced board is still named somewhere")


def test_the_overview_names_teams_as_work_received(tmp_path):
    """The condition the panel was accepted on.

    The pack knows when an activity was created and when it starts; nothing in
    it says who caused the gap. "Planned at under 7 days' notice" over a team
    name asserts the team booked late, which the data cannot support — and a
    board is the artefact most screenshotted and least questioned, so the
    wording has to survive being cropped away from its footnote.
    """
    board = dashboard_skill.BOARDS["board-head-of-communications-overview.md"]
    assert "requests received at" in board.lower()
    assert "planned at under" not in board.lower()


def test_the_overview_spends_its_red_on_the_intervention(tmp_path):
    """Same rule, different answer, because the board asks a different
    question: the panel that answers it is the one that gets the accent.
    """
    board = dashboard_skill.BOARDS["board-head-of-communications-overview.md"]
    panels = re.split(r"^### ", board, flags=re.M)[1:]
    highlighted = [p.splitlines()[0] for p in panels
                   if any(line.strip() == "Highlight: yes" for line in p.splitlines())]
    assert len(highlighted) == 1
    assert "lead team" in highlighted[0].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -k "overview" -v`
Expected: FAIL — `assert 'board-head-of-communications-overview.md' in {...}`

- [ ] **Step 3: Replace the board constant**

In `pipeline/report/dashboard_skill.py`, delete `PORTFOLIO_OVERVIEW` entirely and add in its place:

```python
HEAD_OF_COMMUNICATIONS_OVERVIEW = """# Board — Head of communications overview

**The decision:** where do I intervene, and with whom? This board does not
inventory the plan. Every panel points at something, and the read-out ends by
naming which of the other boards to open.

Five panels. Panel 1 is a tile row across the top, panels 2–4 sit in a row
beneath it, panel 5 closes the board.

### Panel 1 — Where the function stands

Business question: what is behind us, what is imminent, and is the function planning ahead?
Chart: number tiles, one row, aligned on the baseline of the numbers
Source: 01-summary.txt · HORIZON · Planned to date; 01-summary.txt · HORIZON · Next 30 days; 01-summary.txt · PLANNING DISCIPLINE · Median lead time (days); 01-summary.txt · PLANNING DISCIPLINE · Planned at under 7 days' notice; 01-summary.txt · LEADERSHIP AND AUDIENCE · With GEB/GEB-1 involvement; 01-summary.txt · VOLUME · Activities in scope
Footnote: Split at the generation date stated at the top of the summary. Every record here is a plan — this system holds no delivery and no performance, so "planned to date" is plan whose date has passed and never means an activity ran.
Highlight: no

### Panel 2 — Audience load by start week

Business question: in which weeks does the whole organisation get hit at once?
Chart: line chart, one point per ISO week, two series on one axis — activities in the top two audience bands as the message, all activities as a faint context line
Source: 04-calendar.csv · block=audience_band; 04-calendar.csv · block=TOTAL
Footnote: A planning estimate of who is addressed, never measured reach. Solid to the generation date, dashed after it: the forward half thins because it is not written yet, not because activity falls away.
Highlight: no

### Panel 3 — Priority mix

Business question: is the function working on what matters?
Chart: donut with a large white centre, four segments, no highlight
Source: 06-breakdowns.csv · block=priority · measure=activities
Footnote: The levels are peers and the split itself is the answer, so nothing is singled out. The numbered levels run 1 as most urgent to 4 as least.
Highlight: no

### Panel 4 — Late requests by lead team

Business question: which team absorbs the most work booked at under a week's notice?
Chart: horizontal bar, sorted by value
Source: 06-breakdowns.csv · block=lead_team · measure=short_notice
Footnote: Requests received at under 7 days' notice, counted against the team carrying them. The pack knows when an activity was created and when it starts; it does not know who caused the gap, so a team at the top of this bar may be absorbing late work rather than causing it.
Highlight: yes

### Panel 5 — Executive read-out

Business question: what do I do this month, and which board should be opened next?
Chart: none (prose), four to five sentences ending in a route
Source: 01-summary.txt · HORIZON · Rest of the period; 01-summary.txt · LOAD · Median activities per week; 01-summary.txt · LEADERSHIP AND AUDIENCE · Large audience (top two bands)
Footnote: none
Highlight: no

## What this board does not do

No audience-band distribution and no regional distribution. Both are true and
neither changes what anyone does; the one useful fact inside them — that the
unknown audience band holds the external records, whose form has no such field —
belongs in the read-out where it explains something.

Never call an audience figure reach. Never say "the GEB": the field holds both
levels and nothing separates them. Never read the thinning forward plan as a
decline — say it is unwritten.

End the read-out by naming a board: planning notice and lead time belong to
Planning discipline, missing fields to Plan trust, executive time to Leadership
attention. An overview that ends in observations competes with them; one that
ends in a route makes them a set.
"""
```

- [ ] **Step 4: Update the map and the index**

In `BOARDS`, replace the portfolio entry:

```python
BOARDS = {
    "board-head-of-communications-overview.md": HEAD_OF_COMMUNICATIONS_OVERVIEW,
    "board-leadership-attention.md": LEADERSHIP_ATTENTION,
    "board-plan-trust.md": PLAN_TRUST,
}
```

In `SKILL_TEXT`, replace the routing table's first row:

```
| Head of communications overview | Where do I intervene, and with whom? | `board-head-of-communications-overview.md` |
```

- [ ] **Step 5: Make the test helper build the pack the product ships**

`tests/test_agent_pack.py`'s `_pack` helper calls `write_pack(scope, config, ...)` with the plain config, while `pipeline/scripts/build_agent_pack.py` does `config = agent_pack.pack_config(config)` *before* resolving the scope. So every pack test to date has been asserting against a pack shape that is never delivered — harmless until now, and fatal here, because the new board cites two blocks that only exist under `pack_config`.

Change the helper to mirror the build:

```python
def _pack(tmp_path, **overrides):
    """Built the way `build_agent_pack.py` builds it: through `pack_config`.

    The helper used to pass the workbook's own config, so the pack under test
    was a shape the product never ships. That was survivable while the two
    differed only by which rows they kept; it stopped being survivable when
    they started differing by which blocks exist.
    """
    scope, config = _scope(tmp_path, **overrides)
    out_dir = tmp_path / "out"
    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config), out_dir)
    return pack_dir, out_dir, scope, config
```

Note that `_pack` still returns the *unwidened* `config`, because tests that assert on the report's own scope want that one. If a test needs the widened config, it should call `agent_pack.pack_config` itself, as Task 1's tests do.

- [ ] **Step 6: Run the whole file and fix the fallout in the expectations**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_pack.py -v`
Expected: PASS, including `test_every_board_citation_resolves_against_the_pack`.

Tests that enumerate blocks or count rows will see two more blocks than before. **Update the expectation, never narrow the helper back** — the wider pack is the one that ships, and a test asserting against the narrower one was measuring nothing. If a failure looks like it is about something else entirely, read it before changing it.

- [ ] **Step 7: Manifest and commit**

```bash
git add pipeline/report/dashboard_skill.py tests/test_agent_pack.py check.ps1
git commit -m "$(cat <<'EOF'
Point the overview at a person instead of at the portfolio

Portfolio overview answered "is the plan plausible" with an inventory:
total volume, an audience distribution, a regional one. Every panel true,
none of them changing what anyone does.

A head of communications is accountable for a function. So the time panel
is weighted by audience size -- forty activities in a week means nothing,
twelve of them addressed to everyone is what costs the function its
credibility -- the tile row splits at the generation date, and the
read-out ends by naming which board to open next, which is what stops a
general board competing with the three specific ones.

The team panel is worded as work received, not work caused. Nothing in
the pack says who caused a short lead time, and a board is the artefact
most screenshotted and least questioned.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The Agent Builder delivery

The surface actually in use. Its board files are retrieved in chunks rather than loaded, and its prompt is the only thing that can tell an agent the board exists.

**Files:**
- Modify: `pipeline/report/agent_builder.py` (`BOARD_FILE_NAMES`, `INSTRUCTIONS_TEXT`)
- Modify: `check.ps1`
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `dashboard_skill.BOARDS` from Task 3.
- Produces: the upload file `09-board-head-of-communications-overview.txt`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_prompt_names_the_board_that_exists(tmp_path):
    """A knowledge file cannot announce itself, so the prompt is the only
    place a board's existence can be stated — and a prompt naming a board the
    catalogue no longer ships sends the agent looking for a missing file.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert "head of communications overview" in text.lower()
    assert "portfolio overview" not in text.lower()
    for board in ("leadership attention", "plan trust"):
        assert board in text.lower()


def test_the_prompt_still_has_its_margin(tmp_path):
    """The rename costs characters in a field that is 97% full. Measured
    rather than assumed: the 200-character floor exists because the operator
    replaces the placeholder with a longer name before pasting.
    """
    headroom = agent_builder.INSTRUCTIONS_LIMIT - len(agent_builder.INSTRUCTIONS_TEXT)
    assert headroom >= 200, f"only {headroom} spare after the rename"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -k "names_the_board or margin" -v`
Expected: FAIL — `assert 'head of communications overview' in ...`

- [ ] **Step 3: Rename the upload file**

In `pipeline/report/agent_builder.py`:

```python
BOARD_FILE_NAMES = {
    "board-head-of-communications-overview.md":
        "09-board-head-of-communications-overview.txt",
    "board-leadership-attention.md": "10-board-leadership-attention.txt",
    "board-plan-trust.md": "11-board-plan-trust.txt",
}
```

The existing `test_each_board_travels_as_its_own_file` asserts these keys equal `dashboard_skill.BOARDS`'s, so a mismatch fails loudly rather than shipping two boards and three names.

- [ ] **Step 4: Rename the board in the prompt**

In `INSTRUCTIONS_TEXT`, in the `## Your files` list, change the board line to:

```
- `09`–`11-board-*.txt` — one per named executive board: head of communications overview, leadership attention, plan trust
```

That is 13 characters more than the line it replaces, against 225 of headroom — leaving 212 above the 200 floor. Change nothing else in the field. If the measured headroom after your edit is under 200, stop and report the number rather than trimming elsewhere or lowering the floor.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -v`
Expected: PASS, with `test_the_instructions_fit_the_field_with_room_to_spare` reporting about 212.

- [ ] **Step 6: Manifest and commit**

```bash
git add pipeline/report/agent_builder.py tests/test_agent_builder.py check.ps1
git commit -m "$(cat <<'EOF'
Follow the rename onto the surface that has no skills

Agent Builder takes the boards as knowledge files and a prompt, and the
prompt is the only thing that can tell an agent a board exists --
retrieval answers a question, it never says which questions have a fixed
answer waiting. A prompt still naming portfolio overview would send the
agent looking for a file the catalogue no longer ships.

Thirteen characters more in a field that is 97% full, leaving 212 above
the 200 the operator's own organisation name may need. Measured, not
assumed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Build both deliveries and read them

**Files:**
- No source changes expected. Any fix goes back to the task that owns the file.

- [ ] **Step 1: Build in an isolated checkout**

The main working tree may carry another session's work. From the repository root:

```bash
git worktree add --detach "$SCRATCH/t5" HEAD
```

`$SCRATCH` is whatever scratch directory the session was given — never write the
absolute path into a committed file. A local path carries the machine's
directory names, and those name the organisation.

Run from inside it, with the interpreter at the original checkout's `.venv` and `PYTHONPATH` set to the worktree:

```bash
PYTHONPATH=. <repo>/.venv/bin/python -c "
from datetime import date
from pathlib import Path
from pipeline.report import agent_builder, agent_pack
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope

out = Path('/tmp/cplan-hoc-review')
config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
scope = load_fixture_scope(out / 'csv', config)
pack = agent_pack.write_pack(scope, agent_pack.pack_config(config), out / 'pack')
print(agent_builder.write_builder_pack(pack, out / 'builder', scope, config))
"
```

Remove the worktree with `git worktree remove --force <path>` when done.

- [ ] **Step 2: Read the Agent Builder upload folder**

This is the surface in use, so read it as the operator will:

- eleven files, `01` through `11`, and nothing else;
- `09-board-head-of-communications-overview.txt` opens with the shared rules block and then the board, with no seam where the two meet;
- the board is under about 4,000 characters — small enough that a retrieval hit stands a chance of returning it whole, which is the entire reason there is a file per board;
- no board names the organisation;
- `instructions.md`, `description.txt`, `starter-prompts.md`, `README.txt` and `checklist.md` are all OUTSIDE `upload/`.

- [ ] **Step 3: Read `01-summary.txt` and `06-breakdowns.csv`**

- the `HORIZON` section states three figures and they sum to `Activities in scope`;
- `06-breakdowns.csv` carries `block=priority` and `block=lead_team`, both `overlaps=no`;
- every `short_notice` figure is between 0 and its block value's `activities` figure.

- [ ] **Step 4: Read `instructions.md` as the operator pastes it**

Confirm the board line names the three boards that exist, that the file is one paste with no human-facing header, and report its exact character count against the 8,000 limit.

- [ ] **Step 5: Report**

Nothing to commit if it reads correctly — the delivery output is not in git. If something is wrong, fix it in the task that owns it.

---

## Self-Review

**Spec coverage.** The three pack additions and the HORIZON section map to Tasks 1 and 2; the board and the removal of `Portfolio overview` to Task 3; the two-surface consequence to Task 4; the read-through to Task 5. The spec's testing list items 1–5 are covered by the tests in Tasks 1–4, with item 5 (`Portfolio overview` is gone) asserted in Task 3 by scanning the whole skill text rather than only the map.

**Deliberately omitted**, each named in the spec's "Out of scope": a Reach and coverage board, channels, the division cut of panel 4, and any measure of whether an activity ran.

**One latent defect this plan fixes on the way past.** `_pack` built the pack from the workbook's config while the product builds it through `pack_config`, so every pack test was asserting against a shape that never ships. Task 3 Step 5 corrects it, and the expectations that move as a result are the price of the tests becoming true.

**One thing to watch.** Task 2 touches `_summary_sections`, which `test_summary_figures_match_the_workbook` reads label by label against the workbook. `HORIZON` is pack-only, so it must not appear on the sheet and must not break that comparison — read what the test asserts before touching it.
