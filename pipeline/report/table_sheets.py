"""The flat sheets: summary, data quality, audience, mix, activities, glossary.

The calendar lives in its own module; this file holds the six sheets that are
label/value lists and tables. They share the style primitives, so adding a block
is a handful of lines rather than a new layout.
"""

from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from pipeline.report import metrics, style
from pipeline.report.config import (
    AUDIENCE_BANDS,
    BAND_UNKNOWN,
    LARGE_AUDIENCE_BANDS,
    SHORT_NOTICE_DAYS,
)
from pipeline.report.data import EXCLUSION_ORDER
from pipeline.report.derive import (
    GLOBAL_REGION_TOKENS,
    GROUP_WIDE_MIN_DIVISIONS,
    REACH_ORDER,
    split_multi,
)


def _share_label(total_row, value_row, text):
    """The share rides in the label so the value column stays a column of counts."""
    return f'=TEXT(IF(B${total_row}=0,0,B{value_row}/B${total_row}),"0%") & "  {text}"'


def _write_share_row(ws, row, total_row, text, count):
    """A count with its share riding in the label, as a sub (indented/italic) row."""
    ws.cell(row=row, column=1, value=_share_label(total_row, row, text))
    style.write_kpi_row(ws, row, None, count, sub=True)


def build_executive_summary(wb, scope, config):
    ws = wb.create_sheet("Executive Summary")
    ws.sheet_properties.tabColor = style.BRONZE_I
    frame = scope.frame
    row = 1

    row = style.write_section_header(ws, row, "REPORT", 2)
    for label, value in config.describe():
        row = style.write_kpi_row(ws, row, label, value)
    row = style.write_kpi_row(ws, row, "Weeks covered", len(scope.grid.weeks))
    for key, name in scope.source_files:
        row = style.write_kpi_row(ws, row, f"Source: {key}", name)
    row = style.write_kpi_row(ws, row, "Rows read", scope.rows_read)
    for reason in EXCLUSION_ORDER:
        row = style.write_kpi_row(ws, row, f"Excluded: {reason}", scope.excluded[reason])
    row = style.write_kpi_row(ws, row, "Activities in scope", len(frame))
    row += 1

    row = style.write_section_header(ws, row, "VOLUME", 2)
    total_row = row
    row = style.write_kpi_row(ws, row, "Activities in scope", len(frame))
    for source_type in ("internal", "external"):
        count = int((frame.get("source_type") == source_type).sum()) if len(frame) else 0
        _write_share_row(ws, row, total_row, source_type.title(), count)
        row += 1
    for bucket in REACH_ORDER:
        count = int((frame.get("reach") == bucket).sum()) if len(frame) else 0
        _write_share_row(ws, row, total_row, bucket, count)
        row += 1
    row += 1

    stats = metrics.load_stats(scope)
    row = style.write_section_header(ws, row, "LOAD", 2)
    row = style.write_kpi_row(ws, row, "Median activities per week",
                              stats["median_per_week"], fmt=style.NUM_FMT_RATIO)
    row = style.write_kpi_row(ws, row, "Peak week", stats["peak_week_label"])
    row = style.write_kpi_row(ws, row, "Activities in the peak week", stats["peak_week_count"])
    row = style.write_kpi_row(ws, row, "Weeks with no activity", stats["zero_weeks"])
    row = style.write_kpi_row(ws, row, "Longest run of empty weeks", stats["longest_zero_run"])
    row = style.write_kpi_row(ws, row, "Share in the five busiest weeks",
                              stats["top5_share"], fmt=style.NUM_FMT_PCT)
    row += 1

    row = style.write_section_header(ws, row, "LEADERSHIP & AUDIENCE", 2)
    exec_total = row
    executives = int(frame["has_executives"].sum()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "With senior-executive involvement", executives)
    large = int(frame["audience_band"].isin(LARGE_AUDIENCE_BANDS).sum()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "Large audience (top two bands)", large)
    unknown = int((frame["audience_band"] == BAND_UNKNOWN).sum()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "Audience band unknown", unknown)
    style.write_formula(ws, exec_total, 3,
                        f"=IF(B${total_row}=0,0,B{exec_total}/B${total_row})",
                        fmt=style.NUM_FMT_PCT)
    row += 1

    lead = metrics.lead_time_stats(frame) if len(frame) else {
        "counted": 0, "median_days": None, "short_notice": 0}
    row = style.write_section_header(ws, row, "PLANNING DISCIPLINE", 2)
    row = style.write_kpi_row(ws, row, "Median lead time (days)",
                              lead["median_days"] if lead["median_days"] is not None else "—")
    row = style.write_kpi_row(ws, row,
                              f"Planned at under {SHORT_NOTICE_DAYS} days' notice",
                              lead["short_notice"])
    row = style.write_kpi_row(ws, row, "Lead time not measurable",
                              len(frame) - lead["counted"])
    row += 1

    packs = metrics.pack_stats(frame) if len(frame) else {"without_pack": 0}
    row = style.write_section_header(ws, row, "DATA QUALITY", 2)
    median_completeness = int(frame["completeness"].median()) if len(frame) else 0
    row = style.write_kpi_row(ws, row, "Median planning completeness (%)", median_completeness)
    row = style.write_kpi_row(ws, row, "Without a pack link", packs["without_pack"])

    style.finalize_sheet(ws, freeze="A2", widths={"A": 44, "B": 24, "C": 12})


