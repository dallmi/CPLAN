"""Tests for the tracking-ID check.

The question it answers is whether a list of IDs someone was handed exists in
the export at all -- and, when one does not, whether it is absent because the
activity was never created or because a suffix is wrong.
"""

import csv
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("pandas")

from pipeline.scripts import check_tracking_ids


@pytest.fixture(autouse=True)
def _default_output_goes_to_a_scratch_dir(tmp_path, monkeypatch):
    """Every run writes a workbook now, and none of them belongs in the repo."""
    monkeypatch.setattr(check_tracking_ids, "REPORTS_DIR", tmp_path / "reports")


def _ids(tmp_path: Path, *lines: str, name: str = "ids.txt") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_list_keeps_its_order_and_drops_blanks_and_comments(tmp_path):
    path = _ids(
        tmp_path,
        "# the ones from the mail",
        "QRREP-0000058-240709-0000060-EMI",
        "",
        "   ",
        "  QRREP-0000058-240709-0000061-INT  ",
        "   # indented comment",
    )

    id_list = check_tracking_ids.read_id_list(path)

    assert id_list.listed == [
        "QRREP-0000058-240709-0000060-EMI",
        "QRREP-0000058-240709-0000061-INT",
    ]
    assert all(count == 1 for count in id_list.counts.values())


def test_a_repeated_id_is_listed_once_and_counted_twice(tmp_path):
    path = _ids(
        tmp_path,
        "QRREP-0000058-240709-0000060-EMI",
        "qrrep-0000058-240709-0000060-emi",
    )

    id_list = check_tracking_ids.read_id_list(path)

    assert id_list.listed == ["QRREP-0000058-240709-0000060-EMI"]
    assert id_list.counts["QRREP-0000058-240709-0000060-EMI"] == 2


def test_a_text_list_carries_no_extra_columns(tmp_path):
    """The .txt format has one column by construction; nothing to carry."""
    id_list = check_tracking_ids.read_id_list(_ids(tmp_path, "QRREP-0000058-240709-0000060-EMI"))

    assert id_list.extra_columns == ()
    assert id_list.extras == {}


def _xlsx(tmp_path: Path, *rows, name: str = "ids.xlsx", title: str = "Liste", more=()) -> Path:
    """A workbook whose first sheet holds `rows`, first row being the header.

    `more` adds further sheets as (title, rows) pairs, so the sheet-choice
    tests have something to choose between.
    """
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(list(row))
    for other_title, other_rows in more:
        other = workbook.create_sheet(other_title)
        for row in other_rows:
            other.append(list(row))
    path = tmp_path / name
    workbook.save(path)
    return path


def test_an_excel_list_is_read_from_the_tracking_id_column(tmp_path):
    path = _xlsx(
        tmp_path,
        ("Kampagne", "Tracking ID", "Notiz"),
        ("Q3", "QRREP-0000058-240709-0000060-EMI", "aus der Mail"),
        ("Q3", "QRREP-0000058-240709-0000061-INT", ""),
    )

    id_list = check_tracking_ids.read_id_list(path)

    assert id_list.listed == [
        "QRREP-0000058-240709-0000060-EMI",
        "QRREP-0000058-240709-0000061-INT",
    ]


def test_the_columns_beside_the_ids_are_carried_along(tmp_path):
    path = _xlsx(
        tmp_path,
        ("Kampagne", "Tracking ID", "Notiz"),
        ("Q3", "QRREP-0000058-240709-0000060-EMI", "aus der Mail"),
    )

    id_list = check_tracking_ids.read_id_list(path)

    assert id_list.extra_columns == ("Kampagne", "Notiz")
    assert id_list.extras["QRREP-0000058-240709-0000060-EMI"] == {
        "Kampagne": "Q3",
        "Notiz": "aus der Mail",
    }


