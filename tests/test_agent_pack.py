"""The agent pack: the workbook's figures without its formulas, over a wider scope.

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

from pipeline.report import agent_pack, dashboard_skill, metrics
from pipeline.report.calendar_sheet import LABEL_COL, _split_for
from pipeline.report.config import AUDIENCE_BAND_ORDER, ReportConfig
from pipeline.scripts.report_calendar import build_workbook
from tests.report_fixtures import load_fixture_scope


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def _scope(tmp_path, with_packs=False, **overrides):
    config = _config(**overrides)
    return load_fixture_scope(tmp_path / "csv", config,
                              with_packs=with_packs), config


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


def _calendar(pack_dir):
    with (pack_dir / agent_pack.CALENDAR_NAME).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _breakdowns(pack_dir):
    with (pack_dir / agent_pack.BREAKDOWN_NAME).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _figure(rows, block, value, measure):
    """The one figure for a block/value/measure, or None."""
    for row in rows:
        if (row["block"], row["value"], row["measure"]) == (block, value, measure):
            return int(row["figure"])
    return None


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

    "Breakdown dimensions" is excluded by choice, not by construction: it is a
    literal label on both sides, but `_pack` now builds the pack through
    `pack_config` (`test_the_pack_breaks_down_by_priority_and_lead_team`),
    which appends `priority` and `lead_team` to the field list this row
    states. The workbook is built from the unwidened `config` `_pack` returns,
    so the two lists disagree by design -- that gap is the whole reason the
    two configs exist -- and always will.
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
    shared = (set(workbook_pairs) & set(pack_pairs)) - {"Breakdown dimensions"}
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
    for label in ("Planned to date", "Next 30 days from the data date",
                  "Rest of the period"):
        assert label in pairs, f"the summary does not state {label!r}"

    three = sum(int(pairs[label]) for label in
                ("Planned to date", "Next 30 days from the data date",
                 "Rest of the period"))
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
    assert int(pairs["Next 30 days from the data date"]) == int(
        ((starts > generated) & (starts <= generated + timedelta(days=30))).sum())


def test_the_horizon_puts_the_boundary_dates_in_the_right_bucket(tmp_path):
    """The two cusps, pinned by hand rather than mirrored from the code.

    The test above computes its expected values with the same boolean
    expressions the implementation uses (`<=` for the near boundary, `<=`
    again for the +30-day one). That means it agrees with the code no matter
    which way either operator points -- flip `starts <= generated` to `<`, or
    the day-30 `<=` to `<`, and the mirrored test still passes. And the total
    is a partition by construction ("no start date" is its own exclusion
    reason, so every in-scope row lands in exactly one bucket), which makes
    the failure doubly invisible: the three counts still sum to the
    portfolio, so even `test_the_summary_splits_the_portfolio_at_its_own_
    vintage` would not notice. An off-by-one on either cusp is silent
    everywhere except the one tile a reader actually acts on.

    So here the two boundary activities are moved onto the cusps by hand, and
    the expected bucket counts are written as literals computed once by hand
    against the fixture -- not derived from `starts <= generated` again.
    """
    from datetime import timedelta

    import pandas as pd

    scope, config = _scope(tmp_path)
    generated = date(2025, 6, 15)
    boundary_30 = generated + timedelta(days=30)  # 2025-07-15

    # Fixture activities, unmodified: 12 start on or before 2025-06-15, 1
    # (IC-0015, 2025-07-08) falls in the following 30 days, and 7 -- including
    # IC-0016 (2025-10-14) and IC-0013 (2025-12-31) -- start later still.
    # Moving those two onto the cusps shifts one row into each near bucket and
    # leaves the rest of the portfolio (5 rows) where it was, for a
    # hand-checked partition of 13 / 2 / 5 against 20 activities in scope.
    frame = scope.frame.copy()
    on_the_day = frame.index[frame["tracking_id"] == "IC-0016"][0]
    on_day_30 = frame.index[frame["tracking_id"] == "IC-0013"][0]
    # start_date carries the source rows' own time zone (Europe/Zurich in the
    # fixture); a naive Timestamp cannot be assigned into a tz-aware column.
    tz = frame["start_date"].dt.tz
    frame.loc[on_the_day, "start_date"] = pd.Timestamp(generated, tz=tz)
    frame.loc[on_day_30, "start_date"] = pd.Timestamp(boundary_30, tz=tz)
    scope.frame = frame

    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "out",
                                     generated=generated)
    pairs = _summary_pairs((pack_dir / agent_pack.SUMMARY_NAME)
                           .read_text(encoding="utf-8"))

    assert pairs["Planned to date"] == "13", (
        "the activity dated exactly on the generation date "
        f"({generated.isoformat()}) does not land in 'Planned to date': {pairs}")
    assert pairs["Next 30 days from the data date"] == "2", (
        "the activity dated exactly 30 days after the generation date "
        f"({boundary_30.isoformat()}) does not land in "
        f"'Next 30 days from the data date': {pairs}")
    assert pairs["Rest of the period"] == "5", f"unexpected remainder: {pairs}"


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
        weekly[key] = weekly.get(key, 0) + int(row["activities"])

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


@pytest.mark.parametrize("field", ["priority", "lead_team"])
def test_a_comma_inside_a_partitioning_field_stays_one_value(tmp_path, field):
    """A team named after two disciplines carries a comma inside its own name.

    Real value from a real run: one lead team, one comma, and the generic
    splitter read it as two teams -- which put the activity under both and
    stopped `overlaps=no` from being true, so the guard below refused the whole
    pack. The comma belongs to the name, exactly as it does in a person's
    "Last, First", so a partitioning field splits on the semicolon only.

    Both halves are asserted here, because either alone can pass while the
    block is wrong: the value survives whole, AND the block still partitions.

    The value is set on a copy of the fixture scope's own frame, not added to
    `tests/report_fixtures.py`: every other test reads that fixture, and a row
    shaped for one test would leak into all of them.
    """
    scope, config = _scope(tmp_path)
    packed = agent_pack.pack_config(config)
    index = scope.frame.index[0]
    scope.frame.loc[index, field] = "First value, Second value"

    blocks = [(value, subset) for block, value, _, subset
              in agent_pack.iter_blocks(scope, packed) if block == field]
    values = [value for value, _ in blocks]

    # Priority is grouped by meaning, so the raw label is not what lands in the
    # block -- what matters there is that the comma did not multiply the rows.
    if field == "lead_team":
        assert "First value, Second value" in values, (
            f"the comma split one team into two: {values}")
    assert "First value" not in values and "Second value" not in values, (
        f"a fragment of the value became a block of its own: {values}")

    # And the promise the block makes: `overlaps=no` means these rows sum to
    # the portfolio. One activity counted twice is exactly what breaks it.
    assert sum(len(subset) for _, subset in blocks) == len(scope.frame), (
        f"{field} rows no longer sum to the portfolio: "
        f"{[(value, len(subset)) for value, subset in blocks]}")


@pytest.mark.parametrize("field", ["priority", "lead_team"])
def test_a_semicolon_inside_a_partitioning_field_fails_loudly(tmp_path, field):
    """`PARTITION_BREAKDOWN_FIELDS` tells every reader of `overlaps=no` that a
    block's rows sum to the portfolio -- a board sums it. The semicolon stays a
    separator for these fields, so a cell that really does name two teams would
    silently put one activity under both and make that promise false. This must
    raise instead of shipping a pack whose total quietly disagrees with itself.

    Set on a copy of the fixture scope's frame, for the reason above.
    """
    scope, config = _scope(tmp_path)
    index = scope.frame.index[0]
    tracking_id = scope.frame.loc[index, "tracking_id"]
    scope.frame.loc[index, field] = "First value; Second value"

    with pytest.raises(ValueError) as excinfo:
        list(agent_pack.iter_blocks(scope, agent_pack.pack_config(config)))
    message = str(excinfo.value)
    assert field in message, f"error does not name the field {field!r}: {message}"
    assert str(tracking_id) in message, (
        f"error does not name the offending activity {tracking_id!r}: {message}")


def test_the_reporting_skill_ships_the_breakdowns_file(tmp_path):
    """A table of contents naming a file the archive does not hold is worse than
    no table of contents: the agent looks, fails, and answers from somewhere else.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        assert agent_pack.BREAKDOWN_NAME in archive.namelist()


