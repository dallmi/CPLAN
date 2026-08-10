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
    "Communication pack", "Campaign", "BOD*GEB", "Audience", "Time zone",
    # The source misspells "senior", and the two lists name it differently.
    "Other seinor executives",
]

# The size column exists in the internal exports only -- the external form has
# no "Estimated audience size" field at all. Modelling that here rather than
# giving every file the same header is what exercises `data._column`'s
# missing-column path, and it is why external rows band as Unknown.
INTERNAL_HEADER = HEADER + ["Estimated audience size"]
EXTERNAL_HEADER = HEADER


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
        "Campaign": "Campaign one", "BOD*GEB": "", "Time zone": "Europe/Zurich",
        "Other seinor executives": "",
        # Two different source fields, as the real export has them: "Audience"
        # is not a size (it reads "external" on every external row), the band
        # lives in its own column.
        "Audience": "internal", "Estimated audience size": "4200",
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
         **{"Business Division": "", "Region": _lookup("APAC:Japan")}),
    _row(6, "IC-0006", "Neither dimension", "2025-11-05",
         **{"Business Division": "", "Region": ""}),
    _row(7, "IC-0007", "With a GEB/GEB-1 person", "2025-03-19",
         **{"BOD*GEB": "<p>Example, Ada</p>", "Estimated audience size": "250000"}),
    _row(17, "IC-0017", "With other senior executives", "2025-05-21",
         **{"Other seinor executives": "<p>Sample, Ben; Placeholder, Cara</p>"}),
    _row(8, "IC-0008", "Audience as a band label", "2025-06-11",
         **{"Estimated audience size": "10–50k"}),
    _row(9, "IC-0009", "No audience value", "2025-06-12", **{"Estimated audience size": ""}),
    _row(10, "IC-0010", "No start date", None, **{"Start date": ""}),
    _row(11, "IC-0011", "Outside the window", "2024-06-04"),
    _row(17, "IC-0018", "City rolls up to its country", "2025-04-08",
         **{"Region": _lookup("Zurich")}),
    _row(18, "IC-0019", "Region value nobody mapped", "2025-04-09",
         **{"Region": _lookup("Atlantis")}),
    _row(12, "IC-0012", "Incomplete record", "2025-09-24",
         **{"Channel": "", "Lead Team": "", "Communication pack:C": ""}),
    _row(13, "IC-0013", "Last week of the year", "2025-12-31"),
    # Priority: the source system's numbered labels and the studio's words are
    # live at the same time. Every other row here carries "2 - label", which
    # collapses the Mix sheet's priority block to a single row and hides how it
    # is ordered. These three make the ordering observable -- and are chosen so
    # that rank order and alphabetical order genuinely disagree: by rank it is
    # "2 - label", "Medium", "4 - deprioritised", "Low"; alphabetically it is
    # "2 - label", "4 - deprioritised", "Low", "Medium", with Low above Medium.
    _row(14, "IC-0014", "Priority as a word", "2025-04-15", **{"Priority": "Medium"}),
    _row(15, "IC-0015", "Lowest word priority", "2025-07-08", **{"Priority": "Low"}),
    _row(16, "IC-0016", "Low numbered priority", "2025-10-14",
         **{"Priority": "4 - deprioritised"}),
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
         **{"Region": _lookup("All"), "Audience": "external"}),
]

EXTERNAL_ARCHIVE_ROWS = []

# 19 internal + 1 surviving archive + 2 external, minus the losing duplicate.
FIXTURE_ROW_COUNT = 22

# The pack export, in the source's own column names. `LTID` is what the pack
# list calls its identifier -- the name is why `campaign_ltid` is a candidate
# link column and why the choice has to be measured rather than assumed.
PACK_HEADER = [
    "LTID", "Name of communication pack", "Tracking cluster", "Category",
    "Business Division", "Region", "Campaign", "Lead Team", "Partner team",
    "Objective", "Start date", "End date", "Date of launch", "Brief",
    "Created", "Modified",
]


def _pack_row(cpid, name, **overrides):
    row = {
        "LTID": cpid, "Name of communication pack": name,
        "Tracking cluster": _lookup("QRREP"), "Category": "Campaign",
        "Business Division": _lookup("Division A"), "Region": _lookup("EMEA"),
        "Campaign": "Pack lead", "Lead Team": "Team", "Partner team": "",
        "Objective": _lookup("Objective"), "Start date": "2025-01-06",
        "End date": "2025-12-19", "Date of launch": "2025-02-03",
        "Brief": "<p>Synthetic pack description</p>",
        "Created": "2024-11-01", "Modified": "2025-06-01",
    }
    row.update(overrides)
    return row


PACK_ROWS = [
    _pack_row("CP-100", "Pack one"),
    # Nothing in the activity fixture points here. This is the row the whole
    # file exists for: a pack with nothing planned against it.
    _pack_row("CP-200", "Pack with nothing planned"),
    # The same identifier twice, the older losing on Modified -- the way the
    # activity de-dup already resolves a repeated tracking ID.
    _pack_row("CP-100", "Stale pack one", **{"Modified": "2024-12-01"}),
]

# CP-100 and CP-200 survive the de-dup; the stale CP-100 loses.
FIXTURE_PACK_COUNT = 2


def write_pack_csv(directory):
    """Write the pack export and return its path.

    Separate from `write_activity_csvs` on purpose: a scope built without a
    pack list is the state every machine that syncs only the activity exports
    is in, and the tests have to be able to build it.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return _write_csv(directory / "CommunicationPacks.csv", PACK_ROWS, PACK_HEADER)


def _write_csv(path, rows, header):
    lines = [",".join(f'"{h}"' for h in header)]
    for row in rows:
        cells = []
        for header_name in header:
            value = row.get(header_name, "")
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
    path never produces, so this fixture still skips it. (A header-only CSV
    used to crash `transform()` via a `.dt` accessor on an untyped empty
    column; that is fixed now — see `tests/test_process_cplan_load.py`'s
    header-only-CSV test — but it remains outside what `find_input_files`
    would ever hand the ETL, so it stays out of this fixture.)
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    sources = {
        "internal": (directory / "InternalCommunicationActivities.csv",
                     INTERNAL_ROWS, INTERNAL_HEADER),
        "internal_archive": (directory / "InternalCommunicationActivitiesArchive.csv",
                             INTERNAL_ARCHIVE_ROWS, INTERNAL_HEADER),
        "external": (directory / "ExternalCommunicationActivities.csv",
                     EXTERNAL_ROWS, EXTERNAL_HEADER),
        "external_archive": (directory / "ExternalCommunicationActivitiesArchive.csv",
                             EXTERNAL_ARCHIVE_ROWS, EXTERNAL_HEADER),
    }
    files = {}
    for key, (path, rows, header) in sources.items():
        if not rows:
            continue
        files[key] = _write_csv(path, rows, header)
    return files


def load_fixture_scope(directory, config, membership=None):
    from pipeline.report.data import build_scope
    from pipeline.scripts.process_cplan import load_activities

    return build_scope(load_activities(write_activity_csvs(directory)), config, membership)
