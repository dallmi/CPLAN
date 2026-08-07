# Agent Builder Variant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit a second delivery of the same report pack, shaped for Agent Builder in Microsoft 365 Copilot — 8,000 characters of Instructions, no skill packages, knowledge files instead.

**Architecture:** `agent_pack.py` is untouched as the data layer. A new `pipeline/report/agent_builder.py` holds the delivery shape: a hand-compressed instructions literal, a description, four starter prompts, and two knowledge documents converted from the two skills. `build_agent_pack.py` calls both, so one run produces both deliveries from one scope. Output goes to `Projekte/CPLAN/Output/agent-builder` rather than `Input`.

**Tech Stack:** Python 3.13, pytest, stdlib only (`pathlib`, `shutil`). No new dependencies.

## Global Constraints

- **Branch:** `agent-builder-variant`. **Worktree:** `.claude/worktrees/agent-builder`, relative to the repository root. Run every command from the worktree root; the shell does not keep a `cd` between calls, so re-establish it per command or use `git -C`.
- **Python:** `$PY`, set once per shell to the main checkout's interpreter — the worktree has none of its own. From the worktree root: `PY=../../../.venv/bin/python`.
- **The employer's name must never enter the repository** — not in code, identifiers, comments, docs, tests, commit messages, or absolute paths. Use `<ORGANISATION>` in agent-facing text, "the organisation" in prose. Before every commit run the brand grep documented in the workspace `CLAUDE.md`; it must find nothing. Reproducing that command here would put the name in the repository, which is the leak it exists to catch.
- **`TEAM_SIGNATURE = "ECC Measurement & Insights"`** is a literal, not a placeholder. It is the team's own name, not the organisation's, and it stays.
- **Instructions limit: 8,000 characters. Description limit: 1,000. Knowledge sources: 20.** Verbatim from the Microsoft Learn documentation for Agent Builder.
- **`check.ps1` rule:** any change to `check.ps1` bumps `$manifestVersion` in the same commit — the date, or the suffix when the date is already today's. `tests/test_check_manifest.py` fails until it is. Current value on this branch: `2026-08-07.9`.
- **Spec:** `docs/superpowers/specs/2026-08-07-agent-builder-variant-design.md`.

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/scripts/process_cplan.py` | **Modify.** Add `ONEDRIVE_OUTPUT_DIR` beside `ONEDRIVE_INPUT_DIR` (line 50). |
| `pipeline/report/agent_builder.py` | **Create.** The whole delivery shape: the compressed instructions, description, starter prompts, the two knowledge documents, and `write_builder_pack`. |
| `pipeline/scripts/build_agent_pack.py` | **Modify.** Resolve the builder output folder, call `write_builder_pack`, log what to upload where. |
| `tests/test_agent_builder.py` | **Create.** Limits, rule parity with the Studio instructions, the upload set, byte-identity with the pack, the output resolver. |
| `check.ps1` | **Modify.** Manifest entries for the new file and the changed ones, plus the version bump. |
| `README.md` | **Modify.** A subsection under "Agent pack" describing the second delivery. |

One run emits both deliveries. Keeping them on separate commands would allow building one and forgetting the other, and two packs from two runs are two vintages of the same figure — the failure this repository is built to prevent.

---

### Task 1: The output folder

The pack lands in `Input/` because it sits beside the export it is built from. This delivery is not an input to anything, so it lands in `Output/agent-builder`. `resolve_output_dir` never creates its target, for a good reason: a path conjured inside a OneDrive that is not really set up syncs nowhere while looking like it worked. But `Output/` may legitimately not exist yet, and under that rule this delivery would fall silently back into the git checkout. Anchoring on `Input/` keeps the property: its presence proves the CPLAN sync is real, so its sibling can be created safely.

**Files:**
- Modify: `pipeline/scripts/process_cplan.py:50`
- Modify: `pipeline/scripts/build_agent_pack.py` (add a second resolver beside `resolve_output_dir`)
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `process_cplan.find_onedrive_root()`, `process_cplan.ONEDRIVE_INPUT_DIR`, `process_cplan.log`
- Produces: `process_cplan.ONEDRIVE_OUTPUT_DIR`, `build_agent_pack.BUILDER_LOCAL_OUTPUT_DIR`, `build_agent_pack.resolve_builder_output_dir() -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_builder.py`:

```python
"""The same report pack, delivered to a surface that has no skills.

Agent Builder holds 8,000 characters of Instructions and no skill packages at
all, so the rules that live in a skill next door have to live in a knowledge
file or in the prompt. The tests that matter here are the ones holding this
delivery to the pack it is built from, and to the limits the surface enforces.
"""

from pathlib import Path

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("pandas")

from pipeline.scripts import build_agent_pack as build


def test_the_builder_folder_is_created_only_where_the_sync_is_proven(tmp_path, monkeypatch):
    """`Input/` existing is the proof, and `Output/` is created beside it.

    Never creating anything would drop this delivery into the checkout on the
    first run, unsynced -- which is the failure the never-create rule exists to
    prevent, arriving by the other door. Creating unconditionally would make a
    folder inside a OneDrive that is not really set up, which syncs nowhere.
    """
    onedrive = tmp_path / "OneDrive - Example"
    monkeypatch.setattr(build, "find_onedrive_root", lambda: onedrive)

    # No CPLAN Input folder: nothing is created, the local fallback is used.
    assert build.resolve_builder_output_dir() == build.BUILDER_LOCAL_OUTPUT_DIR
    assert not (onedrive / build.ONEDRIVE_OUTPUT_DIR).exists()

    # Input exists, so the sync is real and Output can be created beside it.
    (onedrive / build.ONEDRIVE_INPUT_DIR).mkdir(parents=True)
    expected = onedrive / build.ONEDRIVE_OUTPUT_DIR / build.BUILDER_DIRNAME
    assert build.resolve_builder_output_dir() == expected
    assert expected.exists()

    # No OneDrive at all: the local fallback, and still nothing conjured.
    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    assert build.resolve_builder_output_dir() == build.BUILDER_LOCAL_OUTPUT_DIR


def test_the_two_deliveries_do_not_share_a_folder():
    """One is an input's neighbour, the other is a set of files to upload.

    Sharing a folder would put an answer key beside the export the pipeline
    reads, and would make `Nothing in the pipeline deletes from there` a
    promise about two different things at once.
    """
    assert build.ONEDRIVE_OUTPUT_DIR != build.ONEDRIVE_INPUT_DIR
    assert build.BUILDER_LOCAL_OUTPUT_DIR != build.LOCAL_OUTPUT_DIR
```

- [ ] **Step 2: Run it to verify it fails**

```bash
$PY -m pytest tests/test_agent_builder.py -v
```

Expected: FAIL — `AttributeError: module 'pipeline.scripts.build_agent_pack' has no attribute 'resolve_builder_output_dir'`

- [ ] **Step 3: Add the OneDrive constant**

In `pipeline/scripts/process_cplan.py`, directly after line 50 (`ONEDRIVE_INPUT_DIR = ...`):

```python
# The agent-builder delivery is not an input to anything and is never read
# back, so it does not belong beside the export. `Input` is the folder the
# pipeline reads from; this one is a set of files a person uploads by hand.
ONEDRIVE_OUTPUT_DIR = Path("Projekte") / "CPLAN" / "Output"
```

- [ ] **Step 4: Add the resolver**

In `pipeline/scripts/build_agent_pack.py`, extend the import from `process_cplan` to include `ONEDRIVE_OUTPUT_DIR`, and add after `resolve_output_dir`:

```python
BUILDER_DIRNAME = "agent-builder"
BUILDER_LOCAL_OUTPUT_DIR = PIPELINE_DIR / "output" / BUILDER_DIRNAME


