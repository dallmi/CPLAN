"""The check that says whether a board panel has anything to draw.

Every assertion here is a false verdict this tool produced before it was
fixed. That is deliberate: the tool exists to stop a reader misreading a zero,
so a tool that misreads one itself is worse than none -- it puts a wrong
diagnosis in front of somebody who came here precisely because the raw number
was ambiguous.

The four causes of a zero, and what each is owed:

  a measure that counts a problem, reading zero  -> good news, say it in words
  a column the export carries and nobody fills   -> chase the source owners
  a column the export does not carry             -> not a finding at all
  a pack older than the board asking             -> rebuild the pack
"""

import pytest

pytest.importorskip("pandas")

from pipeline.report import dashboard_skill
from pipeline.report.metrics import REPORTED_FIELDS
from pipeline.scripts import check_board_fill as fill


def _pack(tmp_path, *, quality=None, periods=None, breakdowns=None,
          summary=None):
    """The smallest pack the tool will read, with one part swapped out."""
    pack = tmp_path / "pack"
    pack.mkdir(exist_ok=True)
    (pack / "01-summary.txt").write_text(summary or (
        "CPLAN REPORT - EXECUTIVE SUMMARY\n\n"
        "VOLUME\n------\n"
        "  Activities in scope: 100\n"
        "  Unknown: 0  (0% of the 100 in scope)\n"
    ), encoding="utf-8")
    (pack / "03-data-quality.txt").write_text(quality or (
        "CPLAN REPORT - DATA QUALITY\n\n"
        "FIELD COMPLETENESS\n------------------\n"
        "  field | filled | missing | % missing\n"
        "  bod_geb | 0 | 100 | 100%\n"
        "  communication_pack_cpid | 100 | 0 | 0%\n"
    ), encoding="utf-8")
    (pack / "06-breakdowns.csv").write_text(breakdowns or (
        "block,value,overlaps,measure,figure\n"
        "business_division,Alpha,no,without_pack,0\n"
    ), encoding="utf-8")
    if periods is not None:
        (pack / "08-periods.csv").write_text(periods, encoding="utf-8")
    return pack


def test_zero_is_the_good_news_when_the_measure_counts_a_problem(tmp_path):
    """The first false verdict this tool gave.

    `without_pack` counts activities that record no pack link. Every activity
    linked reads as zero here, which is the healthy plan -- and the tool called
    it "a mapping fault, not a data gap", because it saw a filled column beside
    a zero measure and applied the logic that belongs to `with_executives`.

    Polarity cannot be read off the pack: `activities` and `without_pack` are
    both counts, and nothing in the file says one is bad when large and the
    other when small. So it is written down once, in `COUNTS_ABSENCE`.
    """
    pack = _pack(tmp_path)
    fields = fill.field_completeness(pack)
    verdict, detail = fill.diagnose(
        "06-breakdowns.csv · block=business_division · measure=without_pack",
        [0], fields, 100)
    assert verdict == fill.CLEAN, detail
    assert "good news" in detail
    assert "mapping fault" not in detail


def test_a_clean_panel_does_not_fail_the_run(tmp_path):
    """Nothing to plot because nothing is wrong is not a defect.

    A gate that fails on it teaches the reader to ignore the gate, which costs
    more than the panel it flagged.
    """
    assert fill.CLEAN in fill._HEALTHY
    assert fill.EMPTY not in fill._HEALTHY
    assert fill.UNMEASURABLE not in fill._HEALTHY


def test_an_absent_column_is_not_a_planning_finding(tmp_path):
    """The loudest wrong number the boards can print.

    `without_pack` counts an absence, so a column the export never carried
    reads as every activity in the plan failing to record a pack link -- the
    most alarming figure available and the least likely to be questioned.
    `metrics.pack_stats` returns `len(frame)` for a missing column and for a
    universally blank one alike, so the breakdown file alone cannot tell them
    apart. Crossing it with the field table can.
    """
    pack = _pack(tmp_path, quality=(
        "CPLAN REPORT - DATA QUALITY\n\n"
        "FIELD COMPLETENESS\n------------------\n"
        "  field | filled | missing | % missing\n"
        "  bod_geb | 0 | 100 | 100%\n"
    ))
    verdict, detail = fill.diagnose(
        "06-breakdowns.csv · block=business_division · measure=without_pack",
        [100], fill.field_completeness(pack), 100)
    assert verdict == fill.UNMEASURABLE, detail
    assert "communication_pack_cpid" in detail
    assert "not a planning finding" in detail


