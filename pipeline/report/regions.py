"""Region vocabulary: the source's mixed values resolved to a group and a country.

One source column carries five different kinds of value at once -- a region
("APAC"), a region-qualified place ("APAC:Japan", "Switzerland:Basel"), a bare
country ("Japan"), a bare city ("Zurich"), and a catch-all ("All"). The same
place therefore appears under several spellings, and counting the raw values
does not give a wrong-ish answer, it gives a wrong one: the United Kingdom is
spread over "UK", "United Kingdom", "EMEA:UK", "EMEA:United Kingdom", "London"
and "EMEA:London".

Two derivations come out of here. `region_group` answers "which part of the
world", `country_names` answers "which country" -- cities roll up into theirs,
because a planner does not plan by city.

Anything unrecognised resolves to UNMAPPED rather than being guessed at, and
the Data Quality sheet lists those values with their counts. That listing is
how this table is meant to grow: the report says what is missing instead of
quietly burying it in a bucket.
"""

from pipeline.report.derive import split_multi

GROUP_GLOBAL = "Global"
GROUP_AMERICAS = "Americas"
GROUP_APAC = "APAC"
GROUP_EMEA = "EMEA"
GROUP_SWITZERLAND = "Switzerland"
GROUP_UNMAPPED = "Unmapped"

# Reading order for the calendar block: the catch-all first because it is the
# largest single value in the source, then the groups, then the gap.
GROUP_ORDER = (
    GROUP_GLOBAL, GROUP_AMERICAS, GROUP_APAC, GROUP_EMEA,
    GROUP_SWITZERLAND, GROUP_UNMAPPED,
)

# Switzerland is its own group, not part of EMEA. That is what the source does
# -- it qualifies places as "Switzerland:Basel" exactly as it qualifies them as
# "APAC:Japan" -- and it carries more activities than the rest of EMEA together,
# so folding it in would leave EMEA meaning "Switzerland, plus some others".

# The value means every region, not a missing one.
GLOBAL_VALUES = frozenset({"all", "global", "worldwide", "all regions", "group-wide"})

# Keys in this and the two tables below are folded (lower case, single
# spaces): they are matched against `_key()` output. Only COUNTRY_GROUP
# above carries the spelling the report prints.
# A prefix before a colon that names a region rather than a country.
REGION_PREFIXES = {
    "apac": GROUP_APAC,
    "americas": GROUP_AMERICAS,
    "emea": GROUP_EMEA,
}

# Canonical country -> group. The key is the country name exactly as the
# report should print it -- one table, so a canonical spelling cannot drift
# from the group it belongs to. Matching is case-folded via _COUNTRY_BY_KEY.
COUNTRY_GROUP = {
    # Americas
    "Bahamas": GROUP_AMERICAS,
    "Brazil": GROUP_AMERICAS,
    "Canada": GROUP_AMERICAS,
    "Cayman Islands": GROUP_AMERICAS,
    "Chile": GROUP_AMERICAS,
    "Colombia": GROUP_AMERICAS,
    "Mexico": GROUP_AMERICAS,
    "Panama": GROUP_AMERICAS,
    "Puerto Rico": GROUP_AMERICAS,
    "Uruguay": GROUP_AMERICAS,
    "USA": GROUP_AMERICAS,
    # APAC
    "Australia": GROUP_APAC,
    "China": GROUP_APAC,
    "Hong Kong": GROUP_APAC,
    "India": GROUP_APAC,
    "Japan": GROUP_APAC,
    "Malaysia": GROUP_APAC,
    "Philippines": GROUP_APAC,
    "Singapore": GROUP_APAC,
    "South Korea": GROUP_APAC,
    "Taiwan": GROUP_APAC,
    "Thailand": GROUP_APAC,
    # EMEA
    "Austria": GROUP_EMEA,
    "Bahrain": GROUP_EMEA,
    "France": GROUP_EMEA,
    "Germany": GROUP_EMEA,
    "Ireland": GROUP_EMEA,
    "Israel": GROUP_EMEA,
    "Italy": GROUP_EMEA,
    "Jersey": GROUP_EMEA,
    "Luxembourg": GROUP_EMEA,
    "Middle East": GROUP_EMEA,
    "Monaco": GROUP_EMEA,
    "Poland": GROUP_EMEA,
    "Qatar": GROUP_EMEA,
    "South Africa": GROUP_EMEA,
    "Sweden": GROUP_EMEA,
    "United Arab Emirates": GROUP_EMEA,
    "United Kingdom": GROUP_EMEA,
    # Switzerland
    "Switzerland": GROUP_SWITZERLAND,
}

_COUNTRY_BY_KEY = {}   # filled below, once the tables are complete