def resolve_builder_output_dir():
    """`Output/agent-builder`, created -- but only where `Input/` proves it can be.

    `resolve_output_dir` never creates its target, and the reason holds: a path
    conjured inside a OneDrive that is not really set up syncs nowhere while
    looking like it worked. `Output/` is different only in that it may
    legitimately not exist yet, and refusing to create it would drop this
    delivery into the checkout on every first run -- unsynced, and uploaded
    from the wrong machine, which is the failure the rule is there to prevent.

    `Input/` is the evidence. The pipeline reads from it, so its presence means
    the CPLAN folder is really syncing; a sibling of a real folder is safe to
    create. Without it nothing is conjured and the fallback is reported, exactly
    as next door.
    """
    root = find_onedrive_root()
    if root:
        if (root / ONEDRIVE_INPUT_DIR).exists():
            target = root / ONEDRIVE_OUTPUT_DIR / BUILDER_DIRNAME
            target.mkdir(parents=True, exist_ok=True)
            return target
        log(f"OneDrive root found ({root}) but {ONEDRIVE_INPUT_DIR} does not exist, "
            f"so {ONEDRIVE_OUTPUT_DIR} is not created either")
    return BUILDER_LOCAL_OUTPUT_DIR
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
$PY -m pytest tests/test_agent_builder.py tests/test_agent_pack.py -q
```

Expected: PASS, and the 44 existing agent-pack tests still pass.

- [ ] **Step 6: Commit**

```bash
git add pipeline/scripts/process_cplan.py pipeline/scripts/build_agent_pack.py tests/test_agent_builder.py && \
git commit -m "Put the upload set somewhere it is not mistaken for an input

The pack lands beside the export because it is built from it. This delivery
is read by nobody and uploaded by hand, so it lands in Output instead.

resolve_output_dir never creates its target, and the reason is good: a path
conjured inside a OneDrive that is not really set up syncs nowhere while
looking like it worked. Output/ is different only in that it may not exist
yet, and refusing to create it drops the delivery into the checkout on every
first run -- unsynced, uploaded from the wrong machine, which is the failure
the rule exists to prevent. Input/ existing is the evidence that the sibling
is safe to create.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The compressed instructions

14,423 characters into 8,000, with the two skills' 10,000 gone as well. What survives is the floor: the rules a chart or an answer is wrong on sight for breaking. Everything cut moves to a knowledge document in Task 4, where it may or may not be retrieved — which is why the palette moves *up* into the prompt rather than staying with the rest of the chart rules.

**Files:**
- Create: `pipeline/report/agent_builder.py`
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `agent_pack.ORGANISATION_PLACEHOLDER`, `agent_pack.TEAM_SIGNATURE`, `agent_pack.INSTRUCTIONS_TEXT`, and the pack filename constants (`SUMMARY_NAME`, `GLOSSARY_NAME`, `QUALITY_NAME`, `CALENDAR_NAME`, `ACTIVITIES_CSV_NAME`, `BREAKDOWN_NAME`)
- Produces: `agent_builder.INSTRUCTIONS_TEXT`, `agent_builder.INSTRUCTIONS_LIMIT`, `agent_builder.INSTRUCTIONS_NAME`, `agent_builder.READING_GUIDE_NAME`, `agent_builder.CHART_STANDARDS_NAME`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_builder.py` (and add `from pipeline.report import agent_builder, agent_pack` to the imports):

```python
def test_the_instructions_fit_the_field_with_room_to_spare():
    """8,000 is the surface's limit, and a limit hit exactly is a limit missed.

    Measured with the placeholder still in it: the text is pasted after one
    find-and-replace, and an organisation whose name is longer than
    `<ORGANISATION>` must not be the thing that pushes it over.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert len(text) <= agent_builder.INSTRUCTIONS_LIMIT, (
        f"{len(text)} characters against a field that holds "
        f"{agent_builder.INSTRUCTIONS_LIMIT}")
    headroom = agent_builder.INSTRUCTIONS_LIMIT - len(text)
    assert headroom >= 200, (
        f"only {headroom} characters spare -- too tight for a longer "
        f"organisation name than the {len(agent_pack.ORGANISATION_PLACEHOLDER)}-"
        "character placeholder")


def test_no_rule_was_lost_in_the_compression():
    """A four-fifths cut is where a load-bearing rule quietly goes missing.

    Each marker below is a rule that produces a WRONG answer when absent, not
    merely a duller one: a total that disagrees with the workbook in the
    reader's hand, a sum over rows that must not be summed, a headcount
    presented as reach. The Studio instructions state all of them, and an edit
    here that drops one fails rather than shipping an agent missing a rule.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    for marker in (
            "does not contain sufficient evidence",   # refuse rather than invent
            "how many rows you examined",             # a partial count is named as one
            "out of scope",                           # absent is not zero
            "overlaps=yes",                           # overlapping rows do not sum
            "never call any of it",                   # audience is not reach
            "GEB or GEB-1",                           # one field, two levels
            "one combination, not one channel",       # multi-value strings
            "the week it starts",                     # weekly placement
            "in_report",                              # wider than the workbook
            "planning studio",                        # where to send what is missing
            "#E60000",                                # the accent
            "#7A7870",                                # the default series
            "largest area",                           # red bounded by area, not count
            "half the image",                         # the white ratio
            "No gridlines",
            "You might also ask",                     # the follow-up block's shape
            "Data as of",                             # the footer's date
            agent_pack.TEAM_SIGNATURE,                # the signature
    ):
        assert marker in text, f"the compression dropped {marker!r}"


def test_the_instructions_carry_no_organisation_name():
    """This repository is public. The name is filled in where the text is used.

    A placeholder cannot be forgotten -- it is visible in the pasted text and
    reads as unfinished -- whereas a name committed once stays in every clone
    and fork of the history, whatever a later commit removes.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert agent_pack.ORGANISATION_PLACEHOLDER in text
    for line in text.splitlines():
        if "brand" in line.lower() or "-compliant" in line.lower():
            assert agent_pack.ORGANISATION_PLACEHOLDER in line, (
                f"a brand line without the placeholder: {line!r}")


def test_the_instructions_are_pasted_as_they_stand():
    """No header addressed to the operator, because it would be pasted too.

    The Studio file opens with an HTML comment telling the reader to replace
    the placeholder. Here that comment would spend characters the field cannot
    spare on a sentence the model does not need, and a reader who pastes the
    file pastes the comment with it. The instruction lives in the run output
    and in the README beside the file instead.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert not text.lstrip().startswith("<!--")
    assert "Before pasting" not in text
```

- [ ] **Step 2: Run to verify they fail**

```bash
$PY -m pytest tests/test_agent_builder.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.report.agent_builder'`

- [ ] **Step 3: Create the module with the compressed instructions**

Create `pipeline/report/agent_builder.py`:

