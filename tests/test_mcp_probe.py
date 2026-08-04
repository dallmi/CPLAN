"""Tests for the shape-only database probe (`pipeline/mcp/probe.py`).

The probe exists to be believed about a database nobody running these tests can
look at, so "it ran" is not a passing bar: a probe that mis-classifies is worse
than no probe. Two kinds of test here, therefore.

* **Classification** — every shape the probe can report is pinned against known
  inputs: integers against bands against blanks, combinations against single
  values, each candidate cluster key both filled and empty, a pack nested under
  one cluster against a pack nested under two. These need no database.
* **End to end, on both backends** — the same parametrization the rest of the
  MCP suite uses (`writable_session` from `tests/test_mcp_server.py`, so the
  backend matrix and the synthetic-row builder are defined once). Set
  `CPLAN_TEST_DATABASE_URL` to add the PostgreSQL half.

And one test that is really a safety property rather than a behaviour:
`test_the_rendered_report_contains_no_value_from_the_database` seeds every
probed column with a distinctive marker and asserts no marker survives into the
printed report. The module's whole promise is that its output can leave the
corporate environment; that promise needs a test that fails when someone adds a
tempting `f"...{value}"` to the renderer.

All fixture data is synthetic.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from pipeline.mcp import probe, queries
from pipeline.mcp.engine import create_read_only_engine

# Imported, not redefined: `writable_session` carries the backend
# parametrization and the drop/create lifecycle, and `_activity` carries the
# fully-planned synthetic row every MCP test overrides. Only these two names are
# imported -- pulling in anything called `test_*` would make pytest collect that
# module's whole suite a second time under this file's name.
from tests.test_mcp_server import _activity, writable_session  # noqa: F401


# --------------------------------------------------------------------------
# Shape classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["12000", "0", "250", " 350 ", "12,000", "12'000", "12 000", "-5"],
)
def test_an_integer_audience_reads_as_an_integer(value):
    """Including the thousands groupings the source system may write.

    A grouped headcount is still a headcount: phase 3 has to decide between
    parsing numbers and mapping bands, and `12,000` falling into the band pile
    would push it towards the wrong answer.
    """
    assert probe.value_shape(value) == "integer"


@pytest.mark.parametrize("value", ["< 1000", "<1000", "> 100k", "up to 500", "1000+", "over 5000"])
def test_an_open_ended_band_reads_as_bounded(value):
    assert probe.value_shape(value) == "bounded"


@pytest.mark.parametrize("value", ["1-10k", "10-50k", "50 - 100k", "1000 to 5000", "10–50k"])
def test_a_two_sided_band_reads_as_a_range(value):
    assert probe.value_shape(value) == "range"


@pytest.mark.parametrize("value", [None, "", "   ", "None", "null"])
def test_a_blank_or_sentinel_value_reads_as_blank(value):
    """The sync writes `str(None)` into text columns, and the probe must not
    count that as a filled value -- a column that is 40% literal `'None'` would
    otherwise report as 40% filled and 40% `text`."""
    assert probe.value_shape(value) == "blank"


@pytest.mark.parametrize("value", ["All staff", "Global employees", "Segment A"])
def test_a_label_reads_as_text(value):
    assert probe.value_shape(value) == "text"


def test_a_decimal_is_neither_an_integer_nor_a_band():
    assert probe.value_shape("1.5") == "decimal"
    assert probe.value_shape("1,5") == "decimal"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("12000", 12000), ("12,000", 12000), ("12 000", 12000), ("< 1000", None), ("x", None)],
)
def test_as_integer_parses_only_what_it_classified_as_an_integer(value, expected):
    assert probe.as_integer(value) == expected


def test_the_shape_vocabulary_is_closed():
    """Every classification the probe can emit is a name the report explains."""
    for value in ["12000", "< 1000", "1-10k", "1.5", "All staff", None, "None"]:
        assert probe.value_shape(value) in probe.SHAPES


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


def test_a_tracking_id_redacts_to_its_structure():
    assert probe.redacted_pattern("CLU-1-260110-0000001-EM") == "AAA-N-NNNNNN-NNNNNNN-AA"


@pytest.mark.parametrize(
    "value",
    [
        "CLU-1-260110-0000001-EM",
        "Project Nightingale 2026",
        "a.person@example.invalid",
        "Doe, Jane",
        "12,000",
        "< 1000",
    ],
)
def test_redaction_leaves_no_letter_or_digit_of_the_original(value):
    """The property that makes a pattern safe to print, checked directly.

    Not "the output differs from the input" -- that would pass for a pattern
    that kept every third character. No digit may survive at all, and the only
    letters allowed out are the three mask characters, so what remains is
    punctuation, casing and length, none of which identifies anything.
    """
    pattern = probe.redacted_pattern(value)
    assert not any(char.isdigit() for char in pattern)
    assert {char for char in pattern if char.isalpha()} <= {"N", "A", "a"}


def test_redaction_collapses_whitespace_so_patterns_do_not_fragment():
    assert probe.redacted_pattern("Two words") == "Aaa_aaaaa"


def test_a_long_value_redacts_to_a_truncated_pattern():
    pattern = probe.redacted_pattern("x" * 200)
    assert pattern.endswith("...")
    assert len(pattern) == probe.MAX_PATTERN_LENGTH + 3


def test_a_blank_value_redacts_to_a_named_blank():
    assert probe.redacted_pattern(None) == "<blank>"
    assert probe.redacted_pattern("None") == "<blank>"


# --------------------------------------------------------------------------
# Combinations
# --------------------------------------------------------------------------


def test_the_probe_splits_combinations_with_the_collision_splitter():
    """Pinned against `_normalize_multi`, not reimplemented.

    The question the probe answers is whether splitting these two columns is
    worth a schema change. Answering it with a different splitter than the one
    such a change would adopt would answer a different question.
    """
    for value in ["Email, Intranet", "Email; Intranet", "Email", None, "None"]:
        assert probe.combination_members(value) == queries._normalize_multi(value)


@pytest.mark.parametrize(
    ("value", "members", "combined"),
    [
        ("Email, Intranet", 2, True),
        ("Email; Intranet; Town hall", 3, True),
        ("Email", 1, False),
        ("Email,", 1, False),
        (None, 0, False),
        ("None", 0, False),
    ],
)
def test_a_combination_is_told_apart_from_a_single_value(value, members, combined):
    assert len(probe.combination_members(value)) == members
    assert probe.has_combination(value) is combined


def test_combination_stats_separate_raw_strings_from_members():
    """The number the schema decision turns on.

    Three raw strings over two real members is the case that justifies a members
    table; three raw strings over three members is the case that does not.
    """
    stats = probe.combination_stats(["Email, Intranet", "Email", "Intranet"], 4)
    assert stats["filled"] == 3
    assert stats["combined_rows"] == 1
    assert stats["combination_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert stats["distinct_raw"] == 3
    assert stats["distinct_members"] == 2
    assert stats["max_members"] == 2
    assert stats["with_comma"] == 1
    assert stats["with_semicolon"] == 0


def test_combination_stats_report_nothing_combined_when_nothing_is():
    stats = probe.combination_stats(["Email", "Intranet", None], 3)
    assert stats["combined_rows"] == 0
    assert stats["combination_rate"] == 0.0
    assert stats["distinct_raw"] == stats["distinct_members"] == 2


# --------------------------------------------------------------------------
# Candidate keys
# --------------------------------------------------------------------------


def test_an_empty_candidate_key_reports_how_it_is_empty():
    """NULL and blank-but-present are different upstream problems.

    `campaign_ltid` is empty in every local snapshot; whether production leaves
    it NULL (the sync never writes it) or writes an empty string or the `'None'`
    sentinel (the sync writes it and the source is empty) decides whether the
    column can be adopted as a key at all.
    """
    stats = probe.key_stats([None, None, "", "None"], 4)
    assert stats["filled"] == 0
    assert stats["fill_rate"] == 0.0
    assert stats["distinct"] == 0
    assert stats["null"] == 2
    assert stats["blank_not_null"] == 2
    assert "largest_bucket" not in stats


def test_a_filled_candidate_key_reports_its_bucket_sizes():
    """A key resolving small buckets identifies a planning unit; one resolving
    the whole portfolio identifies the portfolio. Both look identical if only
    the fill rate is reported."""
    stats = probe.key_stats(["A", "A", "A", "B", "C", None], 6)
    assert stats["filled"] == 5
    assert stats["fill_rate"] == pytest.approx(5 / 6, abs=1e-4)
    assert stats["distinct"] == 3
    assert stats["largest_bucket"] == 3
    assert stats["smallest_bucket"] == 1
    assert stats["median_bucket"] == 1.0
    assert stats["singleton_buckets"] == 2
    assert stats["largest_bucket_share"] == pytest.approx(3 / 5, abs=1e-4)


def test_key_stats_never_carry_a_value_through():
    """The stats dict is what the renderer formats, so the guarantee starts here."""
    payload = json.dumps(probe.key_stats(["Nightingale", "Nightingale", "Kestrel"], 3))
    assert "Nightingale" not in payload
    assert "Kestrel" not in payload


def test_a_suppressed_column_reports_no_patterns_at_all():
    assert probe.key_stats(["Alpha", "Beta"], 2, patterns=False)["top_patterns"] == []
    assert probe.key_stats(["Alpha", "Beta"], 2)["top_patterns"] != []


@pytest.mark.parametrize(
    ("tracking_id", "cluster", "prefix"),
    [
        ("CLU-1-260110-0000001-EM", "CLU", "CLU-1"),
        ("CLU-2", "CLU", "CLU-2"),
        ("SOLO", "SOLO", None),
        (None, None, None),
        ("None", None, None),
        ("", None, None),
    ],
)
def test_the_tracking_id_yields_a_cluster_and_a_pack_prefix(tracking_id, cluster, prefix):
    assert probe.tracking_cluster_segment(tracking_id) == cluster
    assert probe.tracking_pack_prefix(tracking_id) == prefix


def test_tracking_id_stats_report_the_segment_histogram():
    """Segment shape is a precondition for reading the cluster answer: a cluster
    key taken from segment one means nothing if the ids are not segmented the
    way the domain model says."""
    stats = probe.tracking_id_stats(
        ["A-1-260110-0000001-EM", "B-2-260110-0000002-EM", "C-3", None], 4
    )
    assert stats["filled"] == 3
    assert stats["segment_counts"] == {2: 1, 5: 2}
    assert stats["five_segment_rate"] == pytest.approx(2 / 3, abs=1e-4)


# --------------------------------------------------------------------------
# Agreement and nesting
# --------------------------------------------------------------------------


def test_two_spellings_of_one_key_agree_one_to_one():
    stats = probe.agreement_stats(["clu", "clu", "abc"], ["CLU", "CLU", "ABC"])
    assert stats["both_present"] == 3
    assert stats["equal_rate"] == 1.0
    assert stats["left_to_right_max_fanout"] == 1
    assert stats["right_to_left_max_fanout"] == 1


def test_a_parent_key_and_a_child_key_fan_out_asymmetrically():
    """The distinction the report is really after: one cluster over two packs is
    a hierarchy, not two names for one key -- and the equality rate alone cannot
    tell the two apart."""
    stats = probe.agreement_stats(["CLU", "CLU"], ["CLU-1", "CLU-2"])
    assert stats["equal_rate"] == 0.0
    assert stats["left_to_right_max_fanout"] == 2
    assert stats["right_to_left_max_fanout"] == 1
    assert stats["left_with_multiple_right"] == 1
    assert stats["right_with_multiple_left"] == 0


def test_rows_missing_either_side_are_not_compared():
    stats = probe.agreement_stats(["CLU", None, "ABC"], [None, "CLU", "ABC"])
    assert stats["both_present"] == 1
    assert stats["equal_rate"] == 1.0


def test_a_pack_under_one_cluster_nests_cleanly():
    stats = probe.nesting_stats(["P1", "P1", "P2"], ["CLU", "CLU", "CLU"])
    assert stats["children_with_a_parent"] == 2
    assert stats["children_with_multiple_parents"] == 0
    assert stats["max_parents_per_child"] == 1


def test_a_pack_under_two_clusters_is_flagged():
    """This is the finding that would stop a `clusters` table from being built:
    a pack spanning two clusters has no foreign key to give."""
    stats = probe.nesting_stats(["P1", "P1"], ["CLU-A", "CLU-B"])
    assert stats["children_with_multiple_parents"] == 1
    assert stats["max_parents_per_child"] == 2


# --------------------------------------------------------------------------
# Shape stats for the audience question
# --------------------------------------------------------------------------


def test_an_integer_audience_column_reports_a_numeric_range():
    stats = probe.shape_stats(["250", "12000", "12000", None], 4)
    assert stats["filled"] == 3
    assert stats["distinct"] == 2
    assert stats["shapes"] == {"integer": 3}
    assert stats["distinct_shapes"] == {"integer": 2}
    assert stats["band_like"] == 0
    assert stats["integer_min"] == 250
    assert stats["integer_max"] == 12000


def test_a_band_audience_column_reports_bands_and_no_range():
    stats = probe.shape_stats(["< 1000", "1-10k", "> 100k"], 3)
    assert stats["shapes"] == {"range": 1, "bounded": 2}
    assert stats["band_like"] == 3
    assert "integer_min" not in stats


def test_a_mixed_audience_column_reports_both_shapes():
    """The migration-shaped answer: neither "parse the integers" nor "map the
    bands" is sufficient on its own, and only the histogram says so."""
    stats = probe.shape_stats(["1200", "1-10k", "All staff"], 3)
    assert stats["shapes"] == {"integer": 1, "range": 1, "text": 1}
    assert stats["band_like"] == 1
    assert stats["integer_min"] == stats["integer_max"] == 1200


