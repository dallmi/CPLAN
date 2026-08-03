"""Per-row derivations: audience band, GEB involvement, objectives, priority."""

import pytest

from pipeline.report.config import (
    BAND_10_50K,
    BAND_1_10K,
    BAND_50_100K,
    BAND_OVER_100K,
    BAND_UNDER_1K,
    BAND_UNKNOWN,
)
from pipeline.report.derive import (
    audience_band,
    executive_names,
    has_executives,
    only_excluded_objectives,
    priority_rank,
    split_multi,
)


# --- split_multi -------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("IB, P&C", ["IB", "P&C"]),
    ("IB; P&C", ["IB", "P&C"]),
    ("  IB  ", ["IB"]),
    ("", []),
    (None, []),
    (float("nan"), []),
    ("IB, , P&C", ["IB", "P&C"]),
])
def test_split_multi(value, expected):
    assert split_multi(value) == expected


# --- audience_band -----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("250", BAND_UNDER_1K),
    ("999", BAND_UNDER_1K),
    ("1000", BAND_1_10K),
    ("9999", BAND_1_10K),
    ("10000", BAND_10_50K),
    ("12000", BAND_10_50K),
    ("49999", BAND_10_50K),
    ("50000", BAND_50_100K),
    ("100000", BAND_50_100K),
    ("100001", BAND_OVER_100K),
    ("12,000", BAND_10_50K),
    ("12'000", BAND_10_50K),
    (4200, BAND_1_10K),
    (4200.0, BAND_1_10K),
    ("4200.00", BAND_1_10K),
    (999.9, BAND_UNDER_1K),
])
def test_numeric_audience_values_map_to_bands(value, expected):
    assert audience_band(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("10–50k", BAND_10_50K),
    ("10-50k", BAND_10_50K),
    ("10 - 50k", BAND_10_50K),
    ("> 100k", BAND_OVER_100K),
    ("<1000", BAND_UNDER_1K),
    # Case, as the source writes it.
    ("1 - 10K", BAND_1_10K),
    ("10 - 50K", BAND_10_50K),
    ("50 - 100K", BAND_50_100K),
    ("> 100K", BAND_OVER_100K),
    # Thousands separators. "< 1.000" used to fall through to Unknown, which
    # silently emptied the smallest band for any source writing it that way.
    ("< 1.000", BAND_UNDER_1K),
    ("< 1'000", BAND_UNDER_1K),
    ("< 1,000", BAND_UNDER_1K),
])
def test_band_labels_survive_dash_case_spacing_and_separator_variants(value, expected):
    assert audience_band(value) == expected


def test_folding_separators_cannot_move_a_raw_count_between_bands():
    """The separator fold is on the label path only. A raw count is read as a
    number first, so 999 and 1000 still land either side of the boundary.
    """
    assert audience_band("999") == BAND_UNDER_1K
    assert audience_band("1000") == BAND_1_10K
    assert audience_band("49999") == BAND_10_50K
    assert audience_band("50000") == BAND_50_100K


# --- only_excluded_objectives ------------------------------------------------

PREFIXES = ("2026: Other",)


@pytest.mark.parametrize("value,expected", [
    ("2026: Other", True),                          # nothing but the catch-all
    ("2026: Other, 2026: Other things", True),      # several, all catch-all
    ("2026: Other, 2026: Growth", False),           # also planned against a real one
    ("2026: Growth", False),
    ("", False),                                    # unclassified is a different gap
    (None, False),
    (float("nan"), False),
])
def test_a_row_goes_only_when_every_objective_is_a_catch_all(value, expected):
    assert only_excluded_objectives(value, PREFIXES) is expected


def test_the_prefix_match_ignores_case_and_surrounding_space():
    assert only_excluded_objectives("  2026: OTHER  ", PREFIXES) is True
    assert only_excluded_objectives("2026: Other", ("  2026: other  ",)) is True


def test_it_is_a_prefix_not_a_substring():
    """"Other" late in a label is a real objective, not the catch-all bucket."""
    assert only_excluded_objectives("Growth and 2026: Other", PREFIXES) is False


def test_no_prefixes_means_nothing_is_excluded():
    assert only_excluded_objectives("2026: Other", ()) is False
    assert only_excluded_objectives("2026: Other", ("", "  ")) is False


@pytest.mark.parametrize("value", ["", None, "all staff", "n/a", float("nan")])
def test_anything_unrecognised_is_unknown(value):
    assert audience_band(value) == BAND_UNKNOWN


# --- has_executives ----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("A. Person", True),
    ("   ", False),
    ("", False),
    (None, False),
    (float("nan"), False),
])
def test_executive_involvement_is_a_non_empty_field(value, expected):
    assert has_executives(value) is expected


# --- executive_names ---------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("A. Person", "A. Person"),
    ("A. Person, B. Person", "A. Person, B. Person"),
    ("A. Person,B. Person", "A. Person, B. Person"),      # spacing normalised
    ("A. Person; B. Person", "A. Person, B. Person"),     # separator normalised
    ("  A. Person  ", "A. Person"),
    ("", ""),
    ("   ", ""),
    (None, ""),
    (float("nan"), ""),
])
def test_executive_names_normalise_to_one_comma_joined_list(value, expected):
    assert executive_names(value) == expected


def test_the_flag_and_the_names_cannot_disagree():
    """has_executives is defined in terms of executive_names, so a value that
    yields no names can never read as involvement.
    """
    for value in ("A. Person", " , ", "", None, ";;", "  "):
        assert has_executives(value) is bool(executive_names(value))


def test_a_comma_inside_one_display_name_reads_as_two_people():
    """A known limitation, recorded rather than hidden.

    The source is a person picker whose display names the ETL joins with ", ";
    a name that itself contains a comma is already indistinguishable from two
    names by the time the report sees it. Display names of the form
    "First Last" are safe. If an export ever delivers "Last, First", the fix
    belongs in the ETL's join, not here -- the information is gone by then.
    """
    assert executive_names("Last, First") == "Last, First"
    assert split_multi("Last, First") == ["Last", "First"]


# --- priority_rank -----------------------------------------------------------

def test_a_leading_integer_wins_with_one_as_most_urgent():
    assert priority_rank("1 - some label") == 4
    assert priority_rank("4 - some label") == 1


def test_the_studio_words_are_the_fallback():
    assert priority_rank("Critical") == 4
    assert priority_rank("low") == 0


def test_an_unknown_value_lands_mid_rank_rather_than_reading_as_low():
    assert priority_rank("whatever") == 1
    assert priority_rank(None) == 1
