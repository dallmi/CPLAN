from decimal import Decimal
from fractions import Fraction

import pytest

from profitability import (
    CostLine,
    Distribution,
    allocate_costs,
    cost_benefit,
    summed_costs,
)


def test_summed_costs_bridges_allocation():
    drivers = {"headcount": Distribution.from_values({"A": 3, "B": 1})}
    rows = allocate_costs(
        [
            CostLine("Rent", Decimal("1000.00"), "headcount"),
            CostLine("Audit", Decimal("100.00"), "headcount"),
        ],
        drivers,
    )
    assert summed_costs(rows) == {"A": Decimal("825.00"), "B": Decimal("275.00")}


def test_cost_benefit_points_sum_and_index():
    costs = {"A": Decimal("750.00"), "B": Decimal("250.00")}
    benefit = Distribution.from_values({"A": 1, "B": 1})
    rows = cost_benefit(costs, benefit)
    by_object = {row.object: row for row in rows}

    assert sum(row.benefit_points for row in rows) == Decimal(1000)
    # A carries 75 % of cost but only 50 % of benefit -> index 66.7
    assert by_object["A"].index == Decimal("66.7")
    assert by_object["B"].index == Decimal("200.0")
    assert by_object["A"].cost_per_point == Decimal("1.50")
    assert by_object["B"].cost_per_point == Decimal("0.50")


def test_cost_benefit_objects_on_one_side_only():
    costs = {"A": Decimal("100.00")}
    benefit = Distribution.from_values({"B": 1})
    rows = cost_benefit(costs, benefit)
    by_object = {row.object: row for row in rows}
    assert set(by_object) == {"A", "B"}
    # A: all cost, no benefit -> no cost-per-point, index 0.
    assert by_object["A"].benefit_points == Decimal(0)
    assert by_object["A"].cost_per_point is None
    assert by_object["A"].index == Decimal("0.0")
    # B: all benefit, no cost -> no index (cost share is zero).
    assert by_object["B"].cost == Decimal(0)
    assert by_object["B"].index is None
    assert by_object["B"].benefit_points == Decimal(1000)


def test_cost_benefit_shares_are_exact_fractions():
    costs = {"A": Decimal("1"), "B": Decimal("2")}
    benefit = Distribution.from_values({"A": 2, "B": 1})
    rows = {row.object: row for row in cost_benefit(costs, benefit)}
    assert rows["A"].cost_share == Fraction(1, 3)
    assert rows["A"].benefit_share == Fraction(2, 3)
    assert rows["A"].index == Decimal("200.0")


def test_cost_benefit_costs_may_be_empty():
    # Benefit objects alone are enough; every cost is zero then.
    rows = cost_benefit({}, Distribution.from_values({"A": 1}))
    assert len(rows) == 1
    assert rows[0].cost == Decimal(0)
    assert rows[0].index is None


def test_cli_cost_benefit_end_to_end(tmp_path, capsys):
    from profitability.cli import main

    (tmp_path / "drivers.csv").write_text(
        "driver,object,value\nheadcount,A,3\nheadcount,B,1\n", encoding="utf-8"
    )
    (tmp_path / "costs.csv").write_text(
        "cost,amount,driver\nRent,1000.00,headcount\n", encoding="utf-8"
    )
    (tmp_path / "benefits.csv").write_text(
        "driver,object,value\nreach,A,1\nreach,B,1\nengagement,A,1\nengagement,B,3\n",
        encoding="utf-8",
    )
    out = tmp_path / "cb.csv"
    code = main(
        [
            "cost-benefit",
            "--costs", str(tmp_path / "costs.csv"),
            "--drivers", str(tmp_path / "drivers.csv"),
            "--benefits", str(tmp_path / "benefits.csv"),
            "--benefit-mix", "reach:50,engagement:50",
            "--out", str(out),
        ]
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("object,cost,")
    assert len(lines) == 3
