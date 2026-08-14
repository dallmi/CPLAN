"""The diagnostic that chooses the pack link, instead of assuming it.

Three activity columns could carry the pack identifier and the exports do not
say which one the pack list answers to. A wrong join does not look wrong --
it looks like a pack file with plausible numbers in it -- so the choice is
measured, and these tests hold the measurement honest.
"""

import pytest

pytest.importorskip("pandas")

from pipeline.scripts import check_pack_link
from pipeline.scripts.process_cplan import load_activities, transform_packs, read_csv_auto
from tests.report_fixtures import PACK_HEADER, PACK_ROWS, _write_csv, write_pack_csv, write_activity_csvs


def test_it_names_the_columns_that_say_what_a_pack_is():
    """The mapping carries the names a real export actually uses.

    This assertion has now been rewritten twice, and the second time is the
    instructive one. It first claimed these columns were unmapped; the map
    was widened and it flipped to mapped. Both versions passed against a
    fixture written from the form's documented field labels -- and the labels
    were wrong. The export calls the pack's name `Title` and misspells the
    cluster column, so `pack_name` and `tracking_cluster` were empty in
    production while this test was green.

    It is pinned to the export's spellings now, and `Category` is gone
    because the export has no such column.
    """
    rows = check_pack_link.unmapped_columns(PACK_HEADER)
    by_name = {raw: status for raw, _, status in rows}

    assert by_name["LTID"] == "mapped"
    assert by_name["Title"] == "mapped"
    assert by_name["Tracking cluser"] == "mapped"
    assert by_name["End date/time"] == "mapped"


def test_a_perfect_rate_over_a_handful_of_packs_is_not_the_link():
    """The rate alone cannot tell the link from a coincidence.

    Measured against a real export: `communication_pack_cpid` and
    `campaign_ltid` both resolved every reference they carried -- 100% each,
    so the rate floor let both through and the run had to stop and ask a
    human. What separates them is reach: the first answered for 203 of 342
    packs, the second for 12. An identifier from another namespace that
    happens to match a few rows is not the pack link, however cleanly those
    few rows resolve.
    """
    import pandas as pd

    packs = pd.DataFrame({"cpid": [f"P-{i:04d}" for i in range(100)]})
    frame = pd.DataFrame({
        "communication_pack_cpid": [f"P-{i:04d}" for i in range(80)] + [""] * 20,
        "campaign_ltid": ["P-0000", "P-0001"] + [""] * 98,
    })

    wide = check_pack_link.score(frame, packs, "communication_pack_cpid")
    narrow = check_pack_link.score(frame, packs, "campaign_ltid")

    # The premise: if the rates ever separate these two, this test has
    # stopped exercising the thing it was written for.
    assert wide.rate == 1.0 and narrow.rate == 1.0

    assert wide.reach >= check_pack_link.MIN_PACK_REACH
    assert narrow.reach < check_pack_link.MIN_PACK_REACH
    assert check_pack_link.select_winners([wide, narrow]) == [wide]


def test_a_candidate_must_clear_both_floors():
    """Two floors, each catching a different kind of wrong answer.

    On the real export `tracking_pack_id` reached the same 202 packs as the
    winner and still resolved only 10% of its references; `campaign_ltid`
    resolved everything and reached almost nothing. Either floor alone lets
    one of them through.
    """
    import pandas as pd

    packs = pd.DataFrame({"cpid": [f"P-{i:04d}" for i in range(100)]})
    frame = pd.DataFrame({
        # Wide reach, poor rate: most references resolve to nothing.
        "tracking_pack_id": [f"P-{i:04d}" for i in range(60)]
                            + [f"X-{i:04d}" for i in range(540)],
    })
    wide_but_wrong = check_pack_link.score(frame, packs, "tracking_pack_id")

    assert wide_but_wrong.reach >= check_pack_link.MIN_PACK_REACH
    assert wide_but_wrong.rate < check_pack_link.MIN_LINK_RATE
    assert check_pack_link.select_winners([wide_but_wrong]) == []