def test_the_id_column_is_found_whatever_its_spelling(tmp_path):
    """Including `Tacking ID` -- the export's own long-standing typo.

    A header pasted out of the export carries it, and refusing that header
    would make the export's mistake the operator's problem.
    """
    for header in ("  tracking id  ", "TRACKING ID", "Tacking ID"):
        path = _xlsx(
            tmp_path,
            (header, "Notiz"),
            ("QRREP-0000058-240709-0000060-EMI", "x"),
            name=f"ids-{header.strip().replace(' ', '_')}.xlsx",
        )

        id_list = check_tracking_ids.read_id_list(path)

        assert id_list.listed == ["QRREP-0000058-240709-0000060-EMI"], header
        assert id_list.extra_columns == ("Notiz",), header


def test_an_excel_list_without_an_id_column_names_the_columns_it_found(tmp_path):
    path = _xlsx(tmp_path, ("Kampagne", "Notiz"), ("Q3", "x"))

    with pytest.raises(check_tracking_ids.IdListError) as error:
        check_tracking_ids.read_id_list(path)

    message = str(error.value)
    assert "Tracking ID" in message
    assert "Kampagne" in message and "Notiz" in message


def test_the_rows_excel_leaves_behind_are_dropped(tmp_path):
    """A list edited down from a longer one arrives with blank rows below it."""
    path = _xlsx(
        tmp_path,
        ("Tracking ID", "Notiz"),
        ("QRREP-0000058-240709-0000060-EMI", "x"),
        (None, None),
        (None, None),
    )

    id_list = check_tracking_ids.read_id_list(path)

    assert id_list.listed == ["QRREP-0000058-240709-0000060-EMI"]


def test_a_row_that_says_something_but_names_no_id_is_an_error(tmp_path):
    """Not a blank row: a note with no ID beside it is an ID someone forgot."""
    path = _xlsx(
        tmp_path,
        ("Tracking ID", "Notiz"),
        ("QRREP-0000058-240709-0000060-EMI", "x"),
        ("", "noch nachtragen"),
    )

    with pytest.raises(check_tracking_ids.IdListError) as error:
        check_tracking_ids.read_id_list(path)

    assert "row 3" in str(error.value)


def test_a_commented_row_in_an_excel_list_is_dropped(tmp_path):
    path = _xlsx(
        tmp_path,
        ("Tracking ID",),
        ("# aus der Mail vom Freitag",),
        ("QRREP-0000058-240709-0000060-EMI",),
    )

    id_list = check_tracking_ids.read_id_list(path)

    assert id_list.listed == ["QRREP-0000058-240709-0000060-EMI"]


def test_a_repeat_in_an_excel_list_keeps_the_first_row_it_came_from(tmp_path):
    """Same rule as the order: first seen wins, so the two cannot disagree."""
    path = _xlsx(
        tmp_path,
        ("Tracking ID", "Notiz"),
        ("QRREP-0000058-240709-0000060-EMI", "erste"),
        ("qrrep-0000058-240709-0000060-emi", "zweite"),
    )

    id_list = check_tracking_ids.read_id_list(path)

    assert id_list.counts["QRREP-0000058-240709-0000060-EMI"] == 2
    assert id_list.extras["QRREP-0000058-240709-0000060-EMI"]["Notiz"] == "erste"


def test_an_excel_list_reads_the_first_sheet_unless_told_otherwise(tmp_path):
    path = _xlsx(
        tmp_path,
        ("Tracking ID",),
        ("QRREP-0000058-240709-0000060-EMI",),
        more=[("Q4", [("Tracking ID",), ("TOWNH-0000012-240301-0000004-TMS",)])],
    )

    assert check_tracking_ids.read_id_list(path).listed == ["QRREP-0000058-240709-0000060-EMI"]
    assert check_tracking_ids.read_id_list(path, sheet="Q4").listed == [
        "TOWNH-0000012-240301-0000004-TMS"
    ]


def test_an_unknown_sheet_name_lists_the_sheets_there_are(tmp_path):
    path = _xlsx(
        tmp_path,
        ("Tracking ID",),
        ("QRREP-0000058-240709-0000060-EMI",),
        more=[("Q4", [("Tracking ID",)])],
    )

    with pytest.raises(check_tracking_ids.IdListError) as error:
        check_tracking_ids.read_id_list(path, sheet="Q5")

    message = str(error.value)
    assert "Q5" in message
    assert "Liste" in message and "Q4" in message


