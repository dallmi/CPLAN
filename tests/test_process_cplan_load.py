"""Tests for the activity-loading step shared by the ETL and the calendar report."""

from pathlib import Path

import pytest

pytest.importorskip("pandas")

import pandas as pd  # noqa: E402

import pipeline.scripts.process_cplan as process_cplan


# The header as the export writes it. The suffix past "public" is a SharePoint
# internal-name detail; the matcher goes by prefix, so the exact tail is
# irrelevant -- and using a plausible one here is what proves that.
HIDE_HEADER = "Hide_x0020_from_x0020_public_x0020_view"


def _activity_frame(**overrides):
    """One activity row as the export hands it over, encoded headers and all."""
    row = {
        "ID": "101",
        "Tracking ID": "QRREP-0000058-240709-0000060-EMI",
        "Title": "Quarterly report mail",
        HIDE_HEADER: "FALSE",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_the_encoded_hide_header_becomes_the_hide_column():
    frame = process_cplan.transform(_activity_frame(), source_type="internal")

    assert process_cplan.HIDE_COLUMN in frame.columns


def test_a_ticked_box_reads_as_hidden():
    frame = process_cplan.transform(
        _activity_frame(**{HIDE_HEADER: "TRUE"}), source_type="internal"
    )

    assert frame[process_cplan.HIDE_COLUMN].tolist() == [True]


@pytest.mark.parametrize("unset", ["FALSE", "False", "false", "0", "", "   ", None])
def test_every_form_of_not_ticked_reads_as_not_hidden(unset):
    """The export writes FALSE on some rows and leaves others empty. Both occur."""
    frame = process_cplan.transform(
        _activity_frame(**{HIDE_HEADER: unset}), source_type="internal"
    )

    assert frame[process_cplan.HIDE_COLUMN].tolist() == [False]


def test_a_value_nobody_anticipated_counts_as_hidden():
    """Fail closed. An unrecognised value is not a licence to publish."""
    assert process_cplan.is_hidden_value("Restricted") is True
    assert process_cplan.is_hidden_value("?") is True


def _flagged(*hidden_flags):
    return pd.DataFrame({
        "tracking_id": [f"QRREP-0000058-240709-000006{i}-EMI"
                        for i in range(len(hidden_flags))],
        process_cplan.HIDE_COLUMN: list(hidden_flags),
    })


def test_hidden_rows_are_dropped_and_counted():
    frame, excluded = process_cplan.exclude_hidden(_flagged(False, True, False, True),
                                                   "internal")

    assert len(frame) == 2
    assert excluded == 2


def test_the_marker_leaves_with_the_rows_it_marked():
    """A hide_from_public column in an output would be a map of the interesting rows."""
    frame, _ = process_cplan.exclude_hidden(_flagged(False, True), "internal")

    assert process_cplan.HIDE_COLUMN not in frame.columns


def test_a_frame_with_nothing_hidden_keeps_every_row():
    frame, excluded = process_cplan.exclude_hidden(_flagged(False, False), "internal")

    assert len(frame) == 2
    assert excluded == 0


def test_the_index_is_reset_so_later_positional_work_is_safe():
    frame, _ = process_cplan.exclude_hidden(_flagged(True, False), "internal")

    assert frame.index.tolist() == [0]


def test_an_export_without_the_column_stops_the_run_and_names_the_file():
    """Both silent answers are wrong: publish everything, or report nothing."""
    bare = pd.DataFrame({"tracking_id": ["QRREP-0000058-240709-0000060-EMI"]})

    with pytest.raises(process_cplan.HiddenColumnMissing) as error:
        process_cplan.exclude_hidden(bare, "InternalCommunicationActivities.csv")

    assert "InternalCommunicationActivities.csv" in str(error.value)


def _export_csv(tmp_path: Path, name: str, *rows) -> Path:
    """One activity export. Each row is (tracking_id, title, hide_value)."""
    import csv

    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Tracking ID", "Title", "Start date", HIDE_HEADER])
        for index, (tracking_id, title, hide) in enumerate(rows, start=1):
            writer.writerow([str(index), tracking_id, title, "2025-03-05", hide])
    return path


def test_hidden_activities_never_reach_the_combined_frame(tmp_path):
    _export_csv(
        tmp_path, "InternalCommunicationActivities.csv",
        ("QRREP-0000058-240709-0000060-EMI", "Quarterly report mail", "FALSE"),
        ("QRREP-0000058-240709-0000061-EMI", "Board briefing", "TRUE"),
    )

    load = process_cplan.load_activities(process_cplan.find_input_files(tmp_path))

    assert load.frame["tracking_id"].tolist() == ["QRREP-0000058-240709-0000060-EMI"]
    assert "Board briefing" not in load.frame["activity_name"].tolist()


def test_the_load_says_how_many_it_excluded_and_from_where(tmp_path):
    _export_csv(
        tmp_path, "InternalCommunicationActivities.csv",
        ("QRREP-0000058-240709-0000060-EMI", "A", "FALSE"),
        ("QRREP-0000058-240709-0000061-EMI", "B", "TRUE"),
    )
    _export_csv(
        tmp_path, "ExternalCommunicationActivities.csv",
        ("PRESS-0000012-240301-0000004-EXT", "C", "TRUE"),
    )

    load = process_cplan.load_activities(process_cplan.find_input_files(tmp_path))

    assert load.hidden_excluded == 2
    assert dict(load.hidden_by_file) == {"internal": 1, "external": 1}


def test_the_marker_column_is_not_in_the_loaded_frame(tmp_path):
    _export_csv(tmp_path, "InternalCommunicationActivities.csv",
                ("QRREP-0000058-240709-0000060-EMI", "A", "FALSE"))

    load = process_cplan.load_activities(process_cplan.find_input_files(tmp_path))

    assert process_cplan.HIDE_COLUMN not in load.frame.columns


INTERNAL_CSV = (
    f"ID,Tracking ID,Title,Start date,Region,Modified,{HIDE_HEADER}\n"
    "1,IC-0001,Active row,2025-03-05,EMEA,2025-03-01,FALSE\n"
)
ARCHIVE_CSV = (
    f"ID,Tracking ID,Title,Start date,Region,Modified,{HIDE_HEADER}\n"
    "1,IC-0001,Stale duplicate,2025-03-05,EMEA,2025-01-01,FALSE\n"
    "2,IC-0002,Archived row,2025-04-09,APAC,2025-04-01,FALSE\n"
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
        f"ID,Tracking ID,Title,Start date,Region,Modified,{HIDE_HEADER}\n",
        encoding="utf-8",
    )

    load = process_cplan.load_activities({"internal": header_only})

    assert load.frame.empty
    assert "Tracking ID" in load.raw_columns["internal"]
    assert load.hidden_excluded == 0
    assert set(load.files) == {"internal"}


def _load(hidden_by_file=(), hidden_excluded=0):
    return process_cplan.ActivityLoad(
        frame=pd.DataFrame(), raw_columns={}, files={},
        duplicates_removed=0,
        hidden_excluded=hidden_excluded,
        hidden_by_file=hidden_by_file,
    )


def test_meta_states_what_was_excluded_and_from_where():
    """The dashboard already reads meta.json for its refresh stamp."""
    from datetime import datetime

    meta = process_cplan.build_meta(
        load=_load(hidden_by_file=(("internal", 1), ("external", 1)), hidden_excluded=2),
        now=datetime(2026, 8, 17, 9, 30),
        full_refresh=True,
        row_counts={"communications": 410},
    )

    assert meta["excluded_total"] == 2
    assert meta["excluded_counts"] == {"internal": 1, "external": 1}


def test_meta_keeps_the_keys_the_dashboard_already_reads():
    """Extraction must not change the contract -- index.html parses this file."""
    from datetime import datetime

    meta = process_cplan.build_meta(
        load=_load(), now=datetime(2026, 8, 17, 9, 30),
        full_refresh=False, row_counts={"communications": 410},
    )

    assert meta["generated_at"] == "2026-08-17 09:30"
    assert meta["generated_at_iso"] == "2026-08-17T09:30:00"
    assert meta["mode"] == "incremental"
    assert meta["row_counts"] == {"communications": 410}


def test_a_run_that_excluded_nothing_still_states_the_zero():
    """An absent key reads as "written before hiding existed"; a zero does not."""
    from datetime import datetime

    meta = process_cplan.build_meta(
        load=_load(), now=datetime(2026, 8, 17, 9, 30),
        full_refresh=True, row_counts={},
    )

    assert meta["excluded_total"] == 0
    assert meta["excluded_counts"] == {}


def test_an_export_that_lost_the_hide_column_stops_the_whole_load(tmp_path):
    """The guard has to hold on the real path, not only on the helper.

    An export changing shape is the one case where guessing is unacceptable in
    both directions, so the loud failure is the feature.
    """
    bare = tmp_path / "InternalCommunicationActivities.csv"
    bare.write_text("ID,Tracking ID,Title,Start date\n1,IC-0001,A,2025-03-05\n",
                    encoding="utf-8")

    with pytest.raises(process_cplan.HiddenColumnMissing) as error:
        process_cplan.load_activities({"internal": bare})

    assert "InternalCommunicationActivities.csv" in str(error.value)


def test_loading_packs_without_an_export_is_not_an_error(tmp_path):
    """The state every machine that syncs only the activity lists is in.

    A missing optional input returns None so callers can carry on, the same
    rule the GEB member list follows. Raising here would stop a run over a
    file most deployments will never have.
    """
    from pipeline.scripts.process_cplan import load_packs
    from tests.report_fixtures import write_activity_csvs

    assert load_packs(write_activity_csvs(tmp_path)) is None


def test_the_pack_load_de_duplicates_on_the_identifier(tmp_path):
    """Two rows for one pack, newest Modified winning -- the rule the
    activity load already applies to a repeated tracking ID.
    """
    from pipeline.scripts.process_cplan import find_input_files, load_packs
    from tests.report_fixtures import (FIXTURE_PACK_COUNT, write_activity_csvs,
                                       write_pack_csv)

    write_activity_csvs(tmp_path)
    write_pack_csv(tmp_path)
    load = load_packs(find_input_files(tmp_path))

    assert load is not None
    assert len(load.frame) == FIXTURE_PACK_COUNT
    assert load.duplicates_removed == 1
    surviving = load.frame.set_index("cpid")["pack_name"].to_dict()
    assert surviving["CP-100"] == "Pack one", "the stale row won the de-dup"


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


def test_the_time_zone_lookup_is_unwrapped_to_its_value():
    """The source column is a lookup, not free text -- it arrives as the
    expanded-reference JSON, the same shape as every other lookup here.

    Mapping it without parsing it was worse than not mapping it at all: the
    ~130-character blob went straight at `activities.time_zone`, a
    `varchar(64)`, and PostgreSQL rejected the INSERT. That killed the daily
    refresh outright, so no row was written at all and every activity still
    read as missing a time zone -- the very symptom the mapping was meant to
    end.

    An unmapped value on purpose, so this pins the unwrapping alone: a
    translated one would pass even if the whole JSON blob were being handed to
    `TIME_ZONE_MAP` and merely missing there.
    """
    row = _mapped_cells(
        ["ID", "Title", "Start date", "Time zone"],
        [
            "1", "A", "2025-03-05",
            '{"@odata.type":"#Microsoft.Azure.Connectors.SharePoint.SPListExpandedReference",'
            '"Id":1,"Value":"Mars Standard Time - GMT+25:00"}',
        ],
    )

    assert row["time_zone"] == "Mars Standard Time - GMT+25:00"


def test_the_display_name_is_translated_to_an_iana_zone():
    """The lookup carries the legacy Java zone descriptions, which no clock
    library and no `<select>` in the studio knows.
    """
    row = _mapped_cells(
        ["ID", "Title", "Start date", "Time zone"],
        [
            "1", "A", "2025-03-05",
            '{"@odata.type":"#Microsoft.Azure.Connectors.SharePoint.SPListExpandedReference",'
            '"Id":1,"Value":"Hong Kong, China, Taiwan Time - GMT+8:00"}',
        ],
    )

    assert row["time_zone"] == "Asia/Shanghai"


def test_the_zone_its_own_activities_contradict_maps_where_the_rows_are():
    """"Middle East Time - GMT+3:30" is Tehran by the label. All seven
    activities using it sit in Abu Dhabi, which is GMT+4 -- the label was
    picked by its name. The rows outrank it.
    """
    row = _mapped("ID,Title,Start date,Time zone", "1,A,2025-03-05,Middle East Time - GMT+3:30")

    assert row["time_zone"] == "Asia/Dubai"


def test_the_translation_survives_a_changed_capital_or_a_double_space():
    """The source writes the label however the list entry was created, and a
    missed translation looks exactly like a zone nobody has mapped yet.
    """
    for label in ("JAPAN STANDARD TIME - GMT+9:00", "Japan  Standard  Time - GMT+9:00"):
        row = _mapped_cells(["ID", "Title", "Start date", "Time zone"],
                            ["1", "A", "2025-03-05", label])
        assert row["time_zone"] == "Asia/Tokyo", label


def test_an_unmapped_zone_is_kept_rather_than_dropped():
    """A zone added to the source list after this table was written must not
    empty the field: the activity would read as missing one it has, which is
    the failure this whole chain exists to end. It stays, and the time-zone
    check reports it as unmapped.
    """
    row = _mapped("ID,Title,Start date,Time zone", "1,A,2025-03-05,Mars Standard Time - GMT+25:00")

    assert row["time_zone"] == "Mars Standard Time - GMT+25:00"


def test_a_plain_text_time_zone_still_survives_the_lookup_parser():
    """Not every export writes the lookup JSON -- a hand-maintained column
    carries the bare value, and the parser has to leave it alone.
    """
    row = _mapped("ID,Title,Start date,Time zone", "1,A,2025-03-05,Europe/Zurich")

    assert row["time_zone"] == "Europe/Zurich"


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
                  "1,A,2025-03-05,A leadership person,Another executive")

    assert row["bod_geb"] == "A leadership person"
    assert row["other_executives"] == "Another executive"


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


