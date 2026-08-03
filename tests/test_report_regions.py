"""Resolving the source's mixed region values into a group and a country."""

import pytest

from pipeline.report.regions import (
    GROUP_AMERICAS,
    GROUP_APAC,
    GROUP_EMEA,
    GROUP_GLOBAL,
    GROUP_SWITZERLAND,
    GROUP_UNMAPPED,
    country_names,
    region_group,
    resolve,
    unmapped_values,
)


@pytest.mark.parametrize("value,group,country", [
    # The catch-all, which is the largest single value in the source.
    ("All", GROUP_GLOBAL, None),
    ("Global", GROUP_GLOBAL, None),
    # Region on its own.
    ("APAC", GROUP_APAC, None),
    ("Americas", GROUP_AMERICAS, None),
    ("EMEA", GROUP_EMEA, None),
    # Region-qualified.
    ("APAC:Japan", GROUP_APAC, "Japan"),
    ("Americas:USA", GROUP_AMERICAS, "USA"),
    ("EMEA:UK", GROUP_EMEA, "United Kingdom"),
    # Country-qualified: the prefix settles both.
    ("Switzerland:Basel", GROUP_SWITZERLAND, "Switzerland"),
    # Bare country.
    ("Japan", GROUP_APAC, "Japan"),
    ("Switzerland", GROUP_SWITZERLAND, "Switzerland"),
    # Bare city rolls up.
    ("Zurich", GROUP_SWITZERLAND, "Switzerland"),
    ("Pune", GROUP_APAC, "India"),
    ("New York", GROUP_AMERICAS, "USA"),
    # Nothing at all.
    ("", None, None),
    (None, None, None),
])
def test_each_shape_the_source_uses_resolves(value, group, country):
    assert resolve(value) == (group, country)


@pytest.mark.parametrize("spelling", [
    "UK", "United Kingdom", "EMEA:UK", "EMEA:United Kingdom", "London", "EMEA:London",
])
def test_the_six_spellings_of_one_country_collapse_to_one(spelling):
    """The reason this module exists. The United Kingdom was spread over six
    rows in the calendar, and every regional figure was wrong, not imprecise.
    """
    assert resolve(spelling) == (GROUP_EMEA, "United Kingdom")


@pytest.mark.parametrize("spelling", ["USA", "Americas:USA", "New York", "Americas:New York"])
def test_the_same_holds_for_the_united_states(spelling):
    assert resolve(spelling) == (GROUP_AMERICAS, "USA")


@pytest.mark.parametrize("spelling", ["China", "APAC:China", "Beijing", "Shanghai"])
def test_and_for_china(spelling):
    assert resolve(spelling) == (GROUP_APAC, "China")


def test_the_two_spellings_of_geneva_are_one_place():
    assert resolve("Geneva") == resolve("Genève") == (GROUP_SWITZERLAND, "Switzerland")


def test_switzerland_is_its_own_group_not_part_of_emea():
    """Michael's decision, 2026-08-03: the source qualifies places as
    "Switzerland:Basel" exactly as it qualifies them "APAC:Japan", and it
    carries more activities than the rest of EMEA together.
    """
    assert resolve("Switzerland")[0] == GROUP_SWITZERLAND
    assert resolve("Zurich")[0] == GROUP_SWITZERLAND
    assert resolve("Germany")[0] == GROUP_EMEA


def test_an_unknown_value_is_unmapped_rather_than_guessed():
    assert resolve("Atlantis") == (GROUP_UNMAPPED, None)


def test_a_qualified_value_keeps_its_region_even_when_the_tail_is_unknown():
    """"EMEA:Somewhere" is still EMEA. Discarding that would throw away what
    the source did tell us.
    """
    assert resolve("EMEA:Somewhere") == (GROUP_EMEA, None)


def test_case_and_spacing_do_not_decide_the_answer():
    assert resolve("  japan  ") == resolve("JAPAN") == (GROUP_APAC, "Japan")


def test_an_activity_in_several_regions_carries_them_all():
    assert region_group("Zurich, APAC:Japan, USA") == "Switzerland, APAC, Americas"
    assert country_names("Zurich, APAC:Japan, USA") == "Switzerland, Japan, USA"


def test_two_values_in_one_group_are_not_repeated():
    assert region_group("Zurich, Basel") == "Switzerland"
    assert country_names("Zurich, Basel") == "Switzerland"


def test_a_region_only_value_contributes_no_country():
    assert region_group("APAC") == "APAC"
    assert country_names("APAC") == ""


def test_unmapped_values_are_listed_with_counts_as_the_source_wrote_them():
    """The Data Quality sheet prints this so the tables can grow. A value only
    ever seen inside a bucket total never gets fixed.
    """
    listed = unmapped_values(["Atlantis", "Atlantis, Japan", "Narnia", "Zurich"])

    assert listed == [("Atlantis", 2), ("Narnia", 1)]


# --- the tables have to stay consistent with each other ----------------------

def test_every_lookup_key_is_folded():
    """The three lookup tables are matched against `_key()` output. A key that
    is not folded matches nothing and silently drops its entry -- which is
    exactly what happened once while writing this module.
    """
    from pipeline.report.regions import (
        CITY_COUNTRY, COUNTRY_ALIASES, REGION_PREFIXES, _key,
    )

    for table, name in ((CITY_COUNTRY, "CITY_COUNTRY"),
                        (COUNTRY_ALIASES, "COUNTRY_ALIASES"),
                        (REGION_PREFIXES, "REGION_PREFIXES")):
        unfolded = [k for k in table if k != _key(k)]
        assert not unfolded, f"{name} keys must be folded: {unfolded}"


def test_every_city_points_at_a_country_the_group_table_knows():
    """A city mapped to a country nobody grouped would resolve to Unmapped
    while looking perfectly well-defined in the table.
    """
    from pipeline.report.regions import CITY_COUNTRY, COUNTRY_GROUP

    orphans = sorted({c for c in CITY_COUNTRY.values() if c not in COUNTRY_GROUP})

    assert not orphans, f"cities point at ungrouped countries: {orphans}"


def test_every_alias_points_at_a_country_the_group_table_knows():
    from pipeline.report.regions import COUNTRY_ALIASES, COUNTRY_GROUP

    orphans = sorted({c for c in COUNTRY_ALIASES.values() if c not in COUNTRY_GROUP})

    assert not orphans, f"aliases point at ungrouped countries: {orphans}"


def test_every_country_resolves_to_the_group_its_table_row_names():
    """The round trip: the table is the only authority, and reading it back
    through resolve() must agree with it.
    """
    from pipeline.report.regions import COUNTRY_GROUP

    for country, group in COUNTRY_GROUP.items():
        assert resolve(country) == (group, country), country


def test_every_group_in_the_tables_appears_in_the_reading_order():
    """GROUP_ORDER drives the calendar block's row order; a group missing from
    it would sort to the end as if it were unknown.
    """
    from pipeline.report.regions import COUNTRY_GROUP, GROUP_ORDER

    assert set(COUNTRY_GROUP.values()) <= set(GROUP_ORDER)