```python
"""The same report pack, delivered to a surface that has no skills.

Copilot Studio takes the rules as skill archives that load before a turn, and
takes as many characters of Instructions as the prompt needs. Agent Builder in
Microsoft 365 Copilot takes 8,000 characters and no archives at all: the only
place a rule can live outside the prompt is a knowledge file, which is
retrieved rather than loaded.

So this module is not a smaller `agent_pack`. The data files are the same
files, from the same run -- `agent_pack` writes them and this module delivers
them. What differs is everything around them, and the difference has one
governing rule: what is wrong on sight goes in the prompt, and what merely
guides goes in a document. If the document is missed the agent draws an ugly
chart; if the palette were in it, the agent would draw an off-brand one.
"""

import shutil

from pipeline.report import agent_pack

# The surface's own numbers, from the Microsoft Learn documentation for Agent
# Builder. Named rather than inlined because a test asserts against them and a
# reader deserves to see what is being obeyed rather than a bare 8000.
INSTRUCTIONS_LIMIT = 8000
DESCRIPTION_LIMIT = 1000
KNOWLEDGE_SOURCE_LIMIT = 20

UPLOAD_DIRNAME = "upload"
INSTRUCTIONS_NAME = "instructions.md"
DESCRIPTION_NAME = "description.txt"
STARTER_PROMPTS_NAME = "starter-prompts.md"
README_NAME = "README.txt"

READING_GUIDE_NAME = "07-reading-guide.txt"
CHART_STANDARDS_NAME = "08-chart-standards.txt"

# The six the skill archive carries, in the order they are numbered. `00-README`
# is left out for the reason the archive leaves it out: it explains the pack to
# a person, and the reading guide does that job for the agent.
UPLOAD_DATA_FILES = (
    agent_pack.SUMMARY_NAME,
    agent_pack.GLOSSARY_NAME,
    agent_pack.QUALITY_NAME,
    agent_pack.CALENDAR_NAME,
    agent_pack.ACTIVITIES_CSV_NAME,
    agent_pack.BREAKDOWN_NAME,
)


# No comment header addressed to the operator. The Studio file opens with one,
# and it is right to: that file is long enough that 330 characters of guidance
# cost nothing. Here they cost four percent of the field, and a reader who
# selects-all and pastes takes the comment into the prompt with them. What the
# operator needs to know is in the run output and in README.txt beside this.
INSTRUCTIONS_TEXT = f"""You are the Communications Planning Insight Agent.

You answer questions about communications planning activity using only the CPLAN report pack in your knowledge, for Internal Communication Planners, Communication Executives and Analytics teams.

## Your files

- `{agent_pack.SUMMARY_NAME}` — portfolio figures: volume, load, lead time, leadership involvement. Carries the period and the `Data as of` date.
- `{agent_pack.GLOSSARY_NAME}` — definitions and reading rules. Read this first.
- `{agent_pack.QUALITY_NAME}` — completeness, pack coverage, record anomalies
- `{agent_pack.CALENDAR_NAME}` — one row per block × value × week
- `{agent_pack.ACTIVITIES_CSV_NAME}` — one row per activity
- `{agent_pack.BREAKDOWN_NAME}` — one row per block × value × measure, for a question crossing two dimensions
- `{READING_GUIDE_NAME}` — who is asking, how to work through an analysis, what this pack answers well
- `{CHART_STANDARDS_NAME}` — which chart answers which question, and how to lay out more than one

There is no Excel workbook behind this agent. Prefer `{agent_pack.SUMMARY_NAME}`, `{agent_pack.CALENDAR_NAME}` and `{agent_pack.BREAKDOWN_NAME}` for any figure they already state: those were computed by tested code. A figure you derive yourself from `{agent_pack.ACTIVITIES_CSV_NAME}` has not been through the report's rules.

Open `{READING_GUIDE_NAME}` before you answer and `{CHART_STANDARDS_NAME}` before you draw. The rules below hold whether or not you reach them.

## Non-negotiable rules

### 1. Evidence first

Every conclusion traces to the data. Never invent causes, trends, benchmarks, forecasts or recommendations. Where the data does not support a conclusion, say: "The dataset does not contain sufficient evidence to answer this question." Separate facts, interpretation and suggested actions.

### 2. Quantify

Report count, percentage, change against a named comparison, and sample size.
Correct: "74 activities were planned in Q3, representing 22% of all recorded activities." Not: "Q3 was very active."

### 3. Show the calculation

For every insight give the fields used, filters applied, date range and calculation logic. When you count over `{agent_pack.ACTIVITIES_CSV_NAME}`, state how many rows you examined. If you cannot see every row, say so instead of estimating — a count from part of the file is a guess wearing a number.

### 4. Surface data quality

Check for missing values, duplicates, empty categories, invalid dates and inconsistent naming, and flag what affects interpretation.

Do NOT flag these — they are the report working as designed:
- A quarter or ISO week naming the year before the period. Scope is an overlap test; those columns label the start, and the start may lie outside.
- Archived activities. Archiving is a list-size workaround in the source system, not a relevance signal.

### 5. CPLAN data rules

These come from the data rather than from good reporting practice, and they override general analytical instinct.

- **Scope is a hard filter.** The period is at the top of `{agent_pack.SUMMARY_NAME}`. An activity outside it is absent, not zero — a question about a date outside the period is out of scope, not an answer of nought.
- **Overlapping rows do not sum.** A row marked `overlaps=yes` sits in a block where one activity appears under two values. Only `block={agent_pack.TOTAL_BLOCK}` is a true total.
- **Audience is a planning estimate, never measured reach.** Summing audience counts contacts, not people — one person inside six activities counts six times. Quote the largest single audience as the ceiling on unique people, and never call any of it "reach".
- **GEB/GEB-1 is one field holding both levels**, with nothing in the data saying which. Never name someone as a GEB member, and never answer "how many activities involve the GEB" — the honest answer is "GEB or GEB-1".
- **`channel` and `target_audience` hold several values in one string.** "Email, Intranet" is one combination, not one channel.
- **Weekly counts place each activity once, in the week it starts.** A six-week campaign is one activity in one week, not six.
- **This pack is wider than the distributed workbook.** It keeps the deprioritised bucket and rows tagged with nothing but the catch-all objective. Every row in `{agent_pack.ACTIVITIES_CSV_NAME}` carries `in_report` and `report_exclusion`; counting `in_report = Yes` reproduces the workbook. Quote the full count and name which one you used: "1,385 in the plan; 1,362 in the report, which leaves out 23 deprioritised."
- **When the answer is not in the pack**, say so and point to the planning studio, which holds the full record. Do not reason your way to a figure.

## Charts

Where a rule gives a number, the number is the rule.

### The {agent_pack.ORGANISATION_PLACEHOLDER} brand palette — these values and no others

| Role | Hex |
|---|---|
| White — every background, and the dominant colour | `#FFFFFF` |
| Black — body text, axis line, rules, data labels | `#000000` |
| Accent red — the one highlighted element | `#E60000` |
| Grey III — lighter series, secondary bars | `#8E8D83` |
| Grey IV — the default series, and footnote text | `#7A7870` |
| Grey V — average and reference lines | `#5A5D5C` |
| Grey VI — the darkest series, dark fills | `#404040` |
| Bordeaux I — a second red where red must appear twice | `#BD000C` |
| Bronze I — a third series | `#B98E2C` |
| Pastel I — tile fills, highlight blocks, alternate rows | `#ECEBE4` |

The greys are warm. A cool grey — `#808080`, `#999999`, a library default — is off-brand though it reads as grey on screen. Status colours are for data-driven status only: red `#BD000C`, amber `#E4A911`, green `#6F7A1A`.

### How much of each

- **At least half the image is unmarked white.** Margins and the space around type count; a filled panel background does not.
- **One red element per chart, at most two in an image.** It is the answer to that chart's business question.
- **Red never covers the largest area.** If the thing you would highlight is already the biggest, leave it grey — the eye lands there anyway.
- **Highlight only where one thing is the answer.** A ranked bar chart, a line with a peak. Where the categories are peers and the split itself is the answer — a donut, a stacked bar — nothing is highlighted.
- **Everything else is grey.** Never fill a tile, header band or panel with red.

### Typography and mechanics

- **Never capitals for emphasis**, in titles, labels or captions. Sentence case throughout. Never underline, never bold with italic.
- **Text is black**; subtitles and footnotes Grey IV. There is no case in this brand for a red heading or a red number.
- Relative to body text: title about 2.5x at light weight, panel heading about 1.2x bold, footnote about 0.8x. One body size per image. Left-align everything.
- **No gridlines**, horizontal or vertical. A single black baseline of about 1pt is the entire frame.
- **Flat and two-dimensional.** No 3D, shadows, gradients, rounded corners, or anything placed behind text.

### Every chart carries

Title · business question · date range · metric definition · source.

Source is the CPLAN report pack with the `Data as of` date from `{agent_pack.SUMMARY_NAME}`. Never name a workbook filename — this agent does not read one. Where the image states a total, the footnote says what that total counts: an image is forwarded without its author, and nobody can ask it which of two true totals it meant.