def test_control_characters_are_stripped_from_every_text_column():
    """A real export carried a vertical tab at the end of an activity title.
    openpyxl refuses such characters outright, so the report died mid-write and
    produced no file at all -- for one stray byte in one row.
    """
    row = _mapped_cells(["ID", "Title", "Start date", "BOD / GEB"],
                        ["1", "Leadership Exchange\x0b", "2025-03-05",
                         "Example\x1f, Ada"])

    assert row["activity_name"] == "Leadership Exchange"
    assert row["bod_geb"] == "Example, Ada"


def test_tabs_and_newlines_survive_the_strip():
    """Only the characters a spreadsheet cannot hold. Tab and newline can."""
    assert process_cplan.strip_control_chars("a\tb\nc") == "a\tb\nc"
    assert process_cplan.strip_control_chars(None) is None
    assert process_cplan.strip_control_chars(42) == 42


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


# --- person emails: aligned extraction for multi-person columns -------------

def test_person_emails_are_extracted_for_every_person_in_an_array():
    """A multi-person field exports a JSON array. The single-object parser
    returned "" for it, so a multi-person column silently carried no emails.
    """
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    raw = (
        '[{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"},'
        ' {"Claims": "i:0#.f|membership|b@example.invalid", "DisplayName": "B, Two"}]'
    )

    assert parse_sp_person_emails(raw) == "a@example.invalid; b@example.invalid"


