"""The calendar report's configuration and its vocabulary.

The three criteria the report is built around -- start date, senior-executive
involvement, audience size -- are hard filters: a row that fails any of them is
absent from every sheet. They are validated here rather than at use, so a typo
stops the run instead of silently emptying the workbook.

The period is the one criterion that may be left open. Each bound stands alone:
`None` means "no bound on that side", so an unset pair covers every dated
activity and a lone `date_from` covers everything from that day on.
"""

from dataclasses import dataclass
from datetime import date

BAND_UNDER_1K = "< 1000"
BAND_1_10K = "1–10k"
BAND_10_50K = "10–50k"
BAND_50_100K = "50–100k"
BAND_OVER_100K = "> 100k"
BAND_UNKNOWN = "Unknown"

# In ascending order of size. The two largest are what "large audience" means
# on the Executive Summary and the Audience sheet.
AUDIENCE_BANDS = (BAND_UNDER_1K, BAND_1_10K, BAND_10_50K, BAND_50_100K, BAND_OVER_100K)
LARGE_AUDIENCE_BANDS = (BAND_50_100K, BAND_OVER_100K)

EXECUTIVES_CHOICES = frozenset({"any", "with", "without"})

SHORT_NOTICE_DAYS = 7


@dataclass(frozen=True)
class ReportConfig:
    date_from: date = None
    date_to: date = None
    executives: str = "any"
    audience_bands: tuple = None
    include_unknown_audience: bool = True
    include_archived: bool = True
    detail_rows: bool = True
    breakdown_fields: tuple = ("business_division", "region")

    def __post_init__(self):
        if (self.date_from is not None and self.date_to is not None
                and self.date_from > self.date_to):
            raise ValueError(
                f"date_from ({self.date_from}) is after date_to ({self.date_to})"
            )
        if self.executives not in EXECUTIVES_CHOICES:
            raise ValueError(
                f"executives must be one of {sorted(EXECUTIVES_CHOICES)}, got {self.executives!r}"
            )
        if self.audience_bands is not None:
            if not self.audience_bands:
                raise ValueError(
                    "audience_bands must name at least one band; use None for all bands"
                )
            unknown = [b for b in self.audience_bands if b not in AUDIENCE_BANDS]
            if unknown:
                raise ValueError(
                    f"unknown audience band(s): {unknown}. Known bands: {list(AUDIENCE_BANDS)}"
                )
        if not self.breakdown_fields:
            raise ValueError("breakdown_fields must name at least one field")

    def covers(self, day):
        """Is `day` inside the period? An unset bound excludes nothing."""
        if self.date_from is not None and day < self.date_from:
            return False
        if self.date_to is not None and day > self.date_to:
            return False
        return True

    def period_label(self):
        """The period in words, for the Executive Summary."""
        if self.date_from is not None and self.date_to is not None:
            return f"{self.date_from.isoformat()} to {self.date_to.isoformat()}"
        if self.date_from is not None:
            return f"from {self.date_from.isoformat()}"
        if self.date_to is not None:
            return f"until {self.date_to.isoformat()}"
        return "all dates"

    def period_slug(self):
        """The period as a filename fragment: short enough to read in Explorer.

        Full calendar years shrink to their year numbers, because that is how a
        planner names them. Anything else spells out the dates rather than
        rounding to a year it does not actually cover.

        Never contains an underscore. The output filename joins name, slug and
        a `%Y_%m_%d` stamp with underscores, so a slug that used them too would
        blur the boundary: "..._2025_2026_08_03" could be a 2025 run stamped
        2026-08-03 or a 2025-2026 run stamped 08-03. Hyphens keep it readable
        both ways.
        """
        if self.date_from is None and self.date_to is None:
            return "all"
        if self.date_from is None:
            return f"until-{self.date_to.isoformat()}"
        if self.date_to is None:
            return f"from-{self.date_from.isoformat()}"
        starts_a_year = (self.date_from.month, self.date_from.day) == (1, 1)
        ends_a_year = (self.date_to.month, self.date_to.day) == (12, 31)
        if starts_a_year and ends_a_year:
            if self.date_from.year == self.date_to.year:
                return str(self.date_from.year)
            return f"{self.date_from.year}-{self.date_to.year}"
        return f"{self.date_from.isoformat()}-{self.date_to.isoformat()}"

    def describe(self):
        """Label/value pairs for the Executive Summary's REPORT section."""
        bands = "all" if self.audience_bands is None else ", ".join(self.audience_bands)
        return [
            ("Period", self.period_label()),
            ("Senior executives", self.executives),
            ("Audience bands", bands),
            ("Unknown audience band", "included" if self.include_unknown_audience else "excluded"),
            ("Archived activities", "included" if self.include_archived else "excluded"),
            ("Activity detail rows", "on" if self.detail_rows else "off"),
            ("Breakdown dimensions", ", ".join(self.breakdown_fields)),
        ]
