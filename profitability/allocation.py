"""Allocate monetary amounts along a distribution, exact to the cent.

Rounding uses the largest-remainder method: every object first gets its share
rounded down to the target precision, then the leftover cents are handed out
to the objects with the largest fractional remainders. The allocated amounts
therefore always sum to exactly the input total.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Iterable, Mapping, Union

from .distribution import Distribution, Number, to_fraction


def allocate(
    amount: Number,
    distribution: Distribution,
    *,
    precision: int = 2,
) -> dict[str, Decimal]:
    """Split ``amount`` along ``distribution`` into amounts with ``precision``
    decimal places that sum to exactly ``amount`` (largest-remainder method).

    Negative amounts (credits) are allocated symmetrically to positive ones.
    """
    total = to_fraction(amount)
    if total < 0:
        flipped = allocate(-total, distribution, precision=precision)
        return {name: -value for name, value in flipped.items()}

    step = Fraction(1, 10**precision)
    exact = {name: total * share for name, share in distribution.shares.items()}

    floored: dict[str, int] = {}  # amounts in integer steps (e.g. cents)
    remainders: dict[str, Fraction] = {}
    for name, value in exact.items():
        steps = value / step
        whole = steps.numerator // steps.denominator
        floored[name] = whole
        remainders[name] = steps - whole

    leftover_steps = total / step - sum(floored.values())
    assert leftover_steps.denominator == 1, "total must be representable at this precision"
    leftover = leftover_steps.numerator

    # Hand out leftover steps by largest remainder; break ties deterministically
    # by larger share, then by name.
    order = sorted(
        distribution.objects,
        key=lambda name: (-remainders[name], -distribution.shares[name], name),
    )
    for name in order[:leftover]:
        floored[name] += 1

    quantum = Decimal(1).scaleb(-precision)
    return {name: Decimal(steps_) * quantum for name, steps_ in floored.items()}


@dataclass(frozen=True)
class CostLine:
    """One cost item to be allocated: a name, an amount and a driver spec.

    ``driver`` is either the name of a single driver (``"headcount"``) or a
    weighted mix (``"headcount:60,revenue:40"``).
    """

    name: str
    amount: Decimal
    driver: str


@dataclass(frozen=True)
class AllocationRow:
    """One resulting slice: cost item x cost object."""

    cost: str
    driver: str
    object: str
    share: Fraction
    amount: Decimal


def resolve_driver(
    spec: str, drivers: Mapping[str, Distribution]
) -> Distribution:
    """Resolve a driver spec against the known driver distributions.

    ``"headcount"`` picks one driver; ``"headcount:60,revenue:40"`` blends
    drivers with the given weights (any positive numbers, normalised).
    """
    spec = spec.strip()
    if not spec:
        raise ValueError("empty driver spec")
    parts: list[tuple[Distribution, Union[int, str]]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if ":" in chunk:
            driver_name, _, weight_text = chunk.partition(":")
            driver_name, weight = driver_name.strip(), weight_text.strip()
        else:
            driver_name, weight = chunk, 1
        if driver_name not in drivers:
            known = ", ".join(sorted(drivers)) or "(none)"
            raise KeyError(f"unknown driver {driver_name!r}; known drivers: {known}")
        parts.append((drivers[driver_name], weight))
    if len(parts) == 1:
        return parts[0][0]
    return Distribution.combine(parts)


def allocate_costs(
    costs: Iterable[CostLine],
    drivers: Mapping[str, Distribution],
    *,
    precision: int = 2,
) -> list[AllocationRow]:
    """Allocate every cost line along its (possibly blended) driver."""
    rows: list[AllocationRow] = []
    for line in costs:
        distribution = resolve_driver(line.driver, drivers)
        amounts = allocate(line.amount, distribution, precision=precision)
        for obj in sorted(amounts):
            rows.append(
                AllocationRow(
                    cost=line.name,
                    driver=line.driver,
                    object=obj,
                    share=distribution.shares[obj],
                    amount=amounts[obj],
                )
            )
    return rows