# Spellings the source uses -> the canonical country above.
COUNTRY_ALIASES = {
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "us": "USA",
    "u.s.": "USA",
    "usa": "USA",
    "united states": "USA",
    "hongkong": "Hong Kong",
    "hong kong": "Hong Kong",
    "uae": "United Arab Emirates",
    "korea": "South Korea",
    "ch": "Switzerland",
}

# City -> the country it belongs to. A planner does not plan by city, so these
# roll up and the city itself never appears as a row.
CITY_COUNTRY = {
    "aarau": "Switzerland",
    "basel": "Switzerland",
    "bern": "Switzerland",
    "biel/bienne": "Switzerland",
    "biel": "Switzerland",
    "carouge": "Switzerland",
    "davos": "Switzerland",
    "geneva": "Switzerland",
    "genève": "Switzerland",
    "geneve": "Switzerland",
    "lausanne": "Switzerland",
    "lugano": "Switzerland",
    "montreux": "Switzerland",
    "opfikon": "Switzerland",
    "riehen": "Switzerland",
    # The group's own conference centre, in Switzerland -- not the Austrian town
    # of the same name.
    "wolfsberg": "Switzerland",
    "zurich": "Switzerland",
    "zürich": "Switzerland",
    "berlin": "Germany",
    "frankfurt": "Germany",
    "milano": "Italy",
    "milan": "Italy",
    "krakow": "Poland",
    "warsaw": "Poland",
    "wroclaw": "Poland",
    "london": "United Kingdom",
    "abu dhabi": "United Arab Emirates",
    "dubai": "United Arab Emirates",
    "beijing": "China",
    "shanghai": "China",
    "hyderabad": "India",
    "mumbai": "India",
    "pune": "India",
    "sydney": "Australia",
    "chicago": "USA",
    "nashville": "USA",
    "new york": "USA",
    "raleigh": "USA",
    "washington dc": "USA",
    "washington d.c.": "USA",
    "weehawken": "USA",
}


def _key(text):
    """Fold case and whitespace so matching is not typography."""
    return " ".join(str(text).lower().split())


_COUNTRY_BY_KEY.update({_key(name): name for name in COUNTRY_GROUP})


def _canonical_country(text):
    """The canonical country for a value, or None if it names no country.

    Always the table's own spelling, never the source's. Returning what the
    source wrote would put "japan" and "JAPAN" on two rows -- the exact
    duplicate this module exists to remove.
    """
    key = _key(text)
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key]
    if key in CITY_COUNTRY:
        return CITY_COUNTRY[key]
    return _COUNTRY_BY_KEY.get(key)


def resolve(value):
    """One source value -> (group, country or None).

    The colon prefix is read first because it is the source's own answer: a
    prefix that names a region settles the group outright, and a prefix that
    names a country settles both. Only then does the whole value get looked up.
    """
    text = str(value or "").strip()
    if not text:
        return None, None
    if _key(text) in GLOBAL_VALUES:
        return GROUP_GLOBAL, None

    prefix, _, rest = text.partition(":")
    if rest:
        prefix_key = _key(prefix)
        if prefix_key in REGION_PREFIXES:
            group = REGION_PREFIXES[prefix_key]
            country = _canonical_country(rest)
            # A qualified place whose tail we cannot name still has its region:
            # "EMEA:Somewhere" is EMEA, and pretending otherwise loses what the
            # source did tell us.
            return group, country
        prefix_country = _canonical_country(prefix)
        if prefix_country:
            return COUNTRY_GROUP.get(prefix_country, GROUP_UNMAPPED), prefix_country
        return GROUP_UNMAPPED, None

    if _key(text) in REGION_PREFIXES:
        return REGION_PREFIXES[_key(text)], None

    country = _canonical_country(text)
    if country:
        return COUNTRY_GROUP.get(country, GROUP_UNMAPPED), country
    return GROUP_UNMAPPED, None


def _joined(values):
    """Unique, in first-seen order, comma-joined for the multi-value blocks."""
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return ", ".join(seen)


def region_group(value):
    """Which part of the world, for one activity's (possibly multi-) region."""
    return _joined(resolve(part)[0] for part in split_multi(value))


def country_names(value):
    """Which country, for one activity's region. Cities roll up into theirs."""
    return _joined(resolve(part)[1] for part in split_multi(value))


def unmapped_values(values):
    """The raw source values that resolve to no group, with their counts.

    What the Data Quality sheet lists so the tables above can be extended. It
    reports the value exactly as the source wrote it -- that is what somebody
    has to search for to fix it.
    """
    counts = {}
    for value in values:
        for part in split_multi(value):
            if resolve(part)[0] == GROUP_UNMAPPED:
                counts[part.strip()] = counts.get(part.strip(), 0) + 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
