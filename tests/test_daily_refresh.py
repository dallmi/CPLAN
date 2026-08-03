"""Smoke tests for pipeline/scripts/daily_refresh.py.

`process_cplan.py` (the pipeline step) requires `pandas`/`duckdb`, which are not
installed in this lean, API-only test environment — `daily_refresh.run_pipeline_step`
therefore takes its pipeline callable as an injectable argument (defaulting to a
lazy import of the real `process_cplan.main` only when actually invoked for real).
These tests always pass a stub in, so no real CSV processing ever happens here.
"""

import sys

import pytest

import pipeline.scripts.daily_refresh as daily_refresh
from pipeline.api.sync_snapshot import SyncReport


def _stub_sync(monkeypatch, calls):
    def fake_resolve_database_url(settings_path):
        calls.append(("resolve_database_url", settings_path))
        return "sqlite:///:memory:"

    def fake_sync_parquet(database_url, parquet_path):
        calls.append(("sync_parquet", database_url, parquet_path))
        return SyncReport(created=1)

    def fake_run_standalone_step(settings_path):
        calls.append("standalone")
        return True

    monkeypatch.setattr(daily_refresh, "resolve_database_url", fake_resolve_database_url)
    monkeypatch.setattr(daily_refresh, "sync_parquet", fake_sync_parquet)
    monkeypatch.setattr(daily_refresh, "run_standalone_step", fake_run_standalone_step)


# --- argument parsing --------------------------------------------------------


def test_default_flags_run_the_full_pipeline_and_sync():
    args = daily_refresh.build_parser().parse_args([])

    assert args.skip_pipeline is False
    assert args.settings == daily_refresh.default_settings_path()
    assert args.parquet == daily_refresh.DEFAULT_PARQUET


def test_skip_pipeline_flag_is_parsed():
    args = daily_refresh.build_parser().parse_args(["--skip-pipeline"])

    assert args.skip_pipeline is True


def test_settings_and_parquet_overrides_are_parsed(tmp_path):
    settings_path = tmp_path / "custom-settings.json"
    parquet_path = tmp_path / "custom.parquet"

    args = daily_refresh.build_parser().parse_args(
        ["--settings", str(settings_path), "--parquet", str(parquet_path)]
    )

    assert args.settings == settings_path
    assert args.parquet == parquet_path


# --- run_pipeline_step orchestration -----------------------------------------


def test_run_pipeline_step_isolates_sys_argv_from_the_pipeline_main(monkeypatch):
    observed_argv = []

    def fake_main():
        observed_argv.append(list(sys.argv))

    monkeypatch.setattr(sys, "argv", ["daily_refresh.py", "--skip-pipeline", "--settings", "x"])

    result = daily_refresh.run_pipeline_step(fake_main)

    assert result is True
    # The injected pipeline main only ever saw its own program name, never
    # daily_refresh's own flags.
    assert observed_argv == [["daily_refresh.py"]]
    # sys.argv is restored once the step returns.
    assert sys.argv == ["daily_refresh.py", "--skip-pipeline", "--settings", "x"]


def test_run_pipeline_step_restores_sys_argv_even_when_the_pipeline_main_raises(monkeypatch):
    def fake_main():
        raise SystemExit(1)

    monkeypatch.setattr(sys, "argv", ["daily_refresh.py", "--skip-pipeline"])

    daily_refresh.run_pipeline_step(fake_main)

    assert sys.argv == ["daily_refresh.py", "--skip-pipeline"]


def test_run_pipeline_step_returns_false_on_nonzero_systemexit():
    def fake_main():
        raise SystemExit(1)

    assert daily_refresh.run_pipeline_step(fake_main) is False


def test_run_pipeline_step_returns_true_on_systemexit_zero():
    def fake_main():
        raise SystemExit(0)

    assert daily_refresh.run_pipeline_step(fake_main) is True


def test_run_pipeline_step_returns_true_on_normal_completion():
    # process_cplan.main() only calls sys.exit() on the "no input files" error path;
    # a normal successful run returns None and that must count as success too.
    calls = []

    def fake_main():
        calls.append("pipeline")

    assert daily_refresh.run_pipeline_step(fake_main) is True
    assert calls == ["pipeline"]


def test_run_pipeline_step_reports_missing_dependency_instead_of_raising(monkeypatch, capsys):
    # process_cplan.py requires pandas/duckdb, absent from this lean, API-only
    # environment. Simulated via the import-resolution seam (_default_pipeline_main)
    # rather than relying on this environment actually lacking the packages, so the
    # test stays deterministic either way.
    def fake_default_pipeline_main():
        raise ModuleNotFoundError("No module named 'duckdb'", name="duckdb")

    monkeypatch.setattr(daily_refresh, "_default_pipeline_main", fake_default_pipeline_main)

    result = daily_refresh.run_pipeline_step()

    assert result is False
    output = capsys.readouterr().out
    assert "missing dependency" in output
    assert "duckdb" in output
    assert "pip install pandas duckdb pyarrow" in output
    assert "--skip-pipeline" in output


