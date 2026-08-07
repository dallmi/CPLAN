"""The agent pack: same figures as the workbook, none of its formulas.

The pack exists because the workbook cannot be read by a retrieval index. That
buys nothing if the two drift, so the tests that matter here are the ones that
hold them to each other -- against the workbook where the workbook states a
figure, and against the frame where it does not.
"""

import csv
import re
import zipfile
from datetime import date

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("pandas")

from pipeline.report import agent_pack
from pipeline.report.calendar_sheet import LABEL_COL, _split_for
from pipeline.report.config import AUDIENCE_BAND_ORDER, ReportConfig
from pipeline.scripts.report_calendar import build_workbook
from tests.report_fixtures import load_fixture_scope


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def _scope(tmp_path, **overrides):
    config = _config(**overrides)
    return load_fixture_scope(tmp_path / "csv", config), config


def _pack(tmp_path, **overrides):
    scope, config = _scope(tmp_path, **overrides)
    out_dir = tmp_path / "out"
    pack_dir = agent_pack.write_pack(scope, config, out_dir)
    return pack_dir, out_dir, scope, config


def _calendar(pack_dir):
    with (pack_dir / agent_pack.CALENDAR_NAME).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _summary_pairs(text):
    """`label -> value` for the "  label: value" lines, shares stripped off."""
    pairs = {}
    for line in text.splitlines():
        match = re.match(r"^  ([^:]+): (.*?)(?:  \(\d+% of the \d+ in scope\))?$", line)
        if match:
            pairs[match.group(1).strip()] = match.group(2).strip()
    return pairs


# ---------------------------------------------------------------------------
# Agreement with the workbook
# ---------------------------------------------------------------------------