def test_shape_stats_count_rows_and_distinct_values_separately():
    """Twelve integers across four hundred rows and four hundred distinct ones
    are the same row histogram and very different columns."""
    stats = probe.shape_stats(["100"] * 10 + ["200"], 11)
    assert stats["shapes"] == {"integer": 11}
    assert stats["distinct_shapes"] == {"integer": 2}


# --------------------------------------------------------------------------
# The pack-key chain
# --------------------------------------------------------------------------


def test_the_pack_chain_follows_the_server_order():
    """Mirrors `queries._PACK_KEY_FIELDS` rather than restating it, so the probe
    cannot describe a chain the MCP server does not use."""
    rows = [
        {"communication_pack_cpid": "CP-1", "tracking_id": "CLU-1-260110-0000001-EM"},
        {"communication_pack_cpid": None, "tracking_id": "CLU-2-260110-0000002-EM"},
        {"communication_pack_cpid": None, "tracking_id": None, "communication_pack": "Pack"},
        {"communication_pack_cpid": None, "tracking_id": None, "campaign": "Camp"},
        {"communication_pack_cpid": "None", "tracking_id": "None"},
    ]
    stats = probe.pack_chain_stats(rows)
    assert stats["chain"] == list(queries._PACK_KEY_FIELDS)
    assert stats["resolved_by"] == {
        "communication_pack_cpid": 1,
        "tracking_pack_id": 1,
        "communication_pack": 1,
        "campaign": 1,
    }
    assert stats["unresolved"] == 1


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


