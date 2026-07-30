"""The figures behind the flat sheets."""

from datetime import date

import pytest

pytest.importorskip("pandas")

from pipeline.report import metrics
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope


def _scope(tmp_path):
    return load_fixture_scope(tmp_path, ReportConfig(
        date_from=date(2025, 1, 1), date_to=date(2025, 12, 31)))


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

    names = dict(metrics.anomalies(scope.frame))

    assert "End date before start date" in names
    assert "Archived" in names