def test_reach_is_zero_rather_than_undefined_without_a_pack_list():
    """No pack rows is a state the diagnostic reports, not one it divides by."""
    import pandas as pd

    empty = check_pack_link.score(pd.DataFrame({"communication_pack_cpid": ["A"]}),
                                  pd.DataFrame({"cpid": []}),
                                  "communication_pack_cpid")
    assert empty.reach == 0.0


def test_the_map_now_covers_every_column_the_fixture_exports():
    """A column the fixture carries and the map does not is a field the pack
    file cannot show.

    The fixture models a real export's column names. That is the only reason
    this assertion means anything: run against names invented from a form
    description, it proves the invention is self-consistent and nothing else.
    The authority remains a `packlink.ps1` run against the live export.
    """
    unmapped = [raw for raw, _, status in check_pack_link.unmapped_columns(PACK_HEADER)
                if status == "unmapped"]
    assert unmapped == [], f"still unmapped: {unmapped}"


def test_the_harmonised_pack_frame_carries_the_identity_fields(tmp_path):
    packs = transform_packs(read_csv_auto(write_pack_csv(tmp_path)))
    for column in ("cpid", "pack_name", "tracking_cluster", "end_date"):
        assert column in packs.columns, f"{column} is missing"
    assert set(packs["pack_name"]) >= {"Pack one", "Pack with nothing planned"}
    # The name has to survive the transform with content, not merely exist:
    # an all-empty column would satisfy the membership check above and still
    # leave every row of `07-packs.csv` nameless.
    assert not packs["pack_name"].isna().any()
    assert set(packs["tracking_cluster"]) == {"QRREP"}


def test_every_export_column_is_accounted_for():
    """One row per column, so a column cannot be silently skipped."""
    rows = check_pack_link.unmapped_columns(PACK_HEADER)
    assert [raw for raw, _, _ in rows] == PACK_HEADER


def test_a_lookups_noise_companion_column_is_unmapped():
    """`transform_packs` drops a lookup's `#Id` companion before it ever
    matches a label -- both columns satisfy the label match on their own, so
    a diagnostic that skips the noise-drop step reports the companion as
    mapped when the harmonised frame will not have it.
    """
    columns = ["LTID", "Business Division", "Business Division#Id", "Region", "Region#Id"]
    by_name = {raw: status for raw, _, status in check_pack_link.unmapped_columns(columns)}

    assert by_name["Business Division"] == "mapped"
    assert by_name["Business Division#Id"] == "unmapped"
    assert by_name["Region"] == "mapped"
    assert by_name["Region#Id"] == "unmapped"


def test_a_second_column_matching_the_same_label_is_unmapped():
    """`transform_packs` claims each label for at most one column -- the
    first match wins and every later column matching the same label is
    dropped. A diagnostic that scores each column independently reports both
    "Objective" and "Objective (draft)" as mapped, when only the first
    survives into the harmonised frame.
    """
    columns = ["LTID", "Objective", "Objective (draft)"]
    by_name = {raw: status for raw, _, status in check_pack_link.unmapped_columns(columns)}

    assert by_name["Objective"] == "mapped"
    assert by_name["Objective (draft)"] == "unmapped"


def test_it_reports_when_there_is_no_pack_export(tmp_path, capsys):
    """A missing optional export is a message, not a traceback."""
    write_activity_csvs(tmp_path)
    assert check_pack_link.main(["--input", str(tmp_path)]) == 1
    assert "no pack export" in capsys.readouterr().out.lower()


def _frames(tmp_path):
    files = write_activity_csvs(tmp_path)
    packs = transform_packs(read_csv_auto(write_pack_csv(tmp_path)))
    return load_activities(files).frame, packs