def _report(rows, probed=probe.PROBED_COLUMNS, missing=()):
    return probe.build_report(rows, backend="sqlite", probed=list(probed), missing=list(missing))


def test_a_column_the_database_lacks_is_reported_rather_than_probed():
    """A read-only probe cannot migrate the database it is pointed at, so a
    missing column has to degrade to a named gap instead of aborting the run --
    otherwise one absent column costs the operator every other answer."""
    report = _report([{"tracking_id": "CLU-1-260110-0000001-EM"}], probed=["tracking_id"],
                     missing=["audience", "channel"])
    assert report["schema"]["missing_expected_columns"] == ["audience", "channel"]
    assert "audience" not in report["audience"]
    assert "by_origin" not in report["audience"]
    assert "channel" not in report["combinations"]
    assert "IS THERE A TRACKING-CLUSTER KEY?" in probe.render(report)


def test_an_empty_database_says_so_instead_of_reporting_zeroes():
    rendered = probe.render(_report([]))
    assert "nothing to characterise" in rendered


# --------------------------------------------------------------------------
# End to end, on every backend
# --------------------------------------------------------------------------


def _probe_session(session):
    rows = probe.read_rows(session, list(probe.PROBED_COLUMNS))
    return probe.build_report(
        rows, backend="test", probed=list(probe.PROBED_COLUMNS), missing=[]
    )


