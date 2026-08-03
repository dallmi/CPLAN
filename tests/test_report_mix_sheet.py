"""Mix over time, lead time by division, and the traceable detail list."""

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from pipeline.report.config import ReportConfig
from pipeline.report.data import build_scope
from pipeline.report.derive import priority_rank
from pipeline.report.table_sheets import (
    ACTIVITY_COLUMNS,
    _quarter_label,
    build_activities,
    build_mix,
    delta_quarters,
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


def test_the_delta_header_names_the_two_quarters_it_actually_compares(tmp_path):
    """The weak `startswith("Δ ") and "−" in h` check above would pass even
    with the two quarter labels swapped, wrong, or naming quarters that are
    not actually the ones compared. Pin the exact text, derived from the scope
    rather than hardcoded, so this catches a wrong header.
    """
    ws, scope = _build(tmp_path, build_mix, "Mix & Lead Time")
    quarters = sorted({q for q in scope.frame["_quarter"] if q is not None})
    first, last = delta_quarters(quarters, scope.grid)
    expected = f"Δ {_quarter_label(last)} − {_quarter_label(first)}"

    headers = [str(ws.cell(row=r, column=c).value)
               for r in range(1, ws.max_row + 1)
               for c in range(1, ws.max_column + 1)]

    assert expected in headers


def test_the_delta_does_not_compare_against_a_one_week_stub_quarter(tmp_path):
    """A full-year window spans FIVE quarters, not four.

    The Thursday rule puts 29 Dec - 4 Jan into the next year's week 1, whose
    Thursday is in January -- so the default window ends with a Q1 holding a
    single week. Taking that as the Δ column's right-hand side makes every row
    of all three crosstabs read strongly negative (about 2% of a year against
    25% of it) and a planner reads the mix as having collapsed.
    """
    ws, scope = _build(tmp_path, build_mix, "Mix & Lead Time")
    quarters = sorted({q for q in scope.frame["_quarter"] if q is not None})

    # The premise: the last quarter present really is a one-week stub.
    weeks_per_quarter = {}
    for week in scope.grid.weeks:
        quarter = scope.grid.quarter_of(week)
        weeks_per_quarter[quarter] = weeks_per_quarter.get(quarter, 0) + 1
    assert weeks_per_quarter[quarters[-1]] == 1
    assert len(quarters) == 5

    first, last = delta_quarters(quarters, scope.grid)

    assert first == quarters[0] == (2025, 1)
    assert last == (2025, 4)
    assert last != quarters[-1]
    assert weeks_per_quarter[last] >= 4

    headers = [str(ws.cell(row=r, column=c).value)
               for r in range(1, ws.max_row + 1)
               for c in range(1, ws.max_column + 1)]
    assert "Δ Q4 2025 − Q1 2025" in headers
    assert not any(h.startswith("Δ Q1 2026") for h in headers)


def test_the_delta_formula_points_at_the_two_named_quarter_columns(tmp_path):
    """Naming the right quarters in the header but subtracting the wrong
    columns would be invisible until someone opened the file in Excel.
    """
    ws, scope = _build(tmp_path, build_mix, "Mix & Lead Time")
    quarters = sorted({q for q in scope.frame["_quarter"] if q is not None})
    first, last = delta_quarters(quarters, scope.grid)

    header_row = next(r for r in range(1, ws.max_row + 1)
                      if ws.cell(row=r, column=1).value == "Value")
    labels = {ws.cell(row=header_row, column=c).value: c
              for c in range(1, ws.max_column + 1)}
    from_col = get_column_letter(labels[_quarter_label(first)])
    to_col = get_column_letter(labels[_quarter_label(last)])
    delta_col = labels[f"Δ {_quarter_label(last)} − {_quarter_label(first)}"]

    value_row = header_row + 1
    assert ws.cell(row=value_row, column=delta_col).value == \
        f"={to_col}{value_row}-{from_col}{value_row}"


def test_the_priority_block_is_ordered_by_rank_not_alphabetically(tmp_path):
    """Two priority vocabularies are live at once, so alphabetical order is
    actively wrong: it interleaves "3 - low priority" with "High" and puts
    Low above Medium. The fixture carries both vocabularies for exactly this.
    """
    ws, _ = _build(tmp_path, build_mix, "Mix & Lead Time")
    column_a = _column_a(ws)
    start = column_a.index("PRIORITY BY QUARTER")
    rows = []
    for label in column_a[start + 2:]:
        if label in ("None", "") or label.isupper():
            break
        rows.append(label)

    assert len(rows) > 1, "the fixture must carry more than one priority value"
    ranks = [priority_rank(label) for label in rows]
    assert ranks == sorted(ranks, reverse=True), f"not ranked most-urgent-first: {rows}"
    assert rows != sorted(rows), "alphabetical order would have passed this test"


def test_the_activities_sheet_lists_every_in_scope_row(tmp_path):
    ws, scope = _build(tmp_path, build_activities, "Activities")

    assert ws.max_row == len(scope.frame) + 1
    assert ws.auto_filter.ref is not None
    assert ws.freeze_panes == "A2"


def test_the_activities_sheet_carries_the_derived_columns(tmp_path):
    ws, _ = _build(tmp_path, build_activities, "Activities")
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]

    assert headers == [header for _, header in ACTIVITY_COLUMNS]
    assert "Audience band" in headers
    assert "GEB involved" in headers
    assert "GEB members" in headers


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