def test_a_person_without_an_email_keeps_its_slot():
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    raw = (
        '[{"DisplayName": "A, One"},'
        ' {"Claims": "i:0#.f|membership|b@example.invalid", "DisplayName": "B, Two"}]'
    )

    assert parse_sp_person_emails(raw) == "; b@example.invalid"


def test_a_single_person_object_still_works():
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    raw = '{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"}'

    assert parse_sp_person_emails(raw) == "a@example.invalid"


def test_plain_text_yields_no_emails():
    """A rich-text source column is a real shape -- it must yield nothing
    rather than raise, so the name path can carry the match alone.
    """
    from pipeline.scripts.process_cplan import parse_sp_person_emails

    assert parse_sp_person_emails("Example, Ada; Sample, Ben") == ""
    assert parse_sp_person_emails("") == ""


def test_the_leadership_column_gains_an_email_column():
    row = _mapped_cells(
        ["ID", "Title", "Start date", "BOD / GEB"],
        ["1", "A", "2025-03-05",
         '[{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"}]'],
    )

    assert row["bod_geb"] == "A, One"
    assert row["bod_geb_email"] == "a@example.invalid"


def test_an_empty_display_name_does_not_shift_the_remaining_emails():
    """parse_sp_lookup drops any element whose display name comes back empty
    before joining. If parse_sp_person_emails emitted one slot per *element*
    regardless, the two would disagree in count -- and zipping them
    positionally would hand this person's address to the next person's name.
    """
    from pipeline.scripts.process_cplan import parse_sp_lookup, parse_sp_person_emails

    raw = (
        '[{"DisplayName": "", "Claims": "i:0#.f|membership|a@example.invalid"},'
        ' {"DisplayName": "B, Two", "Claims": "i:0#.f|membership|b@example.invalid"}]'
    )

    names = parse_sp_lookup(raw, "; ")
    emails = parse_sp_person_emails(raw)

    # The relationship that matters: same number of slots either side.
    assert len(names.split("; ")) == len(emails.split("; "))
    assert names == "B, Two"
    assert emails == "b@example.invalid"


