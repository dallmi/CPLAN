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
    assert pairs["GEB"] == "any"


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
    assert pairs["GEB"] == "any"
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



def _glossary_entries(ws):
    """(term, definition) for every defined row, skipping the section bands."""
    out = []
    for r in range(1, ws.max_row + 1):
        term, definition = ws.cell(row=r, column=1).value, ws.cell(row=r, column=2).value
        if term and definition:
            out.append((str(term), str(definition)))
    return out


MAX_DEFINITION_CHARS = 110


def test_every_glossary_definition_stays_short(tmp_path):
    """Plain and short is the requirement, not a style preference.

    The Glossary drifted into paragraph-long justifications -- one entry ran to
    eight lines explaining why two completeness figures could look inconsistent.
    A reader who needs that much prose to understand a column has been failed by
    the column, not by the Glossary. This pins the ceiling so the drift cannot
    quietly happen again.
    """
    ws, _ = _build(tmp_path, build_glossary)
    entries = _glossary_entries(ws)

    assert entries, "the Glossary has no definitions at all"
    too_long = [(t, len(d)) for t, d in entries if len(d) > MAX_DEFINITION_CHARS]
    assert not too_long, f"definitions over {MAX_DEFINITION_CHARS} chars: {too_long}"


def test_the_glossary_defines_the_terms_a_reader_meets_on_the_sheets(tmp_path):
    """The terms that appear as column headers or row labels elsewhere.

    Deliberately absent, each removed on request: the data source, the note that
    studio-only activities never reach this report, the Thursday week-to-month
    rule, and the comma/semicolon splitting caveat. They are recorded in the
    design document instead. Do not restore them here as a phantom regression --
    if they are wanted back, that is a product decision.
    """
    ws, _ = _build(tmp_path, build_glossary)
    terms = {term for term, _ in _glossary_entries(ws)}
    text = "\n".join(f"{t} {d}" for t, d in _glossary_entries(ws)).lower()

    for term in ("In scope", "Group-wide", "Overlap", "Audience band",
                 "GEB", "Lead time", "Planning completeness",
                 "Weekly counts", "Quarter delta", "Packs"):
        assert term in terms, f"the Glossary does not define {term!r}"

    assert "thursday" not in text
    assert "studio" not in text
    assert "semicolon" not in text
    assert ws.sheet_view.showGridLines is False


def test_the_glossary_lists_fields_the_export_does_not_carry(tmp_path):
    ws, scope = _build(tmp_path, build_glossary)
    column_a = [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]

    assert scope.skipped_completeness_fields      # sanity: the fixture skips time_zone
    assert "FIELDS NOT IN THIS EXPORT" in column_a
    for name in scope.skipped_completeness_fields:
        assert name in column_a
