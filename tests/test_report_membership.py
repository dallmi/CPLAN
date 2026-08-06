"""The GEB membership list: loading it, and matching people against it."""

import pytest
from openpyxl import Workbook

from pipeline.report.membership import (
    MembershipError,
    default_path,
    load_membership,
    normalise_email,
    normalise_name,
)


def _write(tmp_path, text):
    path = tmp_path / "geb-members.csv"
    path.write_text(text, encoding="utf-8")
    return path


def _write_xlsx(tmp_path, rows, name="geb-members.xlsx"):
    """The same list as a workbook, written the way Excel would write it."""
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    path = tmp_path / name
    workbook.save(path)
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


def test_an_unquoted_last_first_name_is_rejected_with_the_row_number(tmp_path):
    """An operator editing the file in Notepad rather than Excel can write
    `,Müller, Anna` without quotes. The csv module then reads three fields;
    DictReader stashes the third under its None restkey, and a silent .get()
    would truncate the name to "Müller" -- matching nobody, filing a real
    member under GEB-1, and leaving Data Quality's "never matched" count
    pointing the operator at the wrong problem. The row must be rejected
    outright, with the row number and the quoting fix named directly.
    """
    path = _write(tmp_path, "email,name\n,Müller, Anna\n")

    with pytest.raises(MembershipError) as excinfo:
        load_membership(path)
    message = str(excinfo.value)
    assert "row 2" in message
    assert "quote" in message.lower()


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


def test_a_directory_path_raises_a_membership_error(tmp_path):
    """A directory where a file was expected must be reported, not raised as
    a raw IsADirectoryError that escapes to a traceback and sends report.ps1's
    catch block into its misleading OneDrive hint.
    """
    directory = tmp_path / "geb-members.csv"
    directory.mkdir()

    with pytest.raises(MembershipError) as excinfo:
        load_membership(directory)
    assert str(directory) in str(excinfo.value)


def test_a_non_utf8_file_raises_a_membership_error(tmp_path):
    """Excel's 'CSV (Comma delimited)' save option writes Windows-1252, not
    UTF-8. One accented name is enough to break `utf-8-sig` decoding -- a
    likely first-run mistake, not an edge case -- and it must produce a
    message naming the file rather than a raw UnicodeDecodeError traceback.
    """
    path = tmp_path / "geb-members.csv"
    path.write_bytes(b'email,name\n,"B\xe9atrice"\n')

    with pytest.raises(MembershipError) as excinfo:
        load_membership(path)
    assert str(path) in str(excinfo.value)


def test_the_shipped_example_loads_and_holds_thirteen_rows():
    """The committed example is the thing the user copies. If it does not load,
    the first thing anyone tries fails.
    """
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "geb-members.csv.example"
    members = load_membership(example)

    assert len(members) == 13
    assert members.is_member("", "geb.member.01@example.invalid") is True


# --- The workbook format -------------------------------------------------
#
# .xlsx exists because the two ways a hand-edited CSV breaks -- Excel's
# Windows-1252 "CSV (Comma delimited)" save, and its semicolon separator on a
# German locale -- are both properties of the CSV export, not of the data. A
# workbook carries its own encoding and needs no separator, so neither can
# happen. Every rule the CSV path enforces has to hold here too.


def test_a_workbook_is_read_like_the_csv(tmp_path):
    path = _write_xlsx(tmp_path, [
        ("email", "name"),
        ("m1@example.invalid", "Placeholder-01, Anna"),
    ])
    members = load_membership(path)

    assert len(members) == 1
    assert members.is_member("Someone Else", "m1@example.invalid") is True
    assert members.is_member("Anna Placeholder-01", "") is True


def test_trailing_blank_rows_are_skipped(tmp_path):
    """Excel hands back every row the sheet has ever touched, so a file edited
    down from a longer list arrives with blank rows below the data. The CSV
    path rejects a blank row as a typo; applying that here would reject the
    normal state of a hand-edited workbook and make the format unusable.
    """
    path = _write_xlsx(tmp_path, [
        ("email", "name"),
        ("m1@example.invalid", "Placeholder-01, Anna"),
        (None, None),
        (None, None),
    ])
    members = load_membership(path)

    assert len(members) == 1


