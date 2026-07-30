"""Per-row derivations: reach, audience band, executive involvement, priority."""

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
    REACH_GROUP_WIDE,
    REACH_MULTI_DIVISION,
    REACH_REGIONAL_ONLY,
    REACH_SINGLE_DIVISION,
    REACH_UNCLASSIFIED,
    audience_band,
    classify_reach,
    has_executives,
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


# --- classify_reach ----------------------------------------------------------

def test_three_or_more_divisions_is_group_wide():
    assert classify_reach("IB, P&C, GWM", "EMEA") == REACH_GROUP_WIDE


def test_a_global_region_is_group_wide_even_with_one_division():
    assert classify_reach("IB", "Global") == REACH_GROUP_WIDE


def test_two_divisions_is_multi_division():
    assert classify_reach("IB, P&C", "EMEA") == REACH_MULTI_DIVISION


def test_one_division_is_single_division():
    assert classify_reach("IB", "EMEA") == REACH_SINGLE_DIVISION


def test_a_region_without_a_division_is_regional_only():
    assert classify_reach("", "APAC") == REACH_REGIONAL_ONLY


def test_neither_field_is_unclassified():
    assert classify_reach(None, None) == REACH_UNCLASSIFIED


# --- audience_band -----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("250", BAND_UNDER_1K),
    ("999", BAND_UNDER_1K),
    ("1000", BAND_1_10K),
    ("9999", BAND_1_10K),
    ("12000", BAND_10_50K),
    ("50000", BAND_50_100K),
    ("100000", BAND_50_100K),
    ("100001", BAND_OVER_100K),
    ("12,000", BAND_10_50K),
    ("12'000", BAND_10_50K),
    (4200, BAND_1_10K),
])
def test_numeric_audience_values_map_to_bands(value, expected):
    assert audience_band(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("10–50k", BAND_10_50K),
    ("10-50k", BAND_10_50K),
    ("10 - 50k", BAND_10_50K),
    ("> 100k", BAND_OVER_100K),
    ("<1000", BAND_UNDER_1K),
])
def test_band_labels_survive_dash_and_spacing_variants(value, expected):
    assert audience_band(value) == expected


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
