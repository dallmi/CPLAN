"""The calendar matrix: outline levels, formulas, and the double-count trap."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.calendar_sheet import (
    FIRST_GRID_COL,
    LABEL_COL,
    TOTAL_COL,
    build_calendar,
)
from pipeline.report.config import ReportConfig
from tests.report_fixtures import load_fixture_scope


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def _sheet(tmp_path, **overrides):
    scope = load_fixture_scope(tmp_path, _config(**overrides))
    wb = Workbook()
    wb.remove(wb.active)
    build_calendar(wb, scope, _config(**overrides))
    return wb["Calendar"], scope


def _labels(ws):
    return {
        ws.cell(row=r, column=LABEL_COL).value: r
        for r in range(3, ws.max_row + 1)
        if ws.cell(row=r, column=LABEL_COL).value
    }


def test_the_header_names_the_axes(tmp_path):
    ws, _ = _sheet(tmp_path)

    assert ws.cell(row=1, column=LABEL_COL).value == "Scope / activity"
    assert ws.cell(row=1, column=TOTAL_COL).value == "Total"
    assert ws.cell(row=1, column=FIRST_GRID_COL).value == "Q1 2025"
    assert ws.freeze_panes == "C3"


def test_columns_carry_the_three_outline_levels_and_open_collapsed(tmp_path):
    ws, _ = _sheet(tmp_path)
    levels = {}
    for letter, dimension in ws.column_dimensions.items():
        levels.setdefault(dimension.outline_level, []).append(letter)

    assert set(levels) >= {0, 1, 2}
    month_letter = levels[1][0]
    week_letter = levels[2][0]
    assert ws.column_dimensions[month_letter].hidden is True
    assert ws.column_dimensions[week_letter].hidden is True
    assert ws.sheet_properties.outlinePr.summaryRight is False


def test_rows_carry_block_dimension_and_activity_levels(tmp_path):
    ws, _ = _sheet(tmp_path)
    labels = _labels(ws)
    block_row = labels["BY REACH"]

    assert ws.row_dimensions[block_row].outline_level == 0
    child_rows = [r for r in range(block_row + 1, ws.max_row + 1)
                  if ws.row_dimensions[r].outline_level == 1]
    assert child_rows
    assert ws.row_dimensions[child_rows[0]].hidden is True


def test_month_and_quarter_cells_are_sum_formulas_over_their_children(tmp_path):
    ws, _ = _sheet(tmp_path)
    row = _labels(ws)["ALL ACTIVITIES"]

    quarter_cell = ws.cell(row=row, column=FIRST_GRID_COL).value
    assert isinstance(quarter_cell, str) and quarter_cell.startswith("=SUM(")
    total_cell = ws.cell(row=row, column=TOTAL_COL).value
    assert isinstance(total_cell, str) and total_cell.startswith("=SUM(")


def test_week_cells_are_literal_counts(tmp_path):
    ws, scope = _sheet(tmp_path)
    row = _labels(ws)["ALL ACTIVITIES"]
    week_columns = [c for c in range(FIRST_GRID_COL, ws.max_column + 1)
                    if ws.column_dimensions[
                        ws.cell(row=1, column=c).column_letter].outline_level == 2]
    values = [ws.cell(row=row, column=c).value for c in week_columns]
    numeric = [v for v in values if isinstance(v, int)]

    assert sum(numeric) == len(scope.frame)


def test_the_reach_block_header_sums_its_children(tmp_path):
    ws, _ = _sheet(tmp_path)
    row = _labels(ws)["BY REACH"]

    assert str(ws.cell(row=row, column=TOTAL_COL).value).startswith("=SUM(")


def test_the_division_block_header_is_a_distinct_count_not_a_sum(tmp_path):
    ws, scope = _sheet(tmp_path)
    labels = _labels(ws)
    header = next(label for label in labels if label.startswith("BY BUSINESS DIVISION"))
    row = labels[header]

    assert "multiple values possible" in header
    assert isinstance(ws.cell(row=row, column=TOTAL_COL).value, str) is False
    assert ws.cell(row=row, column=TOTAL_COL).value == len(scope.frame)


def test_detail_rows_can_be_switched_off(tmp_path):
    with_detail, _ = _sheet(tmp_path, detail_rows=True)
    without_detail, _ = _sheet(tmp_path, detail_rows=False)

    assert with_detail.max_row > without_detail.max_row
    levels = {without_detail.row_dimensions[r].outline_level
              for r in range(3, without_detail.max_row + 1)}
    assert 2 not in levels
