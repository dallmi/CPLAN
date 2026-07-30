"""The calendar report's configuration and its vocabulary.

The three criteria the report is built around -- start date, senior-executive
involvement, audience size -- are hard filters: a row that fails any of them is
absent from every sheet. They are validated here rather than at use, so a typo
stops the run instead of silently emptying the workbook.
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
    date_from: date
    date_to: date
    executives: str = "any"
    audience_bands: tuple = None
    include_unknown_audience: bool = True
    include_archived: bool = True
    detail_rows: bool = True
    breakdown_fields: tuple = ("business_division", "region")

    def __post_init__(self):
        if self.date_from > self.date_to:
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

    def describe(self):
        """Label/value pairs for the Executive Summary's REPORT section."""
        bands = "all" if self.audience_bands is None else ", ".join(self.audience_bands)
        return [
            ("Period", f"{self.date_from.isoformat()} to {self.date_to.isoformat()}"),
            ("Senior executives", self.executives),
            ("Audience bands", bands),
            ("Unknown audience band", "included" if self.include_unknown_audience else "excluded"),
            ("Archived activities", "included" if self.include_archived else "excluded"),
            ("Activity detail rows", "on" if self.detail_rows else "off"),
            ("Breakdown dimensions", ", ".join(self.breakdown_fields)),
        ]
