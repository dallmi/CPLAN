"""Filtering the loaded activities down to the report's scope."""

from datetime import date, timedelta

import pytest

pytest.importorskip("pandas")
import pandas as pd

from pipeline.report import packs as packs_module
from pipeline.report.config import BAND_10_50K, BAND_OVER_100K, ReportConfig
from pipeline.report.data import EXCLUSION_ORDER, build_scope
from pipeline.scripts.process_cplan import ActivityLoad


def _frame(rows):
    columns = [
        "tracking_id", "activity_name", "source_type", "start_date", "end_date",
        "created", "business_division", "region", "channel", "priority",
        "target_audience", "audience", "bod_geb", "communication_pack_cpid",
        "communication_pack", "campaign", "lead", "lead_team",
        "strategic_objectives", "activity_description", "is_archived",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    for column in ("start_date", "end_date", "created"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _row(**overrides):
    base = dict(
        tracking_id="IC-0001", activity_name="A", source_type="internal",
        start_date="2025-03-05", end_date="2025-03-06", created="2025-02-01",
        business_division="IB", region="EMEA", channel="Email", priority="2 - label",
        target_audience="All staff", audience="12000", bod_geb="",
        communication_pack_cpid="CP-1", communication_pack="Pack", campaign="C",
        lead="L", lead_team="T", strategic_objectives="O",
        activity_description="D", is_archived=False,
    )
    base.update(overrides)
    return base


def _load(*rows):
    return ActivityLoad(_frame([list(r.values()) for r in rows] if rows else []),
                        {"internal": ["Tracking ID"]}, {})


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def test_rows_inside_the_window_survive_and_carry_derived_columns():
    scope = build_scope(_load(_row()), _config())

    assert len(scope.frame) == 1
    row = scope.frame.iloc[0]
    assert row["audience_band"] == BAND_10_50K
    assert row["has_executives"] is False or row["has_executives"] == False  # noqa: E712
    assert row["week_index"] == scope.grid.week_index(date(2025, 3, 5))
    assert row["_quarter"] == (2025, 1)
    assert row["lead_time_days"] == 32


def test_a_row_whose_whole_run_falls_outside_the_window_is_excluded():
    load = _load(_row(start_date="2024-06-01", end_date="2024-06-02"))

    scope = build_scope(load, _config())

    assert len(scope.frame) == 0
    assert scope.excluded["date window"] == 1


def test_a_run_that_starts_before_the_window_but_ends_inside_it_survives():
    """The period is an overlap test: an activity running from December into
    February is running during both years and belongs in both reports.
    """
    load = _load(_row(start_date="2024-12-20", end_date="2025-02-15"))

    scope = build_scope(load, _config())

    assert len(scope.frame) == 1
    assert scope.excluded["date window"] == 0


def test_a_run_that_spans_the_whole_window_survives_though_neither_date_is_inside():
    load = _load(_row(start_date="2024-06-01", end_date="2026-06-01"))

    scope = build_scope(load, _config())

    assert len(scope.frame) == 1


def test_the_axis_widens_to_reach_a_row_that_starts_before_the_window():
    """The calendar guarantees a column for every activity it lists, and
    `build_calendar` asserts it. An overlap-admitted row starting in December
    has to have a week to sit in.
    """
    load = _load(_row(start_date="2024-12-20", end_date="2025-02-15"))

    scope = build_scope(load, _config())

    assert scope.frame.iloc[0]["week_index"] is not None
    assert scope.grid.weeks[0].monday <= date(2024, 12, 20)
    assert scope.grid.weeks[-1].monday >= date(2025, 12, 25)   # the named bound is kept


def test_a_row_without_a_start_date_is_excluded_and_counted_separately():
    scope = build_scope(_load(_row(start_date=None)), _config())

    assert len(scope.frame) == 0
    assert scope.excluded["no start date"] == 1


def test_the_executive_filter_keeps_only_involved_rows():
    load = _load(_row(tracking_id="A", bod_geb="Someone"), _row(tracking_id="B", bod_geb=""))

    scope = build_scope(load, _config(executives="with"))

    assert list(scope.frame["tracking_id"]) == ["A"]
    assert scope.excluded["GEB/GEB-1"] == 1


def test_the_executive_filter_can_be_inverted():
    load = _load(_row(tracking_id="A", bod_geb="Someone"), _row(tracking_id="B", bod_geb=""))

    scope = build_scope(load, _config(executives="without"))

    assert list(scope.frame["tracking_id"]) == ["B"]


def test_the_objectives_filter_drops_only_the_pure_catch_all_rows():
    load = _load(
        _row(tracking_id="A", strategic_objectives="2026: Other"),
        _row(tracking_id="B", strategic_objectives="2026: Other, 2026: Growth"),
        _row(tracking_id="C", strategic_objectives="2026: Growth"),
        _row(tracking_id="D", strategic_objectives=""),
    )

    scope = build_scope(load, _config(exclude_objectives=("2026: Other",)))

    assert sorted(scope.frame["tracking_id"]) == ["B", "C", "D"]
    assert scope.excluded["objectives"] == 1


def test_without_configured_prefixes_the_objectives_filter_does_nothing():
    load = _load(_row(tracking_id="A", strategic_objectives="2026: Other"))

    scope = build_scope(load, _config())

    assert list(scope.frame["tracking_id"]) == ["A"]
    assert scope.excluded["objectives"] == 0


def test_an_export_without_the_objectives_column_still_produces_a_scope():
    """`transform()` keeps only the columns the CSV carried, so the field may
    simply be absent. A configured filter must then exclude nothing rather
    than raise.
    """
    frame = pd.DataFrame([{
        "tracking_id": "IC-0001", "activity_name": "A",
        "start_date": pd.Timestamp("2025-03-05"),
    }])
    assert "strategic_objectives" not in frame.columns

    scope = build_scope(ActivityLoad(frame, {}, {}),
                        _config(exclude_objectives=("2026: Other",)))

    assert len(scope.frame) == 1
    assert scope.excluded["objectives"] == 0


def test_the_two_leadership_fields_are_derived_separately():
    """`bod_geb` (GEB and GEB-1, mixed) and the source's separate other-executives
    list are different fields and must never bleed into each other -- the
    GEB/GEB-1 filter counts only the former.
    """
    frame = pd.DataFrame([{
        "tracking_id": "A", "activity_name": "A",
        "start_date": pd.Timestamp("2025-03-05"),
        "bod_geb": "A leadership person",
        "other_executives": "Another executive; And one more",
    }])

    scope = build_scope(ActivityLoad(frame, {}, {}), _config())
    row = scope.frame.iloc[0]

    assert row["executives"] == "A leadership person"
    assert row["senior_executives"] == "Another executive; And one more"
    assert row["has_executives"] is True or row["has_executives"] == True  # noqa: E712


def test_an_other_executive_alone_does_not_count_as_geb_involvement():
    frame = pd.DataFrame([{
        "tracking_id": "A", "activity_name": "A",
        "start_date": pd.Timestamp("2025-03-05"),
        "bod_geb": "", "other_executives": "Another executive",
    }])

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(executives="with"))

    assert len(scope.frame) == 0
    assert scope.excluded["GEB/GEB-1"] == 1


def test_the_priority_filter_drops_the_numbers_it_names():
    load = _load(
        _row(tracking_id="A", priority="1 - price sensitive"),
        _row(tracking_id="B", priority="4 - deprioritised"),
        _row(tracking_id="C", priority="2 - label"),
    )

    scope = build_scope(load, _config(exclude_priorities=(4,)))

    assert sorted(scope.frame["tracking_id"]) == ["A", "C"]
    assert scope.excluded["priority"] == 1


def test_a_word_priority_is_left_alone_by_a_numeric_filter():
    """Two vocabularies are live at once and there is no honest mapping between
    them, so a numeric filter must not silently judge the words.
    """
    load = _load(_row(tracking_id="A", priority="Low"),
                 _row(tracking_id="B", priority="4 - deprioritised"))

    scope = build_scope(load, _config(exclude_priorities=(4,)))

    assert list(scope.frame["tracking_id"]) == ["A"]


def test_without_configured_priorities_nothing_is_dropped():
    load = _load(_row(tracking_id="A", priority="4 - deprioritised"))

    scope = build_scope(load, _config())

    assert list(scope.frame["tracking_id"]) == ["A"]
    assert scope.excluded["priority"] == 0


def test_the_audience_filter_keeps_only_the_named_bands():
    load = _load(_row(tracking_id="A", audience="12000"), _row(tracking_id="B", audience="250000"))

    scope = build_scope(load, _config(audience_bands=(BAND_OVER_100K,),
                                      include_unknown_audience=False))

    assert list(scope.frame["tracking_id"]) == ["B"]
    assert scope.excluded["audience band"] == 1


def test_unknown_audience_rows_can_be_kept_alongside_a_band_filter():
    load = _load(_row(tracking_id="A", audience=""), _row(tracking_id="B", audience="250000"))

    scope = build_scope(load, _config(audience_bands=(BAND_OVER_100K,),
                                      include_unknown_audience=True))

    assert sorted(scope.frame["tracking_id"]) == ["A", "B"]


def test_archived_rows_can_be_excluded():
    load = _load(_row(tracking_id="A", is_archived=True), _row(tracking_id="B", is_archived=False))

    scope = build_scope(load, _config(include_archived=False))

    assert list(scope.frame["tracking_id"]) == ["B"]
    assert scope.excluded["archived"] == 1


def test_completeness_ignores_fields_the_export_does_not_carry():
    scope = build_scope(_load(_row()), _config())

    # time_zone is required in the studio but is not mapped by the ETL, so it
    # must not permanently cap every row's score.
    assert "time_zone" in scope.skipped_completeness_fields
    assert "time_zone" not in scope.completeness_fields
    assert scope.frame.iloc[0]["completeness"] == 100


def test_a_missing_required_field_lowers_completeness_below_100():
    scope = build_scope(_load(_row(channel="")), _config())

    assert scope.frame.iloc[0]["completeness"] < 100


def test_a_source_export_missing_optional_columns_still_produces_a_scope():
    """`transform()` narrows the frame to the columns the CSV actually had, so
    a source export missing one is a real shape. It must produce a workbook
    with one honest gap, not a traceback: `frame.get(name, "")` returns the
    bare scalar, and `zip("", series)` yields nothing, which used to raise
    "Length of values (0) does not match length of index".
    """
    frame = pd.DataFrame([{
        "tracking_id": "IC-0001", "activity_name": "A",
        "start_date": pd.Timestamp("2025-03-05"), "end_date": pd.Timestamp("2025-03-06"),
    }])
    assert "business_division" not in frame.columns
    assert "region" not in frame.columns
    assert "source_type" not in frame.columns

    scope = build_scope(ActivityLoad(frame, {}, {}), _config())

    assert len(scope.frame) == 1
    row = scope.frame.iloc[0]
    assert row["audience_band"] == "Unknown"
    assert row["has_executives"] is False or row["has_executives"] == False  # noqa: E712
    assert row["completeness"] >= 0            # scored against the external field list


def test_the_exclusion_counts_partition_the_rows_that_were_read():
    """`EXCLUSION_ORDER` and the sequence of `drop()` calls have to stay in
    lockstep. The Executive Summary's REPORT section prints these figures as a
    partition of what was read -- rows read, then one line per criterion, then
    rows in scope -- so a row failing two criteria must be counted once, by
    whichever filter reached it first. If the two ever drift apart, the section
    prints overlapping tallies that quietly do not add up.
    """
    load = _load(
        _row(tracking_id="A"),                                     # survives all of it
        _row(tracking_id="B", start_date=None, is_archived=True),  # undated AND archived
        _row(tracking_id="C", start_date="2024-06-01",             # out of window AND
             end_date="2024-06-02",                                #   (whole run outside)
             is_archived=True, audience=""),                       #   archived AND unbanded
        _row(tracking_id="D", is_archived=True, audience=""),      # archived AND unbanded
        _row(tracking_id="E", audience="250000"),                  # wrong band only
    )

    scope = build_scope(load, _config(include_archived=False,
                                      audience_bands=(BAND_10_50K,),
                                      include_unknown_audience=False))

    assert scope.rows_read == 5
    assert list(scope.frame["tracking_id"]) == ["A"]
    assert sum(scope.excluded.values()) + len(scope.frame) == scope.rows_read
    assert set(scope.excluded) == set(EXCLUSION_ORDER)
    # Each multi-failure row lands under the first criterion that removed it,
    # never under both.
    assert scope.excluded["no start date"] == 1     # B, not also "archived"
    assert scope.excluded["date window"] == 1       # C, not also "archived"
    assert scope.excluded["archived"] == 1          # D, not also "audience band"
    assert scope.excluded["audience band"] == 1     # E
    assert scope.excluded["GEB/GEB-1"] == 0


def test_the_exclusion_counts_partition_the_rows_read_under_every_criterion():
    """The same identity with the executive filter live as well, so no drop()
    call is left unexercised by this partition check.
    """
    load = _load(
        _row(tracking_id="A", bod_geb="An executive"),
        _row(tracking_id="B", bod_geb=""),
        _row(tracking_id="C", bod_geb="", start_date=None),
    )

    scope = build_scope(load, _config(executives="with"))

    assert sum(scope.excluded.values()) + len(scope.frame) == scope.rows_read
    assert scope.excluded["GEB/GEB-1"] == 1
    assert scope.excluded["no start date"] == 1


def test_an_empty_load_produces_an_empty_scope_rather_than_an_error():
    scope = build_scope(ActivityLoad(pd.DataFrame(), {}, {}), _config())

    assert scope.frame.empty
    assert scope.rows_read == 0


# --- the time axis: a named bound wins, the data fills in the rest ----------

def _open_config(**overrides):
    return _config(date_from=None, date_to=None, **overrides)


def _span(scope):
    """First and last day the axis reaches."""
    return scope.grid.weeks[0].monday, scope.grid.weeks[-1].monday + timedelta(days=6)


def test_without_a_period_no_dated_row_is_excluded():
    load = _load(_row(tracking_id="A", start_date="2019-03-05"),
                 _row(tracking_id="B", start_date="2026-11-02"))

    scope = build_scope(load, _open_config())

    assert len(scope.frame) == 2
    assert scope.excluded["date window"] == 0


def test_without_a_period_the_axis_spans_the_data_and_gives_every_row_a_column():
    load = _load(_row(tracking_id="A", start_date="2019-03-05"),
                 _row(tracking_id="B", start_date="2026-11-02"))

    scope = build_scope(load, _open_config())

    first, last = _span(scope)
    assert first == date(2019, 3, 4)      # Monday of the earliest activity's week
    assert last == date(2026, 11, 8)      # Sunday of the latest activity's week
    assert scope.frame["week_index"].notna().all()


def test_a_named_period_keeps_its_full_span_even_when_the_data_is_narrower():
    """Asking for 2026 means seeing all of 2026, empty weeks included."""
    load = _load(_row(start_date="2026-06-03"))

    scope = build_scope(load, _config(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)))

    first, last = _span(scope)
    assert first <= date(2026, 1, 1)
    assert last >= date(2026, 12, 31)


