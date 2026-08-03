"""Tests for the activity-loading step shared by the ETL and the calendar report."""

from pathlib import Path

import pytest

pytest.importorskip("pandas")

import pipeline.scripts.process_cplan as process_cplan


INTERNAL_CSV = (
    "ID,Tracking ID,Title,Start date,Region,Modified\n"
    "1,IC-0001,Active row,2025-03-05,EMEA,2025-03-01\n"
)
ARCHIVE_CSV = (
    "ID,Tracking ID,Title,Start date,Region,Modified\n"
    "1,IC-0001,Stale duplicate,2025-03-05,EMEA,2025-01-01\n"
    "2,IC-0002,Archived row,2025-04-09,APAC,2025-04-01\n"
)


def _write(tmp_path: Path) -> dict[str, Path]:
    internal = tmp_path / "InternalCommunicationActivities.csv"
    archive = tmp_path / "InternalCommunicationActivitiesArchive.csv"
    internal.write_text(INTERNAL_CSV, encoding="utf-8")
    archive.write_text(ARCHIVE_CSV, encoding="utf-8")
    return {"internal": internal, "internal_archive": archive}


def test_load_activities_merges_archive_and_flags_it(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    assert set(load.frame["tracking_id"]) == {"IC-0001", "IC-0002"}
    archived = load.frame.set_index("tracking_id")["is_archived"]
    assert archived["IC-0002"] is True or archived["IC-0002"] == True  # noqa: E712


def test_load_activities_keeps_the_most_recently_modified_duplicate(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    row = load.frame.set_index("tracking_id").loc["IC-0001"]
    assert row["activity_name"] == "Active row"


def test_load_activities_counts_the_duplicate_it_removed(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    assert load.duplicates_removed == 1


def test_load_activities_reports_raw_columns_per_file(tmp_path):
    load = process_cplan.load_activities(_write(tmp_path))

    assert "Tracking ID" in load.raw_columns["internal"]
    assert set(load.files) == {"internal", "internal_archive"}


def test_load_activities_with_no_activity_files_returns_an_empty_frame(tmp_path):
    load = process_cplan.load_activities({"packs": tmp_path / "CommunicationPacks.csv"})

    assert load.frame.empty
    assert load.raw_columns == {}
    assert load.files == {}
    assert load.duplicates_removed == 0


def test_load_activities_with_a_header_only_csv_returns_an_empty_frame(tmp_path):
    # A header row with zero data rows happens when the source export (e.g.
    # an empty archive list) has nothing to report. This must not crash the
    # ETL — it should behave like "no activities from this file", not blow up.
    header_only = tmp_path / "InternalCommunicationActivities.csv"
    header_only.write_text(
        "ID,Tracking ID,Title,Start date,Region,Modified\n", encoding="utf-8"
    )

    load = process_cplan.load_activities({"internal": header_only})

    assert load.frame.empty
    assert "Tracking ID" in load.raw_columns["internal"]
    assert set(load.files) == {"internal"}


# --- column mapping: the layer where two real bugs lived ---------------------

def _mapped(header, row):
    """Transform one CSV row and return it as a dict of output columns."""
    import io

    import pandas as pd

    df = pd.read_csv(io.StringIO(f"{header}\n{row}\n"), dtype=str)
    out = process_cplan.transform(df, source_type="internal")
    return out.iloc[0].to_dict()


def _mapped_cells(headers, values):
    """Same, but for values that need real CSV quoting -- lookup JSON."""
    import csv
    import io

    import pandas as pd

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerow(values)
    buffer.seek(0)
    out = process_cplan.transform(pd.read_csv(buffer, dtype=str), source_type="internal")
    return out.iloc[0].to_dict()


def test_the_estimated_size_column_becomes_the_audience_field():
    """The field the studio labels "Estimated audience size" and the database
    has a column for. It used to be fed from the source's own "Audience"
    column, which is not a size at all.
    """
    row = _mapped("ID,Title,Start date,Estimated audience size", "1,A,2025-03-05,1 - 10K")

    assert row["audience"] == "1 - 10K"


def test_the_sources_own_audience_column_no_longer_lands_in_that_field():
    row = _mapped("ID,Title,Start date,Audience", "1,A,2025-03-05,external")

    assert row.get("audience_type") == "external"
    assert "audience" not in row or row["audience"] != "external"


def test_both_audience_columns_survive_side_by_side():
    """The internal export carries both. Whichever order they appear in, the
    size must reach `audience` and the other column must not overwrite it.
    """
    row = _mapped("ID,Title,Start date,Audience,Estimated audience size",
                  "1,A,2025-03-05,internal,50 - 100K")

    assert row["audience"] == "50 - 100K"
    assert row["audience_type"] == "internal"


def test_the_size_column_is_matched_whatever_case_the_source_used():
    for header in ("Estimated audience size", "Estimated Audience Size",
                   "ESTIMATED AUDIENCE SIZE"):
        row = _mapped(f"ID,Title,Start date,{header}", "1,A,2025-03-05,> 100K")
        assert row["audience"] == "> 100K", header


def test_the_size_column_does_not_steal_the_neighbouring_audience_fields():
    """"Target audience" and "Extended audience" are different fields, and the
    longest-label-first ordering has to keep them apart.
    """
    row = _mapped("ID,Title,Start date,Target audience,Extended audience,Estimated audience size",
                  "1,A,2025-03-05,All staff,Contractors,10 - 50K")

    assert row["target_audience"] == "All staff"
    assert row["extended_audience"] == "Contractors"
    assert row["audience"] == "10 - 50K"


def test_the_time_zone_column_is_mapped():
    """Present in every export and required by the studio, but unmapped -- so
    every activity read as missing a time zone it actually had.
    """
    row = _mapped("ID,Title,Start date,Time zone", "1,A,2025-03-05,Europe/Zurich")

    assert row["time_zone"] == "Europe/Zurich"


def test_the_time_zone_column_is_matched_whatever_case_the_source_used():
    for header in ("Time zone", "Time Zone", "TIME ZONE"):
        row = _mapped(f"ID,Title,Start date,{header}", "1,A,2025-03-05,Europe/London")
        assert row["time_zone"] == "Europe/London", header


def test_both_spellings_of_the_non_geb_executive_column_map_to_one_field():
    """The internal and external lists name it differently -- one carries a
    trailing digit -- and the source misspells "senior". Each export is
    transformed on its own, so one wildcard label covers both.
    """
    for header in ("Other seinor executives", "Other seinor executives0",
                   "Other senior executives", "Other Senior Executives"):
        row = _mapped(f"ID,Title,Start date,{header}", "1,A,2025-03-05,A. Person")
        assert row["other_executives"] == "A. Person", header


def test_the_non_geb_column_does_not_capture_the_geb_one():
    row = _mapped("ID,Title,Start date,BOD / GEB,Other seinor executives",
                  "1,A,2025-03-05,A GEB person,A non-GEB person")

    assert row["bod_geb"] == "A GEB person"
    assert row["other_executives"] == "A non-GEB person"


def test_the_non_geb_column_is_html_stripped_like_its_sibling():
    row = _mapped("ID,Title,Start date,Other seinor executives",
                  "1,A,2025-03-05,<p>A. Person</p>")

    assert row["other_executives"] == "A. Person"


def test_a_person_array_is_joined_with_semicolons_not_commas():
    """A display name is "Last, First". Joining two of them with a comma makes
    them indistinguishable from four fragments, and nothing downstream can undo
    that -- so the ambiguity has to be avoided here, where both names are still
    separate objects.
    """
    import json

    people = json.dumps([{"DisplayName": "Example, Ada"},
                         {"DisplayName": "Sample, Ben"}])
    row = _mapped_cells(["ID", "Title", "Start date", "BOD / GEB"],
                        ["1", "A", "2025-03-05", people])

    assert row["bod_geb"] == "Example, Ada; Sample, Ben"


def test_non_person_lookups_still_join_with_commas():
    """Divisions and regions are not people and have no comma inside a value,
    so their join is unchanged -- the semicolon is only for the person fields.
    """
    import json

    divisions = json.dumps([{"Value": "Division A"}, {"Value": "Division B"}])
    row = _mapped_cells(["ID", "Title", "Start date", "Business Division"],
                        ["1", "A", "2025-03-05", divisions])

    assert row["business_division"] == "Division A, Division B"


def test_the_snapshot_import_lets_the_mapped_fields_through():
    """Two allowlists have to agree, and nothing warned when they did not.

    A field can be mapped by the ETL and still never reach the database: the
    snapshot import filters against its own list. `time_zone` was mapped
    nowhere and allowed nowhere, so the studio showed every activity as
    missing one. `audience_type` is deliberately excluded -- it is not a size
    and must not overwrite the field that is.
    """
    from pipeline.api.import_snapshot import ALLOWED_FIELDS

    mapped = set(process_cplan.COLUMN_MAP.values())

    assert "time_zone" in mapped and "time_zone" in ALLOWED_FIELDS
    assert "audience" in mapped and "audience" in ALLOWED_FIELDS
    assert "audience_type" in mapped and "audience_type" not in ALLOWED_FIELDS
