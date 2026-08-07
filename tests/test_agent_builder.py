"""The same report pack, delivered to a surface that has no skills.

Agent Builder holds 8,000 characters of Instructions and no skill packages at
all, so the rules that live in a skill next door have to live in a knowledge
file or in the prompt. The tests that matter here are the ones holding this
delivery to the pack it is built from, and to the limits the surface enforces.
"""

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("pandas")

from pipeline.report import agent_builder, agent_pack
from pipeline.scripts import build_agent_pack as build


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
            "planning studio",                        # where to send what is missing
            "#E60000",                                # the accent
            "#7A7870",                                # the default series
            "largest area",                           # red bounded by area, not count
            "half the image",                         # the white ratio
            "No gridlines",
            "You might also ask",                     # the follow-up block's shape
            "Data as of",                             # the footer's date
            agent_pack.TEAM_SIGNATURE,                # the signature
    ):
        assert marker in text, f"the compression dropped {marker!r}"


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