def test_activities_file_holds_every_activity_once(tmp_path):
    pack_dir, _, scope, _ = _pack(tmp_path)
    with (pack_dir / agent_pack.ACTIVITIES_CSV_NAME).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(scope.frame)
    assert rows[0]["Tracking ID"]


def test_the_activities_file_names_the_pack_it_only_numbered(tmp_path):
    """A bare identifier is not something a reader can ask about.

    `communication_pack` has been in the frame all along -- mapped in
    `COLUMN_MAP`, lookup-parsed like every other reference field -- and was
    simply never exported. An agent handed `CP-100` can group by pack but
    cannot say which pack it grouped, and no question a planner actually
    asks is phrased in identifiers.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    with (pack_dir / agent_pack.ACTIVITIES_CSV_NAME).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert "Pack" in rows[0], "the activities file still carries only the identifier"
    packed = [row for row in rows if row["Pack ID"] == "CP-100"]
    assert packed, "the fixture's packed activities vanished"
    assert all(row["Pack"] == "Pack one" for row in packed)

    # The identifier stays. It is what `07-packs.csv` is joined on, and a
    # name is not unique the way a key is.
    assert "Pack ID" in rows[0]


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
    assert "never measured reach" in text               # the audience correction
    assert "GEB or GEB-1" in text
    assert ".xlsx" not in text, "a workbook filename would go stale on the next run"
    # The persona section moved into the reporting skill; the correction that
    # was made to it travels with it, and is asserted where it now lives.
    _, out_dir, _, _ = _pack(tmp_path)
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        skill = archive.read("SKILL.md").decode("utf-8")
    assert "never described as reach" in skill


def test_the_ways_of_working_sit_in_the_skill_and_the_guards_in_the_prompt(tmp_path):
    """Split by what it costs to miss each half, not by subject.

    Persona priorities, the four analysis steps and the catalogue of questions
    this pack answers well are ways of working: they shape an answer that is
    already being written from the pack, which is exactly the turn on which
    that skill loads. Carrying them on every turn spent about 2,400 characters
    of a prompt that also has to hold the rules a turn cannot afford to miss.

    What must not follow them out is asserted in the same test, because the
    danger of a split is not the move itself but the second move nobody
    noticed: the guards -- scope, overlaps, audience, GEB/GEB-1, the footer --
    stay in the instructions, where they apply whether or not a skill fires.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        skill = archive.read("SKILL.md").decode("utf-8")

    for moved in ("Internal communications planner", "Consider reviewing",
                  "Which weeks have the highest volume?",
                  "Forward planning thins towards the end of the horizon"):
        assert moved in skill, f"{moved!r} did not arrive in the skill"
        assert moved not in text, f"{moved!r} is still carried on every turn"

    for guard in ("Scope is a hard filter", "Overlapping rows do not sum",
                  "never measured reach", "GEB or GEB-1",
                  "Powered by", "Data as of"):
        assert guard in text, f"{guard!r} left the instructions"


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

    # The label is load-bearing, which is only obvious once it is gone. A
    # compression pass dropped "Shape:" and hung the block off the previous
    # sentence's colon; the agent read the `>` as the prompt's own quoting and
    # produced a plain heading with plain bullets, losing the quoted block and
    # the bold that make the offer findable when a reader scans back.
    assert "> **You might also ask**" in text, "the heading left the block quote"
    introduction = text[:text.index("> **You might also ask**")][-400:]
    assert introduction.rstrip().endswith(":"), "nothing introduces the block"
    assert "Shape" in introduction, "the block is no longer labelled as a form"
    assert "copy the formatting, not only the wording" in text


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
    assert sorted(boards) == ["board-head-of-communications-overview.md",
                              "board-leadership-attention.md",
                              "board-plan-trust.md"]

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

    Checked against the board's prose, not its `Source:` lines: panel 1
    legitimately cites `01-summary.txt`'s own "Planned at under 7 days'
    notice" tile, a machine-parsed pointer nobody reads as wording -- unlike
    panel 4's business question and footnote, which a reader does.
    """
    board = dashboard_skill.BOARDS["board-head-of-communications-overview.md"]
    assert "requests received at" in board.lower()
    prose = "\n".join(line for line in board.splitlines()
                      if not line.strip().startswith("Source:"))
    assert "planned at under" not in prose.lower()


def test_no_board_sends_the_reader_to_a_board_that_does_not_exist():
    """A route is worth printing only where the door is.

    The overview closes by naming which board to open next, and until
    2026-08-10 it named `Planning discipline` -- a board the design defers and
    this agent cannot draw. The render followed the instruction exactly and
    told a head of communications to go and open nothing. Case-sensitive on
    purpose: `PLANNING DISCIPLINE` is a section of `01-summary.txt` and every
    panel citing it is fine.
    """
    catalogue = dashboard_skill.SKILL_TEXT + "".join(dashboard_skill.BOARDS.values())
    for deferred in ("Planning discipline", "Reach and coverage",
                     "Portfolio overview"):
        assert deferred not in catalogue, (
            f"a board routes the reader to {deferred!r}, which does not exist")


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


def test_an_image_that_carries_a_total_says_what_it_counts(tmp_path):
    """The rule that answers is worth nothing to an image nobody can question.

    The pack is wider than the distributed workbook, so two totals are true of
    the same portfolio on the same day, and the instructions already require an
    answer to say which one it used. A chart cannot: it is forwarded without
    its author, read by someone holding the workbook, and there is nobody in
    the room to ask. Two dashboards a fortnight apart would then show a
    portfolio that had apparently grown by every deprioritised activity, with
    nothing on either image accounting for it.

    So scope joins title, business question, date range, metric and source as
    something every chart carrying a total must print, and the board checklist
    asks for it where a headline figure is largest and least questioned.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    requirements = text[text.index("### Chart Requirements"):
                        text.index("### The rest of the rules")]
    assert "Scope, whenever the image carries a total." in requirements
    assert "Activities in scope: N" in requirements, "no shape to copy"
    assert "wider than the distributed workbook" in requirements

    # Checked in the general list rather than the board one: the board list is
    # explicitly "on top of" it, so a lone chart carrying a total would
    # otherwise be the one image nothing asks.
    with zipfile.ZipFile(out_dir / agent_pack.BRAND_SKILL_ZIP_NAME) as archive:
        charts = archive.read("SKILL.md").decode("utf-8")
    assert "does the footnote say what that total counts?" in charts
    with zipfile.ZipFile(out_dir / agent_pack.DASHBOARD_SKILL_ZIP_NAME) as archive:
        boards = archive.read("SKILL.md").decode("utf-8")
    assert "The scope check in `chart-standards` matters most here" in boards
    assert "Does the board state what its total counts?" not in boards, (
        "the check is asked twice")