One message per chart. A chart carrying two is two charts.

## Answer format

Executive summary (3–5 bullets) · Key findings, with numbers · Visualizations (1–3 {agent_pack.ORGANISATION_PLACEHOLDER}-compliant charts) · Implications · Data limitations · Recommended follow-up analysis.

**Say each figure once.** These sections divide the work; they do not each get a turn at the same sentence. A figure belongs to one place: the chart, if it has a shape worth seeing, otherwise a line of prose. A number tile is for a figure with no chart beside it. A caption says what the chart *means*, not what it shows. A panel restating its neighbour is a panel to drop.

## Offer the next three questions

After the answer and before the footer, offer three follow-ups as a short list, phrased the way the user would type them. Copy the formatting, not only the wording:

> **You might also ask**
> - How does that split by division?
> - Which weeks in that quarter are the busiest?
> - Which channels carry most of that volume?

Three, every time, including after a one-line factual answer. Never a question you have just answered, and only ones this pack can answer. If a third is hard to find, widen the angle rather than dropping one.

## Close every answer with one footer line

End every answer with this line, and nothing after it:

> _Data as of YYYY-MM-DD · Powered by {agent_pack.TEAM_SIGNATURE}_

The date is the `Data as of` row at the top of `{agent_pack.SUMMARY_NAME}`. **Every turn carries it, not just the first** — a follow-up, a one-line correction, an answer drawing on no figure at all. A footer that appears once and then stops is worse than none: the reader has learnt to expect a vintage, so its absence reads as "still current". The vintage does not change inside a conversation, so restate the date you already gave rather than dropping the line.

If that date is more than four weeks old, add "— this pack may be out of date" before the signature.
"""
```

- [ ] **Step 4: Run to verify the tests pass**

```bash
$PY -m pytest tests/test_agent_builder.py -v
```

Expected: PASS. If `test_the_instructions_fit_the_field_with_room_to_spare` fails, cut from the *chart* sections first — Task 4 puts the chart-type guidance in a document, and the palette and ratio are the only chart rules that must stay here. Never cut a marker from `test_no_rule_was_lost_in_the_compression`.

- [ ] **Step 5: Print the length, so the budget is a fact rather than a hope**

```bash
$PY -c "
import sys; sys.path.insert(0, '.')
from pipeline.report import agent_builder as ab
n = len(ab.INSTRUCTIONS_TEXT)
print(f'{n} characters, {ab.INSTRUCTIONS_LIMIT - n} spare')"
```

Expected: a number at or under 7,800.

- [ ] **Step 6: Commit**

```bash
# brand grep (see the workspace CLAUDE.md) -- must find nothing
git add pipeline/report/agent_builder.py tests/test_agent_builder.py && \
git commit -m "Fit the prompt in a field that holds eight thousand characters

Fourteen thousand of instructions and ten thousand of skills, into eight
thousand and no skills at all. What survives is the floor: the rules an
answer or a chart is wrong on sight for breaking.

The palette moves UP into the prompt rather than staying with the rest of
the chart rules. In Studio it can sit in a skill because the skill loads
before the agent draws; here it would sit in a document that is retrieved
or not. A missed document should cost an ugly chart, not an off-brand one.

A named marker list holds the compression honest: each one is a rule whose
absence produces a wrong answer rather than a duller one, so an edit that
drops one fails instead of shipping an agent quietly missing a rule.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The description and the starter prompts

Two small fields the surface asks for and the Studio delivery has no equivalent of. The description is what the orchestrator reads to decide whether this agent is the one for a question, so it names the domain rather than praising the agent.

**Files:**
- Modify: `pipeline/report/agent_builder.py`
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Produces: `agent_builder.DESCRIPTION_TEXT`, `agent_builder.STARTER_PROMPTS_TEXT`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_builder.py`:

```python
def test_the_description_fits_and_says_what_the_agent_is_for():
    """The orchestrator reads this to decide whether to route a question here.

    A description that praises the agent instead of naming its domain gets it
    picked for questions it cannot answer, which costs more than being missed.
    """
    text = agent_builder.DESCRIPTION_TEXT
    assert len(text) <= agent_builder.DESCRIPTION_LIMIT, (
        f"{len(text)} characters against a field that holds "
        f"{agent_builder.DESCRIPTION_LIMIT}")
    assert "communication" in text.lower()
    assert agent_pack.ORGANISATION_PLACEHOLDER not in text, (
        "the description is not a brand surface, so it needs no replacement")


def test_there_are_at_least_three_starter_prompts():
    """Three is the documented minimum, and they are what a tester tries first.

    They double as the shortest honest statement of scope: a tester who reads
    them learns what this pack answers without being told what it does not.
    """
    lines = [l for l in agent_builder.STARTER_PROMPTS_TEXT.splitlines()
             if l.strip().startswith("- ")]
    assert len(lines) >= 3
```

- [ ] **Step 2: Run to verify they fail**

```bash
$PY -m pytest tests/test_agent_builder.py -k "description or starter" -v
```

Expected: FAIL — `AttributeError: module 'pipeline.report.agent_builder' has no attribute 'DESCRIPTION_TEXT'`

- [ ] **Step 3: Add both literals**

Append to `pipeline/report/agent_builder.py`:

```python
# Names the domain rather than praising the agent. This field is what the
# orchestrator reads when it decides whether a question belongs here, so a
# sentence about how thorough the agent is buys nothing and a sentence about
# what it holds buys the routing. No placeholder: the description is not a
# brand surface, and one more find-and-replace is one more chance to forget.
DESCRIPTION_TEXT = """Answers questions about the internal communication plan \
- volumes, timing by week and quarter, channels, audiences, divisions and \
regions, leadership involvement, and planning quality - from a report pack \
generated by the CPLAN pipeline. Every answer states the figures it used, the \
rows it examined and the date the pack was built. Use it for any question \
about planned communication activities; it does not hold measured reach, \
engagement or any post-delivery result.
"""

# Four rather than the documented minimum of three: one per audience the pack
# serves, plus one that exercises the crossed dimensions, which is the answer
# most likely to expose whether retrieval reached the whole file.
STARTER_PROMPTS_TEXT = """# Starter prompts

Paste each as a separate starter prompt in the Configure tab.