def test_a_carried_but_unfilled_column_is_named(tmp_path):
    """The case the leadership board turns on: four of its five panels plot
    `with_executives`, and the one column under all four is `bod_geb`.
    """
    verdict, detail = fill.diagnose(
        "06-breakdowns.csv · block=business_division · measure=with_executives",
        [0, 0, 0], fill.field_completeness(_pack(tmp_path)), 100)
    assert verdict == fill.EMPTY
    assert "bod_geb is carried and never filled" in detail


def test_it_never_calls_an_unreported_column_missing(tmp_path):
    """The second false verdict, and the more dangerous kind.

    `metrics.field_completeness` walks a fixed list, so a column outside
    `REPORTED_FIELDS` has no row in the quality table whether the export
    carries it or not. Reading that absence as "the export has no such column"
    would be the tool inventing a finding out of its own blind spot -- and
    `created`, which `short_notice` depends on, is exactly such a column.
    """
    assert fill.MEASURE_COLUMN["short_notice"] == "created"
    assert "created" not in REPORTED_FIELDS, (
        "the pack now reports `created`; this tool may state its fill rate")
    verdict, detail = fill.diagnose(
        "08-periods.csv · block=TOTAL · grain=quarter · measure=short_notice",
        [0], fill.field_completeness(_pack(tmp_path)), 100)
    assert verdict == fill.EMPTY
    assert "does not report" in detail
    assert "not carried by the export" not in detail


def test_every_named_column_is_one_the_pack_could_report(tmp_path):
    """Drift guard on the two maps.

    Naming a column that does not exist would print a confident instruction to
    go and fill in a field nobody has. Each entry is either a field the quality
    table reports, or one knowingly outside it -- and the second list is short
    on purpose, because every name on it is a diagnosis the tool cannot make.
    """
    unreported = {"created"}
    for measure, column in fill.MEASURE_COLUMN.items():
        assert column in REPORTED_FIELDS or column in unreported, (
            f"{measure} names {column!r}, which the pack never reports")
    for label, column in fill.LABEL_COLUMN.items():
        assert column in REPORTED_FIELDS, f"{label} names {column!r}"


def test_a_stale_pack_is_told_apart_from_a_drifted_board(tmp_path):
    """Opposite problems arriving as the same error.

    "No row matches" means either a citation nobody updated or a pack built
    before the boards asked for that grain. One is fixed by editing a board,
    the other by rebuilding the pack, and sending somebody to the wrong one
    costs a day.
    """
    pack = _pack(tmp_path, periods=(
        "block,value,overlaps,grain,period,measure,figure\n"
        "TOTAL,all activities,no,year,2026,with_executives,42\n"
    ))
    verdict, detail = fill._unresolved(
        "08-periods.csv · block=TOTAL · grain=quarter · measure=with_executives",
        "no row matches", pack)
    assert verdict == fill.STALE
    assert "Rebuild it" in detail

    gone, detail = fill._unresolved(
        "08-periods.csv · block=TOTAL · grain=quarter · measure=invented",
        "no row matches", pack)
    assert gone == fill.MISSING


