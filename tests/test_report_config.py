"""The report's configuration block validates itself at startup."""

from datetime import date

import pytest

from pipeline.report.config import AUDIENCE_BANDS, BAND_UNKNOWN, ReportConfig


def _config(**overrides):
    base = dict(date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
    base.update(overrides)
    return ReportConfig(**base)


def test_defaults_keep_everything_in_scope():
    config = _config()

    assert config.executives == "any"
    assert config.audience_bands is None
    assert config.include_archived is True
    assert config.breakdown_fields == ("business_division", "region_group",
                                      "country", "executives")


def test_reversed_dates_are_rejected():
    with pytest.raises(ValueError, match="date_from"):
        _config(date_from=date(2025, 12, 31), date_to=date(2025, 1, 1))


def test_an_unknown_executives_choice_is_rejected():
    with pytest.raises(ValueError, match="executives"):
        _config(executives="yes")


def test_a_misspelled_audience_band_is_rejected():
    with pytest.raises(ValueError, match="audience band"):
        _config(audience_bands=("10-50k",))


def test_every_real_band_is_accepted():
    config = _config(audience_bands=AUDIENCE_BANDS)

    assert config.audience_bands == AUDIENCE_BANDS
    assert BAND_UNKNOWN not in AUDIENCE_BANDS


def test_an_empty_band_tuple_is_rejected_rather_than_filtering_everything_away():
    with pytest.raises(ValueError, match="at least one"):
        _config(audience_bands=())


def test_no_excluded_objectives_by_default():
    config = _config()

    assert config.exclude_objectives == ()
    assert dict(config.describe())["Excluded objectives"] == "none"


def test_excluded_objectives_are_named_on_the_summary():
    config = _config(exclude_objectives=("2026: Other", "2026: Misc"))

    assert dict(config.describe())["Excluded objectives"] == "2026: Other, 2026: Misc"


def test_a_blank_objective_prefix_is_rejected_rather_than_emptying_the_report():
    """A blank prefix matches every objective, so it would drop every row that
    carries one -- the loudest possible failure, silently.
    """
    with pytest.raises(ValueError, match="blank prefix"):
        _config(exclude_objectives=("2026: Other", ""))
    with pytest.raises(ValueError, match="blank prefix"):
        _config(exclude_objectives=("   ",))


def test_a_priority_that_is_not_a_number_is_rejected():
    """The filter matches the source's leading integer. A label like
    "4 - deprioritised" would match nothing and silently exclude no rows.
    """
    with pytest.raises(ValueError, match="leading numbers"):
        _config(exclude_priorities=("4 - deprioritised",))
    with pytest.raises(ValueError, match="leading numbers"):
        _config(exclude_priorities=(True,))


def test_excluded_priorities_are_named_on_the_summary():
    assert dict(_config(exclude_priorities=(3, 4)).describe())["Excluded priorities"] == "3, 4"
    assert dict(_config().describe())["Excluded priorities"] == "none"


def test_an_empty_breakdown_tuple_is_rejected():
    with pytest.raises(ValueError, match="breakdown_fields"):
        _config(breakdown_fields=())


def test_describe_reports_the_applied_criteria():
    labels = dict(_config(executives="with").describe())

    assert labels["Period"] == "2025-01-01 to 2025-12-31"
    assert labels["GEB/GEB-1"] == "with"
    assert labels["Audience bands"] == "all"


# --- the period, which is the one criterion that may be left open -----------

def test_a_config_without_a_period_is_valid_and_covers_every_day():
    config = ReportConfig()

    assert config.date_from is None
    assert config.date_to is None
    assert config.covers(date(1999, 1, 1))
    assert config.covers(date(2049, 12, 31))


def test_a_lower_bound_alone_leaves_the_upper_side_open():
    config = ReportConfig(date_from=date(2026, 1, 1))

    assert not config.covers(date(2025, 12, 31))
    assert config.covers(date(2026, 1, 1))
    assert config.covers(date(2049, 1, 1))


def test_an_upper_bound_alone_leaves_the_lower_side_open():
    config = ReportConfig(date_to=date(2026, 12, 31))

    assert config.covers(date(1999, 1, 1))
    assert config.covers(date(2026, 12, 31))
    assert not config.covers(date(2027, 1, 1))


def test_both_bounds_are_inclusive():
    config = _config()

    assert config.covers(date(2025, 1, 1))
    assert config.covers(date(2025, 12, 31))
    assert not config.covers(date(2024, 12, 31))
    assert not config.covers(date(2026, 1, 1))


@pytest.mark.parametrize("window,expected", [
    ((date(2026, 1, 1), date(2026, 12, 31)), "2026-01-01 to 2026-12-31"),
    ((date(2026, 1, 1), None), "from 2026-01-01"),
    ((None, date(2026, 12, 31)), "until 2026-12-31"),
    ((None, None), "all dates"),
])
def test_the_period_label_says_what_the_run_covered(window, expected):
    config = ReportConfig(date_from=window[0], date_to=window[1])

    assert config.period_label() == expected
    assert dict(config.describe())["Period"] == expected


@pytest.mark.parametrize("window,expected", [
    # Full calendar years shrink to their year numbers...
    ((date(2026, 1, 1), date(2026, 12, 31)), "2026"),
    ((date(2025, 1, 1), date(2026, 12, 31)), "2025-2026"),
    # ...anything else spells out the dates rather than rounding to a year it
    # does not actually cover.
    ((date(2026, 4, 1), date(2026, 9, 30)), "2026-04-01-2026-09-30"),
    ((date(2026, 1, 1), date(2026, 6, 30)), "2026-01-01-2026-06-30"),
    ((date(2026, 4, 1), None), "from-2026-04-01"),
    ((None, date(2026, 9, 30)), "until-2026-09-30"),
    ((None, None), "all"),
])
def test_the_period_slug_names_the_window_for_the_filename(window, expected):
    config = ReportConfig(date_from=window[0], date_to=window[1])

    assert config.period_slug() == expected


@pytest.mark.parametrize("window", [
    (date(2026, 1, 1), date(2026, 12, 31)),
    (date(2025, 1, 1), date(2026, 12, 31)),
    (date(2026, 4, 1), date(2026, 9, 30)),
    (date(2026, 4, 1), None),
    (None, date(2026, 9, 30)),
    (None, None),
])
def test_no_slug_contains_an_underscore(window):
    """The filename joins slug and a %Y_%m_%d stamp with underscores; a slug
    that used them too would make "2025_2026_08_03" ambiguous.
    """
    assert "_" not in ReportConfig(date_from=window[0], date_to=window[1]).period_slug()


def test_a_reversed_window_is_rejected_even_though_bounds_are_optional():
    with pytest.raises(ValueError, match="date_from"):
        ReportConfig(date_from=date(2026, 12, 31), date_to=date(2026, 1, 1))
