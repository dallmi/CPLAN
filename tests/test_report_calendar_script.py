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


def test_the_default_output_path_names_the_year(tmp_path):
    path = report_calendar.default_output_path(report_calendar.CONFIG)

    assert str(report_calendar.CONFIG.date_from.year) in path.name
    assert path.suffix == ".xlsx"