def test_summary_figures_match_the_workbook(tmp_path):
    """Every label the Executive Summary states literally says the same here.

    The VOLUME rows are excluded by construction, not by choice: their labels
    on the sheet ARE formulas (`=TEXT(...) & "  Internal"`), so there is no
    literal label to match them on -- which is the whole reason this pack
    exists. `test_volume_counts_match_the_workbook` covers them by position.
    """
    pack_dir, _, scope, config = _pack(tmp_path)
    sheet = build_workbook(scope, config)["Executive Summary"]

    workbook_pairs = {}
    for row in range(1, sheet.max_row + 1):
        cell = sheet.cell(row, 2)
        label, value = sheet.cell(row, 1).value, cell.value
        if isinstance(label, str) and not label.startswith("=") and value is not None:
            # A share is stored as a fraction under a percent number format, so
            # the cell holding 0.45 displays 45%. The pack has no number
            # formats and writes what the reader sees, so the comparison is
            # made on the displayed figure -- otherwise this test would pass
            # only while both sides happened to store shares the same way.
            if isinstance(value, float) and "%" in (cell.number_format or ""):
                value = f"{value:.0%}"
            workbook_pairs[label.strip()] = value

    pack_pairs = _summary_pairs((pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8"))
    shared = set(workbook_pairs) & set(pack_pairs)
    assert len(shared) > 10, f"too few comparable labels ({sorted(shared)})"
    for label in sorted(shared):
        assert str(workbook_pairs[label]) == pack_pairs[label], (
            f"{label}: workbook says {workbook_pairs[label]!r}, "
            f"pack says {pack_pairs[label]!r}")


def test_volume_counts_match_the_workbook(tmp_path):
    """The VOLUME block's counts, matched by position under its header."""
    pack_dir, _, scope, config = _pack(tmp_path)
    sheet = build_workbook(scope, config)["Executive Summary"]

    header = next(r for r in range(1, sheet.max_row + 1)
                  if sheet.cell(r, 1).value == "VOLUME")
    workbook_counts = []
    for row in range(header + 1, sheet.max_row + 1):
        value = sheet.cell(row, 2).value
        if value is None:
            break
        workbook_counts.append(value)

    text = (pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8")
    block = text.split("VOLUME\n")[1].split("\n\n")[0]
    pack_counts = [int(m.group(1)) for m in re.finditer(r": (\d+)", block)]
    assert pack_counts == workbook_counts


def test_calendar_total_row_matches_the_workbook_week_cells(tmp_path):
    """The TOTAL block reproduces the sheet's ALL ACTIVITIES week counts."""
    pack_dir, _, scope, config = _pack(tmp_path)
    sheet = build_workbook(scope, config)["Calendar"]

    week_columns = [c for c in range(1, sheet.max_column + 1)
                    if isinstance(sheet.cell(1, c).value, str)
                    and re.fullmatch(r"W\d{2}", sheet.cell(1, c).value)]
    all_row = next(r for r in range(1, sheet.max_row + 1)
                   if sheet.cell(r, LABEL_COL).value == "ALL ACTIVITIES")
    from_sheet = {
        sheet.cell(1, c).value: sheet.cell(all_row, c).value
        for c in week_columns
        if isinstance(sheet.cell(all_row, c).value, int)
    }

    from_pack = {row["iso_week"]: int(row["activities"]) for row in _calendar(pack_dir)
                 if row["block"] == agent_pack.TOTAL_BLOCK}
    assert from_pack == from_sheet


# ---------------------------------------------------------------------------
# Agreement with the frame
# ---------------------------------------------------------------------------

def test_total_block_sums_to_the_activities_in_scope(tmp_path):
    pack_dir, _, scope, _ = _pack(tmp_path)
    total = sum(int(row["activities"]) for row in _calendar(pack_dir)
                if row["block"] == agent_pack.TOTAL_BLOCK)
    assert total == len(scope.frame)


def test_audience_block_partitions_the_portfolio(tmp_path):
    """A partition, so its rows DO sum to the portfolio -- and are marked so."""
    pack_dir, _, scope, _ = _pack(tmp_path)
    rows = [r for r in _calendar(pack_dir) if r["block"] == "audience_band"]
    assert rows, "no audience rows written"
    assert {r["overlaps"] for r in rows} == {"no"}
    assert sum(int(r["activities"]) for r in rows) == len(scope.frame)
    assert {r["value"] for r in rows} <= set(AUDIENCE_BAND_ORDER)


def test_breakdown_values_carry_their_own_row_counts(tmp_path):
    """Each value's rows add up to the activities that actually name it."""
    pack_dir, _, scope, config = _pack(tmp_path)
    rows = _calendar(pack_dir)
    for field in config.breakdown_fields:
        if field not in scope.frame.columns:
            continue
        expected = {}
        for _, activity in scope.frame.iterrows():
            for name in _split_for(field, activity.get(field)) or ["Not specified"]:
                expected[name] = expected.get(name, 0) + 1
        actual = {}
        for row in rows:
            if row["block"] == field:
                actual[row["value"]] = actual.get(row["value"], 0) + int(row["activities"])
        assert actual == expected, f"{field}: pack {actual} vs frame {expected}"


def test_breakdown_blocks_are_marked_as_overlapping(tmp_path):
    """The sentence the sheet writes into its header, as a column."""
    pack_dir, _, scope, config = _pack(tmp_path)
    fields = {f for f in config.breakdown_fields if f in scope.frame.columns}
    marks = {r["block"]: r["overlaps"] for r in _calendar(pack_dir)}
    for field in fields:
        assert marks.get(field) == "yes", f"{field} is not marked as overlapping"
    assert marks[agent_pack.TOTAL_BLOCK] == "no"


def test_activities_file_holds_every_activity_once(tmp_path):
    pack_dir, _, scope, _ = _pack(tmp_path)
    with (pack_dir / agent_pack.ACTIVITIES_CSV_NAME).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(scope.frame)
    assert rows[0]["Tracking ID"]


# ---------------------------------------------------------------------------
# The properties the pack exists for
# ---------------------------------------------------------------------------

def test_no_cell_in_the_pack_is_a_formula(tmp_path):
    """The defect this whole module answers: a formula has no cached value."""
    pack_dir, out_dir, _, _ = _pack(tmp_path)
    for path in list(pack_dir.iterdir()) + [out_dir / agent_pack.CHECKLIST_NAME]:
        if path.suffix == ".xlsx":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for cell in line.split(","):
                assert not cell.strip().strip('"').startswith("="), (
                    f"{path.name}:{number} carries a formula: {line!r}")


def test_the_prose_files_are_txt_because_md_is_not_crawled(tmp_path):
    pack_dir, _, _, _ = _pack(tmp_path)
    assert not list(pack_dir.glob("*.md"))
    for name in (agent_pack.README_NAME, agent_pack.SUMMARY_NAME,
                 agent_pack.GLOSSARY_NAME, agent_pack.QUALITY_NAME):
        assert (pack_dir / name).suffix == ".txt"


def test_the_glossary_states_the_rules_the_layout_only_implies(tmp_path):
    pack_dir, _, _, _ = _pack(tmp_path)
    text = (pack_dir / agent_pack.GLOSSARY_NAME).read_text(encoding="utf-8")
    for phrase in ("do not sum", "never measured reach", "Archived activities are included",
                   "once, in the week it starts", "GEB or GEB-1",
                   # Without this one a reader -- human or agent -- reports the
                   # previous year's quarter on an in-scope activity as a data
                   # error. It is the overlap rule working, and a real run
                   # raised it as an anomaly to be reviewed.
                   "overlap test, not a start-date test"):
        assert phrase in text, f"the glossary does not state: {phrase}"


def test_the_pack_never_names_the_operators_own_files(tmp_path):
    """The pack is uploaded to where the audience reads; local paths are not.

    The workbook dropped its "Source: <file>" rows for this reason, and the
    argument is stronger here: a filename carrying a date or someone's initials
    invites a question the pack cannot answer, and hands an agent a local path
    to quote back. The agreement test cannot catch this on its own -- it
    compares only labels both sides carry, so a row the workbook has stopped
    printing simply drops out of the comparison.
    """
    pack_dir, out_dir, scope, _ = _pack(tmp_path)
    names = {name for _, name in scope.source_files}
    assert names, "the fixture should have source files, or this proves nothing"
    for path in list(pack_dir.iterdir()) + [out_dir / agent_pack.CHECKLIST_NAME]:
        if path.suffix == ".xlsx":
            continue
        text = path.read_text(encoding="utf-8")
        for name in names:
            assert name not in text, f"{path.name} names the export file {name}"
        assert "Source:" not in text, f"{path.name} carries a Source: row"


def test_the_summary_states_that_scope_is_a_filter(tmp_path):
    """Otherwise a filtered-out activity reads as a zero rather than as absent."""
    pack_dir, _, _, config = _pack(tmp_path)
    text = (pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8")
    assert "OUT OF SCOPE" in text
    assert config.period_label() in text
    assert "Rows read" in text and "Excluded: date window" in text


# ---------------------------------------------------------------------------
# The checklist and the skill package
# ---------------------------------------------------------------------------

def test_what_must_not_be_uploaded_sits_outside_the_pack(tmp_path):
    """Two files must never be grounded on, for two different reasons.

    An answer key inside the pack is retrieved like anything else, and the test
    then measures nothing. Instructions inside the pack are read as data: the
    agent quotes its own rules back as findings, and they stop being rules.
    """
    pack_dir, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        packaged = archive.namelist()
    for name in (agent_pack.CHECKLIST_NAME, agent_pack.INSTRUCTIONS_NAME,
                 agent_pack.EVALUATION_NAME):
        assert not (pack_dir / name).exists(), f"{name} is inside the uploaded folder"
        assert name not in packaged, f"{name} is inside the skill package"
        assert (out_dir / name).exists(), f"{name} was not written at all"


def test_the_instructions_name_no_period_they_will_outlive(tmp_path):
    """Pasted once, kept while the pack is rebuilt underneath it.

    A period or a figure here would be wrong by the next run, and wrong in the
    one place nobody re-reads. The instructions point at the summary instead.
    """
    _, out_dir, _, config = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert config.period_label() not in text
    assert not re.search(r"\b(19|20)\d{2}\b", text), "the instructions name a year"
    assert agent_pack.SUMMARY_NAME in text, "they must point at where the period is"


def test_the_evaluation_set_matches_the_products_own_template(tmp_path):
    """Three columns in this order, the ceilings, and a BOM.

    Taken from the template Copilot Studio hands out, not from documentation:
    the documented format belongs to a different harness, and every field of it
    was wrong here -- the column names, their number, and the character cap.
    """
    _, out_dir, scope, config = _pack(tmp_path)
    path = out_dir / agent_pack.EVALUATION_NAME
    assert path.read_bytes().startswith(b"\xef\xbb\xbf"), (
        "no BOM: Excel and the import dialog fall back to Windows-1252, which "
        "turns an em dash in a team name into mojibake")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == agent_pack.EVALUATION_HEADER
    cases = rows[1:]
    assert cases, "no test cases written"
    assert len(cases) <= agent_pack.EVALUATION_MAX_CASES
    for number, question, response in cases:
        assert len(question) <= agent_pack.EVALUATION_MAX_QUESTION_CHARS
        assert response.strip(), f"no reference reply for {question!r}"
    numbers = [row[0] for row in cases]
    assert len(set(numbers)) == len(numbers), (
        "rows sharing a conversationNumber run as one conversation, so these "
        "independent questions would carry each other's context")
    assert len(cases) == len(agent_pack.checklist_questions(scope, config))


def test_the_evaluation_questions_do_not_carry_their_own_answers(tmp_path):
    """The agent is handed the Question column; an answer in it is a leak.

    This is what makes the evaluation set safe to upload while the checklist is
    not: the expected response is read by whoever reviews the run, never by the
    agent -- unless it has been written into the question.
    """
    _, out_dir, scope, config = _pack(tmp_path)
    with (out_dir / agent_pack.EVALUATION_NAME).open(encoding="utf-8-sig",
                                                     newline="") as handle:
        cases = list(csv.DictReader(handle))
    answers = [str(answer) for _, answer, _, _, _ in
               agent_pack.checklist_questions(scope, config)]
    for case, answer in zip(cases, answers):
        assert not agent_pack._states(case["question"], answer), (
            f"the question gives its own answer away: {case['question']!r}")


def test_the_pack_says_when_it_was_generated(tmp_path):
    """The one figure no other file can imply.

    Period tells a reader which activities are covered; it never says when
    anyone last looked. The pack is rebuilt by hand on one machine, so between
    runs every figure silently ages.
    """
    scope, config = _scope(tmp_path)
    stamp = date(2026, 3, 17)
    out_dir = tmp_path / "out"
    pack_dir = agent_pack.write_pack(scope, config, out_dir, generated=stamp)
    for name in (agent_pack.README_NAME, agent_pack.SUMMARY_NAME):
        text = (pack_dir / name).read_text(encoding="utf-8")
        assert "2026-03-17" in text, f"{name} does not say when it was generated"
    instructions = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert "Data as of" in instructions, "nothing tells the agent to state it"


def test_the_instructions_ask_for_follow_up_questions_every_time(tmp_path):
    """Copilot Studio has no follow-up chips, so the answer has to carry them.

    Starter prompts are the only platform feature, and they appear on the
    welcome page before the first message -- never after an answer. The
    Preferred Output Format already asked for follow-ups, but only as part of a
    report scaffold that a one-line factual answer sheds whole.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert "You might also ask" in text
    assert "including a one-line factual one" in text
    assert "before the footer" in text.lower(), "the footer must stay last"
    assert "this pack can actually answer" in text


def test_the_footer_is_one_line_carrying_both_things(tmp_path):
    """Vintage and signature share a line, and the vintage comes first.

    Two footers stop being a signature and become a masthead, and a reader who
    skips one line skips two -- taking the staleness warning with it, which is
    the half that changes what someone does.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    footer = next(line for line in text.splitlines() if "Powered by" in line)
    assert "Data as of" in footer, "the signature has its own line"
    assert footer.index("Data as of") < footer.index("Powered by")
    assert agent_pack.TEAM_SIGNATURE in footer, "the agent is not signed"
    assert "never split into two" in text


def test_the_instructions_carry_no_organisation_name(tmp_path):
    """This repository is public. The name is filled in where the text is used.

    A placeholder cannot be forgotten -- it is visible in the pasted text and
    reads as unfinished -- whereas a name committed once stays in every clone
    and fork of the history, whatever a later commit removes.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert agent_pack.ORGANISATION_PLACEHOLDER in text
    assert "Before pasting, replace throughout" in text
    for word in ("brand compliance", "-compliant charts", "communication standards"):
        for line in text.splitlines():
            if word in line.lower():
                assert agent_pack.ORGANISATION_PLACEHOLDER in line, (
                    f"a brand line without the placeholder: {line!r}")


def test_the_instructions_are_the_whole_prompt(tmp_path):
    """A full replacement, so every correction sits where it applies.

    An addendum leaves the contradiction in place three sections above it: an
    instruction to flag inconsistent dates still reads as an instruction to
    flag them, however carefully a later paragraph explains the overlap rule.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert "You are the Communications Planning Insight Agent" in text
    assert "There is no Excel workbook behind this agent" in text
    assert "Do NOT flag the following" in text          # the overlap exemption
    assert "never described as reach" in text           # the persona correction
    assert "GEB or GEB-1" in text
    assert ".xlsx" not in text, "a workbook filename would go stale on the next run"


def test_the_footer_is_owed_on_every_turn_not_just_the_first(tmp_path):
    """Observed: the vintage appears on the first answer and then stops.

    The mechanism is mundane -- a follow-up turn does not re-open the summary,
    so the date is no longer in front of the agent and the line quietly goes.
    That is worse than never having had it: a reader who has been given a
    vintage once reads its absence as "still current" rather than as a line
    somebody dropped. The date does not change inside a conversation, so the
    rule is to restate it, and the instructions now say which failure they are
    ruling out rather than only asserting "never omitted".
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert "Every turn carries it, not just the first." in text
    assert "restate the date you already gave" in text
    for turn in ("follow-up answer", "one-line correction", "no figure at all"):
        assert turn in text, f"the rule does not cover a {turn}"


def test_three_follow_up_questions_rather_than_two(tmp_path):
    """Two was the floor and became the ceiling.

    "Two is usually right, never more than three" reads as permission to stop
    at two, and it did. Three is now the count, with the instruction to widen
    the angle when a third is hard rather than to fall back to two -- otherwise
    the shortfall lands exactly on the narrow questions where a reader most
    needs somewhere else to go.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert "Offer the next three questions" in text
    assert "offer three follow-up questions" in text
    assert "Three, every time" in text
    shape = text[text.index("**You might also ask**"):]
    offered = [line for line in shape.splitlines()[:5] if line.startswith("> - ")]
    assert len(offered) == 3, f"the worked example still shows {len(offered)}"
    assert "Two is usually right" not in text, "the old ceiling is still there"


def test_the_chart_rules_ship_as_their_own_skill(tmp_path):
    """Two skills, split by what it costs to miss each half.

    The palette, the ratio and the typography rules stay in the instructions:
    they apply to every chart, a breach is visible at a glance, and
    instructions apply to every turn whereas a skill loads only when the model
    judges it relevant. What moves here is the half that means nothing until a
    plot exists -- and is long enough to crowd the prompt if carried always.

    No data files: this archive is identical between runs, so it is uploaded
    once and re-uploaded only when the rules change, while the report pack
    beside it goes stale weekly.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.BRAND_SKILL_ZIP_NAME) as archive:
        assert archive.namelist() == ["SKILL.md"], "the chart skill carries data"
        skill = archive.read("SKILL.md").decode("utf-8")

    assert skill.startswith("---\nname: chart-standards\n")
    description = next(line for line in skill.splitlines()
                       if line.startswith("description:"))
    assert len(description) <= 1024 + len("description: "), "description over the cap"
    for trigger in ("chart", "dashboard", "plot", "visualise"):
        assert trigger in description, f"nothing routes {trigger!r} to this skill"

    # The half that moved, and the half that must not have.
    for moved in ("Laying out more than one chart", "Before you send it",
                  "Which chart answers which question"):
        assert moved in skill, f"{moved!r} did not move into the skill"
    instructions = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    for floor in ("#E60000", "#7A7870", "One red element per chart",
                  "Never use capitals for emphasis", "No gridlines"):
        assert floor in instructions, f"{floor!r} left the instructions"
    assert "Load that skill before you draw" in instructions, "nothing points at it"
    assert agent_pack.BRAND_SKILL_NAME in instructions

    # Organisation-neutral without a placeholder: the operator uploads this zip
    # unmodified, so there is nothing to find and replace inside it.
    assert agent_pack.ORGANISATION_PLACEHOLDER not in skill


def test_the_visual_rules_are_numbers_rather_than_adjectives(tmp_path):
    """The brand section named one colour and then asked for restraint.

    Everything the pack builds itself carries the full design-system tokens;
    the agent was the one surface without them, and it showed -- capitalised
    headings, red headings, red on eight elements at once, gridlines, bars in
    pure black. An agent cannot honour "accent colors only when necessary",
    because necessary is exactly the judgement it is making. Every rule here
    is therefore countable: a hex, a ratio, or a count of elements.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    for hex_value in ("#FFFFFF", "#000000", "#E60000", "#8E8D83", "#7A7870",
                      "#5A5D5C", "#404040", "#BD000C", "#B98E2C", "#ECEBE4"):
        assert hex_value in text, f"the palette does not name {hex_value}"
    assert "At least half the image is unmarked white" in text
    assert "One red element per chart. At most two in a whole image." in text
    assert "Never use capitals for emphasis" in text
    assert "No gridlines" in text

    # The geometry rules and the self-check moved into the chart skill when the
    # visual section was split; they are asserted where they now live, at the
    # same strictness, rather than dropped.
    with zipfile.ZipFile(out_dir / agent_pack.BRAND_SKILL_ZIP_NAME) as archive:
        skill = archive.read("SKILL.md").decode("utf-8")
    assert "Leave a gutter at least as tall as a panel heading" in skill
    assert "Nothing overlaps anything" in skill
    assert "Before you send it" in skill, "no self-check before rendering"


def test_a_figure_is_stated_once_rather_than_in_every_section(tmp_path):
    """The output format asks for a summary, findings and charts of one dataset.

    Nothing said they were different sentences, so the same number arrived as
    a tile, as a bar and as a bullet -- four of five tiles on the executive
    image were restated by a chart, two of them a third time in the read-out.
    Half the page then carries no information, which is a brand failure before
    it is an editorial one: white space is the thing being spent.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert "Say each figure once" in text
    assert "A figure belongs to **one** place" in text
    assert "has **no** chart in the image" in text, "nothing bounds a number tile"
    # The check that enforces it sits in the chart skill's list, beside the
    # other things read off a finished image.
    with zipfile.ZipFile(out_dir / agent_pack.BRAND_SKILL_ZIP_NAME) as archive:
        skill = archive.read("SKILL.md").decode("utf-8")
    assert "Does any figure appear twice in the image?" in skill


def test_the_checklist_answers_are_computed_from_the_data(tmp_path):
    """The balance of kinds is asserted once, by the test that owns it."""
    _, out_dir, scope, config = _pack(tmp_path)
    assert len(agent_pack.checklist_questions(scope, config)) >= 5
    text = (out_dir / agent_pack.CHECKLIST_NAME).read_text(encoding="utf-8")
    assert str(len(scope.frame)) in text


def _pack_prose(pack_dir):
    return "\n".join((pack_dir / name).read_text(encoding="utf-8")
                     for name in (agent_pack.SUMMARY_NAME, agent_pack.QUALITY_NAME))


def test_every_question_is_graded_by_what_the_pack_actually_states(tmp_path):
    """Both directions, on the probe that produced the grade.

    The inverse is the half that was missing, and its absence is what let the
    first real run mis-grade a question: "how many external activities" was
    written down as a count while `01-summary.txt` said `External: 275`
    outright, so an agent that only ever reads files answered it correctly and
    looked as though it had computed something.
    """
    pack_dir, _, scope, config = _pack(tmp_path)
    prose = _pack_prose(pack_dir)
    for question, _answer, control, _note, probe in agent_pack.checklist_questions(
            scope, config):
        stated = agent_pack._states(prose, *probe)
        if control:
            assert stated, f"graded as a control, but the pack does not state it: {question}"
        else:
            assert not stated, (
                f"graded as a counting question, but the pack states {probe}: {question}")


def test_the_checklist_keeps_questions_of_both_kinds(tmp_path):
    """A list of only controls measures nothing; only counts has no baseline."""
    _, _, scope, config = _pack(tmp_path)
    kinds = [control for _, _, control, _, _ in
             agent_pack.checklist_questions(scope, config)]
    assert sum(kinds) >= 2, "no control questions -- nothing to calibrate against"
    assert kinds.count(False) >= 2, "no counting questions -- nothing to measure"


def test_the_skill_package_has_its_manifest_at_the_archive_root(tmp_path):
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        names = archive.namelist()
        assert "SKILL.md" in names
        manifest = archive.read("SKILL.md").decode("utf-8")
    assert manifest.startswith("---\nname: cplan-reporting\n")
    assert "description:" in manifest.split("---")[1]
    for name in (agent_pack.GLOSSARY_NAME, agent_pack.SUMMARY_NAME,
                 agent_pack.CALENDAR_NAME, agent_pack.ACTIVITIES_CSV_NAME):
        assert name in names


# ---------------------------------------------------------------------------
# Shapes that are real rather than hypothetical
# ---------------------------------------------------------------------------

def test_an_empty_scope_still_writes_a_readable_pack(tmp_path):
    """Every criterion is a hard filter, so an empty scope is one flag away."""
    pack_dir, out_dir, scope, _ = _pack(tmp_path, date_from=date(1990, 1, 1),
                                        date_to=date(1990, 12, 31))
    assert scope.frame.empty
    assert _calendar(pack_dir) == []
    summary = (pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8")
    assert "Activities in scope: 0" in summary
    assert (out_dir / agent_pack.CHECKLIST_NAME).exists()


def test_the_pack_is_rewritten_in_place(tmp_path):
    """A second run replaces the pack rather than accumulating vintages.

    A grounded folder holding two runs answers from both without saying so,
    which is the failure the dated workbook filename already invites next door.
    """
    scope, config = _scope(tmp_path)
    out_dir = tmp_path / "out"
    first = sorted(p.name for p in agent_pack.write_pack(scope, config, out_dir).iterdir())
    second = sorted(p.name for p in agent_pack.write_pack(scope, config, out_dir).iterdir())
    assert first == second
