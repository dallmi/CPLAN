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


# Every real export carries this, so every fixture must: the loader refuses a
# file without it rather than guess whether its rows may be published.
HIDE_HEADER = "Hide_x0020_from_x0020_public_x0020_view"


def _lookup(value: str) -> str:
    return (
        '{"@odata.type":"#Microsoft.Azure.Connectors.SharePoint.SPListExpandedReference",'
        f'"Id":1,"Value":"{value}"}}'
    )


SHORT = "Hong Kong, China, Taiwan Time - GMT+8:00"
SHORT_ZONE = "Asia/Shanghai"  # what the ETL translates SHORT to, and so what is stored
LONG = "Belgrade, Bratislava, Budapest, Ljubljana, Prague Time - GMT+1:00"  # 65 characters
UNMAPPED = "Mars Standard Time - GMT+25:00"  # in no translation table, so it passes through


def _export(tmp_path: Path, header: str, *values: str, hidden=()) -> Path:
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", header, HIDE_HEADER])
        for index, value in enumerate(values, start=1):
            writer.writerow([str(index), f"Activity {index}", "2025-03-05", value,
                             "TRUE" if index in hidden else "FALSE"])
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
    """The blob is ~140 characters; what reaches the column is the 30 inside it.

    An unmapped value, so this pins the unwrapping rather than the translation.
    """
    _export(tmp_path, "Time zone", _lookup(UNMAPPED))

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    assert UNMAPPED in capsys.readouterr().out


def test_a_plain_text_column_is_read_as_it_stands(tmp_path, capsys):
    _export(tmp_path, "Time zone", "Europe/Zurich", "Europe/Zurich", "Asia/Tokyo")

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Europe/Zurich" in out and "Asia/Tokyo" in out


def test_the_sharepoint_encoded_column_name_is_matched(tmp_path, capsys):
    """Exports carry the internal name, where a space is `_x0020_`."""
    _export(tmp_path, "Time_x0020_zone", _lookup(SHORT))

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    assert SHORT_ZONE in capsys.readouterr().out


def test_an_export_without_the_column_fails_rather_than_reporting_all_clear(tmp_path, capsys):
    """No values is not the same as no problem -- it is the older bug's shape."""
    _export(tmp_path, "Region", "EMEA")

    assert check_time_zones.main(["--input", str(tmp_path)]) == 1
    assert "missing a time zone" in capsys.readouterr().out


def test_a_folder_without_an_activity_export_says_so(tmp_path, capsys):
    assert check_time_zones.main(["--input", str(tmp_path)]) == 1
    assert "no activity export found" in capsys.readouterr().out


def test_the_lookups_id_companion_column_is_not_counted_as_a_time_zone(tmp_path, capsys):
    """A lookup exports as a pair: the JSON, and `<label>#Id` beside it.

    Both match the label, so without the ETL's noise filter the ids are measured
    as values -- the distinct count doubles and the list fills with 1.0 and 4.0.
    Seen on a real export: 46 reported where 23 exist.
    """
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", "Time_x0020_zone",
                         "Time_x0020_zone#Id", HIDE_HEADER])
        writer.writerow(["1", "A", "2025-03-05", _lookup(SHORT), "1", "FALSE"])
        writer.writerow(["2", "B", "2025-03-06",
                         _lookup("Japan Standard Time - GMT+9:00"), "4", "FALSE"])

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2 distinct value(s)" in out
    assert "1.0" not in out and "4.0" not in out


def test_a_hidden_activity_is_not_counted(tmp_path):
    """The rule is "gone everywhere", and this check is no exception to it.

    The cost is real and accepted: a held-back row with a broken zone keeps
    that defect, unreported. This check exists to fix data that flows onward,
    and these rows do not flow onward -- while "gone everywhere except here"
    is an exception the first person to forget gets wrong in the direction
    that leaks.
    """
    _export(tmp_path, "Time zone",
            "W. Europe Standard Time",
            "Tokyo Standard Time",
            hidden=(2,))
    files = check_time_zones.find_input_files(tmp_path)

    usage = check_time_zones.collect(files)

    assert "Tokyo Standard Time" not in usage.values
    assert "W. Europe Standard Time" in usage.values
    assert usage.hidden_excluded == 1