- Which weeks in the current quarter carry the most activities?
- Which divisions have the most activities with executive involvement?
- How complete is the plan, and which fields are most often missing?
- How many activities are in scope, and how many does the distributed report leave out?
"""
```

- [ ] **Step 4: Run to verify they pass**

```bash
$PY -m pytest tests/test_agent_builder.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/agent_builder.py tests/test_agent_builder.py && \
git commit -m "Say what the agent is for, in the field that decides the routing

The description is read by the orchestrator, not by a user, so it names the
domain and names what the pack does NOT hold. An agent picked for a
question about measured reach answers it from a plan that has none.

Four starter prompts rather than the documented three: one per audience,
plus one that crosses two dimensions -- the answer most likely to show
whether retrieval reached the whole file.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The two knowledge documents

What the compression cut has to land somewhere. These are near-verbatim lifts of the two skills, minus their YAML front matter (meaningless here — nothing reads it) and minus the parts that moved into the prompt in Task 2.

**Files:**
- Modify: `pipeline/report/agent_builder.py`
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `agent_pack.SKILL_TEXT`, `agent_pack.BRAND_SKILL_TEXT`
- Produces: `agent_builder.READING_GUIDE_TEXT`, `agent_builder.CHART_STANDARDS_TEXT`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_builder.py`:

```python
def test_the_documents_carry_no_front_matter():
    """A skill's YAML header is read by the skill loader, and there is none here.

    Left in, the first thing retrieval returns from either file is two lines of
    metadata addressed to a system that does not exist on this surface.
    """
    for text in (agent_builder.READING_GUIDE_TEXT,
                 agent_builder.CHART_STANDARDS_TEXT):
        assert not text.lstrip().startswith("---")
        assert "name:" not in text.splitlines()[0]


def test_the_documents_do_not_call_themselves_skills():
    """There is no skill on this surface, so a reference to one is a dead end.

    An agent told to "load this skill" looks for a mechanism the surface does
    not have, and what it does next is not something the prompt controls.
    """
    for text in (agent_builder.READING_GUIDE_TEXT,
                 agent_builder.CHART_STANDARDS_TEXT):
        assert "this skill" not in text.lower()


def test_the_reading_guide_keeps_what_the_prompt_could_not():
    """The audiences and the analysis steps are the half that had to move.

    They are guidance rather than floor -- an answer missing them is duller,
    not wrong -- which is exactly why they were the right thing to cut from a
    field of 8,000 characters and the wrong thing to lose entirely.
    """
    text = agent_builder.READING_GUIDE_TEXT
    for marker in ("Internal communications planner", "Communication executive",
                   "Analytics", "Identify outliers", "still being filled in"):
        assert marker in text, f"the reading guide dropped {marker!r}"


def test_the_chart_document_keeps_the_geometry_and_not_the_palette():
    """The palette is in the prompt now, and repeating it invites a drift.

    Two statements of one hex value is two things to keep in step, and the
    copy that goes stale is the one nobody re-reads. What belongs here is the
    part that only matters once something is being drawn.
    """
    text = agent_builder.CHART_STANDARDS_TEXT
    for marker in ("Horizontal bar chart", "Leave a gutter", "Before you send it",
                   "one legend for the image"):
        assert marker in text, f"the chart document dropped {marker!r}"
    assert "| Role | Hex |" not in text, "the palette table belongs in the prompt"
```

- [ ] **Step 2: Run to verify they fail**

```bash
$PY -m pytest tests/test_agent_builder.py -k "document or reading_guide" -v
```

Expected: FAIL — `AttributeError: ... has no attribute 'READING_GUIDE_TEXT'`

- [ ] **Step 3: Add the reading guide**

Append to `pipeline/report/agent_builder.py`. This is `agent_pack.SKILL_TEXT` with the front matter, "Which file answers what", "Rules you must not break", "When you count" and "When to stop" removed — all four are in the prompt now — and the remaining three sections kept as they stand:

```python
# `agent_pack.SKILL_TEXT` minus its front matter and minus the four sections
# that moved into the prompt in this module. What is left is the guidance half:
# who is asking, how to work an analysis, and what to offer as a follow-up. It
# is not repeated in the prompt because an answer that misses it is duller
# rather than wrong, and 8,000 characters cannot hold both halves.
READING_GUIDE_TEXT = """# Reading the CPLAN pack

Your instructions carry the file list and the rules that must not be broken.
This is the rest: how to read for the person asking, and how to work through
an analysis rather than answering the first thing you find.

## Who is asking

Three audiences use this data, and the same figure serves them differently.

**Internal communications planner** — clashes, overload, channel use, audience
saturation by planned size, lead times, regional coordination. Answer three
things: what happened, where the conflicts are, what to review.

**Communication executive** — themes, executive participation (GEB or GEB-1,
which the data does not separate), division activity, planned audience size
(never described as reach), concentration. Keep it short: summary, key risks,
top opportunities.

**Analytics** — method, calculation, segmentation, trend, transparency.
Include definitions, assumptions and limitations.

## How to work through an analysis

1. **Describe** what the data shows — by month, by division, by region.
2. **Identify patterns**, but only ones the data supports: concentration,
   growth, decline, seasonality, uneven distribution. Name the two windows you
   are comparing, and never set a settled quarter against one still being
   filled in. Forward planning thins towards the end of the horizon, so the
   last quarter in scope reads as a collapse when it is merely not yet written.
3. **Identify outliers** — unusually high or low activity, high executive
   participation, exceptional lead times. Show exact figures.
4. **Recommend next review areas**, phrased as "Consider reviewing…" rather
   than "This happened because…" unless the evidence is there.

## What this pack answers well

Use these when you need a follow-up worth offering, or when a question is too
vague to answer as asked.

*Planners* — Which weeks have the highest volume? Where are audience overlaps
occurring? Which divisions cluster on the same dates? Which channels are
overused?

*Executives* — What are the most common themes? Which divisions drive the
highest activity? How much executive participation is recorded? Where are the
gaps?

*Analytics* — Activity distribution by quarter. Regional concentration.
Audience segmentation. Channel proxy metrics. Lead-time distribution.
"""
```

- [ ] **Step 4: Add the chart document**

Append to `pipeline/report/agent_builder.py`. This is `agent_pack.BRAND_SKILL_TEXT` with the front matter removed and its opening paragraph reworded — the original points at "your instructions" for the palette, which is still true here, but calls itself a skill, which is not:

```python
# `agent_pack.BRAND_SKILL_TEXT` minus its front matter, with the opening
# reworded: the original tells the reader the palette is in the instructions,
# which is still true, and calls itself a skill, which on this surface is a
# reference to a mechanism that does not exist. The palette table itself is
# NOT repeated here -- two statements of one hex value is two things to keep
# in step, and the copy that drifts is the one nobody re-reads.
CHART_STANDARDS_TEXT = """# Chart standards

The palette, the red-to-white ratio and the typography rules are in your
instructions and apply whether or not you reach this file. What follows is the
rest: the part that only matters once something is actually being drawn.

## Which chart answers which question

| The question is about | Use | Typical case |
|---|---|---|
| Change over time | Line chart, or column chart for few periods | Activities over time; participation over time |
| Comparing named things | Horizontal bar chart, sorted by value | Division performance; region distribution |
| Parts of a whole | Stacked bar; donut only at five categories or fewer | Channel mix; audience mix |
| Spread and outliers | Scatter plot, or a bar chart with the outlier annotated | Planning lead time; event concentration |

## Colouring the two kinds of chart

The first two rows above and the last one are **comparisons**: one thing is the
answer. Draw the series in Grey IV `#7A7870` and give that one thing — the
tallest bar, the peak, the outlier — the accent red.

The third row is **composition**: the categories are peers and the shape of
the split is the answer, so there is nothing to single out. Take the segments
in this order and leave red out of it entirely:

`#404040` · `#B98E2C` · `#8E8D83` · `#6C5312` · `#B8B3A2` · `#5A5D5C` · `#946F29`

Dark grey, bronze, mid grey, dark bronze, light grey, grey, bronze again —
enough separation for seven segments without a brand colour competing with the
data. Above seven, the categories are too many for a donut before they are too
many for the palette: group the tail into "Other" and say how many it holds.

Red enters a composition chart only when one named segment *is* the question —
"how much of the plan is share-price-sensitive?" makes that segment the answer
and the rest context. "How does this split by priority?" does not. Even then
your instructions' area rule applies: a segment that is already the largest is
carrying the message by size, and colouring it too says nothing new.

## Axes, lines and legends

- Drop the y-axis when every bar carries its own data label. Keep it for line
  charts, where the reader is reading a slope rather than a value.
- Average or reference line: Grey V `#5A5D5C`, dashed, labelled inline —
  `Average = 1,050`, not a legend entry.
- Prefer a donut with a large white centre to a pie. Avoid both above five
  categories.
- Legends: square swatches, text to the right. When several charts share the
  same categories, draw one legend for the image rather than one per chart.
- Sort bars by value unless the categories have their own order (weeks,
  quarters, audience bands). An unsorted bar chart makes the reader do the
  ranking you were supposed to do.

## Laying out more than one chart

A single chart fails by being wrong. An image holding six fails at the seams,
and that is a different discipline.

- **A panel is one block**: heading, business question, plot, footnote. Reserve
  the vertical space for all four *before* drawing the plot. A footnote added
  afterwards lands in the panel underneath — this is the single most common way
  these images break.