def test_the_winning_candidate_is_the_one_that_matches(tmp_path):
    """The fixture links on `communication_pack_cpid` and on nothing else.

    Every activity but one carries `CP-100`; no activity carries a campaign
    LTID or a tracking pack id that a pack row answers to. A candidate that
    scores above zero on those would mean the scoring is matching something
    other than what it claims.
    """
    frame, packs = _frames(tmp_path)

    winner = check_pack_link.score(frame, packs, "communication_pack_cpid")
    assert winner.referenced > 0
    assert winner.matched == winner.referenced
    assert winner.rate == 1.0
    # CP-100 only. CP-200 is the pack nobody planned against.
    assert winner.packs_hit == 1
    assert winner.orphan_packs == 1

    for other in ("campaign_ltid", "tracking_pack_id"):
        assert check_pack_link.score(frame, packs, other).rate == 0.0


def test_an_activity_naming_no_pack_is_not_counted_against_the_rate(tmp_path):
    """`referenced` is the denominator, not the row count.

    One fixture activity carries no pack reference at all. Counting it as a
    miss would drag every candidate below the floor and report a linking
    problem where there is only an unplanned activity.
    """
    frame, packs = _frames(tmp_path)
    scored = check_pack_link.score(frame, packs, "communication_pack_cpid")
    assert scored.referenced < len(frame), "the fixture's unpacked row vanished"


def test_every_candidates_score_is_below_the_floor_when_the_pack_list_matches_nothing(tmp_path):
    """The arithmetic `main()`'s zero-winner path depends on: every `score()`
    sits below `MIN_LINK_RATE` when no pack id the list carries appears in any
    candidate column. This checks only the scores; `test_main_exits_non_zero_
    and_says_so_when_no_candidate_clears_the_floor` below is what checks that
    `main()` actually turns this into exit code 1 and a printed finding --
    this function's previous name promised that and did not test it.
    """
    frame, packs = _frames(tmp_path)
    packs = packs.assign(cpid="NOTHING-MATCHES-THIS")
    scores = [check_pack_link.score(frame, packs, name)
              for name in check_pack_link.PACK_LINK_CANDIDATES]
    assert all(s.rate < check_pack_link.MIN_LINK_RATE for s in scores)