def test_only_the_column_the_etl_maps_is_measured(tmp_path, capsys):
    """`transform()` spends the label on the first matching column, so a second
    one is never stored. Reporting its width would send the reader after a
    problem the database is never asked to have.
    """
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", "Time zone",
                         "Time zone display", HIDE_HEADER])
        writer.writerow(["1", "A", "2025-03-05", SHORT, LONG, "FALSE"])

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    assert "1 distinct value(s)" in capsys.readouterr().out


def test_context_names_the_regions_and_teams_behind_each_zone(tmp_path, capsys):
    """The labels are inherited descriptions, not places anyone typed -- so only
    a zone's own rows say whether it means the place in its name.
    """
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", "Time zone", "Region",
                         "Lead Team", HIDE_HEADER])
        writer.writerow(["1", "A", "2025-03-05", "Middle East Time - GMT+3:30",
                         "APAC", "Pune Delivery", "FALSE"])
        writer.writerow(["2", "B", "2025-03-06", "Middle East Time - GMT+3:30",
                         "APAC", "Pune Delivery", "FALSE"])

    assert check_time_zones.main(["--input", str(tmp_path), "--context"]) == 0
    out = capsys.readouterr().out
    assert "APAC (2)" in out
    assert "Pune Delivery (2)" in out


def test_context_is_off_unless_asked_for(tmp_path, capsys):
    """The width verdict is what the command is for; it must not scroll away."""
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", "Time zone", "Region",
                         HIDE_HEADER])
        writer.writerow(["1", "A", "2025-03-05", SHORT, "APAC", "FALSE"])

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    assert "Who uses each zone" not in capsys.readouterr().out


def test_a_row_without_a_region_is_counted_as_blank_not_dropped(tmp_path, capsys):
    """A zone used only by rows that filled nothing else in is its own finding."""
    path = tmp_path / "InternalCommunicationActivities.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Title", "Start date", "Time zone", "Region",
                         HIDE_HEADER])
        writer.writerow(["1", "A", "2025-03-05", SHORT, "", "FALSE"])

    assert check_time_zones.main(["--input", str(tmp_path), "--context"]) == 0
    assert "(blank) (1)" in capsys.readouterr().out


def test_a_zone_the_map_does_not_translate_is_named(tmp_path, capsys):
    """The one failure that goes quiet: the source list gains an entry, it is
    stored as its display name, and only the drawer's "Not set" ever says so.
    """
    _export(tmp_path, "Time zone", _lookup("Mars Standard Time - GMT+25:00"))

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "not translated to an IANA zone" in out
    assert "Mars Standard Time - GMT+25:00" in out


def test_a_translated_export_reports_nothing_to_map(tmp_path, capsys):
    _export(tmp_path, "Time zone", _lookup(SHORT), _lookup("Japan Standard Time - GMT+9:00"))

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "not translated" not in out
    assert "Asia/Shanghai" in out and "Asia/Tokyo" in out


def test_a_hand_maintained_iana_value_is_not_called_unmapped(tmp_path, capsys):
    """It translates to nothing because it needs no translation."""
    _export(tmp_path, "Time zone", "Asia/Singapore")

    assert check_time_zones.main(["--input", str(tmp_path)]) == 0
    assert "not translated" not in capsys.readouterr().out


def test_the_limit_comes_from_the_model_not_from_a_number_typed_here():
    """A widened column must not leave this check failing rows that now fit."""
    from pipeline.api.app import Activity

    assert check_time_zones.column_limit() == Activity.__table__.c.time_zone.type.length


def test_the_mapping_is_the_etls_own(tmp_path):
    """No second implementation of the column matching or the translation lives
    here: what this counts is what `transform()` produced -- and therefore what
    the sync would store -- so the two cannot disagree.
    """
    _export(tmp_path, "Time zone", _lookup(SHORT))
    files = {"internal": tmp_path / "InternalCommunicationActivities.csv"}

    assert check_time_zones.collect(files).values == {SHORT_ZONE: 1}