- **Leave a gutter at least as tall as a panel heading** between panels, both
  horizontally and vertically. Nothing is ever drawn inside a gutter, including
  an axis label that happens to be long.
- **Nothing overlaps anything.** An annotation sits inside its own plot area,
  clear of the axis labels below it and the subtitle above it. If a peak label
  will not fit above the peak, put it beside the peak.
- **Align the row.** Panels in a row share a top edge and a plot height, and
  their axes line up.
- **Number tiles align on the baseline of their numbers**, not on the centre of
  their boxes. A caption wrapping to two lines must not push its number up, or
  the row of figures reads as a staircase.
- **Every annotation carries its value.** A divider labelled `data as of` says
  nothing. `data as of <date>` says the thing.

Your instructions carry one more layout rule, under "Say each figure once": a
panel that restates what its neighbour already gives is a panel to drop, and
the white space left behind is worth more than the repetition. It is checked
below rather than repeated here.

## Before you send it

Read your own image once against this list. Fix what fails; do not caption it.

1. Does any text touch or overlap other text, a bar, an axis label, or a
   neighbouring panel?
2. Is there more than one red element in a chart, or more than two in the whole
   image? Is red covering the largest area, or sitting on a donut or stacked
   bar that has nothing to single out?
3. Any capitals used for emphasis, any underline, any coloured text?
4. Any gridlines, rounded corners, shadows, or a colour outside the palette?
5. Is at least half the image white?
6. Does every panel carry its heading, business question and source footnote,
   with none of them sitting in a neighbour's space? Where it states a total,
   does the footnote say what that total counts? An image is forwarded without
   its author, and there is nobody in it to ask which of two true totals it
   meant.
7. Does any figure appear twice in the image?

An image failing one of these is redrawn, not explained.
"""
```

- [ ] **Step 5: Run to verify they pass**

```bash
$PY -m pytest tests/test_agent_builder.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
# brand grep (see the workspace CLAUDE.md) -- must find nothing
git add pipeline/report/agent_builder.py tests/test_agent_builder.py && \
git commit -m "Give the cut half a file to live in

What eight thousand characters could not hold is guidance rather than floor:
who is asking, how to work an analysis, which chart answers which question,
how to keep six panels from colliding. An answer missing it is duller; an
answer missing the palette is off-brand. That is why one moved up and the
other moved out.

Both are near-verbatim lifts, minus the YAML front matter -- read by a skill
loader that does not exist on this surface -- and minus every reference to
'this skill', which points at a mechanism the agent will not find.

The palette table is not repeated here. Two statements of one hex value is
two things to keep in step, and the copy that drifts is the one nobody
re-reads.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Assembling the delivery

**Files:**
- Modify: `pipeline/report/agent_builder.py`
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `agent_pack.write_pack`'s returned `pack_dir`, `agent_pack.checklist_text`, `agent_pack.CHECKLIST_NAME`, `agent_pack.README_NAME`
- Produces: `agent_builder.write_builder_pack(pack_dir, out_dir, scope, config) -> Path` (returns the `upload/` directory)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_builder.py`:

```python
def _builder(tmp_path):
    """Both deliveries from one run, the way the command produces them."""
    from datetime import date

    from pipeline.report import agent_pack
    from pipeline.report.config import ReportConfig
    from tests.report_fixtures import load_fixture_scope

    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config)
    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "pack-out")
    out_dir = tmp_path / "builder-out"
    upload_dir = agent_builder.write_builder_pack(pack_dir, out_dir, scope, config)
    return pack_dir, upload_dir, out_dir


def test_the_upload_folder_holds_exactly_what_is_uploaded(tmp_path):
    """Eight files, and the folder is the instruction.

    An operator uploading a folder uploads the folder. Anything in it that
    should not be knowledge becomes knowledge, and the two candidates are both
    here: the answer key, and a README written for a person.
    """
    from pipeline.report import agent_pack

    _, upload_dir, _ = _builder(tmp_path)
    names = sorted(p.name for p in upload_dir.iterdir())
    assert names == sorted(agent_builder.UPLOAD_DATA_FILES
                           + (agent_builder.READING_GUIDE_NAME,
                              agent_builder.CHART_STANDARDS_NAME))
    assert agent_pack.CHECKLIST_NAME not in names, (
        "an agent that can read the answer key passes without computing anything")
    assert agent_pack.README_NAME not in names, (
        "the README explains the pack to a person; the reading guide does it "
        "for the agent")


def test_the_upload_folder_fits_the_knowledge_source_limit(tmp_path):
    """Twenty is the surface's limit, and this delivery must leave room.

    The boards are three more files if `dashboard-boards-skill` lands, and a
    delivery already at the limit could not take them.
    """
    _, upload_dir, _ = _builder(tmp_path)
    assert len(list(upload_dir.iterdir())) <= agent_builder.KNOWLEDGE_SOURCE_LIMIT


def test_the_uploaded_data_is_the_pack_byte_for_byte(tmp_path):
    """Two deliveries of one report, or the divergence is the bug.

    A copy that transformed anything on the way through would let the two
    agents disagree about a figure while both citing the same run, and the
    disagreement would surface as a wrong number that looks right.
    """
    pack_dir, upload_dir, _ = _builder(tmp_path)
    for name in agent_builder.UPLOAD_DATA_FILES:
        assert (upload_dir / name).read_bytes() == (pack_dir / name).read_bytes(), (
            f"{name} differs between the two deliveries")


def test_the_loose_files_are_beside_the_upload_folder_not_inside_it(tmp_path):
    """What is pasted and what is uploaded are different actions.

    The instructions are pasted into a field. Uploaded as knowledge instead,
    the agent reads its own rules as data and quotes them back as findings.
    """
    from pipeline.report import agent_pack

    _, _, out_dir = _builder(tmp_path)
    loose = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    assert loose == sorted([agent_builder.INSTRUCTIONS_NAME,
                            agent_builder.DESCRIPTION_NAME,
                            agent_builder.STARTER_PROMPTS_NAME,
                            agent_builder.README_NAME,
                            agent_pack.CHECKLIST_NAME])


def test_the_delivery_is_rewritten_in_place(tmp_path):
    """A second run replaces it rather than accumulating vintages.

    A knowledge folder holding two runs answers from both without saying so.
    """
    pack_dir, upload_dir, out_dir = _builder(tmp_path)
    first = sorted(p.name for p in upload_dir.iterdir())
    again = agent_builder.write_builder_pack(pack_dir, out_dir)
    assert sorted(p.name for p in again.iterdir()) == first
```

- [ ] **Step 2: Run to verify they fail**

```bash
$PY -m pytest tests/test_agent_builder.py -k "upload or loose or rewritten" -v
```

Expected: FAIL — `AttributeError: ... has no attribute 'write_builder_pack'`

- [ ] **Step 3: Write the assembler**

Note the `scope`/`config` handling: they are used only for the checklist, and `test_the_delivery_is_rewritten_in_place` passes `None` for both to prove a re-run needs nothing but the pack. Append to `pipeline/report/agent_builder.py`:

```python
README_TEXT = f"""CPLAN agent, Agent Builder delivery
====================================

Four things to do, in this order. Nothing here is uploaded except the
contents of {UPLOAD_DIRNAME}\\.

1. Instructions
   Open {INSTRUCTIONS_NAME}, replace every {agent_pack.ORGANISATION_PLACEHOLDER}
   with the organisation's name, and paste the whole file into the
   Instructions field on the Configure tab. Paste it as it stands: it is
   written to fit the field's {INSTRUCTIONS_LIMIT}-character limit exactly as
   delivered, and it is the whole prompt rather than an addendum to one.

2. Description
   Paste {DESCRIPTION_NAME} into the Description field. No replacement needed.

3. Knowledge
   Upload every file in {UPLOAD_DIRNAME}\\ -- all of them, and nothing else.
   The folder is the instruction: what is in it is what the agent is grounded
   on.

