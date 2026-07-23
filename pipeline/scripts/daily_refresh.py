#!/usr/bin/env python3
"""Daily workflow glue: run the CSV pipeline, then sync its output into the CPLAN database.

One command for the daily refresh:
  1. `process_cplan.main()` reads the SharePoint CSV export and writes
     `pipeline/output/communications.parquet`.
  2. `sync_snapshot.sync_parquet()` upserts that parquet into the CPLAN database:
     source wins, conflicts are recorded, nothing is ever deleted (binding policy —
     see `pipeline/api/sync_snapshot.py`).

Activities created directly in the studio (no `legacy_sp_id`) are never touched by the
sync and keep running alongside the mirrored SharePoint rows — parallel operation until
the corp system migrates onto CPLAN.

Usage:
    python -m pipeline.scripts.daily_refresh                  # pipeline + sync
    python -m pipeline.scripts.daily_refresh --skip-pipeline  # sync only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from pipeline.api.import_snapshot import resolve_database_url
from pipeline.api.setup_backend import default_settings_path
from pipeline.api.sync_snapshot import SyncReport, format_report, sync_parquet

PIPELINE_DIR = Path(__file__).resolve().parent.parent  # pipeline/scripts/ -> pipeline/
DEFAULT_PARQUET = PIPELINE_DIR / "output" / "communications.parquet"


def _banner(title: str) -> None:
    print()
    print(f"=== {title} ===")


def _default_pipeline_main() -> Callable[[], None]:
    """Lazily resolve `process_cplan.main`.

    Kept as its own function (rather than inlined into `run_pipeline_step`) purely so
    tests can monkeypatch just this import step to simulate a missing dependency,
    deterministically, regardless of whether `pandas`/`duckdb` actually happen to be
    installed in the environment running the test.
    """
    from pipeline.scripts.process_cplan import main as pipeline_main

    return pipeline_main


def run_pipeline_step(pipeline_main: Callable[[], None] | None = None) -> bool:
    """Run the snapshot pipeline's `main()` in-process. Returns True on success.

    `pipeline_main` defaults to `process_cplan.main`, resolved lazily via
    `_default_pipeline_main()` rather than at module scope: `process_cplan.py`
    requires `pandas`/`duckdb`, which are not installed in the lean, API-only
    environment this module also needs to import into (e.g. a `--skip-pipeline`-only
    sync run, or this module's own tests) — an eager import would make `daily_refresh`
    itself require those packages just to parse `--skip-pipeline`. If that import
    fails, it is caught here and turned into an actionable message — naming the
    missing dependency, the install command, and the `--skip-pipeline` alternative —
    instead of a bare traceback; the command then exits nonzero before the sync step
    runs, same as any other pipeline failure.

    `process_cplan.main()` reads its own flags (`--preview`, `--full-refresh`) straight
    off `sys.argv` and calls `sys.exit(1)` when no input CSVs are found. `sys.argv` is
    swapped to just the program name for the duration of the call so daily_refresh's
    own arguments (e.g. `--skip-pipeline`) can never be misread as a process_cplan
    flag; the resulting `SystemExit` is caught here instead of tearing down the whole
    command.
    """
    if pipeline_main is None:
        try:
            pipeline_main = _default_pipeline_main()
        except ImportError as exc:
            missing = exc.name or str(exc)
            print(f"Cannot run the snapshot pipeline: missing dependency '{missing}'.")
            print("Install the pipeline dependencies with: pip install pandas duckdb pyarrow")
            print("Or run with --skip-pipeline to sync the existing parquet snapshot only.")
            return False

    _banner("Step 1/2 - Snapshot pipeline (process_cplan)")
    original_argv = sys.argv
    sys.argv = original_argv[:1]
    try:
        pipeline_main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code != 0:
            print(f"Snapshot pipeline failed (exit code {code}); skipping database sync.")
            return False
    finally:
        sys.argv = original_argv
    return True


def run_sync_step(settings_path: Path, parquet_path: Path) -> SyncReport:
    _banner("Step 2/2 - Database sync (sync_snapshot)")
    database_url = resolve_database_url(settings_path)
    report = sync_parquet(database_url, parquet_path)
    print(format_report(report))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Skip the CSV pipeline step and sync the existing parquet snapshot only.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.skip_pipeline:
        print("Skipping snapshot pipeline (--skip-pipeline); syncing the existing parquet snapshot only.")
    elif not run_pipeline_step():
        sys.exit(1)

    run_sync_step(args.settings, args.parquet)
    print()
    print("Daily refresh complete.")


if __name__ == "__main__":
    main()
