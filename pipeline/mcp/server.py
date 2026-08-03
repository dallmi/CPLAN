"""Read-only MCP server over the CPLAN planning database (stdio transport).

Run it directly for a manual check, or point an MCP host at it:

    python -m pipeline.mcp.server [--settings PATH]

The database is resolved exactly as `pipeline/scripts/start_cplan.py` resolves
it, so the server always reads whatever backend the studio is configured
against -- and it needs no running API server, because it talks to the database
directly through a connection that refuses writes (see `engine.py`).

stdout belongs to the JSON-RPC transport. Nothing here may print to it; all
diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp.server import MCPServer  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from pipeline.api.setup_backend import (  # noqa: E402
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)
from pipeline.mcp import queries  # noqa: E402
from pipeline.mcp.engine import create_read_only_engine, verify_schema  # noqa: E402

INSTRUCTIONS = """\
CPLAN holds the communication activity plan: one row per planned communication
activity, each with a channel, a priority, an owning lead/lead team, a start and
end date, and a tracking id of the form CLUSTER-PACKNUM-....

Read-only. Start with database_status to learn the size and date range of the
plan. Before filtering on a free-text value (channel, priority, region, ...),
call field_values -- those columns are not enumerations and invented values
return nothing. Use search_activities to narrow down, then get_activity for the
full record of a single activity. planning_gaps answers "what is not ready yet"
using the same completeness rule the studio shows.
"""


def build_server(database_url: str) -> MCPServer:
    engine = create_read_only_engine(database_url)
    # Fail at startup, not on the third tool call: a read-only server cannot run
    # the API's ensure_schema top-up, so an outdated database has to be named
    # plainly before the host ever connects.
    verify_schema(engine)
    server = MCPServer(
        name="cplan",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )

    def read(handler):
        with Session(engine) as session:
            return handler(session)

    @server.tool()
    def database_status() -> dict[str, Any]:
        """Size, date range and freshness of the communication plan.

        Call this first: it reports how many activities exist, how they split
        across internal/external, the planned date range, and when the last
        sync from the source system ran.
        """
        return read(lambda session: queries.database_status(session, engine))

    @server.tool()
    def field_values(field: str, limit: int | None = None) -> dict[str, Any]:
        """Distinct stored values of a filter column, with row counts.

        Use before filtering: channel, priority, region and the rest are free
        text, not enumerations, so a guessed value silently matches nothing.
        Supported fields: channel, priority, source_type, lead_team, lead,
        region, business_division, campaign.
        """
        return read(lambda session: queries.field_values(session, field=field, limit=limit))

    @server.tool()
    def search_activities(
        query: str | None = None,
        channel: str | None = None,
        source_type: str | None = None,
        priority: str | None = None,
        lead: str | None = None,
        campaign: str | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Find activities by text and/or filters; returns compact summaries.

        `query` matches the activity name, tracking id and description
        case-insensitively. `start_after`/`start_before` take 'YYYY-MM-DD' or a
        full ISO timestamp and filter on start_date. `source_type` is 'internal'
        or 'external'. Archived activities are excluded unless asked for.

        Returns at most 50 rows by default (200 hard cap) plus the true match
        count, so a broad search reports its own truncation instead of filling
        the context. Use get_activity for the full record of one row.
        """
        return read(
            lambda session: queries.search_activities(
                session,
                query=query,
                channel=channel,
                source_type=source_type,
                priority=priority,
                lead=lead,
                campaign=campaign,
                start_after=start_after,
                start_before=start_before,
                include_archived=include_archived,
                limit=limit,
            )
        )

    @server.tool()
    def get_activity(identifier: str) -> dict[str, Any]:
        """Full record of one activity, by tracking id or UUID.

        Includes every stored field plus the derived planning_lead_days (days
        between creation and start), tracking_pack_id, and the list of required
        fields still missing.
        """
        return read(lambda session: queries.get_activity(session, identifier))

    @server.tool()
    def planning_gaps(
        source_type: str | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Activities that are not fully planned yet, worst first.

        Applies the studio's completeness rule: every activity needs name,
        description, channel, priority, strategic objectives, region, start and
        end date, time zone, lead and lead team; internal activities also need
        target audience, audience and business division. Returns per-activity
        missing fields plus a tally of which fields are missing most often.
        """
        return read(
            lambda session: queries.planning_gaps(
                session,
                source_type=source_type,
                start_after=start_after,
                start_before=start_before,
                include_archived=include_archived,
                limit=limit,
            )
        )

    @server.tool()
    def activity_counts(
        dimension: str,
        source_type: str | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        """Activity volume grouped by one dimension.

        dimension is one of: channel, priority, source_type, lead_team, lead,
        region, business_division, campaign, month. 'month' buckets by
        start_date as 'YYYY-MM' ('unscheduled' when the date is missing);
        rows with no value for the other dimensions are grouped as
        'Unassigned' rather than dropped.
        """
        return read(
            lambda session: queries.activity_counts(
                session,
                dimension=dimension,
                source_type=source_type,
                start_after=start_after,
                start_before=start_before,
                include_archived=include_archived,
            )
        )

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_backend_config(args.settings or default_settings_path())
    database_url = resolve_backend_database_url(config)
    server = build_server(database_url)
    print(f"cplan MCP server ready ({config.backend}, read-only)", file=sys.stderr)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
