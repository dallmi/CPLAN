"""Tests for the time-zone width check.

The failure it guards against is not hypothetical: a lookup value that does not
fit `activities.time_zone` ends the daily refresh on the INSERT, before one row
is written, and every activity then reads as missing a time zone.
"""

import csv
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from pipeline.scripts import check_time_zones


def _lookup(value: str) -> str:
    return (
        '{"@odata.type":"#Microsoft.Azure.Connectors.SharePoint.SPListExpandedReference",'
        f'"Id":1,"Value":"{value}"}}'
    )


SHORT = "Hong Kong, China, Taiwan Time - GMT+8:00"
LONG = "Belgrade, Bratislava, Budapest, Ljubljana, Prague Time - GMT+1:00"  # 65 characters


def _export(tmp_path: Path, header: str, *values: str) -> Path:
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", header])
        for index, value in enumerate(values, start=1):
            writer.writerow([str(index), f"Activity {index}", "2025-03-05", value])
    return path


def test_a_value_that_does_not_fit_the_column_is_reported_and_fails(tmp_path, capsys):
    _export(tmp_path, "Time zone", _lookup(SHORT), _lookup(LONG))

    exit_code = check_time_zones.main(["--input", str(tmp_path)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert LONG in out, "the offending value must be printed in full, not truncated to fit a table"
    assert "65" in out


def test_values_that_fit_pass(tmp_path, capsys):
    _export(tmp_path, "Time zone", _lookup(SHORT), _lookup("Europe/Zurich"))

    exit_code = check_time_zones.main(["--input", str(tmp_path)])

    assert exit_code == 0
    assert "OK:" in capsys.readouterr().out


def test_the_lookup_json_is_measured_unwrapped(tmp_path, capsys):
    """The blob is ~140 characters; what reaches the column is the 40 inside it."""
    _export(tmp_path, "Time zone", _lookup(SHORT))

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    assert SHORT in capsys.readouterr().out


def test_a_plain_text_column_is_read_as_it_stands(tmp_path, capsys):
    _export(tmp_path, "Time zone", "Europe/Zurich", "Europe/Zurich", "Asia/Tokyo")

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Europe/Zurich" in out and "Asia/Tokyo" in out


def test_the_sharepoint_encoded_column_name_is_matched(tmp_path, capsys):
    """Exports carry the internal name, where a space is `_x0020_`."""
    _export(tmp_path, "Time_x0020_zone", _lookup(SHORT))

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    assert SHORT in capsys.readouterr().out


def test_an_export_without_the_column_fails_rather_than_reporting_all_clear(tmp_path, capsys):
    """No values is not the same as no problem -- it is the older bug's shape."""
    _export(tmp_path, "Region", "EMEA")

    assert check_time_zones.main(["--input", str(tmp_path)]) == 1
    assert "missing a time zone" in capsys.readouterr().out


def test_a_folder_without_an_activity_export_says_so(tmp_path, capsys):
    assert check_time_zones.main(["--input", str(tmp_path)]) == 1
    assert "no activity export found" in capsys.readouterr().out


def test_the_limit_comes_from_the_model_not_from_a_number_typed_here():
    """A widened column must not leave this check failing rows that now fit."""
    from pipeline.api.app import Activity

    assert check_time_zones.column_limit() == Activity.__table__.c.time_zone.type.length


def test_the_column_label_is_read_from_the_etls_own_map():
    """Renaming the source column in COLUMN_MAP must not need a second edit here."""
    assert check_time_zones.is_time_zone_column("Time zone")
    assert not check_time_zones.is_time_zone_column("Region")
