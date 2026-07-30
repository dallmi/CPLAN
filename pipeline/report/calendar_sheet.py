"""The calendar matrix.

Rows are planning dimensions, columns are quarters that expand into months that
expand into ISO weeks. Both axes are Excel outlines, so the sheet opens as a
handful of quarter columns against a handful of block rows and expands on click.

Two rules keep the arithmetic honest:

* Horizontal aggregation is ALWAYS a formula -- a month is the sum of its week
  cells, a quarter the sum of its months, the total the sum of its quarters. The
  sheet cannot contradict itself and the reader can click any figure. This holds
  for every row, including block headers: week cells are always literal counts,
  never a formula, in every row of the sheet.
* Vertical aggregation is a formula only where it is valid, and only in the
  Total (summary) column. The reach buckets partition the portfolio, so that
  block header's Total cell carries a genuine SUM down the member rows -- a
  second, independently auditable route to the same number as the horizontal
  route. The division and region blocks overlap -- an activity naming two
  divisions appears twice -- so their headers' Total cell carries a distinct
  count computed here, and say so in the label. A SUM there would print a bold
  number larger than the portfolio.
"""

from openpyxl.formatting.rule import DataBarRule
from openpyxl.utils import get_column_letter

from pipeline.report import style
from pipeline.report.derive import REACH_ORDER, split_multi

SHEET_NAME = "Calendar"
LABEL_COL = 1
TOTAL_COL = 2
FIRST_GRID_COL = 3
FIRST_DATA_ROW = 3

NOT_SPECIFIED = "Not specified"

FIELD_TITLES = {
    "business_division": "BUSINESS DIVISION",
    "region": "REGION",
}


def _column_positions(columns):
    """Map each grid column to its sheet column index, and group the children."""
    positions = {}
    for offset, column in enumerate(columns):
        positions[(column.kind, column.key)] = FIRST_GRID_COL + offset
    return positions


def _children(columns, grid):
    """For each month column, its week columns; for each quarter, its months."""
    month_weeks = {}
    quarter_months = {}
    current_quarter = None
    current_month = None
    for column in columns:
        if column.kind == "quarter":
            current_quarter = column.key
            quarter_months.setdefault(current_quarter, [])
        elif column.kind == "month":
            current_month = column.key
            month_weeks.setdefault(current_month, [])
            quarter_months[current_quarter].append(current_month)
        else:
            month_weeks[current_month].append(column.key)
    return month_weeks, quarter_months


def _write_grid_row(ws, row, counts, columns, positions, month_weeks, quarter_months,
                    bold=False):
    """Literal week counts, SUM formulas everywhere else (month, quarter, Total).

    This is the ONLY way grid cells are populated -- every row in the sheet,
    including block header rows, gets its week/month/quarter/Total cells this
    way. A block header's Total cell may be overwritten afterwards (see
    `_finish_reach_header` and `_finish_distinct_count_header`), but its
    week/month/quarter cells always come from here, so the horizontal identity
    (month = SUM of its weeks, quarter = SUM of its months) never breaks.
    """
    fill = style.TOTAL_FILL if bold else None
    for column in columns:
        col = positions[(column.kind, column.key)]
        if column.kind == "week":
            value = counts.get(column.key, 0)
            cell = ws.cell(row=row, column=col, value=value or None)
            cell.border = style.THIN_BORDER
            if value:
                cell.number_format = style.NUM_FMT_INT
            if bold:
                cell.font = style.TOTAL_FONT
                cell.fill = style.TOTAL_FILL
            continue

        if column.kind == "month":
            child_keys = [("week", key) for key in month_weeks[column.key]]
        else:
            child_keys = [("month", key) for key in quarter_months[column.key]]
        letters = [get_column_letter(positions[key]) for key in child_keys]
        formula = "=SUM(" + ",".join(f"{letter}{row}" for letter in letters) + ")"
        style.write_formula(ws, row, col, formula, fmt=style.NUM_FMT_INT,
                            fill=fill, bold=bold)

    quarter_letters = [
        get_column_letter(positions[("quarter", column.key)])
        for column in columns if column.kind == "quarter"
    ]
    total_formula = "=SUM(" + ",".join(f"{letter}{row}" for letter in quarter_letters) + ")"
    style.write_formula(ws, row, TOTAL_COL, total_formula, fmt=style.NUM_FMT_INT,
                        fill=fill, bold=bold)