def test_an_unfilled_campaign_ltid_is_reported_as_empty(writable_session):  # noqa: F811
    """The state every local snapshot is in, and the reason phase 3 is blocked."""
    writable_session.add_all([_activity(), _activity()])
    writable_session.flush()

    report = _probe_session(writable_session)
    ltid = report["cluster_keys"]["candidates"]["campaign_ltid"]
    assert ltid["filled"] == 0
    assert ltid["null"] == 2
    assert ltid["blank_not_null"] == 0
    rendered = probe.render(report)
    assert "campaign_ltid: filled 0/2 (0.0%)" in rendered
    assert "empty: 2 NULL, 0 blank-or-sentinel" in rendered


def test_a_filled_campaign_ltid_is_bucketed_and_compared(writable_session):  # noqa: F811
    """Filled on one backend or the other, the three candidate keys must be
    comparable in the same units -- bucket counts and sizes."""
    writable_session.add_all(
        [
            _activity(campaign_ltid="LT-A", tracking_id="LTA-1-260110-0000101-EM",
                      communication_pack_cpid="CP-01"),
            _activity(campaign_ltid="LT-A", tracking_id="LTA-2-260110-0000102-EM",
                      communication_pack_cpid="CP-02"),
            _activity(campaign_ltid="LT-B", tracking_id="LTB-1-260110-0000103-EM",
                      communication_pack_cpid="CP-03"),
        ]
    )
    writable_session.flush()

    candidates = _probe_session(writable_session)["cluster_keys"]["candidates"]
    assert candidates["campaign_ltid"]["distinct"] == 2
    assert candidates["campaign_ltid"]["largest_bucket"] == 2
    assert candidates["tracking_cluster_segment"]["distinct"] == 2
    assert candidates["tracking_pack_prefix"]["distinct"] == 3
    assert candidates["communication_pack_cpid"]["distinct"] == 3


