"""Command line interface.

Two subcommands:

- ``distribute``: turn raw driver values into percentage distributions.
- ``allocate``: allocate cost lines to cost objects along their drivers.
"""

from __future__ import annotations

import argparse
import sys

from .allocation import allocate_costs
from .distribution import NEGATIVE_MODES
from .io_csv import read_costs, read_drivers, write_allocation, write_percentages


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
    dist.add_argument("--drivers", required=True, help="drivers CSV file")
    dist.add_argument("--driver", help="only show this driver (default: all)")
    dist.add_argument("--precision", type=int, default=2, help="percent decimals (default 2)")
    dist.add_argument(
        "--negatives",
        choices=NEGATIVE_MODES,
        default="error",
        help="how to treat negative driver values (default: error)",
    )
    dist.add_argument("--out", help="write result CSV here instead of printing")

    alloc = sub.add_parser(
        "allocate",
        help=(
            "allocate cost lines (CSV: cost,amount,driver) along drivers "
            "(CSV: driver,object,value)"
        ),
    )
    alloc.add_argument("--costs", required=True, help="costs CSV file")
    alloc.add_argument("--drivers", required=True, help="drivers CSV file")
    alloc.add_argument("--precision", type=int, default=2, help="amount decimals (default 2)")
    alloc.add_argument(
        "--negatives",
        choices=NEGATIVE_MODES,
        default="error",
        help="how to treat negative driver values (default: error)",
    )
    alloc.add_argument("--out", help="write result CSV here instead of printing")
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
    drivers = read_drivers(args.drivers, negatives=args.negatives)
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
    drivers = read_drivers(args.drivers, negatives=args.negatives)
    costs = read_costs(args.costs)
    rows = allocate_costs(costs, drivers, precision=args.precision)
    if args.out:
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
    except (ValueError, KeyError, OSError) as error:
        message = error.args[0] if error.args else error
        print(f"error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
