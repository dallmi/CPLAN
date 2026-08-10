"""Tests for the tracking-ID check.

The question it answers is whether a list of IDs someone was handed exists in
the export at all -- and, when one does not, whether it is absent because the
activity was never created or because a suffix is wrong.
"""

import csv
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from pipeline.scripts import check_tracking_ids


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

    listed, counts = check_tracking_ids.read_id_list(path)

    assert listed == [
        "QRREP-0000058-240709-0000060-EMI",
        "QRREP-0000058-240709-0000061-INT",
    ]
    assert all(count == 1 for count in counts.values())


def test_a_repeated_id_is_listed_once_and_counted_twice(tmp_path):
    path = _ids(
        tmp_path,
        "QRREP-0000058-240709-0000060-EMI",
        "qrrep-0000058-240709-0000060-emi",
    )

    listed, counts = check_tracking_ids.read_id_list(path)

    assert listed == ["QRREP-0000058-240709-0000060-EMI"]
    assert counts["QRREP-0000058-240709-0000060-EMI"] == 2


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


def test_a_missing_id_file_says_which_one(tmp_path, capsys):
    _export(tmp_path, "InternalCommunicationActivities.csv", (LIVE, "1", "A"))
    absent = tmp_path / "nope.txt"

    assert check_tracking_ids.main(["--ids", str(absent), "--input", str(tmp_path)]) == 1
    assert "nope.txt" in capsys.readouterr().out


def test_a_folder_without_an_activity_export_says_so(tmp_path, capsys):
    ids = _ids(tmp_path, LIVE)

    assert check_tracking_ids.main(["--ids", str(ids), "--input", str(tmp_path)]) == 1
    assert "no activity export found" in capsys.readouterr().out
