"""A shape-only probe over a CPLAN database, for the phase-three modelling decisions.

    python -m pipeline.mcp.probe [--settings PATH]

Two planned changes -- making communication packs and tracking clusters
first-class records, and turning `audience` into an ordinal size column -- are
write-path schema changes touching the studio, the API and the sync. Both are
blocked on facts about a production database that cannot be copied out of the
corporate environment. This module answers those questions *in place* and prints
what it found.

**Nothing this module prints is a value out of the database.** It emits row
counts, fill rates, distinct cardinalities, bucket-size distributions and shape
classifications, and nothing else. Where an example would help, it prints a
redacted pattern -- `NNNN-NN-NNNNNN`, digits as `N`, letters as `A`/`a` -- never
the string that produced it. No activity name, campaign or pack label, lead,
person, audience label or identifier can reach stdout, whatever the database
holds. That is a property of the code rather than of the data: every value is
reduced to a count or a pattern before it is ever formatted. The report is
therefore safe to share out of the environment by construction, which is the
whole point -- an operator can run it and forward the output without reading the
source first.

Read-only in the same way the MCP server is (`create_read_only_engine`), and
backend-neutral in the same way `queries.py` is: the SQL is a plain column
projection that runs unchanged on PostgreSQL and on a local SQLite snapshot,
with every classification done in Python rather than in a dialect's regex or
cast syntax.

Deliberately free of any `mcp` import, like `queries.py` and `domain.py`: this
is a diagnostic script an operator runs, and requiring the MCP SDK to be
installed to run it would be a trap.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import inspect, select  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from pipeline.api.app import Activity  # noqa: E402
from pipeline.api.setup_backend import (  # noqa: E402
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)
from pipeline.mcp import queries  # noqa: E402
from pipeline.mcp.engine import create_read_only_engine  # noqa: E402


# ------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------


BANNER = """\
CPLAN schema probe -- SHAPE ONLY, SAFE TO SHARE
================================================================
This report contains counts, rates, distinct cardinalities and shape
classifications only. It contains no activity name, campaign or pack label,
lead, person, audience label or identifier from the database. Examples are
printed as redacted patterns (N = digit, A/a = letter), never as values.
It answers the two phase-three modelling questions: whether a tracking cluster
has a real key, and what shape the audience column actually holds."""

# The columns this probe reads. Everything else in `activities` -- names,
# descriptions, leads, emails -- is never selected at all, so it cannot leak
# through a formatting mistake either.
PROBED_COLUMNS: tuple[str, ...] = (
    "tracking_id",
    "campaign_ltid",
    "communication_pack_cpid",
    "communication_pack",
    "campaign",
    "audience",
    "extended_audience",
    "channel",
    "target_audience",
    "strategic_objectives",
    "bod_geb",
    "other_executives",
    "is_archive",
    "synced_version",
)

# The candidate cluster/pack keys, in the order the report discusses them. Two
# are stored columns, two are derived from the tracking id
# (`CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL`): the first segment is the candidate
# CLUSTER key, the first two are `ActivityRead.tracking_pack_id`, which
# `_pack_key` already uses as the second link of the pack chain.
CLUSTER_CANDIDATES: tuple[str, ...] = (
    "campaign_ltid",
    "tracking_cluster_segment",
    "tracking_pack_prefix",
    "communication_pack_cpid",
    "campaign",
)

# The two columns phase 2 disclosed as "holds combinations, matched whole",
# followed by the three already split everywhere, as a control: if the declared
# multi-value columns show a combination rate near zero on this database while
# channel and target_audience do not, that is a fact about this snapshot rather
# than about the ETL.
COMBINATION_COLUMNS: tuple[str, ...] = (
    "channel",
    "target_audience",
    "strategic_objectives",
    "bod_geb",
    "other_executives",
)

# How many redacted patterns to show per column. Enough to see whether a column
# has one shape or several; short enough that the report stays readable.
TOP_PATTERNS = 6

# Candidate keys whose pattern histogram is deliberately NOT printed.
#
# A redacted pattern is safe -- every alphanumeric character is masked -- but it
# still carries word count and word lengths, and for a free-text label with a
# four-value vocabulary that is the closest thing in this report to a
# fingerprint. `campaign` is such a label, and its pattern cannot change the
# answer to any phase-three question: the decision about `campaign` rests
# entirely on its bucket sizes, which are printed. So the pattern buys nothing
# and is left out. Every other candidate is being asked precisely whether it is
# a structured identifier, which is the question a pattern answers.
PATTERN_SUPPRESSED: frozenset[str] = frozenset({"campaign"})

# A redacted pattern longer than this is truncated. Free-text columns would
# otherwise produce a pattern as long as the value -- still leak-free (every
# alphanumeric is masked), but unreadable and pointlessly precise about length.
MAX_PATTERN_LENGTH = 40

_INTEGER = re.compile(r"^[+-]?\d+$")
_DECIMAL = re.compile(r"^[+-]?\d+[.,]\d+$")
# `1-10k`, `10 - 50k`, `1000 to 5000` -- two numbers with something between them.
_RANGE = re.compile(r"^[+-]?\d[\d.,]*\s*[a-z]?\s*(?:-|--|–|to)\s*\d[\d.,]*\s*[a-z]?$", re.IGNORECASE)
# `< 1000`, `>100k`, `up to 500`, `1000+`, `over 100000`.
_BOUNDED = re.compile(
    r"^(?:[<>]=?|≤|≥|under|over|up\s+to|more\s+than|less\s+than|at\s+least)?\s*"
    r"\d[\d.,]*\s*[a-z]?\s*\+?$",
    re.IGNORECASE,
)
# Thousands grouping the source system may write: `12,000`, `12'000`, `12 000`.
_GROUPED_INTEGER = re.compile(r"^[+-]?\d{1,3}(?:[,'\s]\d{3})+$")

SHAPES: tuple[str, ...] = ("blank", "integer", "decimal", "range", "bounded", "text")


# ------------------------------------------------------------------------
# Pure classifiers -- no session, no SQL, no value ever returned
# ------------------------------------------------------------------------


def value_shape(value: Any) -> str:
    """Which of `SHAPES` this value has, without saying what the value is.

    `blank` follows `queries.is_blank`, so the sync's `'None'` sentinel counts
    as empty here exactly as it does everywhere else in the MCP layer -- a
    column that is 40% literal `'None'` must not read as 40% filled.

    `integer` accepts thousands grouping (`12,000`, `12'000`, `12 000`): the
    question phase three has to answer is whether the column holds a headcount
    or a band label, and a grouped headcount is still a headcount.

    `range` and `bounded` are the two band shapes (`1-10k`, `< 1000`). They are
    kept apart from each other because a range band carries two numbers and an
    open band carries one, which is the difference between mapping bands onto an
    ordinal scale mechanically and having to decide what the open ends mean.
    """
    if queries.is_blank(value):
        return "blank"
    text = str(value).strip()
    if _INTEGER.match(text) or _GROUPED_INTEGER.match(text):
        return "integer"
    if _DECIMAL.match(text):
        return "decimal"
    if _RANGE.match(text):
        return "range"
    if _BOUNDED.match(text):
        return "bounded"
    return "text"


def as_integer(value: Any) -> int | None:
    """The integer `value` holds, or None if it does not hold one.

    Used only for the min/max of a numeric column -- an aggregate over the
    column, which the report may state, rather than a value it may print.
    """
    if value_shape(value) != "integer":
        return None
    text = re.sub(r"[,'\s]", "", str(value).strip())
    try:
        return int(text)
    except ValueError:  # pragma: no cover -- the regex already guaranteed it
        return None


def redacted_pattern(value: Any, *, max_length: int = MAX_PATTERN_LENGTH) -> str:
    """`value`'s character shape: digits as `N`, letters as `A`/`a`, rest kept.

    The only thing in this module that is derived from a value's content rather
    than counted, and the reason it is safe is that it is not reversible: every
    alphanumeric character is replaced, so what survives is punctuation, casing
    and length. `CLU-1-260110-0000001-EM` becomes `AAA-N-NNNNNN-NNNNNNN-AA`,
    which settles whether a column holds a structured id without disclosing one.

    Whitespace collapses to a single `_` so that patterns of the same shape but
    different spacing do not fragment the histogram.
    """
    if queries.is_blank(value):
        return "<blank>"
    text = str(value).strip()
    out: list[str] = []
    for char in text:
        if char.isdigit():
            out.append("N")
        elif char.isalpha():
            out.append("A" if char.isupper() else "a")
        elif char.isspace():
            out.append("_")
        else:
            out.append(char)
    pattern = "".join(out)
    if len(pattern) > max_length:
        return pattern[:max_length] + "..."
    return pattern


def combination_members(value: Any) -> list[str]:
    """The members of a possibly-combined value.

    Reuses `detect_collisions`' splitter deliberately (`,` OR `;`,
    unconditionally): the question being answered is whether making `channel`
    and `target_audience` properly multi-valued is worth a schema change, and
    the only honest way to answer it is with the exact splitter such a change
    would adopt. `queries.split_multi` is the wrong one here -- it treats those
    two columns as scalar on purpose.
    """
    return queries._normalize_multi(value)


def has_combination(value: Any) -> bool:
    """Whether this non-blank value holds more than one member."""
    return len(combination_members(value)) > 1


def tracking_segments(tracking_id: Any) -> list[str]:
    """The `-`-separated segments of a tracking id, or [] when it is blank."""
    if queries.is_blank(tracking_id):
        return []
    return str(tracking_id).strip().split("-")


def tracking_cluster_segment(tracking_id: Any) -> str | None:
    """The candidate CLUSTER key: the first segment of the tracking id.

    `None` when the id is blank or has no usable first segment -- so a row with
    a malformed id counts as unkeyed rather than as a cluster of its own.
    """
    segments = tracking_segments(tracking_id)
    if not segments or queries.is_blank(segments[0]):
        return None
    return segments[0].strip()


def tracking_pack_prefix(tracking_id: Any) -> str | None:
    """`CLUSTER-PACKNUM` -- the same rule as `ActivityRead.tracking_pack_id`."""
    segments = tracking_segments(tracking_id)
    if len(segments) < 2:
        return None
    prefix = f"{segments[0].strip()}-{segments[1].strip()}"
    return None if queries.is_blank(prefix.replace("-", "")) else prefix


# ------------------------------------------------------------------------
# Aggregators -- every one returns counts, never a value
# ------------------------------------------------------------------------


def _rate(part: int, whole: int) -> float:
    return 0.0 if whole == 0 else round(part / whole, 4)


def key_stats(values: Sequence[Any], total: int, *, patterns: bool = True) -> dict[str, Any]:
    """How well a candidate key fills, and how big its buckets are.

    The bucket-size distribution is what decides the question: a key that
    resolves 32 buckets of 2-11 rows identifies a planning unit, while one that
    resolves 2 buckets of 273 and 125 identifies the portfolio. Both look
    equally "filled" if only the fill rate is reported, which is why the
    quartiles are here.
    """
    present = [str(value).strip() for value in values if not queries.is_blank(value)]
    nulls = sum(1 for value in values if value is None)
    counts = Counter(present)
    sizes = sorted(counts.values())
    stats: dict[str, Any] = {
        "rows": total,
        "filled": len(present),
        "fill_rate": _rate(len(present), total),
        "null": nulls,
        # Blank-but-not-NULL: an empty string or the sync's 'None'/'null'
        # sentinel. Distinguishes "the sync never writes this column" from
        # "the sync writes it empty", which are different upstream problems.
        "blank_not_null": total - len(present) - nulls,
        "distinct": len(counts),
    }
    if sizes:
        stats.update(
            {
                "largest_bucket": sizes[-1],
                "smallest_bucket": sizes[0],
                "median_bucket": round(float(statistics.median(sizes)), 1),
                "singleton_buckets": sum(1 for size in sizes if size == 1),
                "largest_bucket_share": _rate(sizes[-1], len(present)),
                "top_patterns": pattern_histogram(present) if patterns else [],
            }
        )
    return stats


def pattern_histogram(values: Iterable[Any], *, limit: int = TOP_PATTERNS) -> list[dict[str, Any]]:
    """The most common redacted patterns, with row and distinct-value counts.

    Two counts per pattern, because they answer different questions: `rows` says
    how much of the column has this shape, `distinct_values` says how many
    different values share it -- a structured id shows many distinct values on
    one pattern, a controlled vocabulary shows few.
    """
    rows: Counter[str] = Counter()
    distinct: dict[str, set[str]] = {}
    for value in values:
        pattern = redacted_pattern(value)
        rows[pattern] += 1
        distinct.setdefault(pattern, set()).add(str(value).strip())
    return [
        {"pattern": pattern, "rows": count, "distinct_values": len(distinct[pattern])}
        for pattern, count in rows.most_common(limit)
    ]


def shape_stats(values: Sequence[Any], total: int) -> dict[str, Any]:
    """What shape a column holds -- the `audience` question, generalised.

    Reports the shape histogram over rows AND over distinct values: a column
    holding twelve distinct integers repeated across four hundred rows and one
    holding four hundred distinct integers are the same row histogram and very
    different columns.
    """
    present = [value for value in values if not queries.is_blank(value)]
    shapes = Counter(value_shape(value) for value in present)
    distinct_values = {str(value).strip() for value in present}
    distinct_shapes = Counter(value_shape(value) for value in distinct_values)
    numbers = [number for number in (as_integer(value) for value in present) if number is not None]
    stats: dict[str, Any] = {
        "rows": total,
        "filled": len(present),
        "fill_rate": _rate(len(present), total),
        "distinct": len(distinct_values),
        "shapes": {shape: shapes.get(shape, 0) for shape in SHAPES if shapes.get(shape)},
        "distinct_shapes": {
            shape: distinct_shapes.get(shape, 0) for shape in SHAPES if distinct_shapes.get(shape)
        },
        "band_like": shapes.get("range", 0) + shapes.get("bounded", 0),
        "top_patterns": pattern_histogram(present),
    }
    if numbers:
        stats["integer_min"] = min(numbers)
        stats["integer_max"] = max(numbers)
    return stats


def combination_stats(values: Sequence[Any], total: int) -> dict[str, Any]:
    """Whether a column really holds combinations, and what splitting would buy.

    `distinct_raw` against `distinct_members` is the number the schema decision
    turns on: if they are equal, every stored value is already a single member
    and splitting changes nothing; the wider the gap, the more of the column's
    apparent vocabulary is combinations of a smaller real one.
    """
    present = [str(value).strip() for value in values if not queries.is_blank(value)]
    members_per_row = [combination_members(value) for value in present]
    combined = [members for members in members_per_row if len(members) > 1]
    distinct_raw = {value for value in present}
    distinct_members = {member.strip().lower() for members in members_per_row for member in members}
    comma = sum(1 for value in present if "," in value)
    semicolon = sum(1 for value in present if ";" in value)
    return {
        "rows": total,
        "filled": len(present),
        "fill_rate": _rate(len(present), total),
        "combined_rows": len(combined),
        "combination_rate": _rate(len(combined), len(present)),
        "with_comma": comma,
        "with_semicolon": semicolon,
        "distinct_raw": len(distinct_raw),
        "distinct_members": len(distinct_members),
        "max_members": max((len(members) for members in members_per_row), default=0),
    }


def agreement_stats(left: Sequence[Any], right: Sequence[Any]) -> dict[str, Any]:
    """Whether two candidate keys are the same key, on the rows that carry both.

    `equal` is a case-insensitive, trimmed comparison. The two fan-out figures
    matter more than the equality rate: a key can disagree on spelling and still
    be the same key (1:1 fan-out both ways), while an equal-looking pair that
    fans out 1:many is not one key but two levels of a hierarchy.
    """
    pairs = [
        (str(one).strip(), str(other).strip())
        for one, other in zip(left, right)
        if not queries.is_blank(one) and not queries.is_blank(other)
    ]
    equal = sum(1 for one, other in pairs if one.casefold() == other.casefold())
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for one, other in pairs:
        forward.setdefault(one.casefold(), set()).add(other.casefold())
        backward.setdefault(other.casefold(), set()).add(one.casefold())
    return {
        "both_present": len(pairs),
        "equal": equal,
        "equal_rate": _rate(equal, len(pairs)),
        "left_to_right_max_fanout": max((len(values) for values in forward.values()), default=0),
        "right_to_left_max_fanout": max((len(values) for values in backward.values()), default=0),
        "left_with_multiple_right": sum(1 for values in forward.values() if len(values) > 1),
        "right_with_multiple_left": sum(1 for values in backward.values() if len(values) > 1),
    }


def nesting_stats(child: Sequence[Any], parent: Sequence[Any]) -> dict[str, Any]:
    """Whether each child key sits under exactly one parent key.

    The integrity check a cluster -> pack -> activity hierarchy needs before it
    can become two tables with a foreign key between them. A pack that appears
    under two clusters is not a modelling detail; it is the reason the hierarchy
    cannot be normalised as it stands.
    """
    families: dict[str, set[str]] = {}
    for one, other in zip(child, parent):
        if queries.is_blank(one) or queries.is_blank(other):
            continue
        families.setdefault(str(one).strip().casefold(), set()).add(str(other).strip().casefold())
    sizes = [len(values) for values in families.values()]
    return {
        "children_with_a_parent": len(families),
        "children_with_multiple_parents": sum(1 for size in sizes if size > 1),
        "max_parents_per_child": max(sizes, default=0),
    }


def pack_chain_stats(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Which link of the studio's pack-key chain resolves each activity.

    Mirrors `queries._PACK_KEY_FIELDS` rather than restating the order, so the
    probe cannot describe a chain the server does not use. Reports the count per
    link plus the rows no link resolves -- the activities a `packs` table would
    have no row to point at.
    """
    resolved: Counter[str] = Counter()
    for row in rows:
        values = {
            "communication_pack_cpid": row.get("communication_pack_cpid"),
            "tracking_pack_id": tracking_pack_prefix(row.get("tracking_id")),
            "communication_pack": row.get("communication_pack"),
            "campaign": row.get("campaign"),
        }
        for field in queries._PACK_KEY_FIELDS:
            if not queries.is_blank(values.get(field)):
                resolved[field] += 1
                break
        else:
            resolved["unresolved"] += 1
    return {
        "chain": list(queries._PACK_KEY_FIELDS),
        "resolved_by": {field: resolved.get(field, 0) for field in queries._PACK_KEY_FIELDS},
        "unresolved": resolved.get("unresolved", 0),
    }


