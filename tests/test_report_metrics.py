"""The figures behind the flat sheets."""

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("pandas")

from pipeline.report import metrics, packs
from pipeline.report.config import ReportConfig
from pipeline.report.data import build_scope
from pipeline.scripts.process_cplan import ActivityLoad
from tests.report_fixtures import load_fixture_scope


def _scope(tmp_path):
    return load_fixture_scope(tmp_path, ReportConfig(
        date_from=date(2025, 1, 1), date_to=date(2025, 12, 31)))


def _small_frame():
    """A hand-built frame with a known, countable number of each anomaly.

    Deliberately not routed through the fixture/ETL: `load_activities`
    de-duplicates by tracking_id before `anomalies()` ever sees a frame, so a
    frame built here can carry known blank IDs and end-before-start pairs
    without the loader silently removing any of them first.
    """
    return pd.DataFrame([
        # end before start
        {"tracking_id": "A-1", "start_date": "2025-01-10", "end_date": "2025-01-05",
         "is_archived": False},
        {"tracking_id": "A-2", "start_date": "2025-01-10", "end_date": "2025-01-20",
         "is_archived": False},
        # end before start
        {"tracking_id": "A-3", "start_date": "2025-02-01", "end_date": "2025-01-25",
         "is_archived": True},
        # missing end date, blank tracking id (empty string)
        {"tracking_id": "", "start_date": "2025-03-01", "end_date": None,
         "is_archived": False},
        # blank tracking id (NaN)
        {"tracking_id": None, "start_date": "2025-03-02", "end_date": "2025-03-10",
         "is_archived": False},
    ])


def test_load_stats_finds_the_peak_and_the_empty_weeks(tmp_path):
    scope = _scope(tmp_path)

    stats = metrics.load_stats(scope)

    assert stats["peak_week_count"] >= 1
    assert stats["zero_weeks"] > 0
    assert stats["longest_zero_run"] >= 1
    assert 0 <= stats["top5_share"] <= 1


def test_load_stats_on_an_empty_scope_does_not_divide_by_zero(tmp_path):
    scope = _scope(tmp_path)
    scope.frame = scope.frame.iloc[0:0]

    stats = metrics.load_stats(scope)

    assert stats["peak_week_count"] == 0
    assert stats["top5_share"] == 0
    assert stats["median_per_week"] == 0


def test_load_stats_on_a_scope_with_no_rows_read_at_all_does_not_raise():
    """`build_scope`'s early return for a truly empty load never attaches the
    derived columns (`week_index` included) -- that is the shape a
    header-only export produces, and it is a supported, tested shape of
    `Scope` (see test_report_data.py), not a hypothetical one.
    """
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    load = ActivityLoad(pd.DataFrame(), {}, {})
    scope = build_scope(load, config)
    assert "week_index" not in scope.frame.columns

    stats = metrics.load_stats(scope)

    assert stats == {
        "median_per_week": 0, "peak_week_label": "—", "peak_week_count": 0,
        "zero_weeks": len(scope.grid.weeks), "longest_zero_run": len(scope.grid.weeks),
        "top5_share": 0,
    }


def test_lead_time_counts_only_rows_with_both_dates(tmp_path):
    scope = _scope(tmp_path)

    stats = metrics.lead_time_stats(scope.frame)

    assert stats["counted"] == int(scope.frame["lead_time_days"].notna().sum())
    assert stats["median_days"] is not None


def test_pack_stats_size_the_buckets(tmp_path):
    scope = _scope(tmp_path)

    stats = metrics.pack_stats(scope.frame)

    assert stats["with_pack"] + stats["without_pack"] == len(scope.frame)
    assert stats["packs"] >= 1
    assert stats["largest_pack"] >= 1