def test_campaign_ltid_is_measured_against_the_tracking_cluster(writable_session):  # noqa: F811
    """The question actually being settled: is `campaign_ltid` the cluster, a
    level above it, or unrelated? Here it is exactly the cluster, one to one."""
    writable_session.add_all(
        [
            _activity(campaign_ltid="LTA", tracking_id="LTA-1-260110-0000201-EM"),
            _activity(campaign_ltid="LTA", tracking_id="LTA-2-260110-0000202-EM"),
            _activity(campaign_ltid="LTB", tracking_id="LTB-1-260110-0000203-EM"),
        ]
    )
    writable_session.flush()

    agreement = _probe_session(writable_session)["cluster_keys"]["campaign_ltid_vs_tracking_cluster"]
    assert agreement["both_present"] == 3
    assert agreement["equal_rate"] == 1.0
    assert agreement["left_to_right_max_fanout"] == 1
    assert agreement["right_to_left_max_fanout"] == 1


def test_a_pack_spanning_two_clusters_is_visible_in_the_report(writable_session):  # noqa: F811
    writable_session.add_all(
        [
            _activity(communication_pack_cpid="CP-9", tracking_id="CLA-1-260110-0000301-EM"),
            _activity(communication_pack_cpid="CP-9", tracking_id="CLB-1-260110-0000302-EM"),
        ]
    )
    writable_session.flush()

    nesting = _probe_session(writable_session)["cluster_keys"]["pack_cpid_under_tracking_cluster"]
    assert nesting["children_with_a_parent"] == 1
    assert nesting["children_with_multiple_parents"] == 1


def test_an_integer_audience_is_reported_as_integers(writable_session):  # noqa: F811
    writable_session.add_all(
        [_activity(audience="250"), _activity(audience="12000"), _activity(audience="12000")]
    )
    writable_session.flush()

    stats = _probe_session(writable_session)["audience"]["audience"]
    assert stats["shapes"] == {"integer": 3}
    assert stats["distinct"] == 2
    assert stats["integer_min"] == 250
    assert stats["integer_max"] == 12000
    assert "integer range: 250 to 12000" in probe.render(_probe_session(writable_session))