def build_data_quality(wb, scope, config):
    """The pack problem, quantified: bucket sizes a planner can act on."""
    ws = wb.create_sheet("Data Quality")
    frame = scope.frame
    if frame.empty:
        style.note_missing(ws, "No activities in scope for the configured criteria")
        style.finalize_sheet(ws, freeze="A2")
        return

    row = style.write_section_header(ws, 1, "FIELD COMPLETENESS", 4)
    row = style.write_header_row(ws, row, ["Field", "Filled", "Missing", "% missing"])
    for name, filled, missing in metrics.field_completeness(scope):
        style.write_data_rows(ws, row, [[name, filled, missing]])
        style.write_formula(ws, row, 4, f"=IF(B{row}+C{row}=0,0,C{row}/(B{row}+C{row}))",
                            fmt=style.NUM_FMT_PCT)
        row += 1
    row = style.write_data_rows(ws, row, [["Median completeness (%)",
                                           int(frame["completeness"].median())]])
    row += 1

    packs = metrics.pack_stats(frame)
    row = style.write_section_header(ws, row, "PACK COVERAGE", 4)
    row = style.write_header_row(ws, row, ["Measure", "Count", "", ""])
    pack_rows = [
        ("Activities with a pack link", packs["with_pack"]),
        ("Activities without a pack link", packs["without_pack"]),
        ("Distinct packs", packs["packs"]),
        ("Packs holding exactly one activity", packs["singleton_packs"]),
        ("Packs holding 2 to 10", packs["small_packs"]),
        ("Packs holding 11 to 50", packs["medium_packs"]),
        ("Packs holding more than 50", packs["oversized_packs"]),
        ("Largest pack", packs["largest_pack"]),
    ]
    row = style.write_data_rows(ws, row, [[label, value] for label, value in pack_rows])
    row += 1

    row = style.write_section_header(ws, row, "RECORD ANOMALIES", 4)
    row = style.write_header_row(ws, row, ["Anomaly", "Count", "", ""])
    row = style.write_data_rows(ws, row, [[label, count] for label, count in
                                          metrics.anomalies(frame, scope.duplicates_removed)])

    style.finalize_sheet(ws, freeze="A2", widths={"A": 40, "B": 14, "C": 14, "D": 14})


def _quarter_label(quarter):
    return f"Q{quarter[1]} {quarter[0]}"