def test_asking_a_text_list_for_a_sheet_is_an_error(tmp_path):
    """Silently ignoring it would answer from the wrong list without saying so."""
    path = _ids(tmp_path, "QRREP-0000058-240709-0000060-EMI")

    with pytest.raises(check_tracking_ids.IdListError) as error:
        check_tracking_ids.read_id_list(path, sheet="Q4")

    assert "sheet" in str(error.value).lower()


def test_a_workbook_without_openpyxl_names_the_install(tmp_path):
    """The .txt path must keep working on a machine that has no openpyxl."""
    path = _xlsx(tmp_path, ("Tracking ID",), ("QRREP-0000058-240709-0000060-EMI",))

    with mock.patch.dict(sys.modules, {"openpyxl": None}):
        with pytest.raises(check_tracking_ids.IdListError) as error:
            check_tracking_ids.read_id_list(path)

    assert "openpyxl" in str(error.value)


def test_a_csv_renamed_to_xlsx_says_so_rather_than_traceback(tmp_path):
    path = tmp_path / "ids.xlsx"
    path.write_text("Tracking ID\nQRREP-0000058-240709-0000060-EMI\n", encoding="utf-8")

    with pytest.raises(check_tracking_ids.IdListError) as error:
        check_tracking_ids.read_id_list(path)

    assert "ids.xlsx" in str(error.value)


def _export(tmp_path: Path, name: str, *rows: tuple[str, str, str]) -> Path:
    """One activity export. Each row is (tracking_id, sp_id, title)."""
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Tracking ID", "Title", "Start date"])
        for tracking_id, sp_id, title in rows:
            writer.writerow([sp_id, tracking_id, title, "2026-03-05"])
    return path


LIVE = "QRREP-0000058-240709-0000060-EMI"
OTHER_CHANNEL = "QRREP-0000058-240709-0000060-INT"
SAME_PACK = "QRREP-0000058-240709-0000099-EMI"
ARCHIVED = "TOWNH-0000012-240301-0000004-TMS"


def test_every_activity_export_is_indexed_and_names_its_own_source(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    _export(tmp_path, "ExternalCommunicationActivities.csv", (SAME_PACK, "2", "Press note"))
    _export(tmp_path, "InternalCommunicationActivitiesArchive.csv", (ARCHIVED, "3", "Town hall"))

    files = check_tracking_ids.find_input_files(tmp_path)
    index = check_tracking_ids.build_index(files)

    assert index[LIVE].source == "internal"
    assert index[LIVE].sp_id == "1"
    assert index[LIVE].activity_name == "Quarterly report"
    assert index[SAME_PACK].source == "external"
    assert index[ARCHIVED].source == "internal_archive"


def test_a_live_row_wins_over_an_archived_one_with_the_same_id(tmp_path):
    """Both exports can carry an ID mid-archival. The live row is the answer."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Live"))
    _export(tmp_path, "InternalCommunicationActivitiesArchive.csv", (LIVE, "9", "Archived"))

    index = check_tracking_ids.build_index(check_tracking_ids.find_input_files(tmp_path))

    assert index[LIVE].source == "internal"


def test_the_index_is_keyed_on_the_normalised_id(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (f"  {LIVE.lower()}  ", "1", "A"))

    index = check_tracking_ids.build_index(check_tracking_ids.find_input_files(tmp_path))

    assert LIVE in index


def test_the_pack_and_channel_exports_are_not_searched(tmp_path):
    """A pack ID is not an activity, and reporting one as found would be a lie."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    packs = tmp_path / "CommunicationPacks.csv"
    with open(packs, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "Tracking ID", "Title"])
        writer.writerow(["7", ARCHIVED, "A pack"])

    index = check_tracking_ids.build_index(check_tracking_ids.find_input_files(tmp_path))

    assert ARCHIVED not in index


def _index(*ids: str) -> dict:
    return {
        check_tracking_ids.normalise(value): check_tracking_ids.Entry(
            tracking_id=check_tracking_ids.normalise(value),
            source="internal",
            sp_id="1",
            activity_name="An activity",
        )
        for value in ids
    }


def test_a_wrong_channel_suffix_is_named_as_such():
    hint = check_tracking_ids.find_hint(LIVE, _index(OTHER_CHANNEL))

    assert "channel" in hint.why.lower()
    assert hint.nearest == OTHER_CHANNEL


