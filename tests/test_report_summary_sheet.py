"""The summary carries the criteria, the volume, the load and the caveats."""

from datetime import date

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.config import ReportConfig
from pipeline.report.table_sheets import build_executive_summary, build_glossary
from tests.report_fixtures import load_fixture_scope


def _build(tmp_path, builder):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config)
    wb = Workbook()
    wb.remove(wb.active)
    builder(wb, scope, config)
    return wb.worksheets[0], scope


def _pairs(ws):
    return {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2).value
            for r in range(1, ws.max_row + 1)}


def test_the_summary_states_the_applied_criteria(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    pairs = _pairs(ws)

    assert pairs["Period"] == "2025-01-01 to 2025-12-31"
    assert pairs["Senior executives"] == "any"


def test_the_summary_names_every_source_file(tmp_path):
    ws, scope = _build(tmp_path, build_executive_summary)
    text = "\n".join(str(ws.cell(row=r, column=2).value) for r in range(1, ws.max_row + 1))

    for _, name in scope.source_files:
        assert name in text


def test_the_summary_reports_what_each_criterion_excluded(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    pairs = _pairs(ws)

    assert pairs["Excluded: no start date"] == 1
    assert pairs["Excluded: date window"] == 1


def test_shares_are_formulas_not_baked_numbers(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    labels = [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]

    assert any(label.startswith("=TEXT(IF(") for label in labels)


def test_the_summary_reports_load_and_discipline(tmp_path):
    ws, _ = _build(tmp_path, build_executive_summary)
    pairs = _pairs(ws)

    assert "Peak week" in pairs
    assert "Weeks with no activity" in pairs
    assert "Median lead time (days)" in pairs


def test_the_glossary_records_the_counting_rule_and_the_pack_caveat(tmp_path):
    ws, _ = _build(tmp_path, build_glossary)
    text = "\n".join(
        f"{ws.cell(row=r, column=1).value} {ws.cell(row=r, column=2).value}"
        for r in range(1, ws.max_row + 1)
    )

    assert "Thursday" in text
    assert "start date" in text.lower()
    assert "pack" in text.lower()
    assert "studio" in text.lower()
    assert ws.sheet_view.showGridLines is False