def test_a_band_audience_is_reported_as_bands(writable_session):  # noqa: F811
    """The other half of the phase-3 audience question, and the one the domain
    resource asserted until an eval run caught it."""
    writable_session.add_all(
        [_activity(audience="< 1000"), _activity(audience="1-10k"), _activity(audience="> 100k")]
    )
    writable_session.flush()

    stats = _probe_session(writable_session)["audience"]["audience"]
    assert stats["band_like"] == 3
    assert "integer_min" not in stats


def test_channel_combinations_are_counted_against_raw_strings(writable_session):  # noqa: F811
    writable_session.add_all(
        [
            _activity(channel="Email, Intranet", target_audience="All staff, Managers"),
            _activity(channel="Email", target_audience="All staff"),
            _activity(channel="Intranet", target_audience="Managers"),
        ]
    )
    writable_session.flush()

    combinations = _probe_session(writable_session)["combinations"]
    assert combinations["channel"]["combined_rows"] == 1
    assert combinations["channel"]["distinct_raw"] == 3
    assert combinations["channel"]["distinct_members"] == 2
    assert combinations["target_audience"]["distinct_raw"] == 3
    assert combinations["target_audience"]["distinct_members"] == 2


def test_the_rendered_report_contains_no_value_from_the_database(writable_session):  # noqa: F811
    """The safety property the module is built around, checked end to end.

    Every probed text column carries a distinctive marker; none may survive into
    the printed report. This fails the moment someone makes a finding "legible"
    by interpolating the value that produced it, which is exactly the change
    that would make the output unsafe to carry out of the environment.
    """
    markers = {
        "activity_name": "MARKERNAME",
        "campaign": "MARKERCAMPAIGN",
        "campaign_ltid": "MARKERLTID",
        "communication_pack_cpid": "MARKERCPID",
        "communication_pack": "MARKERPACK",
        "audience": "MARKERAUDIENCE",
        "extended_audience": "MARKEREXTENDED",
        "channel": "MARKERCHANNEL, MARKEROTHER",
        "target_audience": "MARKERTARGET",
        "strategic_objectives": "MARKEROBJECTIVE",
        "bod_geb": "MARKERBOARD",
        "other_executives": "MARKEREXEC",
        "lead": "MARKERLEAD",
        "tracking_id": "MARKERCLUSTER-7-260110-0000401-EM",
    }
    writable_session.add(_activity(**markers))
    writable_session.flush()

    rendered = probe.render(_probe_session(writable_session))
    for value in markers.values():
        for token in value.replace(",", " ").split():
            assert token not in rendered, f"{token} leaked into the report"
    # Guard against a vacuous pass: the report must actually have described the
    # row, not merely failed to mention it.
    assert "filled 1/1 (100.0%)" in rendered


def test_the_probe_runs_over_a_read_only_engine(writable_session):  # noqa: F811
    """The probe connects the way the MCP server does, so the operator running
    it against production cannot write to production by running it."""
    writable_session.add_all([_activity(audience="500"), _activity(audience="9000")])
    writable_session.commit()

    url = writable_session.get_bind().url.render_as_string(hide_password=False)
    read_only = create_read_only_engine(url)
    try:
        report = probe.probe(read_only)
        assert report["rows"]["activities"] == 2
        assert report["audience"]["audience"]["shapes"] == {"integer": 2}
        assert "SHAPE ONLY, SAFE TO SHARE" in probe.render(report)
    finally:
        read_only.dispose()


def test_the_probe_reads_the_columns_it_declares(writable_session):  # noqa: F811
    """`PROBED_COLUMNS` is the allowlist that keeps names and descriptions out of
    the process entirely, so it has to match the real table."""
    engine = writable_session.get_bind()
    assert set(probe.PROBED_COLUMNS) <= probe.available_columns(engine)
    with Session(engine) as reader:
        rows = probe.read_rows(reader, list(probe.PROBED_COLUMNS))
    assert all(set(row) == set(probe.PROBED_COLUMNS) for row in rows)