def test_a_missing_activity_in_an_existing_pack_names_the_pack():
    hint = check_tracking_ids.find_hint(LIVE, _index(SAME_PACK))

    assert hint.nearest == "QRREP-0000058"
    assert "pack" in hint.why.lower()


def test_the_channel_rung_wins_when_both_would_hit():
    """Rung 1 is the more specific answer, so it must be reached first."""
    hint = check_tracking_ids.find_hint(LIVE, _index(SAME_PACK, OTHER_CHANNEL))

    assert hint.nearest == OTHER_CHANNEL


def test_one_character_off_is_named_as_a_typo():
    """A different cluster, so rungs 1 and 2 cannot fire -- only the distance does.

    An ID one letter off *within* the same pack is rung 1's case, not this one.
    """
    wanted = "QRREQ-0000058-240709-0000060-EMI"  # QRREQ, not QRREP

    hint = check_tracking_ids.find_hint(wanted, _index(LIVE))

    assert hint.nearest == LIVE
    assert "one character" in hint.why.lower()


def test_a_dropped_character_counts_as_one_edit():
    hint = check_tracking_ids.find_hint("QRREP-000058-240709-0000060-EMI", _index(LIVE))

    assert hint.nearest == LIVE


def test_an_id_of_the_wrong_shape_is_called_that():
    hint = check_tracking_ids.find_hint("QRREP-58", _index(LIVE))

    assert "shape" in hint.why.lower()


def test_a_malformed_id_still_gets_its_typo_named():
    """The shape note is the symptom; the ID one character away is the cause.

    A dropped separator is both at once: four parts instead of five, and one
    deletion away from the real thing.
    """
    hint = check_tracking_ids.find_hint("QRREP0000058-240709-0000060-EMI", _index(LIVE))

    assert "shape" in hint.why.lower()
    assert hint.nearest == LIVE


def test_nothing_close_produces_no_hint():
    hint = check_tracking_ids.find_hint("ZZZZZ-0000001-200101-0000001-XXX", _index(LIVE))

    assert not hint
    assert hint.text == ""


def test_the_hint_joins_into_one_string_for_a_file():
    hint = check_tracking_ids.find_hint(LIVE, _index(OTHER_CHANNEL))

    assert hint.text == f"wrong channel, it is INT: {OTHER_CHANNEL}"


def test_every_id_present_exits_zero_and_says_so(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _ids(tmp_path, LIVE)

    exit_code = check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])

    assert exit_code == 0
    assert "OK:" in capsys.readouterr().out


def test_a_missing_id_is_printed_with_its_hint_and_exits_nonzero(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (OTHER_CHANNEL, "1", "A"))
    ids = _ids(tmp_path, LIVE)

    exit_code = check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert LIVE in out
    assert "channel" in out.lower()


def test_the_report_prints_the_id_the_hint_points_at_in_full(tmp_path, capsys):
    """A hint that ends in an ellipsis is no hint -- the ID is its whole point.

    It was one: reason and candidate shared a column, and at 32 characters the
    candidate is what the table dropped.
    """
    _export(tmp_path, "InternalCommunicationActivities.csv", (OTHER_CHANNEL, "1", "A"))
    ids = _ids(tmp_path, LIVE)

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])

    assert OTHER_CHANNEL in capsys.readouterr().out


