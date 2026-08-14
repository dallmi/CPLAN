"""Linking an activity to its communication pack, and saying how well it linked.

Which activity column carries the pack identifier is not obvious from the
exports: three are plausible, and picking one by reasoning would put an
unverified assumption under `07-packs.csv`, where a wrong join does not look
wrong. `pipeline/scripts/check_pack_link.py` measures all three against a real
export. This module holds the answer it produced and the rule that keeps it
honest -- a rate reported on every run, and a warning when it drops.
"""

from typing import NamedTuple

# Measured with `pipeline/scripts/check_pack_link.py` against the live export
# of 2026-08-11: 18,425 activities against 342 pack rows.
#
#   communication_pack_cpid   1,844 referenced   1,842 matched   203 packs
#   campaign_ltid               149 referenced     149 matched    12 packs
#   tracking_pack_id         18,394 referenced   1,829 matched   202 packs
#
# The first two both resolved every reference they carried, so the rate could
# not choose between them; reach did. `campaign_ltid` answers for 12 of 342
# packs and its values sit in another namespace (`CCCCC-…` against the pack
# list's `3KEYS-…`) -- an identifier that happens to match a few rows, not the
# pack link. `tracking_pack_id` reaches almost as many packs but resolves only
# a tenth of what it carries, because nearly every activity has a tracking ID
# and most of the pack numbers inside them name no pack row.
#
# Two figures worth carrying forward, both from that run: only a tenth of
# activities reference a pack at all, and 139 of 342 packs had no activity
# pointing at them. Neither is a defect in this join.
#
# Re-run the diagnostic when the export changes shape, and change this line
# if it names a different winner.
PACK_LINK_COLUMN = "communication_pack_cpid"

# The same pack, named a second time and by a different route: the first two
# segments of the generated tracking ID, `<cluster>-<pack number>`, which the
# ETL splits out as `tracking_pack_id`.
#
# Not a replacement for the column above, and deliberately not scored against
# it here -- `check_pack_link.py` measured both on the export of 2026-08-14 and
# they resolve almost the same total by different routes: 1,848 activities
# through the pack field, 1,835 through the tracking ID, and only 1,733 rows
# where both name a pack at all. So neither contains the other, and a pack's
# two counts can differ in both directions.
#
# It exists because the pack field is filled by hand and often is not, while
# the tracking ID is generated for every activity. One pack carrying 110
# activities in its tracking IDs reported five, and nothing in the delivered
# files could say why.
TRACKING_LINK_COLUMN = "tracking_pack_id"

# Below this the run says so rather than presenting a badly joined file as a
# clean one. The same floor `check_pack_link.py` exits non-zero on.
MIN_LINK_RATE = 0.8


class LinkResult(NamedTuple):
    referenced: int
    matched: int

    @property
    def rate(self):
        """Matched over *referenced*, never over the row count.

        An activity that names no pack is an unplanned activity, not a failed
        link. In the denominator it would report a linking problem where
        there is only an empty field.
        """
        return self.matched / self.referenced if self.referenced else 0.0


def key(value):
    """The comparable form of an identifier, or "" when there is none.

    Trimmed and upper-cased on both sides: the identifier travels through
    SharePoint lookups and CSV round-trips, and a link that breaks on a
    trailing space breaks in production and nowhere else.

    Public because `agent_pack` keys its per-pack counts the same way. Two
    modules deriving the same key by two spellings is how a join starts
    disagreeing with the count printed beside it.
    """
    if value is None or value != value:
        return ""
    text = str(value).strip().upper()
    return "" if text in ("", "NAN", "NAT") else text


def _pack_keys(pack_frame):
    if pack_frame is None or "cpid" not in getattr(pack_frame, "columns", []):
        return None
    return {key(value) for value in pack_frame["cpid"]} - {""}


def link(frame, pack_frame):
    """Count how many pack references resolve to a row in the pack list."""
    known = _pack_keys(pack_frame)
    if known is None or PACK_LINK_COLUMN not in frame.columns:
        return LinkResult(0, 0)
    referenced = matched = 0
    for value in frame[PACK_LINK_COLUMN]:
        identifier = key(value)
        if not identifier:
            continue
        referenced += 1
        if identifier in known:
            matched += 1
    return LinkResult(referenced, matched)


def mark(frame, pack_frame):
    """Add `pack_known` -- "Yes", "No", or "" where no pack is named.

    Three states rather than two. An empty reference and a reference to a
    pack that is not in the list are different facts, and the second is the
    data-quality finding; folding them together would hide it inside the
    ordinary business of activities that belong to no pack.

    Without a pack list the column is absent entirely, because an empty
    `pack_known` on every row would assert a check nobody ran.
    """
    known = _pack_keys(pack_frame)
    if known is None or PACK_LINK_COLUMN not in frame.columns:
        return frame
    frame = frame.copy()
    frame["pack_known"] = [
        "" if not key(value) else ("Yes" if key(value) in known else "No")
        for value in frame[PACK_LINK_COLUMN]
    ]
    return frame


def activity_counts(frame, pack_frame, column=PACK_LINK_COLUMN):
    """Activities per pack identifier, over the rows in `frame`.

    Keyed on the pack list's own identifiers so a count can be looked up
    while writing the pack rows. References that match no pack are not
    counted here -- `pack_known` is where those are reported.

    `column` selects which of the two identifiers an activity is read
    through. One function rather than two, because the counting rule is the
    same rule and two copies of it would eventually disagree about a value
    with a trailing space -- and then the pack file would carry two counts
    that differ for a reason nobody could see.
    """
    known = _pack_keys(pack_frame)
    if known is None or column not in frame.columns:
        return {}
    by_key = {}
    for value in frame[column]:
        identifier = key(value)
        if identifier and identifier in known:
            by_key[identifier] = by_key.get(identifier, 0) + 1
    return {
        key(cpid): by_key.get(key(cpid), 0)
        for cpid in pack_frame["cpid"] if key(cpid)
    }