def test_a_row_that_is_blank_only_in_the_key_columns_is_still_an_error(tmp_path):
    """The blank-row skip is narrow on purpose: it fires when the whole row is
    empty, not when someone filled in a note and forgot the name. Widening it
    would file a real member under GEB-1 silently, which is the failure the
    whole feature exists to prevent.
    """
    path = _write_xlsx(tmp_path, [
        ("email", "name", "note"),
        ("m1@example.invalid", "Placeholder-01, Anna", ""),
        (None, None, "joins in Q3"),
    ])

    with pytest.raises(MembershipError, match="row 3"):
        load_membership(path)


def test_a_name_holding_a_comma_needs_no_quoting(tmp_path):
    """The reason to prefer the workbook: "Last, First" is one cell, so the
    unquoted-comma failure the CSV path has to detect cannot arise at all.
    """
    path = _write_xlsx(tmp_path, [("email", "name"), ("", "Müller, Anna")])
    members = load_membership(path)

    assert members.is_member("Anna Müller", "") is True


def test_accented_names_survive(tmp_path):
    """The other reason: no encoding choice to get wrong."""
    path = _write_xlsx(tmp_path, [("email", "name"), ("", "Béatrice Dupont")])
    members = load_membership(path)

    assert members.is_member("Béatrice Dupont", "") is True


def test_a_missing_header_column_is_an_error_in_a_workbook(tmp_path):
    path = _write_xlsx(tmp_path, [("email",), ("a@example.invalid",)])

    with pytest.raises(MembershipError, match="name"):
        load_membership(path)


def test_workbook_headers_tolerate_case_and_padding(tmp_path):
    path = _write_xlsx(tmp_path, [(" Email ", "Name"),
                                  ("m1@example.invalid", "")])
    members = load_membership(path)

    assert members.is_member("", "m1@example.invalid") is True


def test_a_workbook_without_any_row_is_an_error(tmp_path):
    path = _write_xlsx(tmp_path, [("email", "name")])

    with pytest.raises(MembershipError, match="no entries"):
        load_membership(path)


def test_a_non_workbook_named_xlsx_raises_a_membership_error(tmp_path):
    """Saving as CSV and renaming the file is the obvious wrong move. It must
    name the file rather than escape as a raw BadZipFile traceback, which
    report.ps1's catch block would dress up as its OneDrive hint.
    """
    path = tmp_path / "geb-members.xlsx"
    path.write_text("email,name\na@example.invalid,\n", encoding="utf-8")

    with pytest.raises(MembershipError) as excinfo:
        load_membership(path)
    assert str(path) in str(excinfo.value)


def test_a_non_text_cell_is_read_as_text(tmp_path):
    """Excel decides on its own that some cells are numbers. Whatever it hands
    back has to compare as the string a person would have typed.
    """
    path = _write_xlsx(tmp_path, [("email", "name"), ("", 12345)])
    members = load_membership(path)

    assert members.is_member("12345", "") is True


# --- Which file the report picks up on its own ---------------------------


def test_holding_both_default_files_at_once_is_an_error(tmp_path):
    """Picking one silently would split the report on a list the operator is
    not looking at -- and the two lists disagree, or there would only be one.
    """
    (tmp_path / "geb-members.csv").write_text("email,name\na@x.invalid,\n")
    _write_xlsx(tmp_path, [("email", "name"), ("b@x.invalid", "")])

    with pytest.raises(MembershipError) as excinfo:
        default_path(tmp_path)
    message = str(excinfo.value).lower()
    assert "geb-members.xlsx" in message and "geb-members.csv" in message


def test_the_default_finds_either_format_on_its_own(tmp_path):
    assert default_path(tmp_path) is None

    csv_path = _write(tmp_path, "email,name\na@x.invalid,\n")
    assert default_path(tmp_path) == csv_path

    csv_path.unlink()
    xlsx_path = _write_xlsx(tmp_path, [("email", "name"), ("b@x.invalid", "")])
    assert default_path(tmp_path) == xlsx_path