def test_a_pack_missing_a_file_every_build_writes_is_dated_not_faulted(tmp_path):
    """From the first run on real data: fourteen of twenty-three panels read
    `GONE - the pack has no 06-breakdowns.csv`, which invites somebody to go
    and fix boards that were correct. The pack simply had no such file.

    `agent_pack` writes the breakdown and period files on every build, so a
    board citing them cannot be wrong about them existing. Absence dates the
    pack. `07-packs.csv` is excluded on purpose -- it appears only where a
    pack list was synced, so a build without one is a real shape, not an old
    one.
    """
    pack = _pack(tmp_path)  # writes no 08-periods.csv
    assert not (pack / "08-periods.csv").exists()
    verdict, detail = fill._unresolved(
        "08-periods.csv · block=TOTAL · grain=quarter · measure=with_executives",
        "the pack has no 08-periods.csv", pack)
    assert verdict == fill.STALE, detail

    assert "07-packs.csv" not in fill.ALWAYS_WRITTEN, (
        "a build with no pack list would be reported as an old pack")


def test_the_remedy_for_an_old_pack_is_stated_once(tmp_path):
    """One missing file struck fourteen panels on the first real run, and the
    fix printed on every one of them buried the panels worth reading alone.

    It also has to name both old copies. A rebuild fixes an old pack; it
    cannot fix a pipeline too old to write the file, and somebody whose
    rebuild changes nothing needs to be told which tool answers that.
    """
    note = fill.stale_pack_note(_pack(tmp_path))  # writes no 08-periods.csv
    assert note is not None
    assert "08-periods.csv" in note
    assert "Rebuild the pack" in note
    assert "check.ps1" in note, "a stale pipeline needs the other tool named"

    full = tmp_path / "full"
    full.mkdir()
    complete = _pack(full, periods="block,value\nTOTAL,x\n")
    (complete / "04-calendar.csv").write_text("block,value\nTOTAL,x\n",
                                              encoding="utf-8")
    assert fill.stale_pack_note(complete) is None, (
        "a complete pack is told it is old")


def test_the_report_fits_a_console(tmp_path, capsys):
    """Where this report is read, and how it travels.

    It is run in cmd.exe and then photographed and sent on, which is how the
    remedy paragraph first arrived with its middle outside the frame. Nothing
    was lost -- the console wraps rather than truncates -- but it wraps at
    whatever width the window happens to have, and a paragraph that only reads
    correctly in the window it was run in is not a report anybody can forward.

    The pack path is exempt: a path broken across two lines cannot be pasted
    back, which is the one thing a reader is most likely to want to do with it.
    """
    fill.main(["--pack", str(_pack(tmp_path))])
    for line in capsys.readouterr().out.splitlines():
        if line.startswith("Pack: "):
            continue
        assert len(line) <= fill.WIDTH, f"{len(line)} chars: {line}"


def test_it_reads_a_value_that_carries_its_own_gloss():
    """`01-summary.txt` writes the count and then explains it on the same line.
    Taking the whole line as a number yields nothing; taking the head yields
    the figure the panel plots.
    """
    assert fill.number("0  (0% of the 2400 in scope)") == 0
    assert fill.number("2400") == 2400
    assert fill.number("3'541") == 3541
    assert fill.number("2026-08-11") is None
    assert fill.number("") is None


def test_the_boards_are_imported_not_restated(tmp_path):
    """The reason this lives beside the boards rather than in a runbook.

    Add a panel and the check follows it without being edited. A copy of the
    panel list here would pass its own tests forever while the boards moved.
    """
    results, _, _ = fill.audit(_pack(tmp_path))
    audited = {row.board for row in results}
    for board in dashboard_skill.BOARDS:
        assert board in audited, f"{board} is shipped and never checked"
    for board in audited:
        panels = [row for row in results if row.board == board]
        assert panels, f"{board} audited with no panels"


def test_a_panel_is_only_as_drawable_as_its_weakest_citation(tmp_path):
    """Panel 1 of the leadership board cites a filled figure and an empty one.
    Reporting the healthy half would say the panel draws when it does not.
    """
    assert fill._RANK[fill.MISSING] < fill._RANK[fill.EMPTY]
    assert fill._RANK[fill.EMPTY] < fill._RANK[fill.FILLS]
    assert fill._RANK[fill.STALE] < fill._RANK[fill.CLEAN]