def test_pack_stats_count_the_pack_an_activity_was_resolved_to(tmp_path):
    """The summary and the pack file have to be about the same activities.

    `01-summary.txt` states how many activities have no pack; `07-packs.csv`
    counts the ones that do. Read from the pack field while the pack file
    counts the resolved column, the two describe different populations and an
    agent reading both is handed a contradiction it will resolve by picking
    one.
    """
    scope = _scope(tmp_path)
    frame = scope.frame.copy()
    frame[packs.RESOLVED_COLUMN] = "CP-100"
    frame[packs.PACK_LINK_COLUMN] = ""

    stats = metrics.pack_stats(frame)

    assert stats["without_pack"] == 0
    assert stats["with_pack"] == len(frame)


def test_field_completeness_lists_filled_and_missing_per_field(tmp_path):
    scope = _scope(tmp_path)

    rows = metrics.field_completeness(scope)

    by_field = {name: (filled, missing) for name, filled, missing in rows}
    assert "channel" in by_field
    filled, missing = by_field["channel"]
    assert filled + missing == len(scope.frame)
    assert missing >= 1  # the fixture's incomplete record


def test_anomalies_report_the_undated_and_the_blank_tracking_ids(tmp_path):
    scope = _scope(tmp_path)

    names = dict(metrics.anomalies(scope.frame, scope.duplicates_removed))

    assert "End date before start date" in names
    assert "Archived" in names
    # The fixture's archive list carries one stale duplicate of IC-0001;
    # load_activities removes it before build_scope ever sees the frame.
    assert scope.duplicates_removed == 1
    assert names["Duplicate tracking IDs removed on load"] == 1


def test_the_anomalies_block_names_the_excluded_activities():
    """A total the reader cannot explain is worse than no total.

    These rows are not in `frame` -- counting them against it would be a
    tautological zero -- so the figure is computed at load and passed in,
    exactly as the duplicate count above it is.
    """
    names = dict(metrics.anomalies(_small_frame(), duplicates_removed=0,
                                   hidden_excluded=3))

    assert names["Hidden activities excluded on load"] == 3


def test_the_anomalies_block_states_a_zero_when_nothing_was_hidden():
    """The row is unconditional. A figure that appears only when non-zero
    teaches a reader nothing about the runs where it is absent."""
    names = dict(metrics.anomalies(_small_frame()))

    assert names["Hidden activities excluded on load"] == 0


def test_anomalies_counts_end_before_start_pairs():
    names = dict(metrics.anomalies(_small_frame()))

    assert names["End date before start date"] == 2
    assert names["Missing end date"] == 1
    assert names["Blank tracking ID (after de-duplication)"] == 2
    assert names["Archived"] == 1


def test_anomalies_survive_a_source_export_without_an_end_date_column():
    """`pd.to_datetime(frame.get("end_date"))` on an absent column parses None
    and returns the *scalar* pd.NaT, not a Series -- `end.isna()` on that
    raises AttributeError and takes down the whole workbook build, not just
    this block. Every sheet has to degrade to one honest gap instead.
    """
    frame = pd.DataFrame([{"tracking_id": "A-1", "start_date": "2025-01-10"}])
    assert "end_date" not in frame.columns

    names = dict(metrics.anomalies(frame))

    assert names["Missing end date"] == 1
    assert names["End date before start date"] == 0


def test_anomalies_survive_a_frame_with_neither_date_column():
    names = dict(metrics.anomalies(pd.DataFrame([{"tracking_id": "A-1"}])))

    assert names["Missing end date"] == 1
    assert names["End date before start date"] == 0


def test_anomalies_report_the_real_duplicate_count_not_a_post_dedup_zero():
    rows = metrics.anomalies(_small_frame(), duplicates_removed=3)

    counts = dict(rows)
    assert counts["Duplicate tracking IDs removed on load"] == 3
    # The frame itself has already been de-duplicated upstream, so this must
    # come from the passed-in figure, not from a nunique() count against
    # `frame` -- that count is structurally always 0.
    assert counts["Duplicate tracking IDs removed on load"] != 0