def tracking_id_stats(values: Sequence[Any], total: int) -> dict[str, Any]:
    """Whether tracking ids really carry the documented five-segment shape.

    A cluster key derived from segment one is only as trustworthy as the
    segmentation, so the segment-count histogram is a precondition for reading
    anything else in the cluster section.
    """
    present = [value for value in values if not queries.is_blank(value)]
    segment_counts = Counter(len(tracking_segments(value)) for value in present)
    return {
        "rows": total,
        "filled": len(present),
        "fill_rate": _rate(len(present), total),
        "distinct": len({str(value).strip() for value in present}),
        "segment_counts": dict(sorted(segment_counts.items())),
        "five_segment_rate": _rate(segment_counts.get(5, 0), len(present)),
        "top_patterns": pattern_histogram(present),
    }


# ------------------------------------------------------------------------
# Reading the database
# ------------------------------------------------------------------------


def available_columns(engine: Engine) -> set[str]:
    """The `activities` columns this database actually has.

    The probe runs against a production database it must not migrate and cannot
    assume is current, so it degrades instead of refusing: a column the models
    expect but the database lacks is reported as schema drift and skipped,
    rather than aborting the whole run the way `verify_schema` would. Column
    NAMES are schema, not data, and are safe to print.
    """
    return {column["name"] for column in inspect(engine).get_columns(Activity.__tablename__)}


