from decimal import Decimal
from fractions import Fraction

import pytest

from profitability import Distribution


def test_from_values_normalises():
    dist = Distribution.from_values({"IT": 50, "HR": 10, "Sales": 40})
    assert dist.shares == {
        "IT": Fraction(1, 2),
        "HR": Fraction(1, 10),
        "Sales": Fraction(2, 5),
    }
    assert sum(dist.shares.values()) == 1


def test_from_values_accepts_floats_exactly():
    dist = Distribution.from_values({"A": 0.1, "B": 0.2})
    assert dist.shares == {"A": Fraction(1, 3), "B": Fraction(2, 3)}


def test_from_values_rejects_zero_total():
    with pytest.raises(ValueError, match="sum to zero"):
        Distribution.from_values({"A": 0, "B": 0})


def test_negatives_error_by_default():
    with pytest.raises(ValueError, match="negative"):
        Distribution.from_values({"A": -1, "B": 3})


def test_negatives_zero_and_absolute():
    zero = Distribution.from_values({"A": -1, "B": 3}, negatives="zero")
    assert zero.shares == {"A": Fraction(0), "B": Fraction(1)}
    absolute = Distribution.from_values({"A": -1, "B": 3}, negatives="absolute")
    assert absolute.shares == {"A": Fraction(1, 4), "B": Fraction(3, 4)}


def test_equal():
    dist = Distribution.equal(["A", "B", "C"])
    assert dist.shares == {name: Fraction(1, 3) for name in "ABC"}


def test_combine_weighted():
    headcount = Distribution.from_values({"A": 1, "B": 1})
    revenue = Distribution.from_values({"A": 1, "B": 3})
    mixed = Distribution.combine([(headcount, 60), (revenue, 40)])
    assert mixed.shares == {"A": Fraction(2, 5), "B": Fraction(3, 5)}
    assert sum(mixed.shares.values()) == 1


def test_combine_disjoint_objects():
    left = Distribution.from_values({"A": 1})
    right = Distribution.from_values({"B": 1})
    mixed = Distribution.combine([(left, 1), (right, 1)])
    assert mixed.shares == {"A": Fraction(1, 2), "B": Fraction(1, 2)}


def test_with_fixed():
    base = Distribution.from_values({"A": 1, "B": 1, "Overhead": 5})
    dist = base.with_fixed({"Overhead": Fraction(1, 10)})
    assert dist.shares == {
        "Overhead": Fraction(1, 10),
        "A": Fraction(9, 20),
        "B": Fraction(9, 20),
    }


def test_with_fixed_rejects_over_100_percent():
    base = Distribution.from_values({"A": 1, "B": 1})
    with pytest.raises(ValueError, match="exceed"):
        base.with_fixed({"A": Fraction(3, 5), "B": Fraction(3, 5)})


def test_percentages_sum_to_100():
    dist = Distribution.equal(["A", "B", "C"])
    percentages = dist.percentages(precision=2)
    assert sum(percentages.values()) == Decimal("100.00")
    assert sorted(percentages.values(), reverse=True) == [
        Decimal("33.34"),
        Decimal("33.33"),
        Decimal("33.33"),
    ]
