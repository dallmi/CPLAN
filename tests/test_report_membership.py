"""The GEB membership list: loading it, and matching people against it."""

import pytest

from pipeline.report.membership import (
    MembershipError,
    load_membership,
    normalise_email,
    normalise_name,
)


def _write(tmp_path, text):
    path = tmp_path / "geb-members.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_an_absent_file_is_not_an_error():
    """Every machine without the list must still produce a workbook."""
    assert load_membership("/nonexistent/geb-members.csv") is None


def test_a_member_matches_on_email(tmp_path):
    path = _write(tmp_path, 'email,name\nm1@example.invalid,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Someone Else", "m1@example.invalid") is True


def test_a_member_matches_on_name_alone(tmp_path):
    """The email path is unverified against the real export; the name path
    is what the pipeline demonstrably has today, so it must stand on its own.
    """
    path = _write(tmp_path, 'email,name\n,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Anna Placeholder-01", "") is True


def test_either_key_alone_is_sufficient(tmp_path):
    """A plain OR, not a precedence rule: a stale address in the list must not
    silently outrank a correct name.
    """
    path = _write(tmp_path, 'email,name\nold@example.invalid,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Anna Placeholder-01", "new@example.invalid") is True
    assert members.is_member("Someone Else", "old@example.invalid") is True
    assert members.is_member("Someone Else", "new@example.invalid") is False


def test_last_first_and_first_last_compare_equal(tmp_path):
    path = _write(tmp_path, 'email,name\n,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("Anna Placeholder-01", "") is True
    assert members.is_member("Placeholder-01, Anna", "") is True


def test_case_and_whitespace_are_ignored(tmp_path):
    path = _write(tmp_path, 'email,name\nM1@Example.Invalid,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("  anna   placeholder-01 ", "") is True
    assert members.is_member("", "  m1@EXAMPLE.invalid ") is True


def test_the_length_is_the_number_of_rows(tmp_path):
    path = _write(tmp_path, 'email,name\na@example.invalid,\nb@example.invalid,\n')

    assert len(load_membership(path)) == 2


def test_unmatched_counts_entries_nobody_carries(tmp_path):
    path = _write(
        tmp_path,
        'email,name\na@example.invalid,\nb@example.invalid,\n,"Placeholder-03, Clara"\n',
    )
    members = load_membership(path)

    seen = [("Someone Else", "a@example.invalid"), ("Clara Placeholder-03", "")]
    assert members.unmatched(seen) == 1  # only b@ matched nothing


def test_a_correct_list_reports_no_unmatched_entries(tmp_path):
    path = _write(tmp_path, 'email,name\na@example.invalid,\n')
    members = load_membership(path)

    assert members.unmatched([("X", "a@example.invalid")]) == 0


def test_a_missing_header_column_is_an_error(tmp_path):
    path = _write(tmp_path, 'email\na@example.invalid\n')

    with pytest.raises(MembershipError, match="name"):
        load_membership(path)


def test_a_row_with_neither_key_is_an_error(tmp_path):
    """A silently skipped line would leave a member quietly filed under GEB-1 --
    exactly the failure this feature exists to remove.
    """
    path = _write(tmp_path, 'email,name\na@example.invalid,\n,\n')

    with pytest.raises(MembershipError, match="row 3"):
        load_membership(path)


def test_a_file_without_any_row_is_an_error(tmp_path):
    path = _write(tmp_path, 'email,name\n')

    with pytest.raises(MembershipError, match="no entries"):
        load_membership(path)


def test_the_error_names_the_file(tmp_path):
    path = _write(tmp_path, 'email\na@example.invalid\n')

    with pytest.raises(MembershipError, match="geb-members.csv"):
        load_membership(path)


def test_normalisers_are_exported_for_the_caller():
    """data.py normalises the frame side with the same functions, so the two
    sides cannot drift into different notions of equality.
    """
    assert normalise_name("Placeholder-01, Anna") == normalise_name("anna placeholder-01")
    assert normalise_email("  A@B.C ") == "a@b.c"


def test_an_empty_person_never_matches(tmp_path):
    """A blank cell must not match a blank config key."""
    path = _write(tmp_path, 'email,name\n,"Placeholder-01, Anna"\n')
    members = load_membership(path)

    assert members.is_member("", "") is False


def test_the_shipped_example_loads_and_holds_thirteen_rows():
    """The committed example is the thing the user copies. If it does not load,
    the first thing anyone tries fails.
    """
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "geb-members.csv.example"
    members = load_membership(example)

    assert len(members) == 13
    assert members.is_member("", "geb.member.01@example.invalid") is True
