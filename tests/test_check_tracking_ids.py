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

    assert "channel" in hint.lower()
    assert OTHER_CHANNEL in hint


def test_a_missing_activity_in_an_existing_pack_names_the_pack():
    hint = check_tracking_ids.find_hint(LIVE, _index(SAME_PACK))

    assert "QRREP-0000058" in hint
    assert "pack" in hint.lower()


def test_the_channel_rung_wins_when_both_would_hit():
    """Rung 1 is the more specific answer, so it must be reached first."""
    hint = check_tracking_ids.find_hint(LIVE, _index(SAME_PACK, OTHER_CHANNEL))

    assert OTHER_CHANNEL in hint
    assert SAME_PACK not in hint


def test_one_character_off_is_named_as_a_typo():
    """A different cluster, so rungs 1 and 2 cannot fire -- only the distance does.

    An ID one letter off *within* the same pack is rung 1's case, not this one.
    """
    wanted = "QRREQ-0000058-240709-0000060-EMI"  # QRREQ, not QRREP

    hint = check_tracking_ids.find_hint(wanted, _index(LIVE))

    assert LIVE in hint
    assert "one character" in hint.lower()


def test_a_dropped_character_counts_as_one_edit():
    hint = check_tracking_ids.find_hint("QRREP-000058-240709-0000060-EMI", _index(LIVE))

    assert LIVE in hint


def test_an_id_of_the_wrong_shape_is_called_that():
    hint = check_tracking_ids.find_hint("QRREP-58", _index(LIVE))

    assert "shape" in hint.lower() or "part" in hint.lower()


def test_nothing_close_produces_no_hint():
    hint = check_tracking_ids.find_hint("ZZZZZ-0000001-200101-0000001-XXX", _index(LIVE))

    assert hint == ""
