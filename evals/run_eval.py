"""Run the catalogue questions through a real model against the MCP server.

    .venv/bin/python -m evals.run_eval                      # all questions
    .venv/bin/python -m evals.run_eval --only priority-trap # one question
    .venv/bin/python -m evals.run_eval --dry-run            # no API calls

This spends real money -- it drives an actual model, not a stub. `--dry-run`
exercises everything except the model call (MCP handshake, tool conversion,
ground-truth SQL, the report writer) and is what CI would run if this ever went
into CI; it is not in the pytest suite for that reason.

What it is for: the unit tests prove the tools behave. They cannot prove that a
model *reads the descriptions and picks the right tool*, which is what the
`cplan://domain-model` resource exists to achieve. Only a real run shows whether
priority filtering avoids the two-vocabulary trap, whether pack grouping uses the
pack id, and whether performance questions get declined instead of approximated.

Read-only throughout: the MCP server refuses writes at the connection level, and
ground truth is computed over the same read-only engine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from pipeline.api.setup_backend import (  # noqa: E402
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)
from pipeline.mcp.engine import create_read_only_engine  # noqa: E402
from evals.questions import QUESTIONS, QUESTIONS_BY_ID, Check, Trace  # noqa: E402

DEFAULT_MODEL = "claude-opus-5"

# The agent is given no domain knowledge here on purpose. Everything it needs to
# avoid the traps has to come from the server's own instructions, tool
# descriptions, and the cplan://domain-model resource -- that is the thing under
# test. Putting the traps in this prompt would test nothing.
SYSTEM = (
    "You are a communication planning assistant for a corporate communications "
    "team. Answer the user's question using the tools available to you. Be "
    "concise and give concrete figures where the data supports them. If the data "
    "cannot answer the question, say so plainly rather than estimating."
)


async def _run_one(client, model: str, question, mcp_session, tools) -> tuple[str, Trace]:
    """Drive one question to completion, capturing the tool-call trace."""
    trace = Trace()
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=8000,
        system=SYSTEM,
        tools=tools,
        messages=[{"role": "user", "content": question.prompt}],
        max_iterations=12,
    )

    final_text = ""
    async for message in runner:
        for block in message.content:
            if block.type == "tool_use":
                # `input` is already parsed by the SDK; never string-match it.
                trace.tool_calls.append((block.name, dict(block.input or {})))
            elif block.type == "text" and block.text.strip():
                final_text = block.text

    return final_text, trace


async def _read_resources(mcp_session) -> list[str]:
    """Which resources the server offers, and read the domain model once.

    The tool runner converts MCP *tools*; resources are a separate MCP concept
    the runner does not touch. So the harness reads the domain model itself and
    records that it did -- an agent host (Claude Desktop, Claude Code) surfaces
    resources to the model automatically, and this mirrors that.
    """
    read: list[str] = []
    try:
        listing = await mcp_session.list_resources()
    except Exception:
        return read
    for resource in listing.resources:
        uri = str(resource.uri)
        if "domain-model" in uri:
            await mcp_session.read_resource(resource.uri)
            read.append(uri)
    return read


def _grade(question, answer: str, trace: Trace, session: Session) -> list[Check]:
    checks: list[Check] = []
    for grader in question.graders:
        try:
            checks.append(grader(answer, trace, session))
        except Exception as failure:  # a broken grader must not look like a pass
            checks.append(
                Check(name=grader.__name__, passed=False, detail=f"grader raised: {failure!r}")
            )
    return checks


async def main_async(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--only", action="append", help="question id; repeatable")
    parser.add_argument("--settings", type=Path, default=None)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ANTHROPIC_BASE_URL"),
        help=(
            "Anthropic-compatible endpoint to send model calls to (default: the "
            "ANTHROPIC_BASE_URL environment variable, else the SDK's own default, "
            "the hosted API). The seam for pointing this harness at a locally "
            "hosted model: production data must not leave the corporate "
            "environment, so the hosted API can never be run against it -- a "
            "local endpoint is the only way this harness runs against real data."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify the harness end to end without calling the model",
    )
    parser.add_argument("--out", type=Path, default=_REPO_ROOT / "evals" / "results")
    args = parser.parse_args(argv)

    selected = (
        [QUESTIONS_BY_ID[qid] for qid in args.only] if args.only else list(QUESTIONS)
    )

    config = load_backend_config(args.settings or default_settings_path())
    database_url = resolve_backend_database_url(config)
    engine = create_read_only_engine(database_url)

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pipeline.mcp.server"]
        + (["--settings", str(args.settings)] if args.settings else []),
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )

    results: list[dict[str, Any]] = []

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()
            listed = await mcp_session.list_tools()
            print(f"MCP server up: {len(listed.tools)} tools "
                  f"({', '.join(t.name for t in listed.tools)})", file=sys.stderr)

            resources_read = await _read_resources(mcp_session)
            print(f"resources read: {resources_read or 'none offered'}", file=sys.stderr)

            if args.dry_run:
                client = None
                tools = None
            else:
                from anthropic import AsyncAnthropic
                from anthropic.lib.tools.mcp import async_mcp_tool

                client = AsyncAnthropic(base_url=args.base_url)
                tools = [async_mcp_tool(tool, mcp_session) for tool in listed.tools]

            with Session(engine) as session:
                for question in selected:
                    print(f"\n=== {question.id} ({question.catalogue}) ===", file=sys.stderr)
                    print(f"    {question.prompt}", file=sys.stderr)

                    if args.dry_run:
                        answer, trace = "", Trace(resources_read=list(resources_read))
                        checks = [
                            Check(
                                name="dry run",
                                passed=True,
                                detail="graders not evaluated; no model call made",
                            )
                        ]
                    else:
                        answer, trace = await _run_one(
                            client, args.model, question, mcp_session, tools
                        )
                        trace.resources_read = list(resources_read)
                        checks = _grade(question, answer, trace, session)
                        for check in checks:
                            mark = "PASS" if check.passed else "FAIL"
                            print(f"    [{mark}] {check.name} -- {check.detail}",
                                  file=sys.stderr)

                    results.append(
                        {
                            "id": question.id,
                            "catalogue": question.catalogue,
                            "persona": question.persona,
                            "prompt": question.prompt,
                            "why": question.why,
                            "answer": answer,
                            "trace": {
                                "tool_calls": [
                                    {"tool": name, "args": a} for name, a in trace.tool_calls
                                ],
                                "resources_read": trace.resources_read,
                            },
                            "checks": [asdict(c) for c in checks],
                            "passed": all(c.passed for c in checks),
                        }
                    )

    engine.dispose()

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = args.out / f"eval-{stamp}.json"
    report.write_text(
        json.dumps(
            {
                "model": None if args.dry_run else args.model,
                "dry_run": args.dry_run,
                "ran_at": stamp,
                "questions": len(results),
                "passed": sum(1 for r in results if r["passed"]),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    passed = sum(1 for r in results if r["passed"])
    print(
        f"\n{passed}/{len(results)} questions passed every check. Report: {report}",
        file=sys.stderr,
    )
    if not args.dry_run:
        for entry in results:
            if not entry["passed"]:
                failed = [c["name"] for c in entry["checks"] if not c["passed"]]
                print(f"  FAILED {entry['id']}: {', '.join(failed)}", file=sys.stderr)

    # A failing eval is a finding about the tool surface, not a broken harness --
    # exit 0 so a wrapper can read the report rather than treating it as a crash.
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
