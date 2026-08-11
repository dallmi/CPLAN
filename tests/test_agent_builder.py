"""The same report pack, delivered to a surface that has no skills.

Agent Builder holds 8,000 characters of Instructions and no skill packages at
all, so the rules that live in a skill next door have to live in a knowledge
file or in the prompt. The tests that matter here are the ones holding this
delivery to the pack it is built from, and to the limits the surface enforces.
"""

import re
from datetime import date

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("pandas")

from pipeline.report import agent_builder, agent_pack, dashboard_skill
from pipeline.report.config import ReportConfig
from pipeline.scripts import build_agent_pack as build
from tests.report_fixtures import load_fixture_scope


def _builder(tmp_path):
    """Both deliveries from one run, the way the command produces them."""
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config)
    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "pack-out")
    out_dir = tmp_path / "builder-out"
    upload_dir = agent_builder.write_builder_pack(pack_dir, out_dir, scope, config)
    return pack_dir, upload_dir, out_dir


def _builder_with_packs(tmp_path):
    """`_builder`, on a run that has the pack export too."""
    config = ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    scope = load_fixture_scope(tmp_path / "csv", config, with_packs=True)
    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "pack-out")
    out_dir = tmp_path / "builder-out"
    upload_dir = agent_builder.write_builder_pack(pack_dir, out_dir, scope, config)
    return pack_dir, upload_dir, out_dir


def test_the_upload_folder_carries_the_pack_file_in_reading_order(tmp_path):
    """Data files first, rules behind them. An operator uploads a folder, and
    a folder that sorts into reading order is one fewer thing to explain.
    """
    _, upload_dir, _ = _builder_with_packs(tmp_path)

    names = sorted(p.name for p in upload_dir.iterdir())
    assert agent_pack.PACKS_CSV_NAME in names
    assert names.index("08-periods.csv") < names.index("09-reading-guide.txt")
    assert len(names) <= agent_builder.KNOWLEDGE_SOURCE_LIMIT


def test_a_run_without_the_pack_export_still_delivers(tmp_path):
    """The copy step runs one stage after the run that tolerated the missing
    input. Turning it into a crash there would undo the tolerance.
    """
    _, upload_dir, _ = _builder(tmp_path)
    names = [p.name for p in upload_dir.iterdir()]
    assert agent_pack.PACKS_CSV_NAME not in names
    assert "09-reading-guide.txt" in names


def test_a_missing_required_file_fails_the_delivery_rather_than_shrinking_it(tmp_path):
    """The tolerance above is for the pack file, and for nothing else.

    Spread over the other six, it turns a write that failed upstream into an
    upload folder that is quietly one file short. The folder is the
    instruction here -- an operator uploads it whole and the agent is
    grounded on whatever is in it -- so the missing file never announces
    itself, and shows up as a figure the agent could not find.
    """
    pack_dir, _, _ = _builder(tmp_path)
    (pack_dir / agent_pack.ACTIVITIES_CSV_NAME).unlink()

    with pytest.raises(FileNotFoundError):
        agent_builder.write_builder_pack(pack_dir, tmp_path / "second-builder-out")


@pytest.mark.parametrize("with_packs", [False, True])
def test_no_uploaded_document_names_a_file_the_upload_does_not_hold(tmp_path, with_packs):
    """The folder is the delivery, so the folder is what its prose may claim.

    The reading guide's Packs section explains a file and a `pack_known`
    column that only a pack export produces. Delivered beside an upload that
    has neither, it is an instruction to retrieve something that is not
    there -- answered, like every retrieval miss, from whatever is.
    """
    _, upload_dir, _ = _builder_with_packs(tmp_path) if with_packs else _builder(tmp_path)
    held = {path.name for path in upload_dir.iterdir()}
    guide = (upload_dir / agent_builder.READING_GUIDE_NAME).read_text(encoding="utf-8")

    named = set(re.findall(r"\d\d-[A-Za-z-]+\.(?:txt|csv)", guide))
    assert named <= held, (
        f"{agent_builder.READING_GUIDE_NAME} names {sorted(named - held)}, "
        "which is not in the folder it is uploaded with")
    assert (agent_pack.PACKS_CSV_NAME in held) is with_packs
    assert ("## Packs" in guide) is with_packs


