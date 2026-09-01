"""Percentage distributions derived from arbitrary driver values.

A :class:`Distribution` maps named cost objects (departments, products,
projects, ...) to exact fractional shares that sum to 1. Shares are kept as
:class:`fractions.Fraction` internally, so no precision is lost until an
amount is actually allocated and rounded.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Iterable, Mapping, Tuple, Union

Number = Union[int, float, str, Decimal, Fraction]

#: How to treat negative driver values in :meth:`Distribution.from_values`.
NEGATIVE_MODES = ("error", "zero", "absolute")


def to_fraction(value: Number) -> Fraction:
    """Convert a driver value to an exact fraction.

    Floats go through ``Decimal(str(value))`` so that ``0.1`` becomes exactly
    ``1/10`` instead of the binary float it is stored as.
    """
    if isinstance(value, float):
        return Fraction(Decimal(str(value)))
    return Fraction(value)


class Distribution:
    """An exact percentage distribution over named cost objects."""

    def __init__(self, shares: Mapping[str, Fraction]):
        if not shares:
            raise ValueError("a distribution needs at least one object")
        for name, share in shares.items():
            if share < 0:
                raise ValueError(f"share of {name!r} is negative: {share}")
        total = sum(shares.values())
        if total != 1:
            raise ValueError(f"shares must sum to exactly 1, got {total}")
        self._shares: dict[str, Fraction] = dict(shares)

    # ------------------------------------------------------------------ build

    @classmethod
    def from_values(
        cls,
        values: Mapping[str, Number],
        *,
        negatives: str = "error",
    ) -> "Distribution":
        """Build a distribution from raw driver values (headcount, revenue,
        square meters, ticket counts, ... anything numeric).

        ``negatives`` controls how negative values are treated:

        - ``"error"``  -- raise (default; a negative headcount is a data bug)
        - ``"zero"``   -- treat as 0 (object gets no share)
        - ``"absolute"`` -- use the absolute value
        """
        if negatives not in NEGATIVE_MODES:
            raise ValueError(f"negatives must be one of {NEGATIVE_MODES}")
        cleaned: dict[str, Fraction] = {}
        for name, raw in values.items():
            value = to_fraction(raw)
            if value < 0:
                if negatives == "error":
                    raise ValueError(
                        f"driver value of {name!r} is negative ({raw}); "
                        "pass negatives='zero' or negatives='absolute' to allow"
                    )
                value = Fraction(0) if negatives == "zero" else -value
            cleaned[name] = value
        total = sum(cleaned.values())
        if total <= 0:
            raise ValueError("driver values sum to zero; cannot form a distribution")
        return cls({name: value / total for name, value in cleaned.items()})

    @classmethod
    def equal(cls, objects: Iterable[str]) -> "Distribution":
        """Distribute equally over the given objects."""
        names = list(objects)
        return cls.from_values({name: 1 for name in names})

    @classmethod
    def combine(
        cls, parts: Iterable[Tuple["Distribution", Number]]
    ) -> "Distribution":
        """Blend several distributions with weights, e.g. 60 % headcount and
        40 % revenue. Weights are normalised, so ``(d1, 3), (d2, 1)`` means
        75 % / 25 %. Objects missing from one part simply contribute 0 there.
        """
        parts = [(dist, to_fraction(weight)) for dist, weight in parts]
        if not parts:
            raise ValueError("combine() needs at least one distribution")
        for _, weight in parts:
            if weight < 0:
                raise ValueError("combine() weights must not be negative")
        weight_sum = sum(weight for _, weight in parts)
        if weight_sum == 0:
            raise ValueError("combine() weights sum to zero")
        objects: dict[str, Fraction] = {}
        for dist, weight in parts:
            for name, share in dist.shares.items():
                objects[name] = objects.get(name, Fraction(0)) + share * weight / weight_sum
        return cls(objects)

    def with_fixed(self, fixed: Mapping[str, Number]) -> "Distribution":
        """Give some objects fixed shares and distribute the remainder
        pro rata (per this distribution) over the other objects.

        Example: object ``"Overhead"`` always gets 10 %, the remaining 90 %
        follow the headcount distribution.
        """
        fixed_shares = {name: to_fraction(v) for name, v in fixed.items()}
        for name, share in fixed_shares.items():
            if not 0 <= share <= 1:
                raise ValueError(f"fixed share of {name!r} must be within [0, 1]")
        fixed_total = sum(fixed_shares.values())
        if fixed_total > 1:
            raise ValueError("fixed shares exceed 100 %")
        rest_objects = {
            name: share for name, share in self.shares.items() if name not in fixed_shares
        }
        rest_total = sum(rest_objects.values())
        if rest_total == 0 and fixed_total != 1:
            raise ValueError(
                "no objects left to receive the unfixed remainder; "
                "fixed shares must sum to exactly 1 in that case"
            )
        result = dict(fixed_shares)
        for name, share in rest_objects.items():
            result[name] = (1 - fixed_total) * share / rest_total
        return Distribution(result)

    # ----------------------------------------------------------------- access

    @property
    def shares(self) -> dict[str, Fraction]:
        """Exact shares per object; values sum to exactly 1."""
        return dict(self._shares)

    @property
    def objects(self) -> list[str]:
        return list(self._shares)

    def percentages(self, precision: int = 2) -> dict[str, Decimal]:
        """Shares as rounded percent values that sum to exactly 100.

        Uses the largest-remainder method, so e.g. three equal thirds become
        33.34 / 33.33 / 33.33 instead of 33.33 * 3 = 99.99.
        """
        from .allocation import allocate  # local import to avoid a cycle

        return allocate(Decimal(100), self, precision=precision)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Distribution):
            return NotImplemented
        return self._shares == other._shares

    def __repr__(self) -> str:
        inner = ", ".join(
            f"{name}: {float(share):.4f}" for name, share in self._shares.items()
        )
        return f"Distribution({inner})"
