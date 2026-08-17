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


def _chain_frame(field, tracking):
    return pd.DataFrame({packs.PACK_LINK_COLUMN: list(field),
                         packs.TRACKING_LINK_COLUMN: list(tracking)})


def test_the_field_wins_wherever_it_names_a_pack():
    """The deliberate answer outranks the generated one.

    Someone chose the value in the pack field. The tracking ID's pack segment
    is stamped in at creation and cannot be corrected afterwards, so where
    the two disagree -- 15 activities on the live export -- the field is the
    one to believe.
    """
    resolved = packs.resolve(_chain_frame(["CP-1"], ["CP-2"]), _packs("CP-1", "CP-2"))

    assert list(resolved["pack_cpid_used"]) == ["CP-1"]
    assert list(resolved["pack_source"]) == [packs.SOURCE_FIELD]


def test_an_empty_field_falls_back_to_the_tracking_id():
    resolved = packs.resolve(_chain_frame([""], ["CP-2"]), _packs("CP-1", "CP-2"))

    assert list(resolved["pack_cpid_used"]) == ["CP-2"]
    assert list(resolved["pack_source"]) == [packs.SOURCE_TRACKING]


def test_the_fallback_only_takes_a_value_the_pack_list_answers_to():
    """The rule that keeps 16,604 activities out of a pack they never had.

    Every tracking ID carries a pack segment, and a standalone activity's is
    a placeholder. Falling back to whatever the segment says would hand nine
    out of ten activities a pack named `CCCCC-0000000`, which is not a pack
    and is in no list. Matching against the pack list first is what makes the
    placeholder fail to resolve and stay unassigned.
    """
    resolved = packs.resolve(_chain_frame(["", ""], ["CCCCC-0000000", "CP-1"]),
                             _packs("CP-1"))

    assert list(resolved["pack_cpid_used"]) == ["", "CP-1"]
    assert list(resolved["pack_source"]) == ["", packs.SOURCE_TRACKING]


def test_a_field_naming_no_pack_still_yields_to_a_tracking_id_that_does():
    """`NONE` is the opposite of a pack reference, not a pack reference.

    Three activities on the live export carry the literal text `NONE` in the
    pack field. Read as "the field is filled, so use it", that text would
    block the fallback on exactly the rows where the tracking ID names a real
    pack -- and leave the pack file counting a pack called NONE.
    """
    resolved = packs.resolve(_chain_frame(["NONE"], ["CP-1"]), _packs("CP-1"))

    assert list(resolved["pack_cpid_used"]) == ["CP-1"]
    assert list(resolved["pack_source"]) == [packs.SOURCE_TRACKING]


def test_a_dead_reference_stays_visible_when_nothing_else_answers():
    """A value that resolves nowhere is a finding, and deleting it hides one.

    The chain is about filling gaps, not about tidying away references the
    pack list cannot match. Kept as it is, `pack_known` still reports it as
    a reference to a pack that is not in the list.
    """
    resolved = packs.resolve(_chain_frame(["CP-9"], ["CCCCC-0000000"]), _packs("CP-1"))

    assert list(resolved["pack_cpid_used"]) == ["CP-9"]
    assert list(resolved["pack_source"]) == [packs.SOURCE_FIELD]


def test_without_a_pack_list_nothing_is_derived():
    """No list, no way to tell a pack from a placeholder.

    Deriving here would assign the tracking ID's segment to every activity
    that has one -- nine in ten of them -- and call the placeholder a pack.
    The column still appears, carrying the field alone, so everything
    downstream can read one column on every machine.
    """
    resolved = packs.resolve(_chain_frame(["CP-1", ""], ["CP-2", "CP-2"]), None)

    assert list(resolved["pack_cpid_used"]) == ["CP-1", ""]
    assert list(resolved["pack_source"]) == [packs.SOURCE_FIELD, ""]


def test_activity_counts_are_per_pack_identifier():
    counts = packs.activity_counts(_frame("CP-1", "CP-1", "CP-2", ""), _packs("CP-1", "CP-2"))
    assert counts == {"CP-1": 2, "CP-2": 1}


def test_activities_can_be_counted_through_the_tracking_id_instead():
    """The second count, over the identifier the tracking ID spells out.

    A pack is named twice on an activity: in the pack field, which is filled
    by hand and often is not, and in the first two segments of the generated
    tracking ID. Counting only the first is why a pack with 110 activities
    carrying its number reported five -- the five that also had the field
    filled. The same counting rule reads the other column rather than a
    second rule that could drift from it.
    """
    frame = pd.DataFrame({
        packs.PACK_LINK_COLUMN: ["CP-1", "", "", ""],
        packs.TRACKING_LINK_COLUMN: ["CP-1", "CP-1", "CP-1", "CP-2"],
    })

    by_field = packs.activity_counts(frame, _packs("CP-1", "CP-2"))
    by_tracking = packs.activity_counts(frame, _packs("CP-1", "CP-2"),
                                        packs.TRACKING_LINK_COLUMN)

    assert by_field == {"CP-1": 1, "CP-2": 0}
    assert by_tracking == {"CP-1": 3, "CP-2": 1}