def read_rows(session: Session, columns: Sequence[str]) -> list[dict[str, Any]]:
    """One dict per activity, holding only `columns`.

    A plain column projection -- no dialect-specific function, cast or regex --
    so the same statement runs on PostgreSQL and on a SQLite snapshot. Every
    classification happens in Python afterwards, which is also what keeps the
    two backends from disagreeing about what a "band" is.
    """
    selected = [getattr(Activity, name) for name in columns]
    result = session.execute(select(*selected).execution_options(yield_per=1000))
    return [dict(zip(columns, row)) for row in result]


def _column(rows: Sequence[dict[str, Any]], name: str) -> list[Any]:
    return [row.get(name) for row in rows]


def build_report(
    rows: Sequence[dict[str, Any]],
    *,
    backend: str,
    probed: Sequence[str],
    missing: Sequence[str],
) -> dict[str, Any]:
    """The whole finding set as plain data, so it can be tested without printing.

    Every leaf here is a count, a rate, a cardinality, a shape name or a
    redacted pattern. `render` only formats what this returns, so a leak would
    have to be introduced here -- one place to check rather than a printing
    routine to audit line by line.
    """
    total = len(rows)
    clusters = [tracking_cluster_segment(row.get("tracking_id")) for row in rows]
    packs = [tracking_pack_prefix(row.get("tracking_id")) for row in rows]

    candidate_values: dict[str, list[Any]] = {
        "campaign_ltid": _column(rows, "campaign_ltid"),
        "tracking_cluster_segment": clusters,
        "tracking_pack_prefix": packs,
        "communication_pack_cpid": _column(rows, "communication_pack_cpid"),
        "campaign": _column(rows, "campaign"),
    }

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": backend,
        "rows": {
            "activities": total,
            "archived": sum(1 for row in rows if row.get("is_archive")),
            "never_synced": sum(1 for row in rows if row.get("synced_version") is None),
        },
        "schema": {
            "probed_columns": list(probed),
            "missing_expected_columns": list(missing),
        },
        "cluster_keys": {
            "candidates": {
                name: key_stats(values, total, patterns=name not in PATTERN_SUPPRESSED)
                for name, values in candidate_values.items()
                if name in CLUSTER_CANDIDATES
            },
            "campaign_ltid_vs_tracking_cluster": agreement_stats(
                _column(rows, "campaign_ltid"), clusters
            ),
            "campaign_ltid_vs_pack_cpid": agreement_stats(
                _column(rows, "campaign_ltid"), _column(rows, "communication_pack_cpid")
            ),
            "pack_cpid_under_tracking_cluster": nesting_stats(
                _column(rows, "communication_pack_cpid"), clusters
            ),
            "pack_prefix_under_tracking_cluster": nesting_stats(packs, clusters),
        },
        "audience": {
            "audience": shape_stats(_column(rows, "audience"), total),
            "extended_audience": shape_stats(_column(rows, "extended_audience"), total),
            "by_origin": {
                "synced": shape_stats(
                    [row.get("audience") for row in rows if row.get("synced_version") is not None],
                    sum(1 for row in rows if row.get("synced_version") is not None),
                ),
                "never_synced": shape_stats(
                    [row.get("audience") for row in rows if row.get("synced_version") is None],
                    sum(1 for row in rows if row.get("synced_version") is None),
                ),
            },
        },
        "combinations": {
            name: combination_stats(_column(rows, name), total) for name in COMBINATION_COLUMNS
        },
        "packs": {
            "key_chain": pack_chain_stats(rows),
            "cpid_vs_tracking_prefix": agreement_stats(
                _column(rows, "communication_pack_cpid"), packs
            ),
            "label_vs_cpid": agreement_stats(
                _column(rows, "communication_pack"), _column(rows, "communication_pack_cpid")
            ),
            "tracking_id": tracking_id_stats(_column(rows, "tracking_id"), total),
        },
    }
    # Columns the database does not have were never selected, so their sections
    # would silently report an all-blank column as a finding. Drop them instead.
    for section, keys in (
        ("audience", ("audience", "extended_audience")),
        ("combinations", COMBINATION_COLUMNS),
    ):
        for key in list(report[section]):
            if key in keys and key not in probed:
                del report[section][key]
    if "audience" not in probed:
        report["audience"].pop("by_origin", None)
    return report


