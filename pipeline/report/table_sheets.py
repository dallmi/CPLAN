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
from pipeline.report.data import (
    COMPLETENESS_FIELDS_COMMON,
    COMPLETENESS_FIELDS_INTERNAL,
    EXCLUSION_ORDER,
)
from pipeline.report.derive import (
    GLOBAL_REGION_TOKENS,
    GROUP_WIDE_MIN_DIVISIONS,
    REACH_ORDER,
    priority_rank,
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
    row += 1

    # Its own block, deliberately: the rates above are one per *reported* field
    # (metrics.REPORTED_FIELDS -- a wider list chosen for what a planner wants
    # to see missing), while this median is computed over the fields the entry
    # form requires, split by source type. Two correct numbers over two
    # different denominators sitting in one block read as a contradiction --
    # on the test fixture the block shows bod_geb 93% missing and then 100%
    # median completeness. Naming the denominator here is what makes them
    # reconcilable.
    row = style.write_section_header(ws, row, "PLANNING COMPLETENESS", 4)
    row = style.write_header_row(ws, row, ["Measure", "Value", "", ""])
    row = style.write_data_rows(ws, row, [
        ["Median planning completeness (%)", int(frame["completeness"].median())]])
    common = [name for name in COMPLETENESS_FIELDS_COMMON
              if name in scope.completeness_fields]
    internal_only = [name for name in COMPLETENESS_FIELDS_INTERNAL
                     if name in scope.completeness_fields
                     and name not in COMPLETENESS_FIELDS_COMMON]
    row = style.write_data_rows(ws, row, [
        ["Counted for every activity", ", ".join(common) or "—"],
        ["Counted for internal activities in addition", ", ".join(internal_only) or "—"],
        ["Excluded: not carried by this export",
         ", ".join(scope.skipped_completeness_fields) or "—"],
    ])
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
                    "appears in both rows, so those block totals are distinct counts. "
                    "Multi-value fields are split on commas and semicolons, so a single "
                    "value that legitimately contains one reads as two dimension values."),
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
                                  "value. Internal activities are measured against a longer "
                                  "list than external ones; the Data Quality sheet's PLANNING "
                                  "COMPLETENESS block names both. Fields the CSV export does "
                                  "not carry are excluded from the denominator and listed "
                                  "under FIELDS NOT IN THIS EXPORT at the foot of this sheet. "
                                  "This is a different field set from the per-field rates in "
                                  "that sheet's FIELD COMPLETENESS block, which is why the "
                                  "two can look inconsistent."),
        ("Load figures", "Median activities per week, the peak week and its count, weeks with "
                         "no activity, the longest run of empty weeks and the share falling in "
                         "the five busiest weeks are all computed over the one series of weekly "
                         "counts behind the Calendar sheet: each activity counted once, in the "
                         "ISO week of its start date, across every week column in the window. "
                         "They are written as literals rather than formulas because that series "
                         "is not itself on the Executive Summary sheet. The five-busiest-weeks "
                         "share is those five weeks' counts over the total in scope."),
        ("Quarter delta", "The Δ column on the Mix sheet is an absolute difference of counts "
                          "between two quarters, and its header names which two. It is not "
                          "always the last quarter present: the Thursday rule can leave a "
                          "one-week quarter at the end of the window, and measuring a full "
                          "quarter against that would read as a collapse. The last quarter "
                          "carrying at least four weeks is used instead."),
        ("Packs", "Never a grouping dimension in this report. Source pack identifiers collapse "
                  "large parts of the portfolio into oversized buckets, so a pack-based "
                  "roll-up describes the portfolio rather than a planning unit. Pack coverage "
                  "is measured on the Data Quality sheet instead."),
    )),
)


# A quarter carrying fewer grid weeks than this is a stub, not a quarter the Δ
# column can honestly be measured against. Four weeks is roughly a month --
# short, but enough that a difference against it means something.
MIN_DELTA_QUARTER_WEEKS = 4