def test_red_is_bounded_by_area_and_not_only_by_count(tmp_path):
    """"One red element" was obeyed and still produced a half-red image.

    Asked for a share of activities by priority, the agent drew a donut and
    highlighted the largest segment: one red element, rule kept, 54% of the
    picture in Corporate Red. Counting elements bounds nothing, because one
    segment can be half the image.

    The second half of the miss is that highlighting suits a comparison, where
    one thing is the answer, and not a composition, where the categories are
    peers and the split itself is the answer. The studio has drawn donuts from
    a red-free grey-and-bronze sequence all along; the agent had no such rule,
    so it reached for the accent it did have.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    text = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    assert "Red never covers the largest area in the image." in text
    assert "Highlight only where one thing is the answer." in text

    with zipfile.ZipFile(out_dir / agent_pack.BRAND_SKILL_ZIP_NAME) as archive:
        skill = archive.read("SKILL.md").decode("utf-8")
    assert "Colouring the two kinds of chart" in skill
    # The sequence the studio already draws donuts from, and no accent in it.
    for colour in ("#404040", "#B98E2C", "#8E8D83", "#6C5312",
                   "#B8B3A2", "#5A5D5C", "#946F29"):
        assert colour in skill, f"the composition sequence is missing {colour}"
    sequence = skill[skill.index("Colouring the two kinds of chart"):
                     skill.index("## Axes, lines and legends")]
    assert "#E60000" in sequence, "the comparison half lost its accent"
    assert sequence.count("#E60000") == 1, "red crept into the composition sequence"


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


def test_the_pack_keeps_what_the_workbook_plans_past_and_says_so(tmp_path):
    """The pack answers questions; the workbook plans. Different scopes.

    Priority 4 is the bucket nobody plans against, and the objectives filter
    drops rows tagged with nothing but the catch-all -- both belong in a
    planning instrument, and neither belongs in front of someone asking which
    deprioritised activities are coming up. So the pack drops those two
    filters, and keeps the period, which is what the report is about.

    That makes the pack and the workbook disagree about "how many activities",
    which is exactly the failure this repository spends its rules preventing.
    It is survivable only because it is visible from both ends: every row says
    whether the workbook keeps it, the summary says how many it does not, and
    filtering `in_report = Yes` reproduces the workbook's figure. A silent
    divergence would be a wrong number that looks right.
    """
    report_config = _config(exclude_priorities=(4,))
    scope, config = _scope(tmp_path, exclude_priorities=(4,))
    assert scope.excluded["priority"], "the fixture has no priority-4 row to keep"
    dropped_by_report = scope.excluded["priority"]
    kept_by_report = len(scope.frame)

    wide_scope, wide_config = _scope(tmp_path)
    assert agent_pack.pack_config(report_config).exclude_priorities == ()
    out_dir = tmp_path / "wide"
    pack_dir = agent_pack.write_pack(wide_scope, wide_config, out_dir,
                                     report_config=report_config)

    with (pack_dir / agent_pack.ACTIVITIES_CSV_NAME).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == kept_by_report + dropped_by_report, "the pack is not wider"
    out = [r for r in rows if r["in_report"] == "No"]
    assert len(out) == dropped_by_report
    assert {r["report_exclusion"] for r in out} == {"priority"}
    assert len([r for r in rows if r["in_report"] == "Yes"]) == kept_by_report, (
        "in_report = Yes no longer reproduces the workbook's figure")

    summary = (pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8")
    assert "THIS PACK IS WIDER THAN THE DISTRIBUTED WORKBOOK" in summary
    assert f"priority: {dropped_by_report}" in summary
    assert "in_report = Yes" in summary

    # Without a report config nothing changes, which is what keeps every other
    # caller -- and the workbook's own Activities sheet -- untouched.
    plain_dir = agent_pack.write_pack(wide_scope, wide_config, tmp_path / "plain")
    with (plain_dir / agent_pack.ACTIVITIES_CSV_NAME).open(encoding="utf-8") as handle:
        assert "in_report" not in (csv.DictReader(handle).fieldnames or [])


def test_the_pack_carries_nothing_written_only_for_an_index(tmp_path):
    """The data reaches the agent through the skill, not a knowledge source.

    `pack/` was one until two probes showed it was never reached for: a needle
    question found its row by reading the file, and a counting question
    answered by examining every row, which is the one thing chunked retrieval
    cannot do. Both still answered with the knowledge source removed.

    The single-sheet workbook existed only for that index -- its own docstring
    said so, and the skill archive deliberately left it out because an archive
    is read as text and the CSV beside it carries the same rows. With no index
    it had no reader at all, so no file here is one, whatever else is added.

    Built with a pack list so the count reflects the full, packed shape --
    `07-packs.csv` is one more file added since this list was last true.
    """
    pack_dir, _, _, _ = _pack(tmp_path, with_packs=True)
    written = sorted(p.name for p in pack_dir.iterdir())
    assert not [n for n in written if n.endswith(".xlsx")], (
        f"a workbook is being written for a reader that no longer exists: {written}")
    assert not hasattr(agent_pack, "ACTIVITIES_XLSX_NAME")
    assert written == ["00-README.txt", "01-summary.txt", "02-glossary.txt",
                       "03-data-quality.txt", "04-calendar.csv", "05-activities.csv",
                       "06-breakdowns.csv", "07-packs.csv"]


def _packs_file(pack_dir):
    with (pack_dir / agent_pack.PACKS_CSV_NAME).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_the_pack_file_holds_the_pack_nobody_planned_against(tmp_path):
    """The row the file exists for.

    A pack with no activity has nothing to be counted through, so before this
    file it was not merely undescribed -- it was absent. "Which packs have
    nothing planned" is the question that only a row per pack can answer.
    """
    scope, config = _scope(tmp_path, with_packs=True)
    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config),
                                     tmp_path / "out")
    rows = {row["Pack ID"]: row for row in _packs_file(pack_dir)}

    assert set(rows) == {"CP-100", "CP-200"}
    assert rows["CP-200"]["Pack"] == "Pack with nothing planned"
    assert rows["CP-200"]["activities_in_scope"] == "0"
    assert rows["CP-200"]["activities_total"] == "0"
    assert int(rows["CP-100"]["activities_in_scope"]) > 0


def test_the_two_activity_counts_are_not_the_same_number(tmp_path):
    """A pack with nothing this period reads differently from a pack with
    nothing at all, and one column cannot carry both.
    """
    scope, config = _scope(tmp_path, with_packs=True,
                           date_from=date(2025, 1, 1), date_to=date(2025, 3, 31))
    pack_dir = agent_pack.write_pack(scope, agent_pack.pack_config(config),
                                     tmp_path / "out")
    row = {r["Pack ID"]: r for r in _packs_file(pack_dir)}["CP-100"]
    assert int(row["activities_total"]) > int(row["activities_in_scope"])


def test_in_report_actually_discriminates_survivors_from_the_excluded(tmp_path):
    """`in_report` is computed per pack, not defaulted to one answer.

    A pack whose activities all survive the report's own filters reads Yes; a
    pack whose activities are all filtered out reads No. Built from the report
    config's own objectives filter rather than by monkeypatching
    `report_exclusion`: every fixture activity carries exactly the objective
    "Objective", so excluding that prefix drops every row it names, including
    all of CP-100's. Without this, inverting `if not report_exclusion(...)`
    inside `pack_rows` passes every test in this file, because none of them
    reads the `in_report` column through a `report_config`.
    """
    scope, config = _scope(tmp_path, with_packs=True)
    wide_config = agent_pack.pack_config(config)

    kept_dir = agent_pack.write_pack(scope, wide_config, tmp_path / "kept",
                                     report_config=_config())
    kept_row = {r["Pack ID"]: r for r in _packs_file(kept_dir)}["CP-100"]
    assert kept_row["in_report"] == "Yes", "CP-100's activities are not excluded here"

    dropped_dir = agent_pack.write_pack(
        scope, wide_config, tmp_path / "dropped",
        report_config=_config(exclude_objectives=("Objective",)))
    dropped_row = {r["Pack ID"]: r for r in _packs_file(dropped_dir)}["CP-100"]
    assert dropped_row["in_report"] == "No", "every one of CP-100's activities is excluded here"

    plain_dir = agent_pack.write_pack(scope, wide_config, tmp_path / "plain")
    plain_row = {r["Pack ID"]: r for r in _packs_file(plain_dir)}["CP-100"]
    assert plain_row["in_report"] == "", "no report_config means no verdict to state"


def test_without_a_pack_export_the_file_is_not_written(tmp_path):
    """A missing optional input leaves today's pack exactly as it was --
    exactly `00`-`06`, the same seven-minus-one files as before this task.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    assert not (pack_dir / agent_pack.PACKS_CSV_NAME).exists()
    written = sorted(p.name for p in pack_dir.iterdir())
    assert written == ["00-README.txt", "01-summary.txt", "02-glossary.txt",
                       "03-data-quality.txt", "04-calendar.csv", "05-activities.csv",
                       "06-breakdowns.csv"]


