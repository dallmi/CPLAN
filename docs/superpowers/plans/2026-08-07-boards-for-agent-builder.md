# Boards for Agent Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deliver the three named executive boards to Agent Builder, a surface with no skill packages, as three self-contained knowledge files plus 193 characters of routing in the prompt.

**Architecture:** `pipeline/report/agent_builder.py` gains a shared-rules constant and writes three board files into `upload/`, each being that block followed by `dashboard_skill.BOARDS[...]` verbatim. The panel text is never re-authored, so the citation test in `tests/test_agent_pack.py` covers both deliveries. The prompt gains one paragraph naming the three boards, because a knowledge file cannot tell an agent that boards exist.

**Tech Stack:** Python 3.13, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-07-boards-for-agent-builder-design.md`

## Global Constraints

- **No organisation name anywhere in the repository.** Not in code, comments, docs, test data or commit messages. `<ORGANISATION>` is the placeholder the operator replaces, and it appears in `INSTRUCTIONS_TEXT` only.
- **`INSTRUCTIONS_TEXT` must stay within `INSTRUCTIONS_LIMIT` (8,000) AND keep at least 200 characters spare.** It is 7,779 today, so the usable budget is 21 characters, not 221. `tests/test_agent_builder.py::test_the_instructions_fit_the_field_with_room_to_spare` enforces the 200-character floor, and it exists because `<ORGANISATION>` is replaced by a longer name before the text is pasted. Never raise the limit, never lower the floor.
- **`test_no_rule_was_lost_in_the_compression` guards eighteen marker strings** in `INSTRUCTIONS_TEXT`. Any edit to that constant must leave all eighteen present. The two cuts in Task 2 were checked against the list and touch none of them.
- **Knowledge documents are `.txt`, never `.md`** — `.md` is not on the crawled-extension list, and a file that is not crawled is not retrievable.
- **The `upload/` folder is the instruction.** Anything written into it becomes knowledge. Nothing that is not uploaded may be written there.
- **Board panel text is `dashboard_skill.BOARDS` verbatim.** Never a copy, never a re-wording. Two products must not ship two versions of one board.
- **Commit message style:** imperative sentence, no `feat:`/`fix:` prefix, a body explaining *why*, trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **`check.ps1` carries a hand-maintained manifest.** `tests/test_check_manifest.py` requires any manifest-listed file that changes to gain a NEW marker string absent from the version it replaced, plus a `$manifestVersion` bump. Handle it in the same commit as the change; the failing test's message prescribes what it wants.
- **Run tests with** `PYTHONPATH=. .venv/bin/python -m pytest` from the repository root.

---

### Task 1: The three board files

**Files:**
- Modify: `pipeline/report/agent_builder.py` (constants near `CHART_STANDARDS_NAME`; `write_builder_pack`)
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `dashboard_skill.BOARDS`, a `dict[str, str]` whose keys are `board-portfolio-overview.md`, `board-leadership-attention.md`, `board-plan-trust.md` and whose values are the board texts.
- Produces: `agent_builder.BOARD_RULES_TEXT` (str), `agent_builder.BOARD_FILE_NAMES` (a `dict` mapping each `dashboard_skill.BOARDS` key to its upload filename), and three files in `upload/`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_builder.py`, after `test_the_chart_document_keeps_the_geometry_and_not_the_palette`:

```python
def test_each_board_travels_as_its_own_file(tmp_path):
    """One file per board, because retrieval returns chunks and a board is only
    worth having whole.

    A skill package loads entire; a knowledge file does not. An agent handed
    panel 3 of one board and panel 1 of another draws the blended board these
    definitions exist to prevent, so the catalogue is never one document here.
    """
    upload = _delivery(tmp_path)
    names = sorted(p.name for p in upload.iterdir())
    for name in agent_builder.BOARD_FILE_NAMES.values():
        assert name in names, f"{name} is not in the upload folder"
        assert name.endswith(".txt"), f"{name} is not crawled, so not retrievable"
    assert len(agent_builder.BOARD_FILE_NAMES) == 3


def test_a_board_file_is_the_shared_rules_then_the_board_unaltered(tmp_path):
    """The panels are `dashboard_skill`'s text, not a second copy of it.

    Two deliveries shipping two versions of one board is the drift this
    repository is built to prevent, and the citation test over
    `dashboard_skill.BOARDS` only protects the text it actually holds.
    """
    upload = _delivery(tmp_path)
    for key, name in agent_builder.BOARD_FILE_NAMES.items():
        text = (upload / name).read_text(encoding="utf-8")
        assert agent_builder.BOARD_RULES_TEXT in text, f"{name} lost the shared rules"
        assert dashboard_skill.BOARDS[key] in text, f"{name} altered the board"
        assert text.index(agent_builder.BOARD_RULES_TEXT) < text.index(
            dashboard_skill.BOARDS[key]), f"{name} states the rules after the panels"


def test_every_board_file_answers_on_its_own(tmp_path):
    """The rules are repeated three times on purpose.

    In the skill package they sit once in SKILL.md, because the index always
    loads. Nothing loads here, so a fourth file holding them would be a fourth
    thing retrieval can miss -- and it would be missed exactly when a board was
    found, which is the case that matters.
    """
    upload = _delivery(tmp_path)
    for name in agent_builder.BOARD_FILE_NAMES.values():
        text = (upload / name).read_text(encoding="utf-8")
        assert "Highlight: yes" in text
        assert text.count("Highlight: yes") == 1, f"{name} spends the red budget twice"
        # The four rules a board needs and the prompt does not already carry.
        for rule in ("in the order", "grey", "not the footnote", "say so"):
            assert rule in text.lower(), f"{name} does not state {rule!r}"
```

The helper `_delivery` may not exist yet. If the file has no equivalent, add it beside the other helpers at the top:

```python
def _delivery(tmp_path):
    """Build both deliveries over the fixture scope and return the upload folder."""
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config)
    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "pack")
    return agent_builder.write_builder_pack(pack_dir, tmp_path / "builder",
                                            scope, config)
```

Read the existing tests first — several already build a delivery, and if one of them already has such a helper under another name, use that one rather than adding a second.

Add the import if it is not already there:

```python
from pipeline.report import agent_builder, agent_pack, dashboard_skill
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -k board -v`
Expected: FAIL — `AttributeError: module 'pipeline.report.agent_builder' has no attribute 'BOARD_FILE_NAMES'`

- [ ] **Step 3: Add the constants**

In `pipeline/report/agent_builder.py`, after `CHART_STANDARDS_NAME`:

```python
# One file per board rather than one catalogue, because a skill package loads
# whole and a knowledge file is retrieved in chunks. A hit that returns panel 3
# of one board and panel 1 of another produces the blended board the
# definitions exist to prevent, so each board is its own retrieval target and
# small enough -- around 3,000 characters -- to come back entire.
#
# Numbered on from the two rule documents: an operator uploads a folder, and a
# folder that sorts into reading order is one fewer thing to explain.
BOARD_FILE_NAMES = {
    "board-portfolio-overview.md": "09-board-portfolio-overview.txt",
    "board-leadership-attention.md": "10-board-leadership-attention.txt",
    "board-plan-trust.md": "11-board-plan-trust.txt",
}


# Repeated into all three files, and that is the design rather than a
# concession. In the skill package these rules sit once in SKILL.md because the
# index always loads; here nothing loads, so a fourth file holding them would
# be a fourth thing retrieval can miss -- and it would be missed exactly when a
# board WAS found, which is the case that matters. Seven hundred characters
# three times costs nothing against nine spare knowledge slots.
#
# It carries only what a board needs and the prompt does not already state. The
# palette, the ratio and the typography rules are in Instructions, where a
# breach is wrong on sight.
BOARD_RULES_TEXT = """# How to draw a board

Draw the panels this file lists, in the order it lists them, and no others. A
panel you add is a panel nobody asked for; a panel you drop takes its question
with it.

Exactly one panel is red -- the one marked `Highlight: yes`. Every other panel
is grey throughout: bars, lines, markers and numbers. Tile numbers are black on
every board.

A `Source:` line says where to read the figure. It is not the footnote and is
never printed. The printed source footnote is the one your instructions
require: the CPLAN report pack with the `Data as of` date, never a filename.

If you cannot see this file whole, say so and draw nothing rather than filling
in the panels you cannot see.

"""
```

- [ ] **Step 4: Write the files**

In `write_builder_pack`, after the two rule documents are written:

```python
    for key, name in BOARD_FILE_NAMES.items():
        (upload_dir / name).write_text(
            BOARD_RULES_TEXT + dashboard_skill.BOARDS[key], encoding="utf-8")
```

Add `dashboard_skill` to the module's import at the top:

```python
from pipeline.report import agent_pack, dashboard_skill
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -v`
Expected: PASS. `test_the_upload_folder_holds_exactly_what_is_uploaded` and `test_the_upload_folder_fits_the_knowledge_source_limit` both enumerate the folder — read what they assert and update the expected set to the eleven files, keeping their intent intact.

- [ ] **Step 6: Handle the manifest and commit**

`pipeline/report/agent_builder.py` is manifest-listed, so add a new entry with a marker this change introduces and bump `$manifestVersion` to the next suffix. Read `check.ps1` for the current value.

```bash
git add pipeline/report/agent_builder.py tests/test_agent_builder.py check.ps1
git commit -m "$(cat <<'EOF'
Give each board its own file, because retrieval returns chunks

A skill package loads whole. A knowledge file does not, and Agent Builder
has no skill packages at all -- so the board catalogue that ships as one
archive next door would arrive here in fragments. An agent handed panel 3
of one board and panel 1 of another draws the blended board the
definitions were written to prevent.

Three files instead, one per board, each small enough to come back
entire, and each repeating the rules a board needs. That repetition is
the design: in the archive the rules sit once in the index because the
index always loads, and here a fourth file holding them would be missed
exactly when a board was found.

The panels are dashboard_skill's own text, unaltered. Two deliveries
shipping two versions of one board is the drift this repository exists to
prevent, and the citation test only protects the text it actually holds.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The routing, paid for by two justifications

A knowledge file cannot tell an agent that boards exist. The prompt is the only surface that always applies — and it has 21 usable characters, not 221, because a test holds 200 of them back for a longer organisation name. So this task spends 200 characters and frees 204 first.

**Files:**
- Modify: `pipeline/report/agent_builder.py` (`INSTRUCTIONS_TEXT`, `STARTER_PROMPTS_TEXT`, `README_TEXT`)
- Test: `tests/test_agent_builder.py`

**Interfaces:**
- Consumes: `BOARD_FILE_NAMES` from Task 1.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_prompt_is_what_tells_the_agent_boards_exist(tmp_path):
    """A knowledge file cannot announce itself.

    Retrieval answers a question; it does not tell the agent which questions
    have a fixed answer waiting. So the three names, and the instruction to ask
    when none is given, are the one part of the board design that has to be
    bought with prompt characters.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    for board in ("portfolio overview", "leadership attention", "plan trust"):
        assert board in text, f"the prompt does not name {board!r}"
    assert "ask" in text[text.index("portfolio overview"):
                         text.index("portfolio overview") + 400].lower(), (
        "the prompt names the boards without saying to ask which one")


def test_a_starter_prompt_offers_a_board(tmp_path):
    """The only path by which a user who does not know boards exist finds one.

    The prompt reacts to a dashboard being asked for. Nothing reacts to a user
    who has never heard the word, and a starter prompt is what the surface
    shows before the first question.
    """
    prompts = [line for line in agent_builder.STARTER_PROMPTS_TEXT.splitlines()
               if line.strip().startswith("-")]
    assert len(prompts) >= 5, "the board prompt was not added"
    assert any("board" in line.lower() for line in prompts), (
        "no starter prompt offers a board")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -k "boards_exist or starter_prompt_offers" -v`
Expected: FAIL — the prompt does not name `'portfolio overview'`

- [ ] **Step 3: Free the 204 characters first**

Two justifications come out of `INSTRUCTIONS_TEXT`. Both are prose that explains a rule; both leave the rule itself standing. Delete exactly these, including the single leading space that joins each to the sentence before it:

In the `## Close every answer with one footer line` section (146 characters):

```
 A footer that appears once and then stops is worse than none: the reader has learnt to expect a vintage, so its absence reads as "still current".
```

In the `## Answer format` section (58 characters):

```
 A caption says what the chart *means*, not what it shows.
```

Nothing else in either section moves. The footer obligation, the four-week staleness note, the restate-the-date instruction and the `Say each figure once` rule all stay. Verify afterwards that `test_no_rule_was_lost_in_the_compression` still passes — its eighteen markers were checked against these two cuts and none is affected, so a failure there means the wrong text was removed.

- [ ] **Step 4: Add the routing, in the file list**

In `INSTRUCTIONS_TEXT`, in the `## Your files` list, after the `08-chart-standards.txt` line:

```
- `09`–`11-board-*.txt` — one per named executive board: portfolio overview, leadership attention, plan trust
```

