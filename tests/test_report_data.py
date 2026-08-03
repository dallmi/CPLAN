"""Filtering the loaded activities down to the report's scope."""

from datetime import date, timedelta

import pytest

pytest.importorskip("pandas")
import pandas as pd

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


def test_a_row_outside_the_window_is_excluded_and_counted():
    scope = build_scope(_load(_row(start_date="2024-06-01")), _config())

    assert len(scope.frame) == 0
    assert scope.excluded["date window"] == 1


def test_a_row_without_a_start_date_is_excluded_and_counted_separately():
    scope = build_scope(_load(_row(start_date=None)), _config())

    assert len(scope.frame) == 0
    assert scope.excluded["no start date"] == 1


def test_the_executive_filter_keeps_only_involved_rows():
    load = _load(_row(tracking_id="A", bod_geb="Someone"), _row(tracking_id="B", bod_geb=""))

    scope = build_scope(load, _config(executives="with"))

    assert list(scope.frame["tracking_id"]) == ["A"]
    assert scope.excluded["GEB"] == 1


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
    assert scope.excluded["GEB"] == 0


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
    assert scope.excluded["GEB"] == 1
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
