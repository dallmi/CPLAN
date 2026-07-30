"""The quarter / month / ISO-week column grid."""

from datetime import date

from pipeline.report.grid import build_grid


def test_a_full_year_spans_from_its_first_iso_week_to_the_next_years_first():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    assert grid.weeks[0].iso_year == 2025
    assert grid.weeks[0].iso_week == 1
    assert grid.weeks[0].monday == date(2024, 12, 30)
    assert grid.weeks[-1].iso_year == 2026
    assert grid.weeks[-1].iso_week == 1
    assert len(grid.weeks) == 53


def test_the_last_day_of_the_year_has_a_column():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    index = grid.week_index(date(2025, 12, 31))

    assert index == len(grid.weeks) - 1


def test_a_day_outside_the_window_has_no_column():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    assert grid.week_index(date(2024, 6, 1)) is None
    assert grid.week_index(date(2026, 6, 1)) is None


def test_a_week_belongs_to_the_month_of_its_thursday():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))

    # 2025-W01 runs Mon 30 Dec 2024 to Sun 5 Jan 2025; its Thursday is 2 Jan.
    assert grid.month_of(grid.weeks[0]) == (2025, 1)
    # 2026-W01 runs Mon 29 Dec 2025 to Sun 4 Jan 2026; its Thursday is 1 Jan.
    assert grid.month_of(grid.weeks[-1]) == (2026, 1)
    assert grid.quarter_of(grid.weeks[-1]) == (2026, 1)


def test_columns_nest_quarter_then_month_then_its_weeks():
    grid = build_grid(date(2025, 1, 1), date(2025, 3, 31))
    columns = grid.columns()

    assert columns[0].kind == "quarter"
    assert columns[0].level == 0
    assert columns[0].label == "Q1 2025"
    assert columns[1].kind == "month"
    assert columns[1].level == 1
    assert columns[1].label == "Jan 2025"
    assert columns[2].kind == "week"
    assert columns[2].level == 2
    assert columns[2].label == "W01"
    assert columns[2].sublabel == "30 Dec"


def test_every_week_appears_exactly_once_across_the_columns():
    grid = build_grid(date(2025, 1, 1), date(2025, 12, 31))
    week_columns = [c for c in grid.columns() if c.kind == "week"]

    assert len(week_columns) == len(grid.weeks)
    assert len({c.key for c in week_columns}) == len(grid.weeks)


def test_a_single_week_window_produces_one_of_each_column():
    grid = build_grid(date(2025, 3, 3), date(2025, 3, 7))
    kinds = [c.kind for c in grid.columns()]

    assert kinds == ["quarter", "month", "week"]


def test_a_week_whose_thursday_falls_in_the_next_quarter_groups_there():
    grid = build_grid(date(2025, 1, 1), date(2025, 3, 31))
    columns = grid.columns()

    # The last week starts Mon 31 Mar 2025; its Thursday is 3 Apr, so the week
    # belongs to April and Q2 even though the window stops on 31 March.
    quarters = [c.label for c in columns if c.kind == "quarter"]
    months = [c.label for c in columns if c.kind == "month"]

    assert quarters == ["Q1 2025", "Q2 2025"]
    assert months == ["Jan 2025", "Feb 2025", "Mar 2025", "Apr 2025"]
    assert columns[-1].kind == "week"
    assert grid.quarter_of(grid.weeks[-1]) == (2025, 2)
