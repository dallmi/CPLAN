from decimal import Decimal
from fractions import Fraction

import pytest

from profitability import CostLine, Distribution, allocate, allocate_costs, resolve_driver


def test_allocate_sums_exactly():
    dist = Distribution.equal(["A", "B", "C"])
    result = allocate(Decimal("100.00"), dist)
    assert sum(result.values()) == Decimal("100.00")
    assert sorted(result.values(), reverse=True) == [
        Decimal("33.34"),
        Decimal("33.33"),
        Decimal("33.33"),
    ]


def test_allocate_negative_amount_symmetric():
    dist = Distribution.equal(["A", "B", "C"])
    debit = allocate(Decimal("100.00"), dist)
    credit = allocate(Decimal("-100.00"), dist)
    assert credit == {name: -value for name, value in debit.items()}
    assert sum(credit.values()) == Decimal("-100.00")


def test_allocate_precision_zero():
    dist = Distribution.from_values({"A": 2, "B": 1})
    result = allocate(100, dist, precision=0)
    assert result == {"A": Decimal("67"), "B": Decimal("33")}


def test_allocate_deterministic_tie_break():
    dist = Distribution.equal(["B", "A"])  # equal remainders -> name decides
    result = allocate(Decimal("0.01"), dist)
    assert result == {"A": Decimal("0.01"), "B": Decimal("0.00")}


def test_allocate_many_objects_stays_exact():
    dist = Distribution.from_values({f"obj{i:03d}": i + 1 for i in range(97)})
    total = Decimal("12345.67")
    result = allocate(total, dist)
    assert sum(result.values()) == total


def test_resolve_driver_single_and_blend():
    drivers = {
        "headcount": Distribution.from_values({"A": 1, "B": 1}),
        "revenue": Distribution.from_values({"A": 1, "B": 3}),
    }
    assert resolve_driver("headcount", drivers) is drivers["headcount"]
    mixed = resolve_driver("headcount:60, revenue:40", drivers)
    assert mixed.shares == {"A": Fraction(2, 5), "B": Fraction(3, 5)}


def test_resolve_driver_unknown():
    with pytest.raises(KeyError, match="unknown driver"):
        resolve_driver("nope", {"headcount": Distribution.equal(["A"])})


def test_allocate_costs_rows():
    drivers = {
        "headcount": Distribution.from_values({"A": 3, "B": 1}),
        "revenue": Distribution.from_values({"A": 1, "B": 1}),
    }
    costs = [
        CostLine(name="Rent", amount=Decimal("1000.00"), driver="headcount"),
        CostLine(name="Audit", amount=Decimal("99.99"), driver="revenue"),
    ]
    rows = allocate_costs(costs, drivers)
    by_cost = {}
    for row in rows:
        by_cost.setdefault(row.cost, {})[row.object] = row.amount
    assert by_cost["Rent"] == {"A": Decimal("750.00"), "B": Decimal("250.00")}
    assert sum(by_cost["Audit"].values()) == Decimal("99.99")
