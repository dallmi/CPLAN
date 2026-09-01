from decimal import Decimal
from fractions import Fraction

import pytest

openpyxl = pytest.importorskip("openpyxl")

from profitability import allocate_costs
from profitability.io_xlsx import (
    read_costs_xlsx,
    read_drivers_xlsx,
    write_allocation_xlsx,
    write_percentages_xlsx,
)


def _workbook(path, sheets):
    """sheets: {name: [row, ...]} written in order; first sheet stays active."""
    workbook = openpyxl.Workbook()
    default = workbook.active
    for index, (name, rows) in enumerate(sheets.items()):
        worksheet = default if index == 0 else workbook.create_sheet()
        worksheet.title = name
        for row in rows:
            worksheet.append(row)
    workbook.save(path)
    return path


@pytest.fixture
def drivers_xlsx(tmp_path):
    return _workbook(
        tmp_path / "drivers.xlsx",
        {
            "drivers": [
                ["Driver", "Object", "Value"],  # header case-insensitive
                ["headcount", "IT", 50],
                ["headcount", "HR", 10],
                ["headcount", "Sales", 40],
                [None, None, None],  # blank row is skipped
                ["revenue", "IT", 0],
                ["revenue", "HR", 0],
                ["revenue", "Sales", 1250000],
            ]
        },
    )


@pytest.fixture
def costs_xlsx(tmp_path):
    return _workbook(
        tmp_path / "costs.xlsx",
        {
            "costs": [
                ["cost", "amount", "driver"],
                ["Rent", 120000, "headcount"],
                ["Audit", 99.99, "revenue"],
                ["Shared", 50000, "headcount:70,revenue:30"],
            ]
        },
    )


def test_read_drivers_xlsx(drivers_xlsx):
    drivers = read_drivers_xlsx(drivers_xlsx)
    assert set(drivers) == {"headcount", "revenue"}
    assert drivers["headcount"].shares["IT"] == Fraction(1, 2)
    assert drivers["revenue"].shares["Sales"] == 1


def test_read_drivers_xlsx_float_is_exact(tmp_path):
    path = _workbook(
        tmp_path / "drivers.xlsx",
        {"drivers": [["driver", "object", "value"], ["d", "A", 0.1], ["d", "B", 0.2]]},
    )
    drivers = read_drivers_xlsx(path)
    assert drivers["d"].shares == {"A": Fraction(1, 3), "B": Fraction(2, 3)}


def test_read_drivers_xlsx_named_sheet(tmp_path):
    path = _workbook(
        tmp_path / "book.xlsx",
        {
            "notes": [["whatever"]],
            "data": [["driver", "object", "value"], ["d", "A", 1]],
        },
    )
    drivers = read_drivers_xlsx(path, sheet="data")
    assert drivers["d"].shares == {"A": Fraction(1)}
    with pytest.raises(ValueError, match="no sheet 'nope'"):
        read_drivers_xlsx(path, sheet="nope")


def test_read_drivers_xlsx_missing_column(tmp_path):
    path = _workbook(
        tmp_path / "drivers.xlsx", {"drivers": [["driver", "value"], ["d", 1]]}
    )
    with pytest.raises(ValueError, match="missing column"):
        read_drivers_xlsx(path)


def test_read_costs_xlsx(costs_xlsx):
    costs = read_costs_xlsx(costs_xlsx)
    assert [line.name for line in costs] == ["Rent", "Audit", "Shared"]
    assert costs[0].amount == Decimal("120000")
    assert costs[1].amount == Decimal("99.99")
    assert costs[2].driver == "headcount:70,revenue:30"


def test_end_to_end_xlsx_roundtrip(tmp_path, drivers_xlsx, costs_xlsx):
    drivers = read_drivers_xlsx(drivers_xlsx)
    costs = read_costs_xlsx(costs_xlsx)
    rows = allocate_costs(costs, drivers)

    out = tmp_path / "allocation.xlsx"
    write_allocation_xlsx(out, rows)

    worksheet = openpyxl.load_workbook(out).active
    written = list(worksheet.iter_rows(values_only=True))
    assert written[0] == ("cost", "driver", "object", "share_percent", "amount")
    totals: dict[str, Decimal] = {}
    for cost, _driver, _obj, _share, amount in written[1:]:
        totals[cost] = totals.get(cost, Decimal(0)) + Decimal(str(amount))
    assert totals == {
        "Rent": Decimal("120000"),
        "Audit": Decimal("99.99"),
        "Shared": Decimal("50000"),
    }


def test_write_percentages_xlsx(tmp_path, drivers_xlsx):
    drivers = read_drivers_xlsx(drivers_xlsx)
    out = tmp_path / "percent.xlsx"
    write_percentages_xlsx(
        out, {name: dist.percentages() for name, dist in drivers.items()}
    )
    worksheet = openpyxl.load_workbook(out).active
    rows = list(worksheet.iter_rows(values_only=True))
    assert rows[0] == ("driver", "object", "percent")
    headcount = {obj: pct for driver, obj, pct in rows[1:] if driver == "headcount"}
    assert headcount == {"IT": 50.0, "HR": 10.0, "Sales": 40.0}