4. Starter prompts
   {STARTER_PROMPTS_NAME} holds four, one per line. Add each as its own
   starter prompt.

{agent_pack.CHECKLIST_NAME} is NOT uploaded, and NOT pasted. It is the answer
key: questions with their computed answers, for checking the agent by hand
once it is built. An agent that can read it passes every question without
computing anything.

Rebuild both deliveries together with agentpack.cmd. The pack next door and
this folder are two renderings of one run; uploading one that was built on a
different day than the other hands the agent two vintages of the same figure.
"""


def write_builder_pack(pack_dir, out_dir, scope=None, config=None):
    """The delivery Agent Builder takes, from the pack `agent_pack` just wrote.

    `pack_dir` is the source of every data file, copied rather than
    regenerated: regenerating would mean a second pass over the same scope,
    and two passes are two chances to differ. A copy can only be wrong by
    being stale, which the shared run already rules out.

    The upload folder is the instruction. An operator uploading knowledge
    uploads a folder, so anything sitting in it becomes knowledge whether or
    not it should -- which is why the answer key and the README are written
    outside it, next to the file that is pasted rather than uploaded.

    `scope` and `config` are needed only for the checklist. They are optional
    so that a re-run over an existing pack needs nothing but the pack.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = out_dir / UPLOAD_DIRNAME
    upload_dir.mkdir(parents=True, exist_ok=True)

    for name in UPLOAD_DATA_FILES:
        shutil.copyfile(pack_dir / name, upload_dir / name)
    (upload_dir / READING_GUIDE_NAME).write_text(READING_GUIDE_TEXT,
                                                 encoding="utf-8")
    (upload_dir / CHART_STANDARDS_NAME).write_text(CHART_STANDARDS_TEXT,
                                                   encoding="utf-8")

    # Beside the upload folder, never inside it: an agent grounded on its own
    # instructions reads them as data, quotes them back as findings, and the
    # rules stop being rules.
    (out_dir / INSTRUCTIONS_NAME).write_text(INSTRUCTIONS_TEXT, encoding="utf-8")
    (out_dir / DESCRIPTION_NAME).write_text(DESCRIPTION_TEXT, encoding="utf-8")
    (out_dir / STARTER_PROMPTS_NAME).write_text(STARTER_PROMPTS_TEXT,
                                                encoding="utf-8")
    (out_dir / README_NAME).write_text(README_TEXT, encoding="utf-8")
    if scope is not None and config is not None:
        (out_dir / agent_pack.CHECKLIST_NAME).write_text(
            agent_pack.checklist_text(scope, config), encoding="utf-8")
    return upload_dir
```

- [ ] **Step 4: Run to verify they pass**

```bash
$PY -m pytest tests/test_agent_builder.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/report/agent_builder.py tests/test_agent_builder.py && \
git commit -m "Make the folder the instruction

An operator uploading knowledge uploads a folder, so what is in it becomes
knowledge whether or not it should. The answer key and the README are
written outside it for that reason, beside the file that is pasted rather
than uploaded -- an agent grounded on its own instructions reads them as
data and quotes them back as findings.

The data files are copied from the pack rather than regenerated. A second
pass over the same scope is a second chance to differ; a copy can only be
wrong by being stale, and one run rules that out.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: One run, both deliveries

**Files:**
- Modify: `pipeline/scripts/build_agent_pack.py`
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `agent_builder.write_builder_pack`, `build_agent_pack.resolve_builder_output_dir`
- Produces: nothing new — `main()` gains a second delivery

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_builder.py`:

```python
def test_one_run_writes_both_deliveries(tmp_path, monkeypatch, capsys):
    """Two commands would allow building one and forgetting the other.

    A pack refreshed on one path and not the other hands the two agents two
    vintages of the same figure, which is the failure this repository is built
    to prevent -- and it is invisible, because both look freshly built.
    """
    from pipeline.report import agent_builder as ab

    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    monkeypatch.setattr(build, "BUILDER_LOCAL_OUTPUT_DIR", tmp_path / "builder")
    monkeypatch.setattr(build, "resolve_scope",
                        lambda args, config: _fixture_scope(tmp_path, config))

    assert build.main(["--out", str(tmp_path / "pack"), "--year", "2025"]) == 0

    upload = tmp_path / "builder" / ab.UPLOAD_DIRNAME
    assert (upload / ab.READING_GUIDE_NAME).exists()
    assert (tmp_path / "builder" / ab.INSTRUCTIONS_NAME).exists()
    out = capsys.readouterr().out
    assert ab.UPLOAD_DIRNAME in out, "the run never says what to upload"
    assert "not uploaded" in out.lower(), "the run never names the answer key"


def _fixture_scope(tmp_path, config):
    """The fixture scope, in the shape `resolve_scope` returns."""
    from tests.report_fixtures import load_fixture_scope

    return load_fixture_scope(tmp_path / "csv", config), config
```

- [ ] **Step 2: Run to verify it fails**

```bash
$PY -m pytest tests/test_agent_builder.py -k both_deliveries -v
```

Expected: FAIL — the builder folder is never written.

- [ ] **Step 3: Wire it into the run**

In `pipeline/scripts/build_agent_pack.py`, add `from pipeline.report import agent_builder` beside the existing `agent_pack` import. Then in `main()`, after the existing loop that logs the pack's own artefacts and before the final `log(f"Written to {out_dir}")`, insert:

```python
    # The second delivery, from the same pack in the same run. Two commands
    # would allow one to be rebuilt and the other forgotten, and two packs
    # built on two days are two vintages of one figure -- invisible, because
    # both folders look freshly built.
    builder_dir = resolve_builder_output_dir()
    upload_dir = agent_builder.write_builder_pack(pack_dir, builder_dir,
                                                  scope, config)
    log("")
    log(f"{builder_dir.name}\\  -- the Agent Builder delivery")
    log(f"  {agent_builder.UPLOAD_DIRNAME + chr(92):<22} "
        f"{len(list(upload_dir.iterdir()))} files -- upload ALL of these as Knowledge")
    for name, note in (
            (agent_builder.INSTRUCTIONS_NAME,
             f"paste into Instructions -- replace {agent_pack.ORGANISATION_PLACEHOLDER}"),
            (agent_builder.DESCRIPTION_NAME, "paste into Description"),
            (agent_builder.STARTER_PROMPTS_NAME, "four prompts, one per line"),
            (agent_builder.README_NAME, "these four steps, in order"),
            (agent_pack.CHECKLIST_NAME, "ANSWER KEY -- not uploaded, not pasted")):
        path = builder_dir / name
        log(f"  {name:<22} {path.stat().st_size / 1024:>8.1f} KB  {note}")
    log("")
    log(f"Written to {builder_dir}")
```

- [ ] **Step 4: Run to verify it passes**

```bash
$PY -m pytest tests/test_agent_builder.py tests/test_agent_pack.py -q
```

Expected: PASS, all of them.

- [ ] **Step 5: Commit**

```bash
git add pipeline/scripts/build_agent_pack.py tests/test_agent_builder.py && \
git commit -m "Build both deliveries in one run, or build neither

Two commands would let one be rebuilt and the other forgotten. Two packs
built on two days are two vintages of one figure, and nothing on either
folder says so -- both look freshly built, which is what makes it the
expensive kind of wrong.

The run lists the second delivery the way it lists the first: under the
folder each file is in, with the one file that must not be uploaded named
as such. Which artefacts may be uploaded is the only decision this command
leaves to the reader.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The staleness guard and the README

`check.ps1` exists because a hand-copied machine running an old checkout reports itself current. A new file with no manifest entry is invisible to it: the operator's copy simply has no Agent Builder delivery, and `check.ps1` says everything is fine.

**Files:**
- Modify: `check.ps1` (manifest entries and `$manifestVersion`)
- Modify: `README.md`
- Test: `tests/test_check_manifest.py` (existing — it enforces the bump)

