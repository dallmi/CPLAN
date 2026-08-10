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