def test_the_pack_is_written_where_it_can_be_uploaded_from(tmp_path, monkeypatch):
    """The pack is the one artefact that has to leave the machine.

    It is uploaded to the agent by hand, and a folder inside a git checkout is
    unsynced and unfindable from anywhere else -- so it lands in the OneDrive
    folder the source CSVs already arrive in. Never created, only used when it
    is there: a path conjured inside a OneDrive that is not really set up syncs
    nowhere while looking to the operator like it worked.
    """
    import pipeline.scripts.build_agent_pack as build

    onedrive = tmp_path / "OneDrive - Example"
    monkeypatch.setattr(build, "find_onedrive_root", lambda: onedrive)

    assert build.resolve_output_dir() == build.LOCAL_OUTPUT_DIR, (
        "a OneDrive without the CPLAN folder should fall back, not be created")
    assert not (onedrive / build.ONEDRIVE_INPUT_DIR).exists()

    (onedrive / build.ONEDRIVE_INPUT_DIR).mkdir(parents=True)
    assert build.resolve_output_dir() == onedrive / build.ONEDRIVE_INPUT_DIR

    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    assert build.resolve_output_dir() == build.LOCAL_OUTPUT_DIR


def test_the_pack_cannot_be_mistaken_for_its_own_input(tmp_path):
    """Output and input now share a folder, so the names must not overlap.

    Nothing in the pipeline deletes from there and the input globs are all
    specific, so today the two sets sit side by side harmlessly. The failure
    this guards against is a later rename -- a pack file called
    `CommunicationPacks.csv` would be read back in as source data on the next
    run, and the run would succeed, which is the worst way for it to go wrong.
    """
    import fnmatch

    from pipeline.scripts.process_cplan import INPUT_FILES

    pack_dir, out_dir, _, _ = _pack(tmp_path)
    written = [p.name for p in pack_dir.iterdir()] + [p.name for p in out_dir.iterdir()
                                                      if p.is_file()]
    assert written, "nothing was written, so this asserts nothing"
    for name in written:
        for pattern in INPUT_FILES.values():
            assert not fnmatch.fnmatch(name, pattern), (
                f"{name} would be read back as {pattern} source data")


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