def test_the_pasted_prompt_describes_both_states_of_the_pack_file():
    """Instructions cannot follow a run; knowledge files can.

    This text is pasted into a field once and stays there while the pack is
    rebuilt underneath it, so it is the one document that outlives the state
    it was written in: a machine that starts syncing the pack export next
    month would be left with a prompt denying a file it now holds, and one
    that stops would be left with a prompt asserting one it lost. It says
    both, the way the GEB wording here already does.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert agent_pack.PACKS_CSV_NAME in text
    assert "Present only where a pack list was synced" in text, (
        "the prompt asserts the pack file unconditionally, on a surface where "
        "it is delivered only sometimes")


def test_the_builder_folder_is_created_only_where_the_sync_is_proven(tmp_path, monkeypatch):
    """`Input/` existing is the proof, and `Output/` is created beside it.

    Never creating anything would drop this delivery into the checkout on the
    first run, unsynced -- which is the failure the never-create rule exists to
    prevent, arriving by the other door. Creating unconditionally would make a
    folder inside a OneDrive that is not really set up, which syncs nowhere.
    """
    onedrive = tmp_path / "OneDrive - Example"
    monkeypatch.setattr(build, "find_onedrive_root", lambda: onedrive)

    # No CPLAN Input folder: nothing is created, the local fallback is used.
    assert build.resolve_builder_output_dir() == build.BUILDER_LOCAL_OUTPUT_DIR
    assert not (onedrive / build.ONEDRIVE_OUTPUT_DIR).exists()

    # Input exists, so the sync is real and Output can be created beside it.
    (onedrive / build.ONEDRIVE_INPUT_DIR).mkdir(parents=True)
    expected = onedrive / build.ONEDRIVE_OUTPUT_DIR / build.BUILDER_DIRNAME
    assert build.resolve_builder_output_dir() == expected
    assert expected.exists()

    # No OneDrive at all: the local fallback, and still nothing conjured.
    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    assert build.resolve_builder_output_dir() == build.BUILDER_LOCAL_OUTPUT_DIR


def test_the_two_deliveries_do_not_share_a_folder():
    """One is an input's neighbour, the other is a set of files to upload.

    Sharing a folder would put an answer key beside the export the pipeline
    reads, and would make `Nothing in the pipeline deletes from there` a
    promise about two different things at once.
    """
    assert build.ONEDRIVE_OUTPUT_DIR != build.ONEDRIVE_INPUT_DIR
    assert build.BUILDER_LOCAL_OUTPUT_DIR != build.LOCAL_OUTPUT_DIR


def test_the_instructions_fit_the_field_with_room_to_spare():
    """8,000 is the surface's limit, and a limit hit exactly is a limit missed.

    Measured with the placeholder still in it: the text is pasted after one
    find-and-replace, and an organisation whose name is longer than
    `<ORGANISATION>` must not be the thing that pushes it over.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert len(text) <= agent_builder.INSTRUCTIONS_LIMIT, (
        f"{len(text)} characters against a field that holds "
        f"{agent_builder.INSTRUCTIONS_LIMIT}")
    headroom = agent_builder.INSTRUCTIONS_LIMIT - len(text)
    assert headroom >= 200, (
        f"only {headroom} characters spare -- too tight for a longer "
        f"organisation name than the {len(agent_pack.ORGANISATION_PLACEHOLDER)}-"
        "character placeholder")


def test_no_rule_was_lost_in_the_compression():
    """A four-fifths cut is where a load-bearing rule quietly goes missing.

    Each marker below is a rule that produces a WRONG answer when absent, not
    merely a duller one: a total that disagrees with the workbook in the
    reader's hand, a sum over rows that must not be summed, a headcount
    presented as reach. The Studio instructions state all of them, and an edit
    here that drops one fails rather than shipping an agent missing a rule.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    for marker in (
            "does not contain sufficient evidence",   # refuse rather than invent
            "how many rows you examined",             # a partial count is named as one
            "out of scope",                           # absent is not zero
            "overlaps=yes",                           # overlapping rows do not sum
            "never call any of it",                   # audience is not reach
            "GEB or GEB-1",                           # one field, two levels
            "one combination, not one channel",       # multi-value strings
            "the week it starts",                     # weekly placement
            "in_report",                              # wider than the workbook
            "includes M the report excludes",         # and an image says which
            "planning studio",                        # where to send what is missing
            "#E60000",                                # the accent
            "#7A7870",                                # the default series
            "largest area",                           # red bounded by area, not count
            "half the image",                         # the white ratio
            "No gridlines",
            "Data as of",                             # the footer's date
            agent_pack.TEAM_SIGNATURE,                # the signature
    ):
        assert marker in text, f"the compression dropped {marker!r}"


def test_the_prompt_names_the_board_that_exists(tmp_path):
    """A knowledge file cannot announce itself, so the prompt is the only
    place a board's existence can be stated — and a prompt naming a board the
    catalogue no longer ships sends the agent looking for a missing file.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert "head of communications overview" in text.lower()
    assert "portfolio overview" not in text.lower()
    for board in ("leadership attention", "plan trust"):
        assert board in text.lower()


def test_every_surface_requires_the_identifier_beside_the_name(tmp_path):
    """A name is not unique and cannot be looked up; an identifier is both.

    An answer listing activities or packs by name alone reads well and is
    not actionable -- two activities can share a name, and nobody can find
    one in the source system from it. The rule has to sit in the prompt
    rather than the reading guide: retrieval decides whether a guide is
    read, and a rule that holds only when it happens to be retrieved is not
    a rule.
    """
    for name, text in (("instructions", agent_builder.INSTRUCTIONS_TEXT),
                       ("skill", agent_pack.SKILL_TEXT)):
        for header in ("Tracking ID", "Pack ID", "Cluster ID"):
            assert header in text, f"the {name} text never names {header}"

    # The columns the rule points at have to exist, or it instructs the
    # agent to cite something no file carries -- which is how the reading
    # guide came to promise `pack_known` before any file shipped it.
    from pipeline.report.table_sheets import ACTIVITY_COLUMNS

    headers = {header for _, header in ACTIVITY_COLUMNS}
    assert {"Tracking ID", "Pack ID", "Cluster ID"} <= headers
    assert "Pack ID" in agent_pack.PACKS_HEADER


