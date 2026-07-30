"""Mix over time, lead time by division, and the traceable detail list."""

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from pipeline.report.config import ReportConfig
from pipeline.report.data import build_scope
from pipeline.report.table_sheets import (
    ACTIVITY_COLUMNS,
    _quarter_label,
    build_activities,
    build_mix,
)
from pipeline.scripts.process_cplan import ActivityLoad
from tests.report_fixtures import load_fixture_scope


def _build(tmp_path, builder, name):
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path, config)
    wb = Workbook()
    wb.remove(wb.active)
    builder(wb, scope, config)
    return wb[name], scope


def _column_a(ws):
    return [str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1)]


def test_mix_covers_channel_priority_and_source_type(tmp_path):
    ws, _ = _build(tmp_path, build_mix, "Mix & Lead Time")
    labels = _column_a(ws)

    assert "CHANNEL BY QUARTER" in labels
    assert "PRIORITY BY QUARTER" in labels
    assert "INTERNAL VS EXTERNAL BY QUARTER" in labels
    assert "LEAD TIME BY DIVISION" in labels


def test_the_delta_column_names_the_two_quarters_it_compares(tmp_path):
    ws, _ = _build(tmp_path, build_mix, "Mix & Lead Time")
    headers = [str(ws.cell(row=r, column=c).value)
               for r in range(1, ws.max_row + 1) for c in range(1, ws.max_column + 1)]

    assert any(h.startswith("Δ ") and "−" in h for h in headers)


def test_the_delta_header_names_the_first_and_last_quarter_present(tmp_path):
    """The weak `startswith("Δ ") and "−" in h` check above would pass even
    with the two quarter labels swapped, wrong, or naming quarters that are
    not actually the first and last present. Pin the exact text, derived
    from the scope rather than hardcoded, so this catches a wrong header.
    """
    ws, scope = _build(tmp_path, build_mix, "Mix & Lead Time")
    quarters = sorted({q for q in scope.frame["_quarter"] if q is not None})
    expected = f"Δ {_quarter_label(quarters[-1])} − {_quarter_label(quarters[0])}"

    headers = [str(ws.cell(row=r, column=c).value)
               for r in range(1, ws.max_row + 1)
               for c in range(1, ws.max_column + 1)]

    assert expected in headers


def test_the_activities_sheet_lists_every_in_scope_row(tmp_path):
    ws, scope = _build(tmp_path, build_activities, "Activities")

    assert ws.max_row == len(scope.frame) + 1
    assert ws.auto_filter.ref is not None
    assert ws.freeze_panes == "A2"


def test_the_activities_sheet_carries_the_derived_columns(tmp_path):
    ws, _ = _build(tmp_path, build_activities, "Activities")
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]

    assert headers == [header for _, header in ACTIVITY_COLUMNS]
    assert "Reach" in headers
    assert "Audience band" in headers
    assert "Senior executives" in headers


def _empty_scope():
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    load = ActivityLoad(pd.DataFrame(), {}, {})
    return build_scope(load, config)


def test_an_empty_scope_does_not_crash_the_mix_sheet():
    """Task 10 shipped a Critical bug on exactly this shape: a builder that
    raised on the frame `build_scope` produces when nothing was read at all
    -- no columns, not merely no rows. This sheet must degrade gracefully
    instead.
    """
    scope = _empty_scope()
    assert scope.frame.empty
    assert list(scope.frame.columns) == []

    wb = Workbook()
    wb.remove(wb.active)
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    build_mix(wb, scope, config)
    ws = wb["Mix & Lead Time"]

    assert ws.cell(row=1, column=1).value is not None


def test_an_empty_scope_does_not_crash_the_activities_sheet():
    scope = _empty_scope()
    assert scope.frame.empty
    assert list(scope.frame.columns) == []

    wb = Workbook()
    wb.remove(wb.active)
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    build_activities(wb, scope, config)
    ws = wb["Activities"]

    # No rows beyond the header -- the row count still equals the in-scope
    # count exactly (zero), it just never gets the chance to drop anything.
    assert ws.max_row == len(scope.frame) + 1
    assert [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)] == [
        header for _, header in ACTIVITY_COLUMNS
    ]


def test_the_activities_row_count_matches_the_in_scope_count_exactly(tmp_path):
    """The Activities sheet must not silently drop rows: this is the audit
    trail every other sheet's figures have to be traceable back to.
    """
    ws, scope = _build(tmp_path, build_activities, "Activities")
    assert len(scope.frame) > 0  # sanity: the fixture is not itself empty
    assert ws.max_row == len(scope.frame) + 1