def delta_quarters(quarters, grid):
    """The two quarters the Δ column compares: the first, and the last full one.

    The naive choice -- first versus last quarter present -- is wrong for the
    report's own default window. A week belongs to the month containing its
    Thursday (ISO 8601, see the Glossary's "Week to month"), so a full-year
    window spans FIVE quarters, not four: 29 Dec - 4 Jan has its Thursday in
    January, which puts one single week into the following year's Q1. Measuring
    a full quarter against that one-week stub makes every row of every crosstab
    read strongly negative -- roughly 2% of a year against 25% of it -- and a
    planner reads that as the mix having collapsed.

    So: the last quarter carrying a reasonably full complement of weeks. If
    none qualifies, or the only qualifying one is the quarter we are comparing
    *from*, fall back to the last quarter present -- for a genuinely short
    window comparing the two ends is still the most informative thing there
    is, and the header names whichever two quarters it used either way.
    """
    weeks_per_quarter = {}
    for week in grid.weeks:
        quarter = grid.quarter_of(week)
        weeks_per_quarter[quarter] = weeks_per_quarter.get(quarter, 0) + 1

    first = quarters[0]
    full = [q for q in quarters[1:]
            if weeks_per_quarter.get(q, 0) >= MIN_DELTA_QUARTER_WEEKS]
    return first, (full[-1] if full else quarters[-1])


def _crosstab_block(ws, row, quarters, frame, title, field, delta=None, sort_key=None):
    """One label x quarter table with a Total and a quarter-to-quarter delta.

    `delta` names the two quarters the Δ column compares (see
    `delta_quarters`); without it the block compares the first and last
    quarter present. `sort_key` orders the label rows -- plain alphabetical
    by default, which is wrong for priority and right for everything else.

    Rows overlap for multi-valued fields (channel, division): an activity
    naming two channels counts in both of that field's rows. No TOTAL row is
    written across the label rows for the same reason the Audience sheet's
    division block omits one -- a vertical SUM would print a number larger
    than the portfolio, as if it were a true total.
    """
    if not quarters:
        style.write_section_header(ws, row, f"{title} — no data", 3)
        return row + 2

    delta_from, delta_to = delta if delta else (quarters[0], quarters[-1])
    delta_header = f"Δ {_quarter_label(delta_to)} − {_quarter_label(delta_from)}"
    headers = ["Value"] + [_quarter_label(q) for q in quarters] + ["Total", delta_header]
    total_col = len(headers) - 1

    row = style.write_section_header(ws, row, title, len(headers))
    row = style.write_header_row(ws, row, headers)

    values = {}
    for index, activity in frame.iterrows():
        for name in (split_multi(activity.get(field)) or ["Not specified"]):
            values.setdefault(name, []).append(index)

    first_letter = get_column_letter(2)
    last_letter = get_column_letter(total_col - 1)
    from_letter = get_column_letter(2 + quarters.index(delta_from))
    to_letter = get_column_letter(2 + quarters.index(delta_to))
    for name in sorted(values, key=sort_key):
        subset = frame.loc[values[name]]
        counts = [int((subset["_quarter"] == q).sum()) for q in quarters]
        style.write_data_rows(ws, row, [[name] + counts])
        span = f"{first_letter}{row}:{last_letter}{row}"
        style.write_formula(ws, row, total_col, f"=SUM({span})", fmt=style.NUM_FMT_INT)
        style.write_formula(ws, row, total_col + 1, f"={to_letter}{row}-{from_letter}{row}",
                            fmt=style.NUM_FMT_INT)
        row += 1
    return row + 1


def _priority_sort_key(name):
    """Most urgent first. Alphabetical order is actively misleading here.

    Two priority vocabularies are live at once -- the source system's numbered
    labels ("1 - ...", where 1 is most urgent) and the studio's words -- so an
    alphabetical sort interleaves them and puts Low above Medium. Matching only
    the words has already produced a metric reading zero against thousands of
    records (see the Mix sheet's note in the design document), which is why
    this goes through the same rank function the studio uses. The name is the
    tiebreaker so the order is stable within a rank.
    """
    return (-priority_rank(name), name)