def build_audience(wb, scope, config):
    """Audience size and senior-executive involvement -- two of the three
    criteria the whole report is built around.

    The most interesting figure here is the last one: executive involvement
    as a share of *that division's own volume*, not of the portfolio. A
    large division with many such activities may still be using that access
    less than a small one -- the portfolio-wide share would hide that.
    """
    ws = wb.create_sheet("Audience & Executives")
    frame = scope.frame
    if frame.empty or "audience_band" not in frame.columns:
        style.note_missing(ws, "No audience data available (audience column missing)")
        style.finalize_sheet(ws, freeze="A2")
        return

    quarters = sorted({q for q in frame["_quarter"] if q is not None})
    headers = ["Audience band"] + [_quarter_label(q) for q in quarters] + ["Total", "% of total"]
    total_col = len(headers) - 1
    share_col = len(headers)

    row = style.write_section_header(ws, 1, "AUDIENCE BAND BY QUARTER", len(headers))
    row = style.write_header_row(ws, row, headers)
    first_row = row
    for band in list(AUDIENCE_BANDS) + [BAND_UNKNOWN]:
        counts = [int(((frame["audience_band"] == band) & (frame["_quarter"] == q)).sum())
                  for q in quarters]
        style.write_data_rows(ws, row, [[band] + counts])
        span = f"{get_column_letter(2)}{row}:{get_column_letter(total_col - 1)}{row}"
        style.write_formula(ws, row, total_col, f"=SUM({span})", fmt=style.NUM_FMT_INT)
        row += 1
    total_row = row
    for col in range(2, total_col + 1):
        letter = get_column_letter(col)
        style.write_formula(ws, total_row, col, f"=SUM({letter}{first_row}:{letter}{row - 1})",
                            fmt=style.NUM_FMT_INT, fill=style.TOTAL_FILL, bold=True)
    ws.cell(row=total_row, column=1, value="TOTAL").font = style.TOTAL_FONT
    total_letter = get_column_letter(total_col)
    for value_row in range(first_row, total_row):
        style.write_formula(
            ws, value_row, share_col,
            f"=IF({total_letter}${total_row}=0,0,"
            f"{total_letter}{value_row}/{total_letter}${total_row})",
            fmt=style.NUM_FMT_PCT)
    style.write_formula(ws, total_row, share_col, "=1", fmt=style.NUM_FMT_PCT,
                        fill=style.TOTAL_FILL, bold=True)
    row = total_row + 2

    row = style.write_section_header(ws, row, "LARGE AUDIENCE BY MONTH", 4)
    row = style.write_header_row(ws, row, ["Month", "Large audience", "All activities",
                                           "Share of the month"])

    def _week_month(index):
        # week_index is None for rows without a placeable week; on the
        # in-scope frame that never happens (every surviving row's start day
        # falls inside the grid), but a stray NaN from a mixed-dtype column
        # is guarded against rather than assumed away.
        if index is None or index != index:
            return None
        return scope.grid.month_of(scope.grid.weeks[int(index)])

    # Computed once per row up front, not once per row per month: the
    # reference version recomputed `month_of` inside an `.apply()` lambda for
    # every month, which is O(rows x months) for no benefit.
    week_months = frame["week_index"].map(_week_month)
    months = sorted({m for m in week_months if m is not None})
    for month in months:
        in_month = week_months == month
        large = int((in_month & frame["audience_band"].isin(LARGE_AUDIENCE_BANDS)).sum())
        style.write_data_rows(ws, row, [
            [f"{month[0]}-{month[1]:02d}", large, int(in_month.sum())]])
        style.write_formula(ws, row, 4, f"=IF(C{row}=0,0,B{row}/C{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1
    row += 1

    row = style.write_section_header(ws, row, "SENIOR EXECUTIVES BY QUARTER", 4)
    row = style.write_header_row(ws, row, ["Quarter", "With executives", "All activities",
                                           "Share of the quarter"])
    for quarter in quarters:
        in_quarter = frame["_quarter"] == quarter
        style.write_data_rows(ws, row, [
            [_quarter_label(quarter),
             int((in_quarter & frame["has_executives"]).sum()),
             int(in_quarter.sum())]])
        style.write_formula(ws, row, 4, f"=IF(C{row}=0,0,B{row}/C{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1
    row += 1

    row = style.write_section_header(ws, row, "SENIOR EXECUTIVES BY DIVISION", 4)
    row = style.write_header_row(ws, row, ["Division", "With executives",
                                           "All activities", "Share of the division"])
    divisions = {}
    for index, activity in frame.iterrows():
        for name in (split_multi(activity.get("business_division")) or ["Not specified"]):
            divisions.setdefault(name, []).append(index)
    for name in sorted(divisions):
        subset = frame.loc[divisions[name]]
        style.write_data_rows(ws, row, [
            [name, int(subset["has_executives"].sum()), len(subset)]])
        style.write_formula(ws, row, 4, f"=IF(C{row}=0,0,B{row}/C{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1
    # No TOTAL row here: an activity naming two divisions is counted in both
    # rows (see GLOSSARY_SECTIONS' "Overlap" entry), so a vertical SUM would
    # print a number larger than the portfolio, as if it were a true total.

    style.finalize_sheet(ws, freeze="B3", widths={"A": 26})


GLOSSARY_SECTIONS = (
    ("SCOPE", (
        ("In scope", "Activities whose start date falls inside the configured window and "
                     "that pass the senior-executive and audience-band criteria. All three "
                     "are hard filters: a row that fails any of them is absent from every sheet."),
        ("Source", "The SharePoint CSV exports in the OneDrive sync folder, internal and "
                   "external, active and archive lists merged and de-duplicated by tracking ID."),
        ("Not included", "Activities created only in the planning studio. They live in the "
                         "local database and are never written back to the source system, so "
                         "they are invisible to this report."),
    )),
    ("TIME", (
        ("Counting rule", "Each activity is counted once, in the ISO week of its start date. "
                          "Nothing is spread across an activity's runtime: a figure that is "
                          "also a duration cannot be summed."),
        ("Week to month", "A week belongs to the month containing its Thursday (ISO 8601). "
                          "A full-year window therefore carries a thirteenth month column for "
                          "the last days of December, which belong to the next year's week 1."),
        ("Aggregation", "Month, quarter and total cells are SUM formulas over the cells they "
                        "aggregate, so the grid cannot contradict its own totals."),
    )),
    ("DIMENSIONS", (
        ("Group-wide", f"Names {GROUP_WIDE_MIN_DIVISIONS} or more business divisions, or a "
                       f"global region ({', '.join(sorted(GLOBAL_REGION_TOKENS))})."),
        ("Multi-division", "Names two business divisions."),
        ("Single division", "Names exactly one business division."),
        ("Regional only", "Names no division but at least one region."),
        ("Unclassified", "Names neither a division nor a region. Kept visible rather than "
                         "folded into a neighbouring bucket."),
        ("Overlap", "The reach buckets partition the portfolio and sum to the total. The "
                    "division and region blocks do not: an activity naming two divisions "
                    "appears in both rows, so those block totals are distinct counts."),
    )),
    ("MEASURES", (
        ("Audience band", "Mapped from the source audience field, which carries raw counts in "
                          "some exports and band labels in others. Whether that field records "
                          "the estimated audience size is an assumption still to be verified "
                          "against the source system."),
        ("Senior executives", "The source system's executive-involvement field carries a "
                              "value after HTML is stripped."),
        ("Lead time", "Days between the record's creation date and its start date. Rows "
                      "missing either date are not counted."),
        ("Planning completeness", "Share of the fields the entry form requires that carry a "
                                  "value. Fields the CSV export does not carry are excluded "
                                  "from the denominator and listed on the Data Quality sheet."),
        ("Packs", "Never a grouping dimension in this report. Source pack identifiers collapse "
                  "large parts of the portfolio into oversized buckets, so a pack-based "
                  "roll-up describes the portfolio rather than a planning unit. Pack coverage "
                  "is measured on the Data Quality sheet instead."),
    )),
)


def build_glossary(wb, scope, config):
    ws = wb.create_sheet("Glossary")
    ws.sheet_view.showGridLines = False
    row = 1
    for title, terms in GLOSSARY_SECTIONS:
        row = style.write_section_header(ws, row, title, 2)
        for term, definition in terms:
            style.write_kpi_row(ws, row, term, None)
            cell = ws.cell(row=row, column=2, value=definition)
            cell.font = style.BODY_FONT
            cell.alignment = Alignment(
                horizontal=cell.alignment.horizontal, wrap_text=True, vertical="top")
            row += 1
        row += 1

    if scope.skipped_completeness_fields:
        row = style.write_section_header(ws, row, "FIELDS NOT IN THIS EXPORT", 2)
        for name in scope.skipped_completeness_fields:
            row = style.write_kpi_row(
                ws, row, name,
                "Required by the entry form but not carried by the CSV export; "
                "excluded from the completeness denominator.")

    style.finalize_sheet(ws, freeze=None, widths={"A": 28, "B": 90})