def test_the_prompt_still_has_its_margin():
    """The rename costs characters in a field that is 97% full. Measured
    rather than assumed: the 200-character floor exists because the operator
    replaces the placeholder with a longer name before pasting.
    """
    headroom = agent_builder.INSTRUCTIONS_LIMIT - len(agent_builder.INSTRUCTIONS_TEXT)
    assert headroom >= 200, f"only {headroom} spare after the rename"


def test_the_prompt_is_what_tells_the_agent_boards_exist(tmp_path):
    """A knowledge file cannot announce itself.

    Retrieval answers a question; it does not tell the agent which questions
    have a fixed answer waiting. So the three names, and the instruction to ask
    when none is given, are the one part of the board design that has to be
    bought with prompt characters.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    for board in ("head of communications overview", "leadership attention", "plan trust"):
        assert board in text, f"the prompt does not name {board!r}"
    # Up to the next section, not a fixed count: the board names sit in the
    # file list, and the "ask" instruction closes the same section one
    # paragraph later, past the unrelated "prefer these files for a figure
    # already stated" aside that still sits between the two. Ending the slice
    # at `## Non-negotiable rules` clears that aside without ever being able
    # to wander into the next section looking for a stray "ask".
    assert "ask" in text[text.index("head of communications overview"):
                         text.index("## Non-negotiable rules")].lower(), (
        "the prompt names the boards without saying to ask which one")


def test_a_starter_prompt_offers_a_board(tmp_path):
    """The only path by which a user who does not know boards exist finds one.

    The prompt reacts to a dashboard being asked for. Nothing reacts to a user
    who has never heard the word, and a starter prompt is what the surface
    shows before the first question.
    """
    prompts = [line for line in agent_builder.STARTER_PROMPTS_TEXT.splitlines()
               if line.strip().startswith("-")]
    assert len(prompts) >= 5, "the board prompt was not added"
    assert any("board" in line.lower() for line in prompts), (
        "no starter prompt offers a board")


def test_the_instructions_carry_no_organisation_name():
    """This repository is public. The name is filled in where the text is used.

    A placeholder cannot be forgotten -- it is visible in the pasted text and
    reads as unfinished -- whereas a name committed once stays in every clone
    and fork of the history, whatever a later commit removes.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert agent_pack.ORGANISATION_PLACEHOLDER in text
    # Lines that call something the organisation's, not every line saying
    # "brand" -- "off-brand" describes a colour and claims nothing about whose
    # brand it is, and asserting over it would force a placeholder into a
    # sentence that has no owner to name.
    for line in text.splitlines():
        if "brand palette" in line.lower() or "-compliant" in line.lower():
            assert agent_pack.ORGANISATION_PLACEHOLDER in line, (
                f"a line claiming the organisation's without naming it: {line!r}")


