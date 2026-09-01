import csv
from decimal import Decimal
from fractions import Fraction

import pytest

from profitability import allocate_costs
from profitability.io_csv import read_costs, read_drivers, write_allocation


DRIVERS_CSV = """driver,object,value
headcount,IT,50
headcount,HR,10
headcount,Sales,40
revenue,IT,0
revenue,HR,0
revenue,Sales,1000
"""

COSTS_CSV = """cost,amount,driver
Rent,120000.00,headcount
CRM licences,9999.99,revenue
Shared services,50000.00,"headcount:70,revenue:30"
"""


@pytest.fixture
def drivers_file(tmp_path):
    path = tmp_path / "drivers.csv"
    path.write_text(DRIVERS_CSV, encoding="utf-8")
    return path


@pytest.fixture
def costs_file(tmp_path):
    path = tmp_path / "costs.csv"
    path.write_text(COSTS_CSV, encoding="utf-8")
    return path


def test_read_drivers(drivers_file):
    drivers = read_drivers(drivers_file)
    assert set(drivers) == {"headcount", "revenue"}
    assert drivers["headcount"].shares["IT"] == Fraction(1, 2)
    assert drivers["revenue"].shares["Sales"] == 1


def test_read_drivers_sums_duplicate_rows(tmp_path):
    path = tmp_path / "drivers.csv"
    path.write_text(
        "driver,object,value\nheadcount,IT,10\nheadcount,IT,30\nheadcount,HR,40\n",
        encoding="utf-8",
    )
    drivers = read_drivers(path)
    assert drivers["headcount"].shares == {"IT": Fraction(1, 2), "HR": Fraction(1, 2)}


def test_read_drivers_missing_column(tmp_path):
    path = tmp_path / "drivers.csv"
    path.write_text("driver,value\nheadcount,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        read_drivers(path)


def test_read_costs(costs_file):
    costs = read_costs(costs_file)
    assert [line.name for line in costs] == ["Rent", "CRM licences", "Shared services"]
    assert costs[0].amount == Decimal("120000.00")
    assert costs[2].driver == "headcount:70,revenue:30"


def test_end_to_end_csv_roundtrip(tmp_path, drivers_file, costs_file):
    drivers = read_drivers(drivers_file)
    costs = read_costs(costs_file)
    rows = allocate_costs(costs, drivers)

    out = tmp_path / "allocation.csv"
    write_allocation(out, rows)

    with open(out, newline="", encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))

    totals: dict[str, Decimal] = {}
    for row in written:
        totals[row["cost"]] = totals.get(row["cost"], Decimal(0)) + Decimal(row["amount"])
    assert totals == {
        "Rent": Decimal("120000.00"),
        "CRM licences": Decimal("9999.99"),
        "Shared services": Decimal("50000.00"),
    }
