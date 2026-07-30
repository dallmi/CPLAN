"""The fixture must survive the real transform path, or nothing built on it means anything."""

from datetime import date

import pytest

pytest.importorskip("pandas")

from pipeline.report.config import ReportConfig
from pipeline.report.derive import (
    REACH_GROUP_WIDE,
    REACH_REGIONAL_ONLY,
    REACH_UNCLASSIFIED,
)
from tests.report_fixtures import FIXTURE_ROW_COUNT, load_fixture_scope, write_activity_csvs
from pipeline.scripts.process_cplan import load_activities


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def test_the_fixture_loads_and_deduplicates(tmp_path):
    load = load_activities(write_activity_csvs(tmp_path))

    assert len(load.frame) == FIXTURE_ROW_COUNT
    name = load.frame.set_index("tracking_id").loc["IC-0001", "activity_name"]
    assert name == "Single division Q1"


def test_lookup_json_becomes_readable_values(tmp_path):
    load = load_activities(write_activity_csvs(tmp_path))
    row = load.frame.set_index("tracking_id").loc["IC-0002"]

    assert "Division A" in row["business_division"]
    assert "Division C" in row["business_division"]


def test_the_scope_covers_every_reach_bucket(tmp_path):
    scope = load_fixture_scope(tmp_path, _config())

    reaches = set(scope.frame["reach"])
    assert REACH_GROUP_WIDE in reaches
    assert REACH_REGIONAL_ONLY in reaches
    assert REACH_UNCLASSIFIED in reaches


def test_the_scope_excludes_the_undated_and_out_of_window_rows(tmp_path):
    scope = load_fixture_scope(tmp_path, _config())

    assert scope.excluded["no start date"] == 1
    assert scope.excluded["date window"] == 1
    assert "IC-0011" not in set(scope.frame["tracking_id"])