def _pack_statements(pack_dir):
    """Every file whose lines can make a question a control.

    The prose pair plus `06-breakdowns.csv`: once a field is a breakdown
    block, its per-value totals are stated there exactly as finished as a
    prose figure is -- `lead_team,Team,no,activities,19` states "Team: 19" as
    plainly as `External: 275` does. `04-calendar.csv` is deliberately not
    here: it carries the same blocks split by week, and no single line in it
    ever states a value's total for the whole period.
    """
    return _pack_prose(pack_dir) + "\n" + (
        pack_dir / agent_pack.BREAKDOWN_NAME).read_text(encoding="utf-8")


def test_a_question_answered_anywhere_shipped_is_graded_a_control(tmp_path):
    """Pins the property, not today's question list.

    Run against `pack_config`'s widened breakdown fields -- the config a real
    run actually ships, where `lead_team` and `priority` are blocks and
    `06-breakdowns.csv` states each one's top value and count outright. A
    version of this fix that special-cased "the lead-team question" would
    pass today and rot the next time a block gains a value that happens to
    answer some other candidate; this instead checks, for every candidate
    whatever they turn out to be, that being stated anywhere shipped is
    exactly what makes it a control.
    """
    scope, config = _scope(tmp_path)
    packed = agent_pack.pack_config(config)
    pack_dir = agent_pack.write_pack(scope, packed, tmp_path / "out")
    statements = _pack_statements(pack_dir)

    found_a_control = False
    for question, _answer, control, _note, probe in agent_pack.checklist_questions(
            scope, packed):
        stated = agent_pack._states(statements, *probe)
        assert stated == control, (
            f"{question!r}: shipped files "
            f"{'state' if stated else 'do not state'} {probe!r}, "
            f"but is graded control={control}")
        found_a_control = found_a_control or stated
    # A vacuous pass here -- nothing ever stated, nothing ever a control --
    # would hide the exact regression this test exists to catch as surely as
    # not running it at all: the CSV branch has to actually fire on the
    # fixture, not merely exist.
    assert found_a_control, (
        "no candidate's probe is stated anywhere shipped -- this fixture "
        "does not exercise the property this test is meant to pin")


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


