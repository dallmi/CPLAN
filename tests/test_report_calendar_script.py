"""End to end: raw CSVs in, a seven-sheet workbook out."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import load_workbook

import pipeline.scripts.report_calendar as report_calendar
from tests.report_fixtures import write_activity_csvs

EXPECTED_SHEETS = [
    "Executive Summary", "Calendar", "Data Quality",
    "Audience & Executives", "Mix & Lead Time", "Activities", "Glossary",
]


def test_the_script_writes_all_seven_sheets(tmp_path):
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"

    code = report_calendar.main(["--input-dir", str(tmp_path / "input"), "--out", str(out)])

    assert code == 0
    assert out.exists()
    assert load_workbook(out).sheetnames == EXPECTED_SHEETS


def test_the_workbook_reopens_without_repair(tmp_path):
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"
    report_calendar.main(["--input-dir", str(tmp_path / "input"), "--out", str(out)])

    wb = load_workbook(out)

    # Reading the calendar back proves the outline and merged-cell XML is valid.
    assert wb["Calendar"].cell(row=1, column=1).value == "Scope / activity"


def test_an_empty_input_directory_fails_loudly(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    code = report_calendar.main(["--input-dir", str(empty), "--out", str(tmp_path / "x.xlsx")])

    assert code == 1


def test_the_default_run_covers_every_dated_activity(tmp_path):
    """The fixtures carry a 2024 row that the old hard-coded 2025 window cut."""
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"
    report_calendar.main(["--input-dir", str(tmp_path / "input"), "--out", str(out)])

    names = [row[1].value for row in load_workbook(out)["Activities"].iter_rows()]

    assert "Outside the window" in names
    assert dict_of_summary(out)["Period"] == "all dates"


def test_a_year_run_cuts_the_activities_outside_it(tmp_path):
    write_activity_csvs(tmp_path / "input")
    out = tmp_path / "report.xlsx"
    report_calendar.main(["--input-dir", str(tmp_path / "input"),
                          "--year", "2025", "--out", str(out)])

    names = [row[1].value for row in load_workbook(out)["Activities"].iter_rows()]

    assert "Outside the window" not in names
    assert dict_of_summary(out)["Period"] == "2025-01-01 to 2025-12-31"


def dict_of_summary(path):
    """Label -> value from the Executive Summary, whatever column they sit in."""
    labels = {}
    for row in load_workbook(path)["Executive Summary"].iter_rows():
        values = [cell.value for cell in row if cell.value is not None]
        if len(values) >= 2:
            labels[values[0]] = values[1]
    return labels


# --- the period on the command line -----------------------------------------

def _resolve(argv):
    parser = report_calendar.build_parser()
    return report_calendar.resolve_config(
        report_calendar.CONFIG, parser.parse_args(argv), parser)


def test_no_period_flags_leave_the_config_block_alone():
    config = _resolve([])

    assert config == report_calendar.CONFIG
    assert config.date_from is None and config.date_to is None


def test_year_expands_to_the_whole_calendar_year():
    config = _resolve(["--year", "2026"])

    assert config.date_from == date(2026, 1, 1)
    assert config.date_to == date(2026, 12, 31)


def test_from_and_to_set_the_window_verbatim():
    config = _resolve(["--from", "2025-01-01", "--to", "2026-12-31"])

    assert config.date_from == date(2025, 1, 1)
    assert config.date_to == date(2026, 12, 31)
    assert config.period_slug() == "2025-2026"


def test_from_alone_leaves_the_upper_bound_open():
    config = _resolve(["--from", "2026-04-01"])

    assert config.date_from == date(2026, 4, 1)
    assert config.date_to is None


def test_the_other_criteria_survive_a_period_flag():
    config = _resolve(["--year", "2026"])

    assert config.breakdown_fields == report_calendar.CONFIG.breakdown_fields
    assert config.include_archived == report_calendar.CONFIG.include_archived


def test_year_together_with_from_is_refused_rather_than_silently_winning():
    with pytest.raises(SystemExit):
        _resolve(["--year", "2026", "--from", "2026-04-01"])


def test_a_reversed_window_is_refused():
    with pytest.raises(SystemExit):
        _resolve(["--from", "2026-12-31", "--to", "2026-01-01"])


def test_a_malformed_date_is_refused_at_parse_time():
    with pytest.raises(SystemExit):
        _resolve(["--from", "01.04.2026"])


@pytest.mark.parametrize("argv,expected", [
    ([], "CPLAN_calendar_all_"),
    (["--year", "2026"], "CPLAN_calendar_2026_"),
    (["--from", "2025-01-01", "--to", "2026-12-31"], "CPLAN_calendar_2025-2026_"),
    (["--from", "2026-04-01", "--to", "2026-09-30"], "CPLAN_calendar_2026-04-01-2026-09-30_"),
])
def test_the_default_output_path_names_the_period(argv, expected):
    path = report_calendar.default_output_path(_resolve(argv))

    assert path.name.startswith(expected)
    assert path.suffix == ".xlsx"