def test_the_found_ids_stay_a_number_until_all_is_asked_for(tmp_path, capsys):
    """The list is something the reader already has; the missing rows are not."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _ids(tmp_path, LIVE)

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])
    quiet = capsys.readouterr().out
    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--all"])
    loud = capsys.readouterr().out

    assert "Quarterly report" not in quiet
    assert "Quarterly report" in loud


def test_a_repeat_in_the_list_is_named_rather_than_shown_twice(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE, LIVE)

    assert check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Searched" in out
    assert "listed more than once" in out


def test_an_empty_list_is_an_error_not_a_pass(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, "# nothing but a heading")

    assert check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)]) == 1
    assert "no tracking IDs" in capsys.readouterr().out


def test_the_list_beside_the_launcher_is_found_without_being_named(tmp_path):
    _xlsx(tmp_path, ("Tracking ID",), (LIVE,))

    assert check_tracking_ids.default_id_list(tmp_path).name == "ids.xlsx"


def test_a_text_list_is_found_when_there_is_no_workbook(tmp_path):
    _ids(tmp_path, LIVE)

    assert check_tracking_ids.default_id_list(tmp_path).name == "ids.txt"


def test_a_folder_holding_both_lists_is_an_error_not_a_precedence_rule(tmp_path):
    """They only both exist because one was converted from the other.

    The moment they disagree, quietly reading the one the operator is not
    editing answers from a list nobody checked.
    """
    _xlsx(tmp_path, ("Tracking ID",), (LIVE,))
    _ids(tmp_path, ARCHIVED)

    with pytest.raises(check_tracking_ids.IdListError) as error:
        check_tracking_ids.default_id_list(tmp_path)

    message = str(error.value)
    assert "ids.xlsx" in message and "ids.txt" in message


def test_a_folder_holding_no_list_at_all_finds_nothing(tmp_path):
    assert check_tracking_ids.default_id_list(tmp_path) is None


def test_a_run_without_ids_reads_the_list_that_is_lying_there(tmp_path, capsys, monkeypatch):
    """Put the file down, double-click the launcher -- that is the whole flow."""
    monkeypatch.setattr(check_tracking_ids, "LIST_DIR", tmp_path)
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    _xlsx(tmp_path, ("Tracking ID",), (LIVE,))

    exit_code = check_tracking_ids.main(["--input", str(tmp_path)])

    assert exit_code == 0
    assert "ids.xlsx" in capsys.readouterr().out


def test_a_run_without_ids_and_without_a_list_says_what_to_put_where(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(check_tracking_ids, "LIST_DIR", tmp_path)
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))

    exit_code = check_tracking_ids.main(["--input", str(tmp_path)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "ids.xlsx" in out and "--ids" in out


def test_a_sheet_with_nothing_under_its_header_names_the_sheet(tmp_path, capsys):
    """Which sheet was read is the whole question when a workbook has several."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _xlsx(tmp_path, ("Tracking ID",), (LIVE,), more=[("Q4", [("Tracking ID",)])])

    exit_code = check_tracking_ids.main(
        ["--ids", str(ids), "--input", str(tmp_path), "--sheet", "Q4"]
    )

    assert exit_code == 1
    assert "Q4" in capsys.readouterr().out


def test_a_missing_id_file_says_which_one(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    absent = tmp_path / "nope.txt"

    assert check_tracking_ids.main(["--ids", str(absent), "--input", str(tmp_path)]) == 1
    assert "nope.txt" in capsys.readouterr().out


def test_a_folder_without_an_activity_export_says_so(tmp_path, capsys):
    ids = _ids(tmp_path, LIVE)

    assert check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)]) == 1
    assert "no activity export found" in capsys.readouterr().out


def test_the_csv_carries_found_and_missing_rows_without_all(tmp_path, capsys):
    """A file is read by a spreadsheet, not by a person -- --all does not gate it."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _ids(tmp_path, LIVE, ARCHIVED)
    out_csv = tmp_path / "result.csv"

    exit_code = check_tracking_ids.main(
        ["--ids", str(ids), "--input", str(tmp_path), "--csv", str(out_csv)]
    )

    assert exit_code == 1
    with open(out_csv, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    assert [r["id"] for r in rows] == [LIVE, ARCHIVED]
    assert rows[0]["status"] == "found"
    assert rows[0]["source_file"] == "internal"
    assert rows[0]["sp_id"] == "1"
    assert rows[0]["activity_name"] == "Quarterly report"
    assert rows[0]["hint"] == ""
    assert rows[1]["status"] == "missing"
    assert rows[1]["source_file"] == ""
    assert rows[1]["activity_name"] == ""


def test_the_csv_hint_is_the_whole_sentence(tmp_path):
    """The terminal splits it over two columns; a file has room for one string."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (OTHER_CHANNEL, "1", "A"))
    ids = _ids(tmp_path, LIVE)
    out_csv = tmp_path / "result.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--csv", str(out_csv)])

    with open(out_csv, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["hint"] == f"wrong channel, it is INT: {OTHER_CHANNEL}"


def test_the_csv_path_is_named_in_the_report(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE)
    out_csv = tmp_path / "result.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--csv", str(out_csv)])

    assert "result.csv" in capsys.readouterr().out


