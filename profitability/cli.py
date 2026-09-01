"""Command line interface.

Two subcommands:

- ``distribute``: turn raw driver values into percentage distributions.
- ``allocate``: allocate cost lines to cost objects along their drivers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .allocation import allocate_costs
from .distribution import NEGATIVE_MODES
from .io_csv import read_costs, read_drivers, write_allocation, write_percentages

XLSX_SUFFIXES = {".xlsx", ".xlsm", ".xltx"}


def _is_xlsx(path: str) -> bool:
    return Path(path).suffix.lower() in XLSX_SUFFIXES


def load_drivers(path: str, *, sheet: str | None = None, negatives: str = "error"):
    """Read drivers from CSV or Excel, decided by the file extension."""
    if _is_xlsx(path):
        from .io_xlsx import read_drivers_xlsx

        return read_drivers_xlsx(path, sheet=sheet, negatives=negatives)
    return read_drivers(path, negatives=negatives)


def load_costs(path: str, *, sheet: str | None = None):
    """Read cost lines from CSV or Excel, decided by the file extension."""
    if _is_xlsx(path):
        from .io_xlsx import read_costs_xlsx

        return read_costs_xlsx(path, sheet=sheet)
    return read_costs(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profitability",
        description=(
            "Convert driver values into percentage distributions and "
            "allocate costs along them."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dist = sub.add_parser(
        "distribute",
        help="convert driver values (CSV: driver,object,value) into percentages",
    )
    dist.add_argument("--drivers", required=True, help="drivers file (.csv or .xlsx)")
    dist.add_argument("--drivers-sheet", help="worksheet name for an .xlsx drivers file")
    dist.add_argument("--driver", help="only show this driver (default: all)")
    dist.add_argument("--precision", type=int, default=2, help="percent decimals (default 2)")
    dist.add_argument(
        "--negatives",
        choices=NEGATIVE_MODES,
        default="error",
        help="how to treat negative driver values (default: error)",
    )
    dist.add_argument(
        "--out", help="write result here (.csv or .xlsx) instead of printing"
    )

    alloc = sub.add_parser(
        "allocate",
        help=(
            "allocate cost lines (cost,amount,driver) along drivers "
            "(driver,object,value); files may be .csv or .xlsx"
        ),
    )
    alloc.add_argument("--costs", required=True, help="costs file (.csv or .xlsx)")
    alloc.add_argument("--costs-sheet", help="worksheet name for an .xlsx costs file")
    alloc.add_argument("--drivers", required=True, help="drivers file (.csv or .xlsx)")
    alloc.add_argument("--drivers-sheet", help="worksheet name for an .xlsx drivers file")
    alloc.add_argument("--precision", type=int, default=2, help="amount decimals (default 2)")
    alloc.add_argument(
        "--negatives",
        choices=NEGATIVE_MODES,
        default="error",
        help="how to treat negative driver values (default: error)",
    )
    alloc.add_argument(
        "--out", help="write result here (.csv or .xlsx) instead of printing"
    )
    return parser


def _print_table(header: list[str], rows: list[list[str]]) -> None:
    widths = [len(cell) for cell in header]
    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]
    line = "  ".join(cell.ljust(width) for cell, width in zip(header, widths))
    print(line)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


def run_distribute(args: argparse.Namespace) -> int:
    drivers = load_drivers(
        args.drivers, sheet=args.drivers_sheet, negatives=args.negatives
    )
    if args.driver:
        if args.driver not in drivers:
            known = ", ".join(sorted(drivers))
            print(f"unknown driver {args.driver!r}; known: {known}", file=sys.stderr)
            return 2
        drivers = {args.driver: drivers[args.driver]}
    percentages = {
        name: dist.percentages(precision=args.precision)
        for name, dist in drivers.items()
    }
    if args.out:
        if _is_xlsx(args.out):
            from .io_xlsx import write_percentages_xlsx

            write_percentages_xlsx(args.out, percentages)
        else:
            write_percentages(args.out, percentages)
        print(f"wrote {args.out}")
        return 0
    rows = [
        [driver, obj, f"{percentages[driver][obj]} %"]
        for driver in sorted(percentages)
        for obj in sorted(percentages[driver])
    ]
    _print_table(["driver", "object", "percent"], rows)
    return 0


def run_allocate(args: argparse.Namespace) -> int:
    drivers = load_drivers(
        args.drivers, sheet=args.drivers_sheet, negatives=args.negatives
    )
    costs = load_costs(args.costs, sheet=args.costs_sheet)
    rows = allocate_costs(costs, drivers, precision=args.precision)
    if args.out:
        if _is_xlsx(args.out):
            from .io_xlsx import write_allocation_xlsx

            write_allocation_xlsx(args.out, rows, precision=args.precision)
        else:
            write_allocation(args.out, rows, precision=args.precision)
        print(f"wrote {args.out}")
        return 0
    table = [
        [row.cost, row.driver, row.object, f"{float(row.share * 100):.2f} %", f"{row.amount}"]
        for row in rows
    ]
    _print_table(["cost", "driver", "object", "share", "amount"], table)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "distribute":
            return run_distribute(args)
        return run_allocate(args)
    except (ValueError, KeyError, OSError, ImportError) as error:
        message = error.args[0] if error.args else error
        print(f"error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