def _counts(frame, grid):
    """Week key -> number of activities starting in that week."""
    counts = {}
    for index in frame["week_index"]:
        if index is None or (isinstance(index, float) and index != index):
            continue
        key = grid.weeks[int(index)].key
        counts[key] = counts.get(key, 0) + 1
    return counts


def _label_cell(ws, row, text, level, bold=False, hidden=False):
    cell = ws.cell(row=row, column=LABEL_COL, value=text)
    cell.border = style.THIN_BORDER
    if bold:
        cell.font = style.TOTAL_FONT
        cell.fill = style.TOTAL_FILL
    ws.row_dimensions[row].outline_level = level
    if hidden:
        ws.row_dimensions[row].hidden = True


def build_calendar(wb, scope, config):
    ws = wb.create_sheet(SHEET_NAME)
    grid = scope.grid
    columns = grid.columns()
    positions = _column_positions(columns)
    month_weeks, quarter_months = _children(columns, grid)

    ws.sheet_properties.outlinePr.summaryRight = False
    ws.sheet_properties.outlinePr.summaryBelow = False

    # --- header -------------------------------------------------------------
    ws.merge_cells(start_row=1, start_column=LABEL_COL, end_row=2, end_column=LABEL_COL)
    ws.merge_cells(start_row=1, start_column=TOTAL_COL, end_row=2, end_column=TOTAL_COL)
    style.write_header_row(ws, 1, ["Scope / activity", "Total"])
    for column in columns:
        col = positions[(column.kind, column.key)]
        style.write_header_row(ws, 1, [column.label], col_start=col)
        style.write_header_row(ws, 2, [column.sublabel], col_start=col)
        letter = get_column_letter(col)
        ws.column_dimensions[letter].outline_level = column.level
        ws.column_dimensions[letter].hidden = column.level > 0
        ws.column_dimensions[letter].width = 11 if column.kind == "week" else 13

    if scope.frame.empty:
        style.note_missing(ws, "No activities in scope for the configured criteria")
        style.finalize_sheet(ws, freeze="C3", widths={"A": 52, "B": 12})
        return

    row = FIRST_DATA_ROW
    bar_ranges = []

    # --- all activities -----------------------------------------------------
    _label_cell(ws, row, "ALL ACTIVITIES", level=0, bold=True)
    _write_grid_row(ws, row, _counts(scope.frame, grid), columns, positions,
                    month_weeks, quarter_months, bold=True)
    row += 1

    def write_value_row(label, subset, level, hidden):
        nonlocal row
        _label_cell(ws, row, label, level=level, hidden=hidden)
        _write_grid_row(ws, row, _counts(subset, grid), columns, positions,
                        month_weeks, quarter_months)
        value_row = row
        row += 1
        if config.detail_rows:
            ordered = subset.sort_values("start_day", kind="stable")
            for _, activity in ordered.iterrows():
                _label_cell(ws, row, f"  {activity.get('activity_name') or 'Untitled'}",
                            level=level + 1, hidden=True)
                week_key = grid.weeks[int(activity["week_index"])].key
                _write_grid_row(ws, row, {week_key: 1}, columns, positions,
                                month_weeks, quarter_months)
                row += 1
        return value_row

    # --- reach: a partition, so its Total is a genuine SUM down the column --
    _label_cell(ws, row, "BY REACH", level=0, bold=True)
    header_row = row
    row += 1
    member_rows = []
    for bucket in REACH_ORDER:
        subset = scope.frame[scope.frame["reach"] == bucket]
        if subset.empty:
            continue
        member_rows.append(write_value_row(bucket, subset, level=1, hidden=True))
    # Week/month/quarter cells stay the normal, honest way: literal weekly
    # counts over the whole (partitioned) scope, horizontal SUMs above them --
    # identical in shape to the ALL ACTIVITIES row, since a true partition's
    # per-week total is the same number either way. Only the Total (B) column
    # is deliberately written as a second, independent formula that sums the
    # member rows vertically, so a reader can audit that the reach buckets
    # really do add back up to the portfolio.
    _write_grid_row(ws, header_row, _counts(scope.frame, grid), columns, positions,
                    month_weeks, quarter_months, bold=True)
    _finish_reach_header(ws, header_row, member_rows)
    bar_ranges.append(member_rows)

    # --- breakdown fields: overlapping, so a distinct count -----------------
    for field in config.breakdown_fields:
        if field not in scope.frame.columns:
            continue
        title = f"BY {FIELD_TITLES.get(field, field.upper())} — multiple values possible"
        _label_cell(ws, row, title, level=0, bold=True)
        header_row = row
        row += 1
        values = {}
        for _, activity in scope.frame.iterrows():
            names = split_multi(activity.get(field)) or [NOT_SPECIFIED]
            for name in names:
                values.setdefault(name, []).append(activity.name)
        member_rows = []
        for name in sorted(values, key=lambda n: (n == NOT_SPECIFIED, n)):
            subset = scope.frame.loc[values[name]]
            member_rows.append(write_value_row(name, subset, level=1, hidden=True))
        # Week/month/quarter cells: the same true, non-overlapping distinct
        # count as ALL ACTIVITIES (an activity tagged with two divisions is
        # still counted once here). Only the Total column is overwritten with
        # a literal below -- never a SUM -- because summing the member rows
        # vertically would double-count activities that appear in more than
        # one division/region.
        _write_grid_row(ws, header_row, _counts(scope.frame, grid), columns, positions,
                        month_weeks, quarter_months, bold=True)
        _finish_distinct_count_header(ws, header_row, len(scope.frame))
        bar_ranges.append(member_rows)

    for member_rows in bar_ranges:
        if not member_rows:
            continue
        sqref = " ".join(f"B{r}" for r in member_rows)
        ws.conditional_formatting.add(sqref, DataBarRule(
            start_type="num", start_value=0, end_type="max",
            color=style.GRAY_IV, showValue=True))

    style.finalize_sheet(ws, freeze="C3", widths={"A": 52, "B": 12})


def _finish_reach_header(ws, header_row, member_rows):
    """Overwrite the Total cell with a genuine SUM down the member rows.

    Valid only for a partition: the reach block. Every activity lands in
    exactly one reach bucket, so summing the member rows' Total column gives
    back the same number as the horizontal route (summing this row's own
    quarters) -- the reader can click either path.
    """
    formula = "=SUM(" + ",".join(f"B{r}" for r in member_rows) + ")" \
        if member_rows else "=0"
    style.write_formula(ws, header_row, TOTAL_COL, formula, fmt=style.NUM_FMT_INT,
                        fill=style.TOTAL_FILL, bold=True)


def _finish_distinct_count_header(ws, header_row, total):
    """Overwrite the Total cell with a literal, never a SUM.

    Valid only where members overlap: the division and region blocks. An
    activity naming two divisions appears in two member rows, so a vertical
    SUM here would print a bold number larger than the portfolio. The true
    count is computed in Python instead and written as a plain literal.
    """
    cell = ws.cell(row=header_row, column=TOTAL_COL, value=total)
    cell.font = style.TOTAL_FONT
    cell.fill = style.TOTAL_FILL
    cell.number_format = style.NUM_FMT_INT
    cell.border = style.THIN_BORDER
