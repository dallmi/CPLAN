"""The same report pack, delivered to a surface that has no skills.

Agent Builder holds 8,000 characters of Instructions and no skill packages at
all, so the rules that live in a skill next door have to live in a knowledge
file or in the prompt. The tests that matter here are the ones holding this
delivery to the pack it is built from, and to the limits the surface enforces.
"""

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("pandas")

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