def build_mix(wb, scope, config):
    """Channel, priority and internal/external mix over the quarters in scope,
    plus lead time by division -- how far ahead planning actually happens.
    """
    ws = wb.create_sheet("Mix & Lead Time")
    frame = scope.frame
    if frame.empty:
        style.note_missing(ws, "No activities in scope for the configured criteria")
        style.finalize_sheet(ws, freeze="A2")
        return

    quarters = sorted({q for q in frame["_quarter"] if q is not None})
    delta = delta_quarters(quarters, scope.grid) if quarters else None

    row = _crosstab_block(ws, 1, quarters, frame, "CHANNEL BY QUARTER", "channel",
                          delta=delta)
    row = _crosstab_block(ws, row, quarters, frame, "PRIORITY BY QUARTER", "priority",
                          delta=delta, sort_key=_priority_sort_key)
    row = _crosstab_block(ws, row, quarters, frame,
                          "INTERNAL VS EXTERNAL BY QUARTER", "source_type",
                          delta=delta)

    row = style.write_section_header(ws, row, "LEAD TIME BY DIVISION", 6)
    row = style.write_header_row(ws, row, [
        "Division", "Measurable", "Median days",
        f"Under {SHORT_NOTICE_DAYS} days", "Share short notice", "Min / max days"])
    divisions = {}
    for index, activity in frame.iterrows():
        for name in (split_multi(activity.get("business_division")) or ["Not specified"]):
            divisions.setdefault(name, []).append(index)
    for name in sorted(divisions):
        stats = metrics.lead_time_stats(frame.loc[divisions[name]])
        span = "—" if stats["min_days"] is None else f"{stats['min_days']} / {stats['max_days']}"
        style.write_data_rows(ws, row, [[
            name, stats["counted"],
            stats["median_days"] if stats["median_days"] is not None else "—",
            stats["short_notice"], None, span]])
        style.write_formula(ws, row, 5, f"=IF(B{row}=0,0,D{row}/B{row})",
                            fmt=style.NUM_FMT_PCT)
        row += 1

    style.finalize_sheet(ws, freeze="B3", widths={"A": 30})


ACTIVITY_COLUMNS = (
    ("tracking_id", "Tracking ID"),
    ("activity_name", "Activity"),
    ("source_type", "Type"),
    ("channel", "Channel"),
    ("start_date", "Start"),
    ("end_date", "End"),
    ("_iso_week", "ISO week"),
    ("_quarter_label", "Quarter"),
    ("priority", "Priority"),
    ("lead", "Lead"),
    ("lead_team", "Lead team"),
    ("target_audience", "Target audience"),
    ("audience_band", "Audience band"),
    ("business_division", "Divisions"),
    ("region", "Regions"),
    ("reach", "Reach"),
    ("_executives", "Senior executives"),
    ("communication_pack_cpid", "Pack ID"),
    ("campaign", "Campaign"),
    ("strategic_objectives", "Communications pillars"),
    ("completeness", "Completeness %"),
    ("lead_time_days", "Lead time (days)"),
    ("is_archived", "Archived"),
)


def build_activities(wb, scope, config):
    """Every in-scope activity, one row each, raw fields and derived ones
    side by side -- the audit trail every other sheet's figures trace back to.
    """
    ws = wb.create_sheet("Activities")
    frame = scope.frame
    style.write_header_row(ws, 1, [header for _, header in ACTIVITY_COLUMNS])
    if frame.empty:
        style.finalize_sheet(ws, freeze="A2")
        return

    rows = []
    for _, activity in frame.iterrows():
        index = activity["week_index"]
        week = scope.grid.weeks[int(index)] if index == index and index is not None else None
        quarter = activity["_quarter"]
        values = []
        for field, _ in ACTIVITY_COLUMNS:
            if field == "_iso_week":
                values.append(f"{week.iso_year}-{week.label}" if week else "")
            elif field == "_quarter_label":
                values.append(_quarter_label(quarter) if quarter else "")
            elif field == "_executives":
                values.append("Yes" if activity["has_executives"] else "No")
            elif field in ("start_date", "end_date"):
                value = activity.get(field)
                values.append(value.date() if hasattr(value, "date") and value == value
                              else None)
            elif field == "lead_time_days":
                value = activity.get(field)
                values.append(int(value) if value == value and value is not None else None)
            else:
                value = activity.get(field)
                values.append("" if value is None or value != value else value)
        rows.append(values)

    date_columns = {
        i + 1: style.NUM_FMT_DATE
        for i, (field, _) in enumerate(ACTIVITY_COLUMNS)
        if field in ("start_date", "end_date")
    }
    style.write_data_rows(ws, 2, rows, fmt_map=date_columns)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(ACTIVITY_COLUMNS))}{len(rows) + 1}"
    style.finalize_sheet(ws, freeze="A2")


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
