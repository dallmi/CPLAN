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
    """The mapping now carries the pack form's identity fields.

    This test used to assert the opposite: that `Name of communication
    pack`, `Tracking cluster`, `Category` and `End date` were unmapped, which
    was true until the map was widened to cover them. A pack file built
    without them cannot name a pack -- so once the gap closed, the honest
    version of this test is that they are mapped, not that the gap survived.
    """
    rows = check_pack_link.unmapped_columns(PACK_HEADER)
    by_name = {raw: status for raw, _, status in rows}

    assert by_name["LTID"] == "mapped"
    assert by_name["Name of communication pack"] == "mapped"
    assert by_name["Tracking cluster"] == "mapped"
    assert by_name["Category"] == "mapped"
    assert by_name["End date"] == "mapped"


def test_the_map_now_covers_every_column_the_fixture_exports():
    """The fixture is the documented pack form. A column it carries and the
    map does not is a field the pack file cannot show.
    """
    unmapped = [raw for raw, _, status in check_pack_link.unmapped_columns(PACK_HEADER)
                if status == "unmapped"]
    assert unmapped == [], f"still unmapped: {unmapped}"


def test_the_harmonised_pack_frame_carries_the_identity_fields(tmp_path):
    packs = transform_packs(read_csv_auto(write_pack_csv(tmp_path)))
    for column in ("cpid", "pack_name", "tracking_cluster", "category", "end_date"):
        assert column in packs.columns, f"{column} is missing"
    assert set(packs["pack_name"]) >= {"Pack one", "Pack with nothing planned"}


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
    assert "No candidate reaches 80%" in out


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

    assert "No candidate reaches 80%" in out
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
    assert "2 candidates clear 80%: communication_pack_cpid, campaign_ltid" in out
