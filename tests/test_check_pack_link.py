"""The diagnostic that chooses the pack link, instead of assuming it.

Three activity columns could carry the pack identifier and the exports do not
say which one the pack list answers to. A wrong join does not look wrong --
it looks like a pack file with plausible numbers in it -- so the choice is
measured, and these tests hold the measurement honest.
"""

import pytest

pytest.importorskip("pandas")

from pipeline.scripts import check_pack_link
from tests.report_fixtures import PACK_HEADER, write_pack_csv, write_activity_csvs


def test_it_names_the_columns_the_etl_does_not_map():
    """The mapping carries none of the pack form's identity fields.

    An unmapped column is invisible twice over: absent from the harmonised
    frame, and absent from any error, because nothing asked for it. Listing
    them is what turns "the mapping is probably incomplete" into a decision
    someone can take.
    """
    rows = check_pack_link.unmapped_columns(PACK_HEADER)
    by_name = {raw: status for raw, _, status in rows}

    assert by_name["LTID"] == "mapped"
    assert by_name["Name of communication pack"] == "unmapped"
    assert by_name["Tracking cluster"] == "unmapped"
    assert by_name["Category"] == "unmapped"
    assert by_name["End date"] == "unmapped"


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
