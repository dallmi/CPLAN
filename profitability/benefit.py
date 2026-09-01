"""Put allocated costs next to a benefit distribution.

Profitability is benefit over cost, not cost alone. The benefit side reuses
the driver mechanism: benefit metrics (reach, engagement, outcome scores,
revenue, ...) are normalised per metric and blended with weights into one
benefit :class:`~profitability.distribution.Distribution` — exactly how cost
drivers are blended. This module compares that distribution against the
allocated costs per object:

- **benefit points**: the benefit share expressed on a fixed points scale
  (default 1000), largest-remainder rounded so the points sum exactly;
- **cost per point**: allocated cost divided by benefit points;
- **index**: benefit share over cost share × 100 — above 100 the object
  yields more benefit than its cost share, below 100 less.

The index is a relative efficiency measure, not a monetary ROI, unless the
benefit metric itself is monetary (e.g. revenue per client segment).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from typing import Mapping, Optional

from .allocation import allocate
from .distribution import Distribution


@dataclass(frozen=True)
class CostBenefitRow:
    """One cost object compared across the cost and benefit side."""

    object: str
    cost: Decimal
    cost_share: Fraction
    benefit_share: Fraction
    benefit_points: Decimal
    cost_per_point: Optional[Decimal]  # None when the object has no points
    index: Optional[Decimal]  # benefit share / cost share * 100; None if no cost


def cost_benefit(
    costs_by_object: Mapping[str, Decimal],
    benefit: Distribution,
    *,
    points: int = 1000,
    precision: int = 2,
) -> list[CostBenefitRow]:
    """Compare allocated costs per object against a benefit distribution.

    ``costs_by_object`` holds the (already allocated) total cost per object,
    e.g. the summed output of :func:`~profitability.allocation.allocate_costs`.
    Objects appearing on only one side get a zero on the other.
    """
    objects = list(costs_by_object)
    for name in benefit.objects:
        if name not in costs_by_object:
            objects.append(name)
    if not objects:
        raise ValueError("cost_benefit() needs at least one object")

    total_cost = sum(
        (Decimal(costs_by_object.get(name, 0)) for name in objects), Decimal(0)
    )
    if total_cost < 0:
        raise ValueError("total cost must not be negative")

    point_amounts = allocate(points, benefit, precision=0)
    quantum = Decimal(1).scaleb(-precision)

    rows: list[CostBenefitRow] = []
    for name in objects:
        cost = Decimal(costs_by_object.get(name, 0))
        cost_share = (
            Fraction(cost) / Fraction(total_cost) if total_cost > 0 else Fraction(0)
        )
        benefit_share = benefit.shares.get(name, Fraction(0))
        benefit_points = point_amounts.get(name, Decimal(0))

        cost_per_point = (
            (cost / benefit_points).quantize(quantum, rounding=ROUND_HALF_UP)
            if benefit_points > 0
            else None
        )
        index = (
            (
                Decimal(
                    (benefit_share / cost_share * 100).numerator
                )
                / Decimal((benefit_share / cost_share * 100).denominator)
            ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if cost_share > 0
            else None
        )
        rows.append(
            CostBenefitRow(
                object=name,
                cost=cost,
                cost_share=cost_share,
                benefit_share=benefit_share,
                benefit_points=benefit_points,
                cost_per_point=cost_per_point,
                index=index,
            )
        )
    return rows


def summed_costs(rows) -> dict[str, Decimal]:
    """Sum allocated amounts per object from :class:`AllocationRow` items —
    the natural bridge from ``allocate_costs()`` into ``cost_benefit()``.
    """
    totals: dict[str, Decimal] = {}
    for row in rows:
        totals[row.object] = totals.get(row.object, Decimal(0)) + row.amount
    return totals