def test_main_exits_zero_and_names_the_winner_when_exactly_one_candidate_clears_the_floor(tmp_path, capsys):
    """The command's success contract, not just `score()`'s arithmetic.

    Task 6 reads `PACK_LINK_COLUMN` off exactly this line of output, so the
    line has to exist and the exit code has to be 0 -- a passing `score()`
    test does not prove `main()` still reports either.
    """
    write_activity_csvs(tmp_path)
    write_pack_csv(tmp_path)
    assert check_pack_link.main(["--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PACK_LINK_COLUMN = communication_pack_cpid" in out


def test_main_exits_non_zero_and_says_so_when_no_candidate_clears_the_floor(tmp_path, capsys):
    """A pack list that links to nothing is a finding, not a crash -- and
    `main()`, not just `score()`, has to say so and exit non-zero.
    """
    write_activity_csvs(tmp_path)
    # A pack export whose only identifier no activity column carries: every
    # candidate scores 0%, on real input read through the real CLI entry
    # point, not on a Score built by hand.
    mismatched = [dict(row, LTID="NOTHING-MATCHES-THIS") for row in PACK_ROWS]
    _write_csv(tmp_path / "CommunicationPacks.csv", mismatched, PACK_HEADER)

    assert check_pack_link.main(["--input", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert ("No candidate clears both floors (80% of its own references, "
            "25% of the pack list)") in out


def test_the_pre_merge_gate_and_the_runtime_warning_share_one_floor():
    """One policy, one value, and not two that agree today.

    `report_calendar` warns below `packs.MIN_LINK_RATE` on every run; this
    tool exits non-zero below its own. While those were two literals, each
    commented as "the same floor" as the other, a gate could pass at a rate
    the runtime warns about -- and both sides would look internally
    consistent, which is what makes that drift the kind nobody finds.
    """
    from pipeline.report import packs

    assert check_pack_link.MIN_LINK_RATE == packs.MIN_LINK_RATE


def test_the_zero_result_prints_both_sides_of_the_comparison(tmp_path, capsys):
    """The outcome this tool exists for is the one it could not diagnose.

    Three candidates at 0% is the answer an operator has to act on, and the
    activity-side samples alone cannot say what it means: an export that
    genuinely does not link and one whose identifiers are merely formatted
    differently -- `CP-100` against `100` -- produce exactly the same zero,
    and lead somewhere completely different.

    The pack-side line is printed once, because the pack list's identifiers
    do not vary by which activity column is being scored.
    """
    write_activity_csvs(tmp_path)
    mismatched = [dict(row, LTID="9" + str(row["LTID"]).split("-")[-1])
                  for row in PACK_ROWS]
    _write_csv(tmp_path / "CommunicationPacks.csv", mismatched, PACK_HEADER)

    assert check_pack_link.main(["--input", str(tmp_path)]) == 1
    out = capsys.readouterr().out

    assert ("No candidate clears both floors (80% of its own references, "
            "25% of the pack list)") in out
    assert "communication_pack_cpid sample values: CP-100" in out, (
        "the activity side lost its samples")
    assert "pack list sample values: 9100, 9200" in out, (
        "a zero with only one side shown cannot be told from a format mismatch")
    assert out.count("pack list sample values") == 1, (
        "the pack ids do not vary by candidate; printing them three times "
        "says nothing new and buries the activity-side lines")


def test_the_orphan_column_header_says_what_it_counts(tmp_path, capsys):
    """`orphan_activities` counts distinct identifiers, not activity rows.

    A human makes the merge call off this table, and a column headed
    "Orphan act." is a number they would reasonably compare against the row
    count -- which it is not, and which it can be far smaller than when one
    unknown pack id sits on forty activities. The field name stays; the
    printed header is the part a reader sees.
    """
    write_activity_csvs(tmp_path)
    write_pack_csv(tmp_path)

    assert check_pack_link.main(["--input", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Orphan IDs" in out
    assert "Orphan act." not in out


def test_a_placeholder_on_thousands_of_activities_is_not_a_pack_reference():
    """The generic identifier is measured, not assumed.

    Every tracking ID carries a cluster and a pack segment, and standalone
    activities -- the great majority -- get generic ones. Counting those as
    references to a pack is what made `tracking_pack_id` read 18,394
    referenced and 1,829 matched on the real export: a 10% rate that
    describes the placeholder's share, not a linking defect.

    Which value is the placeholder is not knowable in advance, so it is
    derived: a value that matches no pack row and still sits on a large share
    of the activities is a placeholder, because a real pack id that is not in
    the pack list cannot legitimately be that popular.
    """
    import pandas as pd

    pack_ids = {f"3KEYS-{i:07d}" for i in range(10)}
    series = pd.Series(["GEN-0000000"] * 900
                       + [f"3KEYS-{i:07d}" for i in range(10)]
                       + ["3KEYS-9999999"])

    generic = check_pack_link.generic_values(series, pack_ids)

    assert generic == {"GEN-0000000": 900}


def test_a_rare_unmatched_identifier_is_a_dead_reference_not_a_placeholder():
    """The two failures have to stay apart, because they lead apart.

    A placeholder means "this activity has no pack", which is the normal
    state and no defect at all. A pack id on a handful of activities that the
    pack list does not answer to means a pack is missing from the export or
    the id is dead -- the finding worth acting on. Folding them together
    would bury the second inside the first, which is exactly the size
    difference between them.
    """
    import pandas as pd

    pack_ids = {"3KEYS-0000001"}
    series = pd.Series(["GEN-0000000"] * 500 + ["3KEYS-0000001"] * 20
                       + ["3KEYS-0000404"] * 3)

    generic = check_pack_link.generic_values(series, pack_ids)

    assert "3KEYS-0000404" not in generic
    assert "GEN-0000000" in generic


def test_a_share_of_a_tiny_export_does_not_make_a_placeholder():
    """A placeholder is a value thousands of activities share. On eight rows
    there is nothing to share.

    Share alone is a rule that inverts on small input: in a hand-built export,
    or a fixture, every distinct unmatched value holds a large share of the
    column and would be waved through as "no pack" -- which is the one
    category the report presents as expected. The dead references it is
    supposed to surface would disappear into it exactly when the export is
    small enough for someone to check by hand.
    """
    import pandas as pd

    series = pd.Series(["DEAD-0000404"] * 4 + [f"3KEYS-{i:07d}" for i in range(4)])

    assert check_pack_link.generic_values(series, {"3KEYS-0000000"}) == {}


def _index(*pack_ids):
    return check_pack_link.build_index(set(pack_ids))


def test_a_reference_the_pack_list_answers_to_is_resolved():
    assert check_pack_link.classify("3KEYS-0000058", _index("3KEYS-0000058"),
                                    {}) == check_pack_link.RESOLVED


def test_a_placeholder_is_reported_as_generic_rather_than_as_a_miss():
    """The category that is not a defect, and has to be visible as such.

    It matches no pack and never will. Reported as a miss it inflates the
    only number a reader uses to judge the join; reported as its own
    category it says what it is -- an activity with no pack.
    """
    assert check_pack_link.classify("GEN-0000000", _index("3KEYS-0000058"),
                                    {"GEN-0000000": 900}) == check_pack_link.GENERIC


def test_the_same_pack_number_under_another_cluster_is_named_as_such():
    """A repairable join, and one a plain set membership test cannot see.

    The pack list carries the pack under one cluster prefix and the activity's
    tracking ID was built with another. The pack exists, the number is right,
    and only the prefix disagrees -- which is a mapping decision, not a
    missing pack, and reads as a flat miss until it is separated out.
    """
    assert check_pack_link.classify("QRREP-0000058", _index("3KEYS-0000058"),
                                    {}) == check_pack_link.CLUSTER_DIFFERS


def test_a_number_that_matches_only_unpadded_is_a_format_difference():
    """`58` and `0000058` are the same pack written twice."""
    assert check_pack_link.classify("3KEYS-58", _index("3KEYS-0000058"),
                                    {}) == check_pack_link.PADDING_DIFFERS


def test_a_pack_number_two_packs_share_is_ambiguous_rather_than_matched():
    """The case that would make a prefix-tolerant join quietly wrong.

    Two packs in different clusters carrying the same number, and an
    activity naming that number under a third. Repairing the join by number
    alone would assign one of them -- with no evidence for either -- and the
    result reads exactly like a clean match. It has to be its own category so
    the decision stays with a human.
    """
    assert check_pack_link.classify(
        "OTHER-0000058", _index("3KEYS-0000058", "QRREP-0000058"),
        {}) == check_pack_link.AMBIGUOUS


def test_a_reference_nothing_answers_to_on_any_rung_is_the_finding():
    assert check_pack_link.classify("3KEYS-0000404", _index("3KEYS-0000058"),
                                    {}) == check_pack_link.NO_PACK


def test_the_rate_ignores_the_placeholders_it_was_told_about():
    """The comparison the old score could not make.

    Scored with the placeholders in the denominator, a column that resolves
    every real reference it carries reads as a 1% link -- which is the share
    of activities that have a pack, reported as if it were the share of
    references that resolve. The two questions have different answers and
    only one of them is about the join.
    """
    import pandas as pd

    packs = pd.DataFrame({"cpid": [f"3KEYS-{i:07d}" for i in range(10)]})
    frame = pd.DataFrame({"tracking_pack_id": ["GEN-0000000"] * 990
                                              + [f"3KEYS-{i:07d}" for i in range(10)]})

    raw = check_pack_link.score(frame, packs, "tracking_pack_id")
    honest = check_pack_link.score(frame, packs, "tracking_pack_id",
                                   ignore={"GEN-0000000": 990})

    assert raw.rate < 0.05
    assert honest.rate == 1.0
    assert honest.referenced == 10


def test_the_chain_falls_back_only_where_the_first_column_is_empty():
    """The fallback is a fallback, not a second opinion.

    Where `communication_pack_cpid` says something it wins outright --
    it is the column the source system fills deliberately. The tracking ID
    speaks only for the rows it leaves empty, and a placeholder there is
    still no pack rather than a value worth carrying forward.
    """
    import pandas as pd

    frame = pd.DataFrame({
        "communication_pack_cpid": ["3KEYS-0000001", "", ""],
        "tracking_pack_id": ["QRREP-0000009", "3KEYS-0000002", "GEN-0000000"],
    })

    chained = check_pack_link.with_chain(frame, {"GEN-0000000": 1})

    assert list(chained[check_pack_link.CHAIN_COLUMN]) == [
        "3KEYS-0000001", "3KEYS-0000002", ""]


def test_the_two_columns_disagreeing_is_reported_with_both_values():
    """The veto on the chain, and the only number that can see a wrong join.

    Where both columns are filled they are two independent statements about
    the same activity. Every disagreement is a row the chain would resolve to
    one pack while the source system names another, and a count alone cannot
    be judged -- the pair has to be printed, because whether `3KEYS-0000001`
    against `QRREP-0000001` is a cluster prefix drifting or two different
    packs is not a question this tool can answer.
    """
    import pandas as pd

    frame = pd.DataFrame({
        "communication_pack_cpid": ["3KEYS-0000001", "3KEYS-0000002", "", "3KEYS-0000003"],
        "tracking_pack_id": ["3KEYS-0000001", "QRREP-0000002", "3KEYS-0000009",
                             "GEN-0000000"],
    })

    verdict = check_pack_link.agreement(frame, {"GEN-0000000": 1})

    # The third row has no first-column value and the fourth carries a
    # placeholder: neither is two statements about one activity.
    assert verdict.both == 2
    assert verdict.agree == 1
    assert verdict.disagree == 1
    assert verdict.samples == (("3KEYS-0000002", "QRREP-0000002"),)


def _standalone_export(directory, packed=3, standalone=30):
    """An export shaped like the real one: mostly standalone activities.

    Every tracking ID carries a pack segment; the standalone rows carry the
    generic one. Written with the two columns this measurement reads, because
    a fixture that also models divisions and audiences would say nothing more
    about the question and hide which column the assertions are about.
    """
    header = ["Tracking ID", "Communication pack:C"]
    rows = [{"Tracking ID": f"3KEYS-0000058-250101-{i:07d}-EMI",
             "Communication pack:C": "3KEYS-0000058"} for i in range(packed)]
    rows += [{"Tracking ID": f"GEN-0000000-250101-{i:07d}-EMI",
              "Communication pack:C": ""} for i in range(standalone)]
    _write_csv(directory / "InternalCommunicationActivities.csv", rows, header)
    _write_csv(directory / "CommunicationPacks.csv",
               [{"LTID": "3KEYS-0000058", "Title": "Pack one"}], PACK_HEADER)
    return directory


def test_main_names_the_generic_identifier_it_measured(tmp_path, capsys):
    """The placeholder is reported by value, not silently compensated for.

    A rule that quietly drops the most common unmatched value is a rule
    nobody can check. Naming it lets a reader confirm it against the source
    system -- and catches the case the rule cannot tell apart on its own, a
    stale pack export where a genuine pack id is missing from the list and
    sits on thousands of activities.
    """
    _standalone_export(tmp_path)
    check_pack_link.main(["--input", str(tmp_path)])
    out = capsys.readouterr().out

    assert "tracking_pack_id generic identifiers: GEN-0000000" in out
    assert "30 activities" in out


def test_main_scores_the_tracking_id_without_the_placeholders(tmp_path, capsys):
    """The number the decision turns on.

    With the placeholders counted as references the column reads 9%; without
    them it reads 100%, and the difference is entirely the standalone
    activities that never had a pack. Both numbers are printed, because a
    reader who sees only the second would conclude the tracking ID links
    almost every activity to a pack -- it links the few that have one.
    """
    _standalone_export(tmp_path)
    check_pack_link.main(["--input", str(tmp_path)])
    out = capsys.readouterr().out

    assert ("tracking_pack_id: 9% of 33 references, "
            "100% of the 3 that are not placeholders") in out


def test_main_breaks_the_references_into_categories(tmp_path, capsys):
    """Which kind of miss it is, not merely that it missed."""
    _standalone_export(tmp_path)
    check_pack_link.main(["--input", str(tmp_path)])
    out = capsys.readouterr().out

    assert "resolved" in out
    assert "generic" in out


def test_the_chain_is_measured_but_never_wins_on_its_own(tmp_path, capsys):
    """It is a proposal, not a column.

    The chain resolves as cleanly as its first column and reaches at least as
    far, so scored as a candidate it would tie with `communication_pack_cpid`
    on every healthy export -- and `main()` would report a tie needing a human
    on a run where nothing is wrong. Worse, a tie is how this tool says "I
    cannot choose", which is the opposite of what the chain's score means.
    `PACK_LINK_COLUMN` names one column the ETL reads; the chain needs code
    that does not exist yet, and the agreement veto below decides whether it
    should.
    """
    _standalone_export(tmp_path)
    exit_code = check_pack_link.main(["--input", str(tmp_path)])
    out = capsys.readouterr().out

    assert check_pack_link.CHAIN_COLUMN in out, "the chain was not measured"
    assert exit_code == 0
    assert "PACK_LINK_COLUMN = communication_pack_cpid" in out


def test_main_prints_the_disagreement_with_both_values(tmp_path, capsys):
    """The veto, and both sides of it.

    An export where the tracking ID names one pack and the pack field names
    another on the same activity. The chain would resolve it to the second
    and look clean doing so.
    """
    header = ["Tracking ID", "Communication pack:C"]
    rows = [{"Tracking ID": "QRREP-0000058-250101-0000001-EMI",
             "Communication pack:C": "3KEYS-0000058"}]
    _write_csv(tmp_path / "InternalCommunicationActivities.csv", rows, header)
    _write_csv(tmp_path / "CommunicationPacks.csv",
               [{"LTID": "3KEYS-0000058", "Title": "Pack one"}], PACK_HEADER)

    check_pack_link.main(["--input", str(tmp_path)])
    out = capsys.readouterr().out

    assert "1 disagree" in out
    assert "3KEYS-0000058 vs QRREP-0000058" in out


def test_the_detail_csv_carries_every_identifier_and_its_category(tmp_path):
    """The report leaves the machine as a file, not as a screenshot."""
    _standalone_export(tmp_path)
    detail = tmp_path / "detail.csv"

    check_pack_link.main(["--input", str(tmp_path), "--detail", str(detail)])

    import csv
    rows = list(csv.DictReader(detail.open(encoding="utf-8")))
    by_identifier = {row["identifier"]: row for row in rows
                     if row["column"] == "tracking_pack_id"}

    assert by_identifier["GEN-0000000"]["category"] == check_pack_link.GENERIC
    assert by_identifier["GEN-0000000"]["activities"] == "30"
    assert by_identifier["3KEYS-0000058"]["category"] == check_pack_link.RESOLVED


def _numbers(*pack_ids):
    import pandas as pd

    return pd.DataFrame({"cpid": list(pack_ids)})


def test_the_pack_number_alone_finds_a_pack_whose_cluster_prefix_differs():
    """The join the cluster-and-number one cannot make.

    On the live export the tracking ID carries the generic cluster `CCCCC`
    over a real pack number while the pack itself sits under another prefix.
    Cluster and number together miss every one of those; the number alone is
    the whole point of measuring this separately.
    """
    import pandas as pd

    frame = pd.DataFrame({"tracking_pack_number": ["0000184", "0000185"]})

    joined = check_pack_link.number_join(frame, _numbers("SPONS-0000184"), {})

    assert joined.score.referenced == 2
    assert joined.score.matched == 1
    assert joined.score.packs_hit == 1


def test_a_number_two_packs_share_is_counted_apart_from_the_matches():
    """The cost of dropping the prefix, in the same report as the benefit.

    Without the cluster there is nothing left to tell two packs with the same
    number apart. Counting such a reference as matched would assign one of
    them at random and look exactly like a clean join, so it is counted on its
    own line -- and a reader can weigh it against what the variant gains.
    """
    import pandas as pd

    frame = pd.DataFrame({"tracking_pack_number": ["0000184", "0000184", "0000185"]})
    packs = _numbers("SPONS-0000184", "3KEYS-0000184", "3KEYS-0000185")

    joined = check_pack_link.number_join(frame, packs, {})

    assert joined.score.matched == 1, "only the unambiguous number matched"
    assert joined.ambiguous_refs == 2
    assert joined.ambiguous_packs == 2


def test_the_number_join_ignores_the_placeholder_number():
    """`0000000` is 90% of the column and no pack at all."""
    import pandas as pd

    frame = pd.DataFrame({"tracking_pack_number": ["0000000"] * 30 + ["0000184"]})

    joined = check_pack_link.number_join(frame, _numbers("SPONS-0000184"),
                                         {"0000000": 30})

    assert joined.score.referenced == 1
    assert joined.score.rate == 1.0


def test_main_scores_the_pack_number_beside_the_other_candidates(tmp_path, capsys):
    """It belongs in the same table, or it cannot be compared with them."""
    _standalone_export(tmp_path)
    check_pack_link.main(["--input", str(tmp_path)])
    out = capsys.readouterr().out

    assert check_pack_link.NUMBER_COLUMN in out
    assert "packs share a number" in out


def test_the_launcher_passes_on_every_flag_the_check_accepts():
    """The machine that has the production export runs the launcher.

    Not `python -m`: the corp machine is reached through `packlink.cmd`, so a
    flag the Python entry point accepts and the launcher does not forward is
    a flag nobody there can use. The one that matters most is the flag that
    writes the report to a file -- without it the whole measurement has to be
    read off a console window and typed out by hand.

    Derived from the parser rather than listed here, so a flag added later
    cannot be forgotten quietly.
    """
    from pathlib import Path

    launcher = (Path(check_pack_link.__file__).resolve().parents[2]
                / "packlink.ps1").read_text(encoding="utf-8")

    flags = [option
             for action in check_pack_link.build_parser()._actions
             for option in action.option_strings
             if option.startswith("--") and option != "--help"]

    assert flags, "the parser exposes no flags at all"
    for flag in flags:
        assert flag in launcher, f"packlink.ps1 cannot pass {flag} on"


def test_main_exits_non_zero_and_names_the_tie_when_more_than_one_candidate_clears_the_floor(tmp_path, capsys):
    """A tie is not `main()`'s to break silently.

    A minimal, hand-built export where `Communication pack:C` and `Campaign
    LTID` both carry the same pack id on every row -- so both candidates
    clear the floor together. `main()` must name the tie and refuse to pick
    one on its own: Task 6 reads a human's decision out of this output, not
    a guess the tool made because it had to return something.
    """
    header = ["Communication pack:C", "Campaign LTID"]
    rows = [{"Communication pack:C": "MULTI-1", "Campaign LTID": "MULTI-1"} for _ in range(3)]
    _write_csv(tmp_path / "InternalCommunicationActivities.csv", rows, header)
    tied_pack = [{"LTID": "MULTI-1"}]
    _write_csv(tmp_path / "CommunicationPacks.csv", tied_pack, PACK_HEADER)

    assert check_pack_link.main(["--input", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert ("2 candidates clear both floors: "
            "communication_pack_cpid, campaign_ltid") in out
