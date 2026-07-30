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
    assert config.breakdown_fields == ("business_division", "region")


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


def test_an_empty_breakdown_tuple_is_rejected():
    with pytest.raises(ValueError, match="breakdown_fields"):
        _config(breakdown_fields=())


def test_describe_reports_the_applied_criteria():
    labels = dict(_config(executives="with").describe())

    assert labels["Period"] == "2025-01-01 to 2025-12-31"
    assert labels["Senior executives"] == "with"
    assert labels["Audience bands"] == "all"