# ---------------------------------------------------------------------------
# The boards, held to the pack they cite
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# The GEB member list
#
# The plumbing was never the gap: `build_agent_pack.py` shares `resolve_scope`
# with the workbook, so `--geb-members` already split the breakdown blocks. The
# gap was that every prose file in the pack went on telling the agent no such
# split exists, and `.loop.md` records three separate occasions on which prose
# that contradicts the data won -- an agent believes the sentence, because that
# is what the sentence is for.
#
# So these tests come in pairs. One half pins what a machine WITHOUT the list
# gets, which is every machine that has not been given one, and is the
# regression that matters most. The other half pins that the pack with a list
# says the same thing its own files show.
# ---------------------------------------------------------------------------

def _members(*names):
    from pipeline.report.membership import Entry, Membership, normalise_name
    return Membership(entries=tuple(
        Entry(email="", name=normalise_name(name)) for name in names))


# The one fixture activity that names anybody in `bod_geb` (IC-0007).
GEB_PERSON = "Example, Ada"


def _pack_with_members(tmp_path, *names, **overrides):
    """`_pack`, with a membership list and the split fields `resolve_scope` sets.

    Both halves are needed together and neither is optional: the membership
    produces the columns, and swapping `executives` for its two halves in
    `breakdown_fields` is what makes the blocks appear. A test that loaded the
    list and left the fields alone would build a pack the product never ships.
    """
    from dataclasses import replace as _replace

    from pipeline.report.config import EXECUTIVES_SPLIT

    config = agent_pack.pack_config(_config(**overrides))
    fields = []
    for field in config.breakdown_fields:
        fields.extend(EXECUTIVES_SPLIT) if field == "executives" else fields.append(field)
    config = _replace(config, breakdown_fields=tuple(fields))
    scope = load_fixture_scope(tmp_path / "csv", config, membership=_members(*names))
    out_dir = tmp_path / "out"
    pack_dir = agent_pack.write_pack(scope, config, out_dir)
    return pack_dir, out_dir, scope, config


