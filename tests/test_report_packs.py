"""Linking an activity to its pack, and saying how well it linked."""

import pytest

pytest.importorskip("pandas")

import pandas as pd

from pipeline.report import packs


def _frame(*values):
    return pd.DataFrame({packs.PACK_LINK_COLUMN: list(values)})


def _packs(*ids):
    return pd.DataFrame({"cpid": list(ids), "pack_name": [f"Pack {i}" for i in ids]})


def test_an_activity_naming_no_pack_is_not_a_failed_link():
    """Three states, not two. An empty reference is an unplanned activity;
    a reference resolving to nothing is a broken one. Folding the first into
    the second would report a data problem that is not there.
    """
    marked = packs.mark(_frame("CP-1", "", None), _packs("CP-1"))
    assert list(marked["pack_known"]) == ["Yes", "", ""]


def test_a_reference_to_a_pack_that_is_not_in_the_list_says_so():
    marked = packs.mark(_frame("CP-1", "CP-9"), _packs("CP-1"))
    assert list(marked["pack_known"]) == ["Yes", "No"]


def test_the_rate_is_over_referenced_rows_only():
    result = packs.link(_frame("CP-1", "CP-9", ""), _packs("CP-1"))
    assert result.referenced == 2
    assert result.matched == 1
    assert result.rate == 0.5


def test_matching_ignores_case_and_padding():
    """The identifier travels through SharePoint lookups and CSV round-trips.
    A link that breaks on a trailing space is a link that breaks in
    production and nowhere else.
    """
    marked = packs.mark(_frame(" cp-1 "), _packs("CP-1"))
    assert list(marked["pack_known"]) == ["Yes"]


def test_no_pack_list_leaves_the_frame_alone():
    """No export means no column. An empty `pack_known` on every row would
    assert a check nobody ran.
    """
    marked = packs.mark(_frame("CP-1"), None)
    assert "pack_known" not in marked.columns


def test_activity_counts_are_per_pack_identifier():
    counts = packs.activity_counts(_frame("CP-1", "CP-1", "CP-2", ""), _packs("CP-1", "CP-2"))
    assert counts == {"CP-1": 2, "CP-2": 1}
