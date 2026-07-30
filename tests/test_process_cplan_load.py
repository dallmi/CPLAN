"""Tests for the activity-loading step shared by the ETL and the calendar report."""

from pathlib import Path

import pytest

pytest.importorskip("pandas")

import pipeline.scripts.process_cplan as process_cplan


INTERNAL_CSV = (
    "ID,Tracking ID,Title,Start date,Region,Modified\n"
    "1,IC-0001,Active row,2025-03-05,EMEA,2025-03-01\n"
)
ARCHIVE_CSV = (
    "ID,Tracking ID,Title,Start date,Region,Modified\n"
    "1,IC-0001,Stale duplicate,2025-03-05,EMEA,2025-01-01\n"
    "2,IC-0002,Archived row,2025-04-09,APAC,2025-04-01\n"
)


def _write(tmp_path: Path) -> dict[str, Path]:
    internal = tmp_path / "InternalCommunicationActivities.csv"
    archive = tmp_path / "InternalCommunicationActivitiesArchive.csv"
    internal.write_text(INTERNAL_CSV, encoding="utf-8")
    archive.write_text(ARCHIVE_CSV, encoding="utf-8")
    return {"internal": internal, "internal_archive": archive}


def test_load_activities_merges_archive_and_flags_it(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    assert set(load.frame["tracking_id"]) == {"IC-0001", "IC-0002"}
    archived = load.frame.set_index("tracking_id")["is_archived"]
    assert archived["IC-0002"] is True or archived["IC-0002"] == True  # noqa: E712


def test_load_activities_keeps_the_most_recently_modified_duplicate(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    row = load.frame.set_index("tracking_id").loc["IC-0001"]
    assert row["activity_name"] == "Active row"


def test_load_activities_reports_raw_columns_per_file(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    assert "Tracking ID" in load.raw_columns["internal"]
    assert set(load.files) == {"internal", "internal_archive"}


def test_load_activities_with_no_activity_files_returns_an_empty_frame(tmp_path):
    load = process_cplan.load_activities({"packs": tmp_path / "CommunicationPacks.csv"})

    assert load.frame.empty
    assert load.raw_columns == {}
    assert load.files == {}