def test_the_instructions_are_pasted_as_they_stand():
    """No header addressed to the operator, because it would be pasted too.

    The Studio file opens with an HTML comment telling the reader to replace
    the placeholder. Here that comment would spend characters the field cannot
    spare on a sentence the model does not need, and a reader who pastes the
    file pastes the comment with it. The instruction lives in the run output
    and in the README beside the file instead.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert not text.lstrip().startswith("<!--")
    assert "Before pasting" not in text


def test_the_description_fits_and_says_what_the_agent_is_for():
    """The orchestrator reads this to decide whether to route a question here.

    A description that praises the agent instead of naming its domain gets it
    picked for questions it cannot answer, which costs more than being missed.
    """
    text = agent_builder.DESCRIPTION_TEXT
    assert len(text) <= agent_builder.DESCRIPTION_LIMIT, (
        f"{len(text)} characters against a field that holds "
        f"{agent_builder.DESCRIPTION_LIMIT}")
    assert "communication" in text.lower()
    assert agent_pack.ORGANISATION_PLACEHOLDER not in text, (
        "the description is not a brand surface, so it needs no replacement")


def test_there_are_at_least_three_starter_prompts():
    """Three is the documented minimum, and they are what a tester tries first.

    They double as the shortest honest statement of scope: a tester who reads
    them learns what this pack answers without being told what it does not.
    """
    lines = [l for l in agent_builder.STARTER_PROMPTS_TEXT.splitlines()
             if l.strip().startswith("- ")]
    assert len(lines) >= 3


def test_the_documents_carry_no_front_matter():
    """A skill's YAML header is read by the skill loader, and there is none here.

    Left in, the first thing retrieval returns from either file is two lines of
    metadata addressed to a system that does not exist on this surface.
    """
    for text in (agent_builder.READING_GUIDE_TEXT,
                 agent_builder.CHART_STANDARDS_TEXT):
        assert not text.lstrip().startswith("---")
        assert "name:" not in text.splitlines()[0]


def test_the_documents_do_not_call_themselves_skills():
    """There is no skill on this surface, so a reference to one is a dead end.

    An agent told to "load this skill" looks for a mechanism the surface does
    not have, and what it does next is not something the prompt controls.
    """
    for text in (agent_builder.READING_GUIDE_TEXT,
                 agent_builder.CHART_STANDARDS_TEXT):
        assert "this skill" not in text.lower()


def test_the_reading_guide_keeps_what_the_prompt_could_not():
    """The audiences and the analysis steps are the half that had to move.

    They are guidance rather than floor -- an answer missing them is duller,
    not wrong -- which is exactly why they were the right thing to cut from a
    field of 8,000 characters and the wrong thing to lose entirely.
    """
    # Whitespace-collapsed: these markers are prose, and prose in this file is
    # wrapped at 79 columns. Matching the raw text would make a test pass or
    # fail on where a line happened to break, which is not what it is asking.
    text = " ".join(agent_builder.READING_GUIDE_TEXT.split())
    for marker in ("Internal communications planner", "Communication executive",
                   "Analytics", "Identify outliers", "still being filled in"):
        assert marker in text, f"the reading guide dropped {marker!r}"


def test_the_chart_document_keeps_the_geometry_and_not_the_palette():
    """The palette is in the prompt now, and repeating it invites a drift.

    Two statements of one hex value is two things to keep in step, and the
    copy that goes stale is the one nobody re-reads. What belongs here is the
    part that only matters once something is being drawn.
    """
    text = " ".join(agent_builder.CHART_STANDARDS_TEXT.split())
    for marker in ("Horizontal bar chart", "Leave a gutter", "Before you send it",
                   "one legend for the image"):
        assert marker in text, f"the chart document dropped {marker!r}"
    assert "| Role | Hex |" not in text, "the palette table belongs in the prompt"


def test_both_copies_of_the_chart_standards_carry_the_same_layout_rules():
    """Two surfaces, one geometry, and nothing but memory keeping them in step.

    This document is `agent_pack.BRAND_SKILL_TEXT` reworded by hand, so a rule
    added to one copy is a rule missing from the other until somebody
    remembers. The layout rules are the half worth guarding: they are what the
    2026-08-10 render broke, and it would have broken the same way on either
    surface, because both are drawn from the same instruction.
    """
    for name, text in (("the skill", agent_pack.BRAND_SKILL_TEXT),
                       ("the knowledge file", agent_builder.CHART_STANDARDS_TEXT)):
        collapsed = " ".join(text.split())
        for marker in ("Cut the canvas into panel rectangles first",
                       "A heading and the line beneath it are two lines",
                       "as wide as its longest category name",
                       "place it outside every plot area"):
            assert marker in collapsed, f"{name} dropped {marker!r}"


def test_only_the_surface_without_follow_up_chips_asks_for_follow_ups():
    """The one rule this prompt drops rather than compresses.

    The Studio block is justified by its surface and not by the agent:
    Copilot Studio offers no follow-up chips, so an answer that does not carry
    its own suggestions ends in a dead end. Agent Builder puts suggestions
    under every answer itself, and a prompt asking for three more produces two
    competing sets on one turn -- the model's and the surface's -- with
    nothing telling the reader which the agent stands behind.

    Asserted from both sides, because the failure has run in both directions:
    the block arrived here by being copied with the rest of the prompt, and
    the next person reconciling the two files will read its absence as drift
    unless something fails when they put it back.

    The footer is the deliberate contrast below it. It is owed on every turn
    on every surface, so both prompts carry the vintage and the signature.
    """
    studio = agent_pack.INSTRUCTIONS_TEXT
    builder = agent_builder.INSTRUCTIONS_TEXT
    assert "You might also ask" in studio, (
        "Studio has no follow-up chips -- the answer has to carry them")
    assert "You might also ask" not in builder, (
        "Agent Builder generates its own follow-ups; a second set competes "
        "with the surface's rather than adding to it")
    for name, text in (("Studio", studio), ("Builder", builder)):
        assert "Data as of" in text, f"{name} dropped the vintage"
        assert agent_pack.TEAM_SIGNATURE in text, f"{name} dropped the signature"


def test_both_prompts_require_the_scope_footnote_in_one_shape():
    """The rule that survives being forwarded, stated identically on both.

    It reached the Studio prompt eighteen minutes after this one was cut from
    it, and eight later edits to `agent_builder` never noticed: the checklist
    question travelled -- "does the footnote say what that total counts?" --
    while the answer stayed behind. A question with no answer is worse here
    than on the other surface, because here the question is in a file
    retrieval has to find, and the boards that most need it are the artefacts
    least likely to be questioned once they are wrong.

    The shape is asserted rather than the intent. Two footnotes saying the
    same thing in two wordings are two totals as far as a reader holding both
    images is concerned, which is the failure the rule exists to prevent.
    """
    shape = "Activities in scope: N — includes M the report excludes"
    for name, text in (("the Studio prompt", agent_pack.INSTRUCTIONS_TEXT),
                       ("the Builder prompt", agent_builder.INSTRUCTIONS_TEXT)):
        assert shape in text, f"{name} does not state the scope footnote"


def test_each_board_travels_as_its_own_file(tmp_path):
    """One file per board, because retrieval returns chunks and a board is only
    worth having whole.

    A skill package loads entire; a knowledge file does not. An agent handed
    panel 3 of one board and panel 1 of another draws the blended board these
    definitions exist to prevent, so the catalogue is never one document here.
    """
    _, upload, _ = _builder(tmp_path)
    names = sorted(p.name for p in upload.iterdir())
    for name in agent_builder.BOARD_FILE_NAMES.values():
        assert name in names, f"{name} is not in the upload folder"
        assert name.endswith(".txt"), f"{name} is not crawled, so not retrievable"
    # Nothing else couples this catalogue to `dashboard_skill.BOARDS`. Renaming
    # a board already raises KeyError in `_builder` above, loud and fine;
    # ADDING one to `dashboard_skill.BOARDS` alone is silent instead -- Studio
    # would ship four boards, Agent Builder would still ship three, the prompt
    # would still say "say which three there are", and every assertion above
    # would still pass, because `BOARD_FILE_NAMES` itself never changed. A
    # length check pinned at 3 does not catch that: it is a claim about this
    # dict alone, and this dict is exactly the one that did not move.
    # Comparing the two key sets is the only check that sees the divergence,
    # so it replaces the length check rather than joining it.
    assert set(agent_builder.BOARD_FILE_NAMES) == set(dashboard_skill.BOARDS), (
        "agent_builder.BOARD_FILE_NAMES and dashboard_skill.BOARDS name "
        "different boards")


def test_a_board_file_is_the_shared_rules_then_the_board_unaltered(tmp_path):
    """The panels are `dashboard_skill`'s text, not a second copy of it.

    Two deliveries shipping two versions of one board is the drift this
    repository is built to prevent, and the citation test over
    `dashboard_skill.BOARDS` only protects the text it actually holds.
    """
    _, upload, _ = _builder(tmp_path)
    for key, name in agent_builder.BOARD_FILE_NAMES.items():
        text = (upload / name).read_text(encoding="utf-8")
        assert agent_builder.BOARD_RULES_TEXT in text, f"{name} lost the shared rules"
        assert dashboard_skill.BOARDS[key] in text, f"{name} altered the board"
        assert text.index(agent_builder.BOARD_RULES_TEXT) < text.index(
            dashboard_skill.BOARDS[key]), f"{name} states the rules after the panels"


def test_every_board_file_answers_on_its_own(tmp_path):
    """The rules are repeated three times on purpose.

    In the skill package they sit once in SKILL.md, because the index always
    loads. Nothing loads here, so a fourth file holding them would be a fourth
    thing retrieval can miss -- and it would be missed exactly when a board was
    found, which is the case that matters.
    """
    _, upload, _ = _builder(tmp_path)
    for name in agent_builder.BOARD_FILE_NAMES.values():
        text = (upload / name).read_text(encoding="utf-8")
        # Lines that ARE the field, not the sentence in BOARD_RULES_TEXT that
        # merely names it: `test_agent_pack.py` counts the same way, over the
        # same concern -- a substring count would also catch `Highlight: yes`
        # inside the rules sentence describing the field, always adding one
        # short of a real second panel spending the budget.
        chosen = [line for line in text.splitlines()
                  if line.strip() == "Highlight: yes"]
        assert len(chosen) == 1, f"{name} spends the red budget {len(chosen)} times"
        # The four rules a board needs and the prompt does not already carry.
        for rule in ("in the order", "grey", "not the footnote", "say so"):
            assert rule in text.lower(), f"{name} does not state {rule!r}"


def test_the_upload_folder_holds_exactly_what_is_uploaded(tmp_path):
    """Eleven files without a pack export, and the folder is the instruction.

    An operator uploading a folder uploads the folder. Anything in it that
    should not be knowledge becomes knowledge, and the two candidates are both
    written next door: the answer key, and a README addressed to a person.

    Built without a pack export, so `07-packs.csv` is one of `UPLOAD_DATA_FILES`
    that this run never had to copy -- filtered against the pack directory
    rather than hardcoded, so this test does not itself assume which of the
    data files are optional.
    """
    pack_dir, upload_dir, _ = _builder(tmp_path)
    names = sorted(p.name for p in upload_dir.iterdir())
    data_files = tuple(name for name in agent_builder.UPLOAD_DATA_FILES
                       if (pack_dir / name).exists())
    assert names == sorted(data_files
                           + (agent_builder.READING_GUIDE_NAME,
                              agent_builder.CHART_STANDARDS_NAME)
                           + tuple(agent_builder.BOARD_FILE_NAMES.values()))
    assert agent_pack.CHECKLIST_NAME not in names, (
        "an agent that can read the answer key passes without computing anything")
    assert agent_pack.README_NAME not in names, (
        "the README explains the pack to a person; the reading guide does it "
        "for the agent")


def test_the_upload_folder_fits_the_knowledge_source_limit(tmp_path):
    """Twenty is the surface's limit, and eleven files must still leave room.

    The boards landed as three of the eleven -- the largest single addition
    since the limit was set -- so this is the count a future file has to leave
    room against.
    """
    _, upload_dir, _ = _builder(tmp_path)
    assert len(list(upload_dir.iterdir())) <= agent_builder.KNOWLEDGE_SOURCE_LIMIT


def test_the_uploaded_data_is_the_pack_byte_for_byte(tmp_path):
    """Two deliveries of one report, or the divergence is the bug.

    A copy that transformed anything on the way through would let the two
    agents disagree about a figure while both citing the same run, and the
    disagreement would surface as a wrong number that looks right.

    Built with a pack export so every name in `UPLOAD_DATA_FILES` -- including
    `07-packs.csv`, present only on this fixture -- has a source file to
    compare against.
    """
    pack_dir, upload_dir, _ = _builder_with_packs(tmp_path)
    for name in agent_builder.UPLOAD_DATA_FILES:
        assert (upload_dir / name).read_bytes() == (pack_dir / name).read_bytes(), (
            f"{name} differs between the two deliveries")


def test_the_loose_files_are_beside_the_upload_folder_not_inside_it(tmp_path):
    """What is pasted and what is uploaded are different actions.

    The instructions are pasted into a field. Uploaded as knowledge instead,
    the agent reads its own rules as data and quotes them back as findings.
    """
    _, _, out_dir = _builder(tmp_path)
    loose = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    assert loose == sorted([agent_builder.INSTRUCTIONS_NAME,
                            agent_builder.DESCRIPTION_NAME,
                            agent_builder.STARTER_PROMPTS_NAME,
                            agent_builder.README_NAME,
                            agent_pack.CHECKLIST_NAME])


def test_the_delivery_is_rewritten_in_place(tmp_path):
    """A second run replaces it rather than accumulating vintages.

    A knowledge folder holding two runs answers from both without saying so.
    The re-run passes no scope, which is also how it proves that refreshing
    the upload set needs nothing but the pack it is built from.
    """
    pack_dir, upload_dir, out_dir = _builder(tmp_path)
    first = sorted(p.name for p in upload_dir.iterdir())
    again = agent_builder.write_builder_pack(pack_dir, out_dir)
    assert sorted(p.name for p in again.iterdir()) == first


def test_one_run_writes_both_deliveries(tmp_path, monkeypatch, capsys):
    """Two commands would allow building one and forgetting the other.

    A pack refreshed on one path and not the other hands the two agents two
    vintages of the same figure, which is the failure this repository is built
    to prevent -- and it is invisible, because both folders look freshly built.
    """
    def _scope(args, config, **kwargs):
        return load_fixture_scope(tmp_path / "csv", config), config

    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    monkeypatch.setattr(build, "BUILDER_LOCAL_OUTPUT_DIR", tmp_path / "builder")
    monkeypatch.setattr(build, "resolve_scope", _scope)

    assert build.main(["--out", str(tmp_path / "pack"), "--year", "2025"]) == 0

    builder_dir = tmp_path / "builder"
    assert (builder_dir / agent_builder.UPLOAD_DIRNAME
            / agent_builder.READING_GUIDE_NAME).exists()
    assert (builder_dir / agent_builder.INSTRUCTIONS_NAME).exists()

    out = capsys.readouterr().out
    assert agent_builder.UPLOAD_DIRNAME in out, "the run never says what to upload"
    assert "not uploaded" in out.lower(), "the run never names the answer key"


def test_the_prompt_carries_both_leadership_states(tmp_path):
    """This prompt is pasted once and stays while the pack is rebuilt under it,
    so it cannot be conditional on a run -- it has to describe both states.

    The Studio prompt was corrected in the same change and this one is a
    separate constant, which is exactly how the two deliveries drift: one gets
    the fix, the other ships a pack whose blocks its own rules forbid.
    """
    text = agent_builder.INSTRUCTIONS_TEXT
    assert "executives_geb" in text, "the prompt never mentions the split blocks"
    assert "GEB or GEB-1" in text, "the no-list branch is gone"
    assert "never add the two" in text, "the two blocks do not sum, and it is unsaid"
    assert "with nothing saying which" not in text, (
        "the prompt again asserts, without condition, that the levels cannot "
        "be separated")


def test_the_uploaded_glossary_follows_the_run_not_the_prompt(tmp_path):
    """The prompt describes both states; the knowledge files describe THIS one.

    They are copied from the pack rather than regenerated, so this is really a
    test that the copy is the conditional file and not a second, static one --
    the failure would be an upload folder whose glossary contradicts the
    breakdown file sitting next to it.
    """
    from dataclasses import replace

    from pipeline.report.config import EXECUTIVES_SPLIT
    from pipeline.report.membership import Entry, Membership, normalise_name

    config = agent_pack.pack_config(
        ReportConfig(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31)))
    fields = []
    for field in config.breakdown_fields:
        fields.extend(EXECUTIVES_SPLIT) if field == "executives" else fields.append(field)
    config = replace(config, breakdown_fields=tuple(fields))
    members = Membership(entries=(Entry(email="", name=normalise_name("Example, Ada")),))
    scope = load_fixture_scope(tmp_path / "csv", config, membership=members)

    pack_dir = agent_pack.write_pack(scope, config, tmp_path / "pack-out")
    upload = agent_builder.write_builder_pack(pack_dir, tmp_path / "builder-out",
                                              scope, config)
    glossary = (upload / agent_pack.GLOSSARY_NAME).read_text(encoding="utf-8")
    assert agent_pack.GEB_RULE_SPLIT in glossary
    assert agent_pack.GEB_RULE_COMBINED not in glossary
    breakdowns = (upload / agent_pack.BREAKDOWN_NAME).read_text(encoding="utf-8")
    assert "executives_geb," in breakdowns


def test_the_prompt_tells_the_agent_the_pack_file_exists():
    """Retrieval answers a question; it does not say which questions have a
    file waiting. The pointer is the only thing that does.
    """
    assert agent_pack.PACKS_CSV_NAME in agent_builder.INSTRUCTIONS_TEXT


def test_the_reading_guide_says_how_the_two_files_join():
    """The cost of not copying the pack's lead onto the activity row is that
    the agent has to be told where to look instead.
    """
    text = agent_builder.READING_GUIDE_TEXT
    assert agent_pack.PACKS_CSV_NAME in text
    assert "Pack ID" in text
    assert "nothing planned" in text.lower()


def test_the_mirror_puts_this_runs_upload_set_in_the_agents_own_folder(tmp_path):
    """The step that used to be a manual copy, and could be forgotten.

    A pack rebuilt and not copied leaves the agent answering from the previous
    run while both folders look freshly built -- the failure this module is
    written around, arriving through the one gap the run did not close.
    """
    _, upload_dir, _ = _builder_with_packs(tmp_path)
    target = tmp_path / "agent"
    target.mkdir()

    copied, removed = agent_builder.mirror_upload(upload_dir, target)

    assert copied == sorted(p.name for p in upload_dir.iterdir())
    assert removed == []
    assert sorted(p.name for p in target.iterdir()) == copied
    for name in copied:
        assert (target / name).read_bytes() == (upload_dir / name).read_bytes()


def test_the_mirror_removes_a_file_this_runs_numbering_replaced(tmp_path):
    """The boards moved from 09-11 to 10-12 when the chart rules became a
    knowledge file. Copying alone would leave both numberings in the folder,
    both retrievable and both looking current.
    """
    _, upload_dir, _ = _builder(tmp_path)
    target = tmp_path / "agent"
    target.mkdir()
    stale = target / "09-board-leadership-attention.txt"
    stale.write_text("last month's board", encoding="utf-8")

    copied, removed = agent_builder.mirror_upload(upload_dir, target)

    assert removed == [stale.name]
    assert not stale.exists()
    assert sorted(p.name for p in target.iterdir()) == copied


def test_the_mirror_leaves_alone_what_it_did_not_write(tmp_path):
    """The folder belongs to whoever set the agent up, not to this run. A
    mirror that tidies is a mirror that deletes someone's notes.
    """
    _, upload_dir, _ = _builder(tmp_path)
    target = tmp_path / "agent"
    target.mkdir()
    kept = target / "notes.txt"
    kept.write_text("why this agent exists", encoding="utf-8")

    _, removed = agent_builder.mirror_upload(upload_dir, target)

    assert removed == []
    assert kept.read_text(encoding="utf-8") == "why this agent exists"


def test_the_mirror_carries_no_answer_key_and_no_instructions(tmp_path):
    """Everything in that folder is knowledge, exactly as in `upload/`. An
    agent that can read the answers passes without computing anything, and one
    grounded on its own instructions quotes them back as findings.
    """
    _, upload_dir, out_dir = _builder(tmp_path)
    target = tmp_path / "agent"
    target.mkdir()

    copied, _ = agent_builder.mirror_upload(upload_dir, target)

    for name in (agent_pack.CHECKLIST_NAME, agent_builder.INSTRUCTIONS_NAME,
                 agent_builder.README_NAME, agent_builder.STARTER_PROMPTS_NAME):
        assert (out_dir / name).exists(), "the delivery no longer writes " + name
        assert name not in copied
        assert not (target / name).exists()


def test_the_mirror_never_creates_the_folder_it_writes_into(tmp_path):
    """A folder conjured inside a sync that is not really set up takes the
    upload set nowhere and looks like it worked -- the same rule the output
    resolvers follow, for the same reason.
    """
    _, upload_dir, _ = _builder(tmp_path)
    missing = tmp_path / "not-synced" / "agent"

    with pytest.raises(FileNotFoundError):
        agent_builder.mirror_upload(upload_dir, missing)
    assert not missing.exists()


def test_the_agent_folder_is_found_by_shape_and_never_inside_the_checkout(tmp_path, monkeypatch):
    """The path holds a tenant and a site that differ per machine, so the run
    cannot know it -- only that the operator created a folder of that shape.
    A checkout that grew one must not become the destination for an upload.
    """
    home = tmp_path / "home"
    monkeypatch.setattr(build.Path, "home", staticmethod(lambda: home))

    (home / "Library - Documents" / build.AGENT_DIR_TAIL).mkdir(parents=True)
    assert build.find_agent_dirs() == [home / "Library - Documents" / build.AGENT_DIR_TAIL]

    checkout = home / "checkout"
    monkeypatch.setattr(build, "REPO_DIR", checkout)
    (checkout / build.AGENT_DIR_TAIL).mkdir(parents=True)
    assert build.find_agent_dirs() == [home / "Library - Documents" / build.AGENT_DIR_TAIL]


def test_two_candidate_folders_are_reported_rather_than_guessed_between(tmp_path, monkeypatch, capsys):
    """The wrong knowledge in the right place is not visible from either
    folder, so an ambiguous match writes to neither.
    """
    home = tmp_path / "home"
    monkeypatch.setattr(build.Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv(build.AGENT_DIR_ENV, raising=False)
    for site in ("Site A - Documents", "Site B - Documents"):
        (home / site / build.AGENT_DIR_TAIL).mkdir(parents=True)

    assert build.resolve_agent_dir() is None
    out = capsys.readouterr().out
    assert "Site A - Documents" in out and "Site B - Documents" in out
    assert "--agent-dir" in out


def test_a_named_folder_that_is_not_there_is_an_error_rather_than_a_fallback(tmp_path, monkeypatch, capsys):
    """Falling back would hand the operator a folder that looks maintained and
    holds last week's figures -- the run has to say the mirror did not happen.
    """
    home = tmp_path / "home"
    (home / "Library - Documents" / build.AGENT_DIR_TAIL).mkdir(parents=True)
    monkeypatch.setattr(build.Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(build.AGENT_DIR_ENV, str(tmp_path / "typo"))

    assert build.resolve_agent_dir() is None
    assert "does not exist" in capsys.readouterr().out

    # And the flag outranks the environment, both ways round.
    assert build.resolve_agent_dir(str(home / "Library - Documents" / build.AGENT_DIR_TAIL)) \
        == home / "Library - Documents" / build.AGENT_DIR_TAIL


def test_the_run_mirrors_without_being_asked_and_says_where(tmp_path, monkeypatch, capsys):
    """The whole point: one command, and the folder the agent reads is current.
    """
    def _scope(args, config, **kwargs):
        return load_fixture_scope(tmp_path / "csv", config), config

    home = tmp_path / "home"
    target = home / "Library - Documents" / build.AGENT_DIR_TAIL
    target.mkdir(parents=True)
    monkeypatch.setattr(build.Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv(build.AGENT_DIR_ENV, raising=False)
    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    monkeypatch.setattr(build, "BUILDER_LOCAL_OUTPUT_DIR", tmp_path / "builder")
    monkeypatch.setattr(build, "resolve_scope", _scope)

    assert build.main(["--out", str(tmp_path / "pack"), "--year", "2025"]) == 0

    upload_dir = tmp_path / "builder" / agent_builder.UPLOAD_DIRNAME
    assert sorted(p.name for p in target.iterdir()) == sorted(p.name for p in upload_dir.iterdir())
    assert str(target) in capsys.readouterr().out


def test_a_mirror_that_was_asked_for_and_did_not_happen_fails_the_run(tmp_path, monkeypatch):
    """Zero would report it as a clean run, which is how a stale folder gets
    uploaded from. Its own code, because the pack itself was written.
    """
    def _scope(args, config, **kwargs):
        return load_fixture_scope(tmp_path / "csv", config), config

    monkeypatch.setattr(build.Path, "home", staticmethod(lambda: tmp_path / "home"))
    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    monkeypatch.setattr(build, "BUILDER_LOCAL_OUTPUT_DIR", tmp_path / "builder")
    monkeypatch.setattr(build, "resolve_scope", _scope)

    code = build.main(["--out", str(tmp_path / "pack"), "--year", "2025",
                       "--agent-dir", str(tmp_path / "typo")])

    assert code == build.MIRROR_MISSING_EXIT
    assert code not in (0, 1, 2), "shares a code with a failed run or a mistyped flag"
    assert (tmp_path / "builder" / agent_builder.INSTRUCTIONS_NAME).exists(), (
        "the pack itself has to survive a mirror that could not happen")


def test_a_run_with_no_agent_folder_anywhere_is_still_a_clean_run(tmp_path, monkeypatch, capsys):
    """Nobody asked for a mirror on that machine. The run says how to ask.
    """
    def _scope(args, config, **kwargs):
        return load_fixture_scope(tmp_path / "csv", config), config

    monkeypatch.setattr(build.Path, "home", staticmethod(lambda: tmp_path / "home"))
    monkeypatch.delenv(build.AGENT_DIR_ENV, raising=False)
    monkeypatch.setattr(build, "find_onedrive_root", lambda: None)
    monkeypatch.setattr(build, "BUILDER_LOCAL_OUTPUT_DIR", tmp_path / "builder")
    monkeypatch.setattr(build, "resolve_scope", _scope)

    assert build.main(["--out", str(tmp_path / "pack"), "--year", "2025"]) == 0
    out = capsys.readouterr().out
    assert build.AGENT_DIR_ENV in out and "--agent-dir" in out