def test_a_one_sided_period_takes_its_open_edge_from_the_data():
    load = _load(_row(tracking_id="A", start_date="2025-06-04"),
                 _row(tracking_id="B", start_date="2027-02-10"))

    scope = build_scope(load, _config(date_from=date(2026, 1, 1), date_to=None))

    assert len(scope.frame) == 1               # the 2025 row is out
    first, last = _span(scope)
    assert first <= date(2026, 1, 1)           # the named bound is kept...
    assert last == date(2027, 2, 14)           # ...the open edge follows the data


def test_a_later_filter_narrows_the_rows_but_not_the_time_axis():
    """Archived, executives and audience say *who* appears, not *when* the
    report is about. Letting them move the axis would make it shift for
    surprising reasons.
    """
    load = _load(_row(tracking_id="A", start_date="2025-03-05", is_archived=False),
                 _row(tracking_id="B", start_date="2026-09-02", is_archived=True))

    scope = build_scope(load, _open_config(include_archived=False))

    assert len(scope.frame) == 1
    assert scope.excluded["archived"] == 1
    assert _span(scope)[1] == date(2026, 9, 6)   # still reaches the archived row


def test_an_open_period_with_no_dated_rows_still_produces_an_axis():
    scope = build_scope(_load(_row(start_date=None)), _open_config())

    assert scope.frame.empty
    assert scope.grid.weeks          # a column-less sheet would be unopenable