def test_a_bare_string_among_person_objects_does_not_shift_the_remaining_emails():
    """`parse_sp_lookup`'s list branch also accepts bare strings (taxonomy
    arrays can contain them). parse_sp_person_emails must walk the same
    branches, or a bare string throws off the count the same way an empty
    display name does.
    """
    from pipeline.scripts.process_cplan import parse_sp_lookup, parse_sp_person_emails

    raw = (
        '["Just, Text",'
        ' {"DisplayName": "B, Two", "Claims": "i:0#.f|membership|b@example.invalid"}]'
    )

    names = parse_sp_lookup(raw, "; ")
    emails = parse_sp_person_emails(raw)

    assert len(names.split("; ")) == len(emails.split("; "))
    assert names == "Just, Text; B, Two"
    assert emails == "; b@example.invalid"


def test_a_blank_email_field_falls_back_to_claims():
    """Old behaviour tested `"Email" in parsed` and returned the value
    verbatim, so a blank or null Email produced "" rather than falling back
    to Claims. `_claims_email` tests truthiness instead, so it now falls
    through -- a deliberate change, pinned here so it stays one.
    """
    from pipeline.scripts.process_cplan import parse_sp_person_email

    raw = (
        '{"Email": "", "Claims": "i:0#.f|membership|a@example.invalid",'
        ' "DisplayName": "A, One"}'
    )

    assert parse_sp_person_email(raw) == "a@example.invalid"


# --- parse_sp_person_email (singular): direct coverage -----------------------
# Nothing called this directly before -- which is how its Email-truthiness
# change above shipped unnoticed.

def test_parse_sp_person_email_extracts_from_a_single_object():
    from pipeline.scripts.process_cplan import parse_sp_person_email

    raw = '{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"}'

    assert parse_sp_person_email(raw) == "a@example.invalid"


def test_parse_sp_person_email_returns_empty_for_non_json_text():
    from pipeline.scripts.process_cplan import parse_sp_person_email

    assert parse_sp_person_email("Example, Ada") == ""
    assert parse_sp_person_email("") == ""


def test_parse_sp_person_email_ignores_an_array():
    """Single-person fields only. It must not silently start handling
    arrays -- that is `parse_sp_person_emails`' job.
    """
    from pipeline.scripts.process_cplan import parse_sp_person_email

    raw = '[{"Claims": "i:0#.f|membership|a@example.invalid", "DisplayName": "A, One"}]'

    assert parse_sp_person_email(raw) == ""
