"""Per-row derivations for the calendar report.

Each of these turns one or two raw source fields into a value the report groups
or filters on. They are deliberately small and separately tested: the reach
constants in particular are guesses against the live vocabulary and are expected
to be adjusted after the first real run.
"""

import math
import re

from pipeline.report.config import (
    BAND_10_50K,
    BAND_1_10K,
    BAND_50_100K,
    BAND_OVER_100K,
    BAND_UNDER_1K,
    BAND_UNKNOWN,
)

REACH_GROUP_WIDE = "Group-wide"
REACH_MULTI_DIVISION = "Multi-division"
REACH_SINGLE_DIVISION = "Single division"
REACH_REGIONAL_ONLY = "Regional only"
REACH_UNCLASSIFIED = "Unclassified"

# Ordered widest-first, which is the order the Calendar sheet lists them in.
REACH_ORDER = (
    REACH_GROUP_WIDE,
    REACH_MULTI_DIVISION,
    REACH_SINGLE_DIVISION,
    REACH_REGIONAL_ONLY,
    REACH_UNCLASSIFIED,
)

# Naming this many divisions or more is treated as addressing the whole
# organisation. A guess against the live vocabulary -- revisit after a real run.
GROUP_WIDE_MIN_DIVISIONS = 3
GLOBAL_REGION_TOKENS = frozenset({"global", "worldwide", "all regions"})


def _text(value):
    """Source values arrive as str, None, or pandas NaN. Normalise to a string."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def split_multi(value):
    """SharePoint multi-value lookups arrive joined, e.g. "IB, P&C"."""
    text = _text(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"[;,]", text) if part.strip()]


def classify_reach(business_division, region):
    """One mutually exclusive bucket per activity, so the block sums to the total."""
    divisions = split_multi(business_division)
    regions = [r.lower() for r in split_multi(region)]

    if any(r in GLOBAL_REGION_TOKENS for r in regions):
        return REACH_GROUP_WIDE
    if len(divisions) >= GROUP_WIDE_MIN_DIVISIONS:
        return REACH_GROUP_WIDE
    if len(divisions) > 1:
        return REACH_MULTI_DIVISION
    if len(divisions) == 1:
        return REACH_SINGLE_DIVISION
    if regions:
        return REACH_REGIONAL_ONLY
    return REACH_UNCLASSIFIED


# Boundaries in ascending order: (upper bound inclusive, band).
_BAND_BOUNDS = (
    (999, BAND_UNDER_1K),
    (9_999, BAND_1_10K),
    (49_999, BAND_10_50K),
    (100_000, BAND_50_100K),
)

_NUMERIC = re.compile(r"^\d[\d\s.,']*$")

_BAND_LOOKUP = {
    "<1000": BAND_UNDER_1K,
    "under1000": BAND_UNDER_1K,
    "1-10k": BAND_1_10K,
    "10-50k": BAND_10_50K,
    "50-100k": BAND_50_100K,
    ">100k": BAND_OVER_100K,
    "over100k": BAND_OVER_100K,
}


def _as_number(text):
    if not _NUMERIC.match(text):
        return None
    digits = re.sub(r"[\s.,']", "", text)
    return int(digits) if digits else None


def _normalise_band(text):
    """Fold dash variants and whitespace so label matching is not typography."""
    folded = text.lower()
    folded = re.sub(r"[‐-―−]", "-", folded)
    return re.sub(r"\s+", "", folded)


def audience_band(value):
    """Map a raw count or a band label onto one of the five known bands.

    The source field is heterogeneous: raw counts from some exports, band labels
    from the studio. Whether it carries the "Estimated audience size" value at
    all is an assumption recorded in the knowledge base; concentrating it here
    means there is one place to correct it.
    """
    text = _text(value)
    if not text:
        return BAND_UNKNOWN

    number = _as_number(text)
    if number is not None:
        for upper, band in _BAND_BOUNDS:
            if number <= upper:
                return band
        return BAND_OVER_100K

    return _BAND_LOOKUP.get(_normalise_band(text), BAND_UNKNOWN)


def has_executives(value):
    """Involvement means the source field carries anything after stripping."""
    return bool(_text(value))


_PRIORITY_WORDS = {"critical": 4, "high": 3, "medium": 2, "normal": 1, "low": 0}


def priority_rank(value):
    """Rank a priority the way the studio does (analytics.js::priorityRank).

    Two vocabularies are live at once: the studio's words, and the source
    system's numbered labels where 1 is most urgent. A leading integer wins
    because it is unambiguous; the words are the fallback; anything else lands
    mid-rank rather than silently reading as low.
    """
    text = _text(value)
    numbered = re.match(r"^(\d+)", text)
    if numbered:
        return max(0, 5 - int(numbered.group(1)))
    return _PRIORITY_WORDS.get(text.lower(), 1)