from pipeline.report.membership import Membership, Entry


def _members(*pairs):
    """A Membership from (email, name) pairs, already normalised by Entry."""
    from pipeline.report.membership import normalise_email, normalise_name
    return Membership(entries=tuple(
        Entry(email=normalise_email(e), name=normalise_name(n)) for e, n in pairs))


def _leadership_row(bod_geb, bod_geb_email=""):
    return {
        "tracking_id": "A", "activity_name": "A",
        "start_date": pd.Timestamp("2025-03-05"),
        "bod_geb": bod_geb, "bod_geb_email": bod_geb_email,
    }


def test_without_a_membership_the_split_columns_are_absent():
    """Every machine without the list gets today's workbook, unchanged."""
    frame = pd.DataFrame([_leadership_row("Person, One")])

    scope = build_scope(ActivityLoad(frame, {}, {}), _config())

    assert "executives_geb" not in scope.frame.columns
    assert "executives_geb1" not in scope.frame.columns
    assert scope.membership is None
    assert scope.unmatched_members == 0


def test_a_configured_member_lands_in_the_geb_column():
    frame = pd.DataFrame([_leadership_row("Person, One")])
    members = _members(("", "Person, One"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == "One Person"
    assert row["executives_geb1"] == ""


def test_anyone_else_in_the_field_lands_in_geb1():
    frame = pd.DataFrame([_leadership_row("Other, Two")])
    members = _members(("", "Person, One"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == ""
    assert row["executives_geb1"] == "Two Other"


def test_the_two_columns_partition_the_source_field():
    """Every person appears in exactly one column, and none is lost."""
    frame = pd.DataFrame([_leadership_row("Person, One; Other, Two; Third, Three")])
    members = _members(("", "Person, One"), ("", "Third, Three"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == "One Person; Three Third"
    assert row["executives_geb1"] == "Two Other"
    assert row["executives"] == "One Person; Two Other; Three Third"


def test_an_email_identifies_a_member_whose_name_differs():
    frame = pd.DataFrame([
        _leadership_row("Married, Anna", "anna@example.invalid")])
    members = _members(("anna@example.invalid", "Maiden, Anna"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)

    assert scope.frame.iloc[0]["executives_geb"] == "Anna Married"


def test_emails_pair_positionally_with_names():
    frame = pd.DataFrame([
        _leadership_row("A, One; B, Two", "a@example.invalid; b@example.invalid")])
    members = _members(("b@example.invalid", ""))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == "Two B"
    assert row["executives_geb1"] == "One A"


def test_a_mismatched_email_count_falls_back_to_names_only():
    """Positional pairing is only safe while the counts agree. Where they do
    not, guessing an alignment would attribute someone else's address.
    """
    frame = pd.DataFrame([_leadership_row("A, One; B, Two", "only@example.invalid")])
    members = _members(("only@example.invalid", ""))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)
    row = scope.frame.iloc[0]

    assert row["executives_geb"] == ""
    assert row["executives_geb1"] == "One A; Two B"


def test_unmatched_configuration_entries_are_counted():
    frame = pd.DataFrame([_leadership_row("Person, One")])
    members = _members(("", "Person, One"), ("", "Nobody, Zero"))

    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), members)

    assert scope.unmatched_members == 1


def test_unmatched_is_counted_over_rows_the_objectives_filter_dropped():
    """A member whose only activity is dropped by the objectives filter still
    reads as unmatched, which is the honest answer: this workbook shows
    nothing of theirs. This filter runs late -- after the GEB/GEB-1 split
    must be derived -- so it is the case that catches the split being
    computed against rows the workbook no longer shows.
    """
    row = _leadership_row("Person, One")
    row["strategic_objectives"] = "2026: Other"
    frame = pd.DataFrame([row])
    members = _members(("", "Person, One"))

    scope = build_scope(
        ActivityLoad(frame, {}, {}),
        _config(exclude_objectives=("2026:",)),
        members,
    )

    assert scope.frame.empty
    assert scope.unmatched_members == 1


def test_unmatched_is_counted_over_rows_the_priority_filter_dropped():
    """Same guarantee against the priority filter, which runs later still."""
    row = _leadership_row("Person, One")
    row["priority"] = "4 - Low"
    frame = pd.DataFrame([row])
    members = _members(("", "Person, One"))

    scope = build_scope(
        ActivityLoad(frame, {}, {}),
        _config(exclude_priorities=(4,)),
        members,
    )

    assert scope.frame.empty
    assert scope.unmatched_members == 1


def test_the_scope_carries_the_pack_list_and_the_link_rate(tmp_path):
    """The pack file needs the pre-filter counts, so the scope has to hold
    them: a pack showing zero in scope and zero overall is a different
    finding from one showing zero in scope and forty overall.

    That promise only means something if the two counts can actually differ.
    The fixture's date window drops one row that references CP-100 (the row
    with no start date) plus the row outside the window, so the in-scope
    count -- read straight off `pack_known`, independently of however
    `pack_counts_all` computed its own number -- comes out lower than the
    pre-filter one. Asserting `>` against that live figure, rather than a
    hard-coded constant, is what catches `pack_counts_all` quietly being
    computed on the filtered frame instead of the unfiltered one: a filtered
    implementation would make the two sides equal and this would fail.
    """
    from tests.report_fixtures import load_fixture_scope

    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config, with_packs=True)

    in_scope_cp100 = int((scope.frame["pack_known"] == "Yes").sum())

    assert scope.packs is not None
    assert scope.pack_link.rate == 1.0
    assert scope.pack_counts_all["CP-100"] > in_scope_cp100
    assert scope.pack_counts_all["CP-200"] == 0
    assert "pack_known" in scope.frame.columns


def test_the_link_rate_is_measured_over_every_row_the_export_carried(tmp_path):
    """The rate and the floor it is compared against need one denominator.

    `MIN_LINK_RATE` was established by `check_pack_link.py`, which scores
    every row the export carries. Measuring here over in-scope rows only
    compares two different populations: this fixture is a total link failure
    -- half the references resolve to nothing -- that a filtered measurement
    reports as a perfect 100%, because the one row carrying the evidence is
    outside the period.

    The mirror case is as bad and not testable in one fixture: filters that
    keep the badly-linked rows make a healthy export cry wolf. Both look like
    a link problem from the log line, and neither is one.
    """
    from pipeline.scripts.process_cplan import find_input_files, load_packs
    from tests.report_fixtures import write_pack_csv

    write_pack_csv(tmp_path)
    pack_load = load_packs(find_input_files(tmp_path))

    frame = _frame([
        _row(tracking_id="IC-1", start_date="2025-03-05", end_date="2025-03-06",
             communication_pack_cpid="CP-100"),
        # The only row that says anything is wrong, and the only one a
        # filtered measurement cannot see: outside the period, and naming a
        # pack the list does not carry.
        _row(tracking_id="IC-2", start_date="2019-03-05", end_date="2019-03-06",
             communication_pack_cpid="CP-NOT-IN-THE-LIST"),
    ])
    scope = build_scope(ActivityLoad(frame, {}, {}), _config(), None, pack_load)

    assert len(scope.frame) == 1, "the badly-linked row is out of scope, as intended"
    assert (scope.pack_link.referenced, scope.pack_link.matched) == (2, 1)
    assert scope.pack_link.rate == 0.5
    assert scope.pack_link.rate < packs_module.MIN_LINK_RATE, (
        "a rate this bad has to reach the warning the floor exists for")


def test_a_scope_without_a_pack_export_is_unchanged(tmp_path):
    """Today's output, exactly, on a machine that has no pack list."""
    from tests.report_fixtures import load_fixture_scope

    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config)

    assert scope.packs is None
    assert scope.pack_link is None
    assert "pack_known" not in scope.frame.columns


def test_an_empty_frame_still_carries_the_pack_fields(tmp_path):
    """`build_scope` has two `Scope(...)` construction sites: this one (the
    early return for an empty activity frame) and the one every other test
    here exercises. A pack_load reaching only the second would pass every
    other test in this file and still lose `packs`/`pack_link`/
    `pack_counts_all` on the one machine whose activity export is empty --
    silently, since the dataclass default for all three is None and an
    empty scope is otherwise a legitimate result, not an error.
    """
    from pipeline.scripts.process_cplan import find_input_files, load_packs
    from tests.report_fixtures import FIXTURE_PACK_COUNT, write_pack_csv

    write_pack_csv(tmp_path)
    pack_load = load_packs(find_input_files(tmp_path))

    scope = build_scope(ActivityLoad(pd.DataFrame(), {}, {}), _config(), None, pack_load)

    assert scope.frame.empty
    assert scope.packs is not None
    assert len(scope.packs) == FIXTURE_PACK_COUNT
    assert scope.pack_link is not None
    assert scope.pack_counts_all is not None
