"""Filtering the loaded activities down to the report's scope."""

from datetime import date

import pytest

pytest.importorskip("pandas")
import pandas as pd

from pipeline.report.config import BAND_10_50K, BAND_OVER_100K, ReportConfig
from pipeline.report.data import build_scope
from pipeline.report.derive import REACH_SINGLE_DIVISION
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
    assert row["reach"] == REACH_SINGLE_DIVISION
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
    assert scope.excluded["senior executives"] == 1


def test_the_executive_filter_can_be_inverted():
    load = _load(_row(tracking_id="A", bod_geb="Someone"), _row(tracking_id="B", bod_geb=""))

    scope = build_scope(load, _config(executives="without"))

    assert list(scope.frame["tracking_id"]) == ["B"]


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


def test_an_empty_load_produces_an_empty_scope_rather_than_an_error():
    scope = build_scope(ActivityLoad(pd.DataFrame(), {}, {}), _config())

    assert scope.frame.empty
    assert scope.rows_read == 0