def test_without_a_list_the_glossary_still_refuses_to_name_a_geb_member(tmp_path):
    """The state every machine that has not been given the list is in.

    Nothing about the pack may change until a list exists, and the wording is
    pinned rather than merely "some GEB sentence": this is the sentence that
    stops an agent answering "how many activities involve the GEB" from a field
    that cannot answer it.
    """
    pack_dir, _, scope, _ = _pack(tmp_path)
    assert scope.membership is None
    glossary = (pack_dir / agent_pack.GLOSSARY_NAME).read_text(encoding="utf-8")
    assert agent_pack.GEB_RULE_COMBINED in glossary
    assert agent_pack.GEB_RULE_SPLIT not in glossary
    assert "Never name someone as a GEB member" in glossary
    # The workbook leaves the GEB term undefined without a list, because
    # defining a term it never prints would be its own small lie. The pack
    # mirrors that -- and the assertion is on a definition line, not on the
    # letters, which appear in the combined rule above.
    assert "\n  GEB: " not in glossary


def test_with_a_list_the_glossary_says_what_separated_the_levels(tmp_path):
    """The rule the pack is entitled to state once a list exists.

    Three things have to be in it, and each prevents a specific wrong answer:
    the blocks by name (so the agent knows where to look), the list as the
    source (so a reader is never told the source data made the distinction),
    and that the two do not sum (an activity naming people at both levels
    counts in both).
    """
    pack_dir, _, scope, _ = _pack_with_members(tmp_path, GEB_PERSON)
    assert scope.membership is not None
    glossary = (pack_dir / agent_pack.GLOSSARY_NAME).read_text(encoding="utf-8")
    assert agent_pack.GEB_RULE_SPLIT in glossary
    assert agent_pack.GEB_RULE_COMBINED not in glossary
    assert "Never name someone as a GEB member" not in glossary
    for phrase in ("executives_geb", "executives_geb1", "supplied", "do NOT sum"):
        assert phrase in glossary, f"the split rule does not state: {phrase}"
    # The workbook's own term, arriving through `_glossary_sections` rather
    # than being written a second time here.
    assert "\n  GEB: " in glossary


def test_the_glossary_rule_names_only_blocks_the_pack_actually_carries(tmp_path):
    """A rule pointing at a block that is not in the file is a rule that
    teaches the agent to distrust the rules. `executives_geb1` is named by the
    split rule, so at least one of the two named blocks has to be there -- the
    fixture has a single GEB person, so the geb block is the one that exists.
    """
    pack_dir, _, _, _ = _pack_with_members(tmp_path, GEB_PERSON)
    blocks = {row["block"] for row in _breakdowns(pack_dir)}
    assert "executives_geb" in blocks
    assert "executives" not in blocks, (
        "the split replaces the combined block; side by side, a reader adding "
        "them counts the same person twice")