# --- run_sync_step ------------------------------------------------------------


def test_run_sync_step_uses_resolved_database_url_and_given_parquet_path(monkeypatch, tmp_path):
    calls = []
    _stub_sync(monkeypatch, calls)
    settings_path = tmp_path / "settings.json"
    parquet_path = tmp_path / "communications.parquet"

    report = daily_refresh.run_sync_step(settings_path, parquet_path)

    assert calls == [
        ("resolve_database_url", settings_path),
        ("sync_parquet", "sqlite:///:memory:", parquet_path),
    ]
    assert report.created == 1


# --- main() end-to-end orchestration ------------------------------------------


def test_main_runs_pipeline_then_sync_in_order(monkeypatch):
    calls = []
    _stub_sync(monkeypatch, calls)

    def fake_run_pipeline_step():
        calls.append("pipeline")
        return True

    monkeypatch.setattr(daily_refresh, "run_pipeline_step", fake_run_pipeline_step)

    daily_refresh.main([])

    call_names = [c if isinstance(c, str) else c[0] for c in calls]
    assert call_names == ["pipeline", "resolve_database_url", "sync_parquet", "standalone"]


def test_main_skip_pipeline_only_runs_sync(monkeypatch):
    calls = []
    _stub_sync(monkeypatch, calls)

    def fail_if_called():
        raise AssertionError("pipeline step must not run with --skip-pipeline")

    monkeypatch.setattr(daily_refresh, "run_pipeline_step", fail_if_called)

    daily_refresh.main(["--skip-pipeline"])

    call_names = [c if isinstance(c, str) else c[0] for c in calls]
    assert call_names == ["resolve_database_url", "sync_parquet", "standalone"]


def test_main_stops_before_sync_and_exits_nonzero_when_pipeline_step_fails(monkeypatch):
    calls = []
    _stub_sync(monkeypatch, calls)
    monkeypatch.setattr(daily_refresh, "run_pipeline_step", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        daily_refresh.main([])

    assert exc_info.value.code == 1
    assert calls == []  # sync never invoked


def test_main_reports_missing_dependency_and_stops_before_sync(monkeypatch, capsys):
    # End-to-end: a missing pandas/duckdb install must exit the whole command
    # nonzero, with an actionable message, and never reach the sync step.
    calls = []
    _stub_sync(monkeypatch, calls)

    def fake_default_pipeline_main():
        raise ModuleNotFoundError("No module named 'duckdb'", name="duckdb")

    monkeypatch.setattr(daily_refresh, "_default_pipeline_main", fake_default_pipeline_main)

    with pytest.raises(SystemExit) as exc_info:
        daily_refresh.main([])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "missing dependency" in output
    assert "duckdb" in output
    assert "pip install pandas duckdb pyarrow" in output
    assert "--skip-pipeline" in output
    assert calls == []  # sync never invoked


# --- the standalone export step -----------------------------------------------


def test_skip_standalone_leaves_the_export_out(monkeypatch):
    calls = []
    _stub_sync(monkeypatch, calls)
    monkeypatch.setattr(daily_refresh, "run_pipeline_step", lambda: calls.append("pipeline") or True)

    daily_refresh.main(["--skip-standalone"])

    call_names = [c if isinstance(c, str) else c[0] for c in calls]
    assert call_names == ["pipeline", "resolve_database_url", "sync_parquet"]


def test_a_failing_export_does_not_make_a_successful_refresh_look_failed(monkeypatch, capsys, tmp_path):
    """The asymmetry that makes step 3 safe to add to the daily run.

    The refresh's job is done once the database is current. A locked output file
    or a read-only directory must therefore be reported and survived, not turned
    into a nonzero exit that sends somebody hunting for a sync problem that isn't
    there. Run on its own the build still fails loudly — there the file is the
    point.
    """
    def explode(database_url, out_path):
        raise PermissionError("output file is open in another program")

    monkeypatch.setattr(daily_refresh, "resolve_database_url", lambda _: "sqlite:///:memory:")
    monkeypatch.setattr(
        "pipeline.scripts.build_studio_standalone.build", explode, raising=True
    )

    ok = daily_refresh.run_standalone_step(tmp_path / "settings.json")

    assert ok is False
    output = capsys.readouterr().out
    assert "Standalone export skipped" in output
    assert "open in another program" in output
    # Names the way out, so the message is actionable rather than merely honest.
    assert "python -m pipeline.scripts.build_studio_standalone" in output