def test_the_columns_from_an_excel_list_stand_beside_the_answer(tmp_path):
    """The result goes back to whoever sent the list -- with their own columns."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _xlsx(
        tmp_path,
        ("Kampagne", "Tracking ID", "Notiz"),
        ("Q3", LIVE, "aus der Mail"),
        ("Q3", ARCHIVED, ""),
    )
    out_csv = tmp_path / "result.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--out", str(out_csv)])

    with open(out_csv, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    assert list(rows[0]) == list(check_tracking_ids.CSV_COLUMNS) + ["Kampagne", "Notiz"]
    assert rows[0]["Kampagne"] == "Q3"
    assert rows[0]["Notiz"] == "aus der Mail"
    assert rows[1]["Notiz"] == ""


def test_a_text_list_leaves_the_result_columns_exactly_as_they_were(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE)
    out_csv = tmp_path / "result.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--out", str(out_csv)])

    with open(out_csv, newline="", encoding="utf-8-sig") as handle:
        assert next(csv.reader(handle)) == list(check_tracking_ids.CSV_COLUMNS)


def test_the_default_result_is_a_workbook_named_for_the_day(tmp_path):
    path = check_tracking_ids.default_output_path()

    assert path.suffix == ".xlsx"
    assert path.parent == check_tracking_ids.REPORTS_DIR
    assert datetime.now().strftime("%Y_%m_%d") in path.name


def test_a_run_that_names_no_file_still_writes_the_workbook(tmp_path, capsys):
    """Excel in, Excel out: the file is the point, not a flag to remember."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _ids(tmp_path, LIVE)

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)])

    written = check_tracking_ids.default_output_path()
    assert written.is_file()
    assert written.name in capsys.readouterr().out


def test_the_workbook_carries_every_id_with_its_own_columns(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "Quarterly report"))
    ids = _xlsx(tmp_path, ("Tracking ID", "Kampagne"), (LIVE, "Q3"), (ARCHIVED, "Q4"))
    out = tmp_path / "result.xlsx"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--out", str(out)])

    openpyxl = pytest.importorskip("openpyxl")
    sheet = openpyxl.load_workbook(out).worksheets[0]
    rows = [[cell.value for cell in row] for row in sheet.iter_rows()]

    assert rows[0] == list(check_tracking_ids.CSV_COLUMNS) + ["Kampagne"]
    assert rows[1][:2] == [LIVE, "found"]
    assert rows[1][-1] == "Q3"
    assert rows[2][:2] == [ARCHIVED, "missing"]


def test_the_workbook_header_stays_put_and_filters(tmp_path):
    """Filtering to the missing rows is the one thing this file is opened for."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE, ARCHIVED)
    out = tmp_path / "result.xlsx"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--out", str(out)])

    openpyxl = pytest.importorskip("openpyxl")
    sheet = openpyxl.load_workbook(out).worksheets[0]

    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:F3"


def test_an_out_path_ending_in_csv_still_writes_a_csv(tmp_path):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE)
    out = tmp_path / "result.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--out", str(out)])

    with open(out, newline="", encoding="utf-8-sig") as handle:
        assert [r["id"] for r in csv.DictReader(handle)] == [LIVE]


def test_an_unknown_out_extension_names_the_two_it_knows(tmp_path, capsys):
    """Guessing a format would write the file the caller did not ask for."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE)

    exit_code = check_tracking_ids.main(
        ["--ids", str(ids), "--input", str(tmp_path), "--out", str(tmp_path / "result.txt")]
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert ".xlsx" in out and ".csv" in out


def test_the_csv_flag_still_names_the_file_it_always_did(tmp_path):
    """The older flag stays: notes and scripts already carry it."""
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    ids = _ids(tmp_path, LIVE)
    out = tmp_path / "old-way.csv"

    check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path), "--csv", str(out)])

    assert out.is_file()
    assert not check_tracking_ids.default_output_path().exists()
