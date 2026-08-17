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


def mark(frame, pack_frame, column=PACK_LINK_COLUMN):
    """Add `pack_known` -- "Yes", "No", or "" where no pack is named.

    Three states rather than two. An empty reference and a reference to a
    pack that is not in the list are different facts, and the second is the
    data-quality finding; folding them together would hide it inside the
    ordinary business of activities that belong to no pack.

    Without a pack list the column is absent entirely, because an empty
    `pack_known` on every row would assert a check nobody ran.

    `column` selects which identifier is being judged, for the reason
    `activity_counts` takes one: after the chain the question is about the
    pack the activity was resolved to, not about the field alone.
    """
    known = _pack_keys(pack_frame)
    if known is None or column not in frame.columns:
        return frame
    frame = frame.copy()
    frame["pack_known"] = [
        "" if not key(value) else ("Yes" if key(value) in known else "No")
        for value in frame[column]
    ]
    return frame


# Where a resolved pack came from. Written beside the value, never inferred
# from it: once the two routes are merged into one column, a figure computed
# from it cannot be traced back without this, and "the pack field said so" and
# "the tracking ID implied it" are not the same claim about an activity.
SOURCE_FIELD = "pack field"
SOURCE_TRACKING = "tracking ID"

RESOLVED_COLUMN = "pack_cpid_used"
RESOLVED_NAME_COLUMN = "pack_name_used"
SOURCE_COLUMN = "pack_source"


def resolve(frame, pack_frame):
    """Add the pack each activity belongs to, and where that came from.

    The field first, the tracking ID second, in three steps:

    1. The pack field, wherever it names a pack the list answers to. Someone
       chose that value; the tracking ID's segment is stamped in at creation
       and cannot be corrected afterwards, so where the two disagree the
       field wins.
    2. Otherwise the tracking ID's pack segment, and only when the pack list
       answers to it. That condition is what keeps the placeholder out: every
       tracking ID carries a pack segment, a standalone activity's is generic,
       and a fallback that took the segment as written would hand nine out of
       ten activities a pack that does not exist.
    3. Otherwise the field's own value, unchanged. A reference nothing
       answers to is a finding, and `pack_known` is where it is reported --
       dropping it here would tidy the finding away.

    Without a pack list nothing is derived at all: with nothing to match
    against, step 2 cannot tell a pack from a placeholder. The columns are
    still written, carrying the field alone, so every reader downstream can
    read one column on every machine.
    """
    # A frame with no rows is left exactly as it is. Every filter can empty a
    # scope, and the empty one the report builds carries no columns at all --
    # three empty columns bolted onto it would be a shape no reader of an
    # empty frame expects, describing rows that do not exist.
    if not len(frame):
        return frame

    # An empty set, not None: no pack list and an empty one lead to the same
    # place here -- there is nothing to recognise a pack by, so step 2 cannot
    # run and every membership test below is simply false.
    known = _pack_keys(pack_frame) or set()
    names = {}
    if pack_frame is not None and "pack_name" in getattr(pack_frame, "columns", []):
        names = {key(cpid): name
                 for cpid, name in zip(pack_frame["cpid"], pack_frame["pack_name"])
                 if key(cpid)}

    field = frame[PACK_LINK_COLUMN] if PACK_LINK_COLUMN in frame.columns else None
    tracking = (frame[TRACKING_LINK_COLUMN]
                if known and TRACKING_LINK_COLUMN in frame.columns else None)

    used, sources, used_names = [], [], []
    for index in range(len(frame)):
        raw = field.iloc[index] if field is not None else None
        from_field = key(raw)
        from_tracking = key(tracking.iloc[index]) if tracking is not None else ""

        if from_field and from_field in known:
            value, source = from_field, SOURCE_FIELD
        elif from_tracking and from_tracking in known:
            value, source = from_tracking, SOURCE_TRACKING
        elif from_field:
            value, source = from_field, SOURCE_FIELD
        else:
            value, source = "", ""

        used.append(value)
        sources.append(source)
        used_names.append(names.get(value, ""))

    frame = frame.copy()
    frame[RESOLVED_COLUMN] = used
    frame[SOURCE_COLUMN] = sources
    # The name the pack list gives it, not the one the activity carries: for a
    # row resolved through the tracking ID the activity has no pack name at
    # all, and a column that is empty on exactly those rows cannot be grouped
    # by -- which is how a reader asks about packs.
    frame[RESOLVED_NAME_COLUMN] = [
        name or ("" if not value else _activity_pack_name(frame, index))
        for index, (value, name) in enumerate(zip(used, used_names))
    ]
    return frame


def _activity_pack_name(frame, index):
    """The pack name the activity itself carries, where the list has none."""
    if "communication_pack" not in frame.columns:
        return ""
    value = frame["communication_pack"].iloc[index]
    return "" if value is None or value != value else str(value)


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
