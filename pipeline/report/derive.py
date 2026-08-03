"""Per-row derivations for the calendar report.

Each of these turns one or two raw source fields into a value the report groups
or filters on. They are deliberately small and separately tested, because the
source vocabulary is only partly known and these are the places to correct it.
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


def _as_number(value):
    # Handle numeric types directly, truncating toward zero. This bypasses string
    # round-trip ambiguities: a pandas upcasted float64 column reads correctly.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)

    # String path: treat . as a decimal point, not a separator. This field is
    # written by machine exports, which emit "4200.00" for a count, not "12.000"
    # European-formatted data would need a different reader.
    text = str(value).strip()
    if not _NUMERIC.match(text):
        return None
    # Strip only whitespace, comma and apostrophe; keep decimal point.
    stripped = re.sub(r"[\s,']", "", text)
    # Accept integers or decimals; take only the integer part.
    decimal_match = re.match(r"^(\d+)", stripped)
    if decimal_match:
        return int(decimal_match.group(1))
    return None


def _normalise_band(text):
    """Fold typography so label matching is not spelling.

    Dash variants, case and whitespace, plus thousands separators: a source
    writing "< 1.000" or "< 1'000" means the same band as "< 1000" and used to
    fall through to Unknown. Only the *label* path calls this -- a raw count has
    already been read as a number by then -- so dropping separators here cannot
    turn one number into another.
    """
    folded = text.lower()
    folded = re.sub(r"[‐-―−]", "-", folded)
    folded = re.sub(r"[.,']", "", folded)
    return re.sub(r"\s+", "", folded)


def audience_band(value):
    """Map a raw count or a band label onto one of the five known bands.

    The source field is heterogeneous: raw counts from some exports, band labels
    from the studio. Whether it carries the "Estimated audience size" value at
    all is an assumption recorded in the knowledge base; concentrating it here
    means there is one place to correct it.
    """
    # Try numeric path first, handling both raw numeric types and string forms.
    number = _as_number(value)
    if number is not None:
        for upper, band in _BAND_BOUNDS:
            if number <= upper:
                return band
        return BAND_OVER_100K

    # Fall back to band label lookup.
    text = _text(value)
    if not text:
        return BAND_UNKNOWN
    return _BAND_LOOKUP.get(_normalise_band(text), BAND_UNKNOWN)


PERSON_SEPARATOR = "; "


def split_people(value):
    """The people named in one cell.

    Semicolon only -- never comma. A person picker's display names arrive as
    "Last, First", so the comma belongs *inside* a name; splitting on it turns
    two people into four fragments. The source itself separates several people
    with a semicolon, and the ETL joins person arrays the same way, so this is
    the one separator that means "next person" in both paths.
    """
    text = _text(value)
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def person_name(text):
    """"Last, First" read as "First Last"; anything else left alone.

    Exactly one comma is the pattern the source writes. Zero commas is already
    a plain name. Two or more is one of the inconsistencies the source is known
    to contain -- no rule would reliably say which part is which, so it is
    passed through verbatim rather than mangled into a confident guess.
    """
    parts = text.split(",")
    if len(parts) != 2:
        return text.strip()
    last, first = (part.strip() for part in parts)
    if not last or not first:
        return text.strip()
    return f"{first} {last}"


def executive_names(value):
    """The people named in the source field, normalised and semicolon-joined.

    Names come out as "First Last" -- which is what a reader expects, and which
    also leaves no comma behind for a downstream splitter to trip over. Where a
    name does not follow the source's "Last, First" pattern it is kept as it
    stands; the semicolon join means an unexpected comma is still safe.
    """
    return PERSON_SEPARATOR.join(person_name(name) for name in split_people(value))


def has_executives(value):
    """Involvement means at least one person is named."""
    return bool(executive_names(value))


def only_excluded_objectives(value, prefixes):
    """True when every objective named on the row starts with one of `prefixes`.

    The point of the filter is to drop the catch-all bucket, not the activities
    that merely touch it. An activity tagged "2026: Other" *and* a real
    objective is planned against something, so it stays; only one tagged with
    nothing but catch-alls goes.

    A row naming no objectives at all is not "nothing but the catch-all" -- it
    is unclassified, a different gap that the Data Quality sheet already counts.
    It stays too, so this filter can never silently swallow the empty case.
    """
    labels = split_multi(value)
    if not labels:
        return False
    wanted = tuple(_text(p).lower() for p in prefixes if _text(p))
    if not wanted:
        return False
    return all(label.lower().startswith(wanted) for label in labels)


def priority_number(value):
    """The source system's leading priority number, or None.

    Only the numbered vocabulary has one. The studio's words (Critical, High,
    Medium, Low) carry no number and cannot be mapped onto one without
    inventing a correspondence, so they return None and any filter built on
    this leaves them alone rather than guessing.
    """
    match = re.match(r"^(\d+)", _text(value))
    return int(match.group(1)) if match else None


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