# ------------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------------


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _patterns_line(patterns: Sequence[dict[str, Any]]) -> list[str]:
    return [
        f"      {entry['pattern']}  ({entry['rows']} rows, {entry['distinct_values']} distinct)"
        for entry in patterns
    ]


def _agreement_lines(left: str, right: str, stats: dict[str, Any]) -> list[str]:
    """Two lines per key pair: how often they agree, and how they fan out.

    The fan-out is spelled out in words rather than as `3:32`, because which
    side of that colon is which decides whether the answer is "one key" or "two
    levels of a hierarchy" -- and a reader of a shared report has no source to
    check the ordering against.
    """
    return [
        f"   {left} vs {right}: {stats['both_present']} rows carry both, "
        f"{_pct(stats['equal_rate'])} equal",
        f"      one {left} spans up to {stats['left_to_right_max_fanout']} "
        f"{right} values ({stats['left_with_multiple_right']} span more than one); "
        f"one {right} spans up to {stats['right_to_left_max_fanout']} {left} values "
        f"({stats['right_with_multiple_left']} span more than one)",
    ]


def render(report: dict[str, Any]) -> str:
    """Format `build_report`'s data. Prints nothing it was not given."""
    out: list[str] = [BANNER, ""]
    rows = report["rows"]
    out.append(
        f"Database: {report['backend']} | activities: {rows['activities']} "
        f"(archived {rows['archived']}, never synced {rows['never_synced']}) "
        f"| probed at {report['generated_at']}"
    )
    missing = report["schema"]["missing_expected_columns"]
    if missing:
        out.append(
            "Schema drift: this database is missing columns the models expect, "
            f"skipped by this run -- {', '.join(missing)}"
        )
    if rows["activities"] == 0:
        out.append("")
        out.append("The activities table is empty; there is nothing to characterise.")
        return "\n".join(out)

    out.append("")
    out.append("1. IS THERE A TRACKING-CLUSTER KEY?")
    out.append("   Candidate keys, by how they bucket the portfolio:")
    for name, stats in report["cluster_keys"]["candidates"].items():
        out.append(
            f"   - {name}: filled {stats['filled']}/{stats['rows']} ({_pct(stats['fill_rate'])}), "
            f"{stats['distinct']} distinct"
        )
        if stats["filled"]:
            out.append(
                f"      buckets: smallest {stats['smallest_bucket']}, "
                f"median {stats['median_bucket']}, largest {stats['largest_bucket']} "
                f"({_pct(stats['largest_bucket_share'])} of filled rows), "
                f"{stats['singleton_buckets']} singletons"
            )
            out.extend(_patterns_line(stats["top_patterns"]))
        else:
            out.append(
                f"      empty: {stats['null']} NULL, "
                f"{stats['blank_not_null']} blank-or-sentinel"
            )
    out.extend(
        _agreement_lines(
            "campaign_ltid",
            "tracking_cluster_segment",
            report["cluster_keys"]["campaign_ltid_vs_tracking_cluster"],
        )
    )
    out.extend(
        _agreement_lines(
            "campaign_ltid",
            "communication_pack_cpid",
            report["cluster_keys"]["campaign_ltid_vs_pack_cpid"],
        )
    )
    for label, key in (
        ("pack cpid", "pack_cpid_under_tracking_cluster"),
        ("tracking pack prefix", "pack_prefix_under_tracking_cluster"),
    ):
        nesting = report["cluster_keys"][key]
        out.append(
            f"   nesting -- {label} under cluster segment: "
            f"{nesting['children_with_a_parent']} packs, "
            f"{nesting['children_with_multiple_parents']} in more than one cluster "
            f"(max {nesting['max_parents_per_child']})"
        )
    out.append(
        "   Decides: whether a `clusters` table can be keyed on a stored column, "
        "on the tracking-id prefix, or not at all."
    )

    out.append("")
    out.append("2. WHAT SHAPE DOES `audience` HOLD?")
    for name, stats in report["audience"].items():
        if name == "by_origin":
            continue
        out.extend(_render_shape(name, stats))
    origin = report["audience"].get("by_origin")
    if origin:
        out.append(
            "   by origin -- synced rows: "
            + _shape_summary(origin["synced"])
            + " | never-synced rows: "
            + _shape_summary(origin["never_synced"])
        )
    out.append(
        "   Decides: whether `audience` becomes an ordinal column by parsing "
        "integers, by mapping bands, or by both with a migration in between."
    )

    out.append("")
    out.append("3. DO `channel` AND `target_audience` REALLY HOLD COMBINATIONS?")
    for name, stats in report["combinations"].items():
        out.append(
            f"   - {name}: filled {stats['filled']}/{stats['rows']} "
            f"({_pct(stats['fill_rate'])}), {_pct(stats['combination_rate'])} of filled values "
            f"hold more than one member (max {stats['max_members']}); "
            f"{stats['distinct_raw']} distinct raw strings vs "
            f"{stats['distinct_members']} distinct members"
        )
        out.append(
            f"      separators present: {stats['with_comma']} rows with ',', "
            f"{stats['with_semicolon']} with ';'"
        )
    out.append(
        "   Decides: whether splitting channel/target_audience into a members "
        "table is worth a schema change, or whole-string matching is already exact."
    )

    out.append("")
    out.append("4. WHAT WOULD A `packs` TABLE BE KEYED ON?")
    chain = report["packs"]["key_chain"]
    resolved = ", ".join(f"{field} {count}" for field, count in chain["resolved_by"].items())
    out.append(f"   pack-key chain resolves: {resolved}; unresolved {chain['unresolved']}")
    for left, right, key in (
        ("communication_pack_cpid", "tracking_pack_prefix", "cpid_vs_tracking_prefix"),
        ("communication_pack", "communication_pack_cpid", "label_vs_cpid"),
    ):
        out.extend(_agreement_lines(left, right, report["packs"][key]))
    tracking = report["packs"]["tracking_id"]
    out.append(
        f"   tracking_id: filled {tracking['filled']}/{tracking['rows']} "
        f"({_pct(tracking['fill_rate'])}), {tracking['distinct']} distinct, "
        f"{_pct(tracking['five_segment_rate'])} carry the documented five segments"
    )
    out.append(f"      segment-count histogram: {tracking['segment_counts']}")
    out.extend(_patterns_line(tracking["top_patterns"]))
    out.append(
        "   Decides: whether pack identity can be one column with a stable label, "
        "and how many activities a `packs` table would leave unlinked."
    )
    out.append("")
    out.append(
        "Read the fan-out figures before the equality rates: two keys can disagree "
        "on spelling and still be one key, while an equal-looking pair that fans "
        "out one-to-many is two levels of a hierarchy, not one key."
    )
    return "\n".join(out)