def test_the_summary_states_the_geb_subset_only_once_a_list_exists(tmp_path):
    """The workbook prints this as an indented sub-row. Indentation is exactly
    what this file may not lean on -- a chunked read can keep the line and lose
    its parent -- so the relationship is asserted to be in the label itself.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    without = (pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8")
    assert "With GEB/GEB-1 involvement" in without
    assert "With GEB involvement" not in without

    pack_dir, _, scope, _ = _pack_with_members(tmp_path / "b", GEB_PERSON)
    with_list = (pack_dir / agent_pack.SUMMARY_NAME).read_text(encoding="utf-8")
    pairs = _summary_pairs(with_list)
    label = "With GEB involvement (a subset of GEB/GEB-1 involvement)"
    assert label in pairs, f"the summary does not state {label!r}"
    frame = scope.frame
    assert int(pairs[label]) == int((frame["executives_geb"] != "").sum())
    assert int(pairs[label]) <= int(pairs["With GEB/GEB-1 involvement"])
    # No GEB-1 line beside it: an activity can name people at both levels, so
    # the two would not partition the combined figure, and a reader subtracting
    # one from it would get a number that means nothing.
    assert "With GEB-1 involvement" not in with_list


def test_data_quality_reports_the_list_only_where_there_is_one(tmp_path):
    """A typo in the list and a person genuinely at GEB-1 level produce the
    same outcome in the pack. Only this count tells them apart, and the
    workbook prints it -- a pack that dropped it would answer the same question
    two ways.
    """
    pack_dir, _, _, _ = _pack(tmp_path)
    assert "GEB LIST" not in (pack_dir / agent_pack.QUALITY_NAME).read_text(encoding="utf-8")

    pack_dir, _, scope, _ = _pack_with_members(tmp_path / "b", GEB_PERSON, "Nobody, Here")
    text = (pack_dir / agent_pack.QUALITY_NAME).read_text(encoding="utf-8")
    assert "  GEB list entries | 2" in text
    assert scope.unmatched_members == 1
    assert "  GEB list entries never matched | 1" in text


def test_the_activity_rows_split_the_leadership_column_only_with_a_list(tmp_path):
    """Two empty columns claiming a distinction nothing made would be worse
    than no columns at all, so they arrive with the list and not before.
    """
    scope, config = _scope(tmp_path)
    headers, _ = agent_pack.activity_rows(scope)
    assert "GEB members" not in headers
    assert "GEB-1 members" not in headers
    assert "GEB/GEB-1 members" in headers, "the combined column is not conditional"

    _, _, scope, _ = _pack_with_members(tmp_path / "b", GEB_PERSON)
    headers, _ = agent_pack.activity_rows(scope)
    # Appended, not spliced in beside the combined column: the pack's activity
    # rows are the workbook's Activities sheet in the same order, and a column
    # set that reshuffles under a reader is worse than one that grows.
    from pipeline.report.table_sheets import ACTIVITY_COLUMNS as _COLUMNS
    assert headers[:len(_COLUMNS)] == [header for _, header in _COLUMNS]
    assert headers[len(_COLUMNS):] == ["GEB members", "GEB-1 members"]


def test_the_two_split_columns_reconstruct_the_combined_one(tmp_path):
    """The three leadership columns are consistent by construction, and a
    reader will assume it. Everyone in the combined column is in exactly one of
    the two halves -- never both, never neither.
    """
    _, _, scope, _ = _pack_with_members(tmp_path, GEB_PERSON)
    headers, rows = agent_pack.activity_rows(scope)
    combined = headers.index("GEB/GEB-1 members")
    geb, geb1 = headers.index("GEB members"), headers.index("GEB-1 members")

    def _people(value):
        return {part.strip() for part in str(value).split(";") if part.strip()}

    seen_any = False
    for row in rows:
        both = _people(row[geb]) | _people(row[geb1])
        assert _people(row[combined]) == both, row[combined]
        assert not (_people(row[geb]) & _people(row[geb1])), "a person on both sides"
        seen_any = seen_any or bool(both)
    assert seen_any, "the fixture named nobody, so this proved nothing"


def test_in_report_stays_the_last_column_when_the_split_columns_arrive(tmp_path):
    """The reconciliation columns are documented as coming last, and a reader
    told to look at the end of the row has to find them there.
    """
    _, _, scope, config = _pack_with_members(tmp_path, GEB_PERSON)
    headers, _ = agent_pack.activity_rows(scope, report_config=_config())
    assert headers[-2:] == ["in_report", "report_exclusion"]


def test_the_pasted_prompts_hold_whichever_pack_is_underneath(tmp_path):
    """The instructions and the board files are pasted once and stay there
    while the pack is rebuilt underneath them, so they cannot be conditional on
    a run. They must therefore describe BOTH states rather than assert either
    -- and the failure this pins is the old wording, which told the agent flatly
    that nothing separates the levels.
    """
    _, out_dir, _, _ = _pack(tmp_path)
    instructions = (out_dir / agent_pack.INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    with zipfile.ZipFile(out_dir / agent_pack.SKILL_ZIP_NAME) as archive:
        skill = archive.read("SKILL.md").decode("utf-8")
    boards = "".join(dashboard_skill.BOARDS.values())

    for text, name in ((instructions, "instructions"), (skill, "skill"),
                       (boards, "boards")):
        assert "executives_geb" in text, f"the {name} never mention the split blocks"
    # Both branches, in the one file that carries the rules on every turn.
    assert "GEB or GEB-1" in instructions          # the no-list branch survives
    assert "never add the two blocks together" in instructions

    # The exact wording each of these replaced. Pinned as a sentence rather
    # than as a keyword because the words themselves are all still in use --
    # what may not come back is the UNCONDITIONAL claim, which an agent
    # holding a pack full of executives_geb rows would believe over the rows.
    for name, text, superseded in (
            ("instructions", instructions,
             "both levels**, with nothing in the data saying which"),
            ("skill", skill, "which the data does not separate"),
            ("boards", boards, "nothing in the data separating them")):
        assert superseded not in text, (
            f"the {name} again assert, without condition, that the levels "
            f"cannot be separated: {superseded!r}")


def test_the_checklist_asks_about_the_split_only_where_it_exists(tmp_path):
    """A question nothing in the pack can answer is not a test of the agent.

    It grades as a control on purpose: `01-summary.txt` states the figure one
    line below the combined one, so an agent that quotes the combined figure
    has read the wrong line rather than failed to count -- and reading the
    wrong line is the whole failure mode of a distinction the source data does
    not make.
    """
    _, _, scope, config = _pack(tmp_path)
    questions = [q for q, *_ in agent_pack.checklist_questions(scope, config)]
    assert not [q for q in questions if "GEB" in q]

    _, _, scope, config = _pack_with_members(tmp_path / "b", GEB_PERSON)
    entries = agent_pack.checklist_questions(scope, config)
    asked = [entry for entry in entries if "GEB member" in entry[0]]
    assert len(asked) == 1, "the checklist does not ask about the split"
    question, answer, control, _note, _probe = asked[0]
    assert answer == int((scope.frame["executives_geb"] != "").sum())
    assert control, "the summary states this figure, so reading it is enough"
