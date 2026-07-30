"""Synthetic SharePoint-shaped activity exports for the report tests.

Raw source column names and lookup JSON, so the tests exercise the same
transform path the real run does. All content is synthetic and
organisation-neutral: generic division, region and audience values, no personal
names, no production identifiers.
"""

import json
from pathlib import Path

HEADER = [
    "ID", "Tracking ID", "Title", "Activity", "Target audience", "Business Division",
    "Region", "Channel", "Priority", "Strategic Objectives", "Lead", "Lead Team",
    "Start date", "End date", "Created", "Modified", "Communication pack:C",
    "Communication pack", "Campaign", "BOD*GEB", "Audience",
]


def _lookup(*values):
    return json.dumps([{"Id": i + 1, "Value": v} for i, v in enumerate(values)])


def _row(sp_id, tracking_id, name, start, **overrides):
    row = {
        "ID": sp_id, "Tracking ID": tracking_id, "Title": name,
        "Activity": "<p>Synthetic description</p>", "Target audience": "All staff",
        "Business Division": _lookup("Division A"), "Region": _lookup("EMEA"),
        "Channel": _lookup("Email"), "Priority": "2 - label",
        "Strategic Objectives": "Objective", "Lead": "Lead person",
        "Lead Team": "Team", "Start date": start, "End date": start,
        "Created": "2025-01-05", "Modified": "2025-06-01",
        "Communication pack:C": "CP-100", "Communication pack": "Pack one",
        "Campaign": "Campaign one", "BOD*GEB": "", "Audience": "4200",
    }
    row.update(overrides)
    return row


# One row per situation the report has to survive. Kept small and explicit so a
# failing assertion points at a named case rather than at row 37 of a blob.
INTERNAL_ROWS = [
    _row(1, "IC-0001", "Single division Q1", "2025-02-12"),
    _row(2, "IC-0002", "Three divisions is group-wide", "2025-02-13",
         **{"Business Division": _lookup("Division A", "Division B", "Division C")}),
    _row(3, "IC-0003", "Global region is group-wide", "2025-05-07",
         **{"Region": _lookup("Global")}),
    _row(4, "IC-0004", "Two divisions", "2025-08-20",
         **{"Business Division": _lookup("Division A", "Division B")}),
    _row(5, "IC-0005", "Region only", "2025-11-04",
         **{"Business Division": "", "Region": _lookup("APAC")}),
    _row(6, "IC-0006", "Neither dimension", "2025-11-05",
         **{"Business Division": "", "Region": ""}),
    _row(7, "IC-0007", "With senior executives", "2025-03-19",
         **{"BOD*GEB": "<p>An executive</p>", "Audience": "250000"}),
    _row(8, "IC-0008", "Audience as a band label", "2025-06-11",
         **{"Audience": "10–50k"}),
    _row(9, "IC-0009", "No audience value", "2025-06-12", **{"Audience": ""}),
    _row(10, "IC-0010", "No start date", None, **{"Start date": ""}),
    _row(11, "IC-0011", "Outside the window", "2024-06-04"),
    _row(12, "IC-0012", "Incomplete record", "2025-09-24",
         **{"Channel": "", "Lead Team": "", "Communication pack:C": ""}),
    _row(13, "IC-0013", "Last week of the year", "2025-12-31"),
]

# Same tracking ID as IC-0001 with an older Modified: must lose the de-dup.
INTERNAL_ARCHIVE_ROWS = [
    _row(1, "IC-0001", "Stale archived duplicate", "2025-02-12",
         **{"Modified": "2025-01-01"}),
    _row(20, "IC-0020", "Genuinely archived", "2025-04-02"),
]

EXTERNAL_ROWS = [
    _row(30, "EC-0001", "External single division", "2025-02-19",
         **{"Channel": _lookup("Press")}),
    _row(31, "EC-0002", "External group-wide", "2025-07-16",
         **{"Region": _lookup("Worldwide"), "Audience": "150000"}),
]

EXTERNAL_ARCHIVE_ROWS = []

# 13 internal + 1 surviving archive + 2 external, minus the losing duplicate.
FIXTURE_ROW_COUNT = 16


def _write_csv(path, rows):
    lines = [",".join(f'"{h}"' for h in HEADER)]
    for row in rows:
        cells = []
        for header in HEADER:
            value = row.get(header, "")
            text = "" if value is None else str(value)
            cells.append('"' + text.replace('"', '""') + '"')
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_activity_csvs(directory):
    """Write the four activity exports and return the find_input_files mapping.

    Row lists that are empty are skipped entirely: no file is written and no
    key is returned for them. This mirrors `find_input_files`, which globs
    for files that exist on disk — a deployment with no external archive
    export simply has no such file, so the mapping has no `external_archive`
    key. Writing a header-only CSV would model a shape the real discovery
    path never produces. It would also currently crash the ETL: `transform()`
    calls `.dt` on date columns, and a zero-row column stays `object` dtype
    (nothing for `.apply` to infer datetime-ness from), so `.dt` raises. That
    is a real bug in `pipeline/scripts/process_cplan.py`, already reported
    separately — this fixture deliberately does not exercise it.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    sources = {
        "internal": (directory / "InternalCommunicationActivities.csv", INTERNAL_ROWS),
        "internal_archive": (
            directory / "InternalCommunicationActivitiesArchive.csv", INTERNAL_ARCHIVE_ROWS),
        "external": (directory / "ExternalCommunicationActivities.csv", EXTERNAL_ROWS),
        "external_archive": (
            directory / "ExternalCommunicationActivitiesArchive.csv", EXTERNAL_ARCHIVE_ROWS),
    }
    files = {}
    for key, (path, rows) in sources.items():
        if not rows:
            continue
        files[key] = _write_csv(path, rows)
    return files


def load_fixture_scope(directory, config):
    from pipeline.report.data import build_scope
    from pipeline.scripts.process_cplan import load_activities

    return build_scope(load_activities(write_activity_csvs(directory)), config)