def _shape_summary(stats: dict[str, Any]) -> str:
    if not stats["filled"]:
        return "no filled values"
    shapes = ", ".join(f"{count} {shape}" for shape, count in stats["shapes"].items())
    summary = f"{stats['distinct']} distinct, {shapes}"
    if "integer_min" in stats:
        summary += f", integer range {stats['integer_min']}-{stats['integer_max']}"
    return summary


def _render_shape(name: str, stats: dict[str, Any]) -> list[str]:
    lines = [
        f"   - {name}: filled {stats['filled']}/{stats['rows']} "
        f"({_pct(stats['fill_rate'])}), {stats['distinct']} distinct values"
    ]
    if not stats["filled"]:
        return lines
    lines.append(
        "      rows by shape: "
        + ", ".join(f"{shape} {count}" for shape, count in stats["shapes"].items())
        + f" (band-like {stats['band_like']})"
    )
    lines.append(
        "      distinct values by shape: "
        + ", ".join(f"{shape} {count}" for shape, count in stats["distinct_shapes"].items())
    )
    if "integer_min" in stats:
        lines.append(f"      integer range: {stats['integer_min']} to {stats['integer_max']}")
    lines.extend(_patterns_line(stats["top_patterns"]))
    return lines


# ------------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------------


def probe(engine: Engine, *, backend: str | None = None) -> dict[str, Any]:
    """Run every probe against `engine` and return the findings."""
    present = available_columns(engine)
    probed = [name for name in PROBED_COLUMNS if name in present]
    missing = [name for name in PROBED_COLUMNS if name not in present]
    with Session(engine) as session:
        rows = read_rows(session, probed)
    return build_report(
        rows,
        backend=backend or engine.dialect.name,
        probed=probed,
        missing=missing,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Characterise the SHAPE of a CPLAN database for the phase-three "
            "modelling decisions. Prints counts, rates and redacted patterns "
            "only -- never a stored value -- so the output is safe to share."
        )
    )
    parser.add_argument("--settings", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_backend_config(args.settings or default_settings_path())
    database_url = resolve_backend_database_url(config)
    engine = create_read_only_engine(database_url)
    try:
        print(render(probe(engine, backend=config.backend)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
