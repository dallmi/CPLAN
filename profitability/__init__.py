"""Profitability: percentage distributions and exact cost allocation."""

from .allocation import (
    AllocationRow,
    CostLine,
    allocate,
    allocate_costs,
    resolve_driver,
)
from .distribution import Distribution

__all__ = [
    "AllocationRow",
    "CostLine",
    "Distribution",
    "allocate",
    "allocate_costs",
    "resolve_driver",
]

__version__ = "0.1.0"
