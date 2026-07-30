"""The summary carries the criteria, the volume, the load and the caveats."""

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.config import ReportConfig
from pipeline.report.data import build_scope
from pipeline.report.table_sheets import build_executive_summary, build_glossary
from pipeline.scripts.process_cplan import ActivityLoad
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


def test_the_summary_still_renders_the_report_section_on_an_empty_scope():
    """Nothing in scope is exactly when the REPORT section -- the criteria,
    the source files, which filter removed what -- matters most. It must
    render rather than raise, even though the empty-load path never attaches
    the derived columns (week_index included) that the other sections read.
    """
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = build_scope(ActivityLoad(pd.DataFrame(), {}, {}), config)
    wb = Workbook()
    wb.remove(wb.active)

    build_executive_summary(wb, scope, config)

    ws = wb.worksheets[0]
    pairs = _pairs(ws)
    assert pairs["Period"] == "2025-01-01 to 2025-12-31"
    assert pairs["Senior executives"] == "any"
    assert pairs["Excluded: no start date"] == 0
    assert pairs["Excluded: date window"] == 0
    assert pairs["Rows read"] == 0


def test_every_share_formula_divides_by_its_own_section_total(tmp_path):
    """A formula that names the wrong denominator row still renders a
    plausible-looking percentage -- startswith("=TEXT(IF(") alone cannot
    catch that. Check the actual cell references instead.
    """
    ws, _ = _build(tmp_path, build_executive_summary)
    rows = {ws.cell(row=r, column=1).value: r for r in range(1, ws.max_row + 1)}
    total_row = rows["Activities in scope"]

    checked = 0
    for r in range(1, ws.max_row + 1):
        label = ws.cell(row=r, column=1).value
        if not isinstance(label, str) or not label.startswith("=TEXT(IF("):
            continue
        assert f"B${total_row}=0" in label, f"row {r} guards the wrong total"
        assert f"B{r}/B${total_row}" in label, f"row {r} divides the wrong cells"
        checked += 1
    assert checked >= 7  # internal/external plus the five reach buckets


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


def test_the_glossary_names_the_derivation_of_every_literal_figure(tmp_path):
    """Where a literal sits next to formulas, the design requires the Glossary
    to say how it was derived. The Executive Summary's LOAD section is five
    such literals -- median per week, peak week, zero weeks, longest zero run,
    top-5 share -- and had no entry at all.
    """
    ws, _ = _build(tmp_path, build_glossary)
    text = "\n".join(
        f"{ws.cell(row=r, column=1).value} {ws.cell(row=r, column=2).value}"
        for r in range(1, ws.max_row + 1)
    ).lower()

    assert "load figures" in text
    for phrase in ("median", "peak week", "no activity", "longest run", "busiest weeks"):
        assert phrase in text, f"the Glossary does not account for {phrase!r}"


def test_the_glossary_records_the_multi_value_splitting_rule(tmp_path):
    """A division or channel value that legitimately contains a comma reads as
    two dimension values. That is a real reading hazard on the Calendar and Mix
    sheets, so it belongs next to the overlap caveat.
    """
    ws, _ = _build(tmp_path, build_glossary)
    text = "\n".join(str(ws.cell(row=r, column=2).value)
                     for r in range(1, ws.max_row + 1)).lower()

    assert "semicolon" in text
    assert "comma" in text


def test_the_glossary_points_at_where_the_skipped_fields_are_listed(tmp_path):
    """The Planning completeness entry used to send the reader to the Data
    Quality sheet for fields the export does not carry. They are listed on the
    Glossary itself, under FIELDS NOT IN THIS EXPORT.
    """
    ws, scope = _build(tmp_path, build_glossary)
    column_a = [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]
    text = "\n".join(str(ws.cell(row=r, column=2).value)
                     for r in range(1, ws.max_row + 1))

    assert scope.skipped_completeness_fields  # sanity: the fixture skips time_zone
    assert "FIELDS NOT IN THIS EXPORT" in column_a
    entry = next(t for t in text.split("\n") if t.startswith("Share of the fields"))
    assert "FIELDS NOT IN THIS EXPORT" in entry
    assert "this sheet" in entry