- [ ] **Step 1: Run the manifest test to see it enforce the rule**

```bash
$PY -m pytest tests/test_check_manifest.py -q
```

Expected: PASS (nothing has changed in `check.ps1` yet).

- [ ] **Step 2: Add the manifest entries**

In `check.ps1`, after the `build_agent_pack.py` block (around line 199), add:

```powershell
    # The second delivery. A copy without these has no Agent Builder pack at
    # all, and nothing above notices: every file it does have is current.
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "def write_builder_pack";   Why = "the Agent Builder delivery - a NEW file; without it the run writes only the Studio pack and the test users have nothing to install" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "INSTRUCTIONS_LIMIT";       Why = "the 8,000-character limit is asserted rather than assumed - an older copy can hold a prompt the field silently truncates, and a truncated prompt loses the footer and the follow-ups first" },
    @{ Path = "pipeline\report\agent_builder.py"; Marker = "CHART_STANDARDS_NAME";     Why = "the chart geometry ships as a knowledge file because this surface has no skills - an older copy leaves the agent with the palette and no guidance on which chart to draw" },
    @{ Path = "pipeline\scripts\build_agent_pack.py"; Marker = "resolve_builder_output_dir"; Why = "the Agent Builder delivery lands in OneDrive Output beside the pack's Input - an older copy writes it into the checkout, unsynced, and the operator uploads a stale one from the wrong machine" },
    @{ Path = "pipeline\scripts\process_cplan.py"; Marker = "ONEDRIVE_OUTPUT_DIR";     Why = "the Output folder constant - without it build_agent_pack.py fails to import and NO pack is written at all, not merely the second one" },
```

- [ ] **Step 3: Bump the version, in the same commit**

Two edits, both required — the variable and the manifest entry that checks it. Change `2026-08-07.9` to `2026-08-07.10` in both places:

```powershell
$manifestVersion = "2026-08-07.10"
```
```powershell
    @{ Path = "check.ps1";                     Marker = '$manifestVersion = "2026-08-07.10"'; Why = "this script itself - an old copy checks a new repository against an old manifest and reports it fine" },
```

- [ ] **Step 4: Run the manifest test**

```bash
$PY -m pytest tests/test_check_manifest.py -q
```

Expected: PASS. If it fails, it names which of the two version strings was missed.

- [ ] **Step 5: Document it in the README**

In `README.md`, at the end of the "Agent pack" section (immediately before `## Daily workflow`), add:

```markdown
#### The same pack for Agent Builder

Publishing through Copilot Studio needs registration and review. Agent Builder
in Microsoft 365 Copilot needs neither — an agent built there is shared with
named people, or exported as a ZIP for an administrator, the day it is
finished. `agentpack.cmd` writes that delivery too, from the same run, into
`Projekte/CPLAN/Output/agent-builder` (`pipeline/output/agent-builder/` without
OneDrive). `README.txt` in that folder is the four steps in order.

The surface holds 8,000 characters of Instructions and **no skill packages at
all**, so the two skills have nowhere to go: `07-reading-guide.txt` and
`08-chart-standards.txt` ship as knowledge files instead, and `upload/` holds
those two plus the six data files — eight sources against a limit of twenty.
`00-README.txt` stays out for the reason the skill archive leaves it out, and
`checklist.md` stays out because an agent that can read the answer key passes
without computing anything.

This inverts two decisions made deliberately next door — the rules were moved
*out* of Instructions into skills, and the knowledge source was *removed* after
two probes showed it was never reached for. Both inversions are forced by the
surface rather than chosen. The consequence to watch is the one the probes
found: counting over `05-activities.csv` worked because the agent read the file
whole, and chunked retrieval is the one thing that cannot. `06-breakdowns.csv`
and `01-summary.txt` pre-compute what they can, and the signal that it is not
enough is the agent no longer writing "examined all N rows".

The design is in
[`docs/superpowers/specs/2026-08-07-agent-builder-variant-design.md`](docs/superpowers/specs/2026-08-07-agent-builder-variant-design.md).
```

Also add two rows to the artefact table near the end of the README (the one listing `pipeline/output/cplan_studio_standalone.html`):

```markdown
| `<OneDrive>/Projekte/CPLAN/Output/agent-builder/upload/` | Agent Builder knowledge — eight files, uploaded whole |
| `<OneDrive>/Projekte/CPLAN/Output/agent-builder/instructions.md` | Agent Builder Instructions — pasted, after one find-and-replace |
```

- [ ] **Step 6: Run everything, and check the brand rule**

```bash
$PY -m pytest tests/ -q 2>&1 | tail -5 && \
# brand grep (see the workspace CLAUDE.md) -- must find nothing
```

Expected: the full suite passes, and the brand grep exits 1.

- [ ] **Step 7: Commit**

```bash
git add check.ps1 README.md && \
git commit -m "Make the second delivery visible to the staleness check

check.ps1 exists because a hand-copied machine running an old checkout
reports itself current. A new file with no manifest entry is invisible to
it: the operator's copy has no Agent Builder delivery at all, and every
file it does have is current, so the check passes in green.

The process_cplan entry is the one that matters most. Without
ONEDRIVE_OUTPUT_DIR the import fails and NO pack is written -- not merely
the second one -- so an operator with a new build_agent_pack.py and an old
process_cplan.py loses both.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Verification

After Task 7, verify the real artefact rather than only the tests. The fixture scope proves the shapes; a real build proves the delivery.

- [ ] **Build against the fixture and read the output**

```bash
$PY -c "
import sys; sys.path.insert(0, '.')
from datetime import date
from pathlib import Path
from pipeline.report import agent_builder, agent_pack
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope

out = Path('/tmp/cplan-builder-check')
config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
scope = load_fixture_scope(out / 'csv', config)
pack = agent_pack.write_pack(scope, config, out / 'pack')
upload = agent_builder.write_builder_pack(pack, out / 'builder', scope, config)
print('upload/:')
for p in sorted(upload.iterdir()):
    print(f'  {p.name:<24} {p.stat().st_size/1024:>7.1f} KB')
print('beside it:')
for p in sorted((out / 'builder').iterdir()):
    if p.is_file():
        print(f'  {p.name:<24} {p.stat().st_size/1024:>7.1f} KB')
i = (out / 'builder' / agent_builder.INSTRUCTIONS_NAME).read_text(encoding='utf-8')
print(f'instructions: {len(i)} chars, {agent_builder.INSTRUCTIONS_LIMIT - len(i)} spare')
"
```

Expected: eight files in `upload/`, five beside it, and the instructions under 8,000 with at least 200 spare.

- [ ] **Read `instructions.md` end to end.** It is the artefact a person pastes and never re-reads. Check that no sentence refers to a skill, a workbook filename, or a file that is not in `upload/`.

- [ ] **Read `README.txt`.** The four steps must be followable by someone who has not read this plan.

## Self-Review Notes

Checked against the spec:

- **Every spec decision has a task.** Data files unchanged (Task 5 copies rather than regenerates); separate module (Task 2); hand-written not derived (Task 2); floor carries more weight (Task 2 palette, Task 4 excludes it); `.txt` documents (Task 4 constants); no human header (Task 2, asserted); placeholder kept (Task 2, asserted); `Output/agent-builder` (Task 1); create-only-when-`Input`-exists (Task 1, asserted).
- **Every spec test has a task.** All eight bullets from the spec's Tests section appear across Tasks 1–6.
- **`evaluation.csv` dropped** — no task writes it, which is the spec's decision.
- **One deviation from the spec, deliberate:** the spec left the command open; this plan puts both deliveries in `agentpack.cmd`. Two commands would allow building one and forgetting the other, and the spec's own "two renderings of one report" argument decides it.
- **`checklist.md` is written twice**, once per delivery folder, because the two folders are now in different OneDrive parents and an operator works in one of them. Identical content from identical inputs, so the duplication cannot disagree.