And extend the sentence that already says when to open a rule document — `Open `07-reading-guide.txt` before you answer and `08-chart-standards.txt` before you draw.` — by appending to it:

```
 Draw a board only from its own file; if none is named, say which three there are and ask.
```

Together these are 200 characters against the 204 just freed. Do not reword either: the wording was measured against a field that is 97% full. The list line is deliberately the place the three names live, so the agent can answer "which boards are there?" without retrieving anything.

- [ ] **Step 5: Add the starter prompt**

In `STARTER_PROMPTS_TEXT`, add as the last bullet:

```
- Show me the leadership attention board.
```

And in `README_TEXT`, change `holds four, one per line` to `holds five, one per line`.

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_agent_builder.py -v`
Expected: PASS, with `test_the_instructions_fit_the_field_with_room_to_spare` reporting headroom of about 225.

If that test fails, do NOT raise `INSTRUCTIONS_LIMIT` and do NOT lower the 200-character floor. Report the exact character count and stop: the budget is the constraint this entire design was built around, and a design that no longer fits is a design to revisit rather than a test to loosen.

- [ ] **Step 7: Handle the manifest and commit**

Add a manifest entry with a new marker and bump `$manifestVersion`.

```bash
git add pipeline/report/agent_builder.py tests/test_agent_builder.py check.ps1
git commit -m "$(cat <<'EOF'
Trade two justifications for the sentence that says boards exist

A knowledge file cannot announce itself. Retrieval answers a question; it
never tells the agent which questions have a fixed answer waiting -- so
the three board names have to be bought with prompt characters, and this
field has 21 of them once the 200 a longer organisation name may need are
held back.

So two passages leave: the footer rule's justification and the caption
refinement. Both explain a rule rather than state one, and both rules stay
standing without them -- which is the same test the four-fifths
compression already applied to everything else in this field. 204 out,
200 in.

The boards join the file list beside the other two rule documents rather
than sitting in the chart section, so the three names are somewhere the
agent can read them without retrieving anything.

A fifth starter prompt names a board, because the prompt only reacts to a
dashboard being asked for and a user who has never heard the word has no
other way to find one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Build both deliveries and read them

**Files:**
- No source changes expected. Any fix goes back to the task that owns the file.

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: nothing.

- [ ] **Step 1: Build**

The real entry point needs source CSV exports that are not on this machine. Build the fixture delivery into a real directory instead — same `write_builder_pack`, synthetic rows:

```bash
PYTHONPATH=. .venv/bin/python -c "
from datetime import date
from pathlib import Path
from pipeline.report import agent_builder, agent_pack
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope

out = Path('/tmp/cplan-builder-review')
config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
scope = load_fixture_scope(out / 'csv', config)
pack = agent_pack.write_pack(scope, config, out / 'pack')
print(agent_builder.write_builder_pack(pack, out / 'builder', scope, config))
"
```

- [ ] **Step 2: Read the upload folder**

Check by eye:
- eleven files, numbered `01` through `11`, nothing else;
- each board file opens with the shared rules and then the board, with no seam or duplicated heading where the two meet;
- no board file names the organisation;
- `checklist.md` and `instructions.md` are NOT inside `upload/`.

- [ ] **Step 3: Read `instructions.md` as the operator will**

Confirm the routing paragraph reads naturally where it sits — not as a fragment glued to the chart rules — and that the file is still one paste with no human-facing header. Count its characters and confirm the figure against `INSTRUCTIONS_LIMIT`.

- [ ] **Step 4: Report**

Nothing to commit if it all reads correctly; the delivery output is not in git. If something is wrong, fix it in the task that owns it.

---

## Self-Review

**Spec coverage.** One file per board and the self-contained rules block → Task 1. The verbatim-panels decision → Task 1, tested. The 193-character routing and the fifth starter prompt → Task 2. The `README_TEXT` count → Task 2. The manifest consequence is folded into both tasks rather than given its own, because the manifest test forces it into the same commit as the change — the last plan learned this the hard way and its Task 5 turned out to be empty.

**Deliberate omissions**, each stated in the spec's "Out of scope": the index's panel-contract explanation, a board evaluation set, and a pointer from `07-reading-guide.txt`.

**One thing to watch.** Task 1 Step 5 touches two existing tests that enumerate the upload folder. Update the expected set, never the assertion's intent — one of them exists to prove nothing extra is ever written where knowledge is uploaded from.
