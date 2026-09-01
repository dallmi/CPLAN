"""CSV input/output for drivers, cost lines and allocation results."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Union

from .allocation import AllocationRow, CostLine
from .distribution import Distribution

PathLike = Union[str, Path]

DRIVER_COLUMNS = ("driver", "object", "value")
COST_COLUMNS = ("cost", "amount", "driver")


def _require_columns(fieldnames, required, path: PathLike) -> None:
    missing = [column for column in required if column not in (fieldnames or [])]
    if missing:
        raise ValueError(
            f"{path}: missing column(s) {', '.join(missing)}; "
            f"expected columns {', '.join(required)}"
        )


def read_drivers(
    path: PathLike, *, negatives: str = "error"
) -> dict[str, Distribution]:
    """Read driver values from a CSV with columns ``driver,object,value`` and
    return one normalised :class:`Distribution` per driver.
    """
    raw: dict[str, dict[str, Decimal]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, DRIVER_COLUMNS, path)
        for line_no, row in enumerate(reader, start=2):
            driver = (row["driver"] or "").strip()
            obj = (row["object"] or "").strip()
            text = (row["value"] or "").strip()
            if not driver and not obj and not text:
                continue  # blank line
            if not driver or not obj:
                raise ValueError(f"{path}:{line_no}: driver and object must not be empty")
            try:
                value = Decimal(text)
            except InvalidOperation:
                raise ValueError(f"{path}:{line_no}: invalid value {text!r}") from None
            per_driver = raw.setdefault(driver, {})
            # The same driver/object pair may appear on several lines
            # (e.g. monthly figures); values are summed.
            per_driver[obj] = per_driver.get(obj, Decimal(0)) + value
    if not raw:
        raise ValueError(f"{path}: no driver rows found")
    return {
        driver: Distribution.from_values(values, negatives=negatives)
        for driver, values in raw.items()
    }


def read_costs(path: PathLike) -> list[CostLine]:
    """Read cost lines from a CSV with columns ``cost,amount,driver``."""
    lines: list[CostLine] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, COST_COLUMNS, path)
        for line_no, row in enumerate(reader, start=2):
            name = (row["cost"] or "").strip()
            amount_text = (row["amount"] or "").strip()
            driver = (row["driver"] or "").strip()
            if not name and not amount_text and not driver:
                continue
            if not name or not driver:
                raise ValueError(f"{path}:{line_no}: cost and driver must not be empty")
            try:
                amount = Decimal(amount_text)
            except InvalidOperation:
                raise ValueError(
                    f"{path}:{line_no}: invalid amount {amount_text!r}"
                ) from None
            lines.append(CostLine(name=name, amount=amount, driver=driver))
    if not lines:
        raise ValueError(f"{path}: no cost rows found")
    return lines


def write_allocation(path: PathLike, rows: list[AllocationRow], *, precision: int = 2) -> None:
    """Write allocation rows as ``cost,driver,object,share_percent,amount``."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cost", "driver", "object", "share_percent", "amount"])
        for row in rows:
            share_percent = float(row.share * 100)
            writer.writerow(
                [row.cost, row.driver, row.object, f"{share_percent:.4f}", f"{row.amount}"]
            )


def write_percentages(
    path: PathLike, percentages: Mapping[str, Mapping[str, Decimal]]
) -> None:
    """Write per-driver percentages as ``driver,object,percent``."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["driver", "object", "percent"])
        for driver in sorted(percentages):
            for obj in sorted(percentages[driver]):
                writer.writerow([driver, obj, f"{percentages[driver][obj]}"])
