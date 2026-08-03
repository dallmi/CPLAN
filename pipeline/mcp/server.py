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
from pipeline.mcp.domain import domain_model  # noqa: E402
from pipeline.mcp.engine import create_read_only_engine, verify_schema  # noqa: E402

INSTRUCTIONS = """\
CPLAN holds the communication activity plan: one row per planned communication
activity, each with a channel, a priority, an owning lead/lead team, a start and
end date, and a tracking id of the form CLUSTER-PACKNUM-....

Read-only, and planning only -- there is no performance, reach or engagement data
here. Say so plainly rather than approximating it from planning fields.

READ THE `cplan://domain-model` RESOURCE FIRST. It carries five properties of this
data that otherwise produce confidently wrong answers: priority runs on two
different vocabularies at once, archived does not mean irrelevant, the filter
columns are free text rather than enumerations, three columns hold several values
in one string, and the audience column is an unverified size band.

Then: database_status for size and freshness, field_values before filtering on any
free-text value, search_activities to narrow, get_activity for one full record,
planning_gaps for what is not ready yet, activity_counts for volumes. Every list
answer is capped and reports its own truncation -- narrow the filters instead of
raising the limit.
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

    @server.resource(
        "cplan://domain-model",
        name="CPLAN domain model",
        description=(
            "The planning domain model, both priority vocabularies, the archive "
            "semantics, the multi-value columns and the completeness rule. Read "
            "before answering anything quantitative."
        ),
        mime_type="text/markdown",
    )
    def cplan_domain_model() -> str:
        return domain_model()

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

    @server.tool(
        description=(
            "Distinct stored values of a filter column, with row counts.\n\n"
            "Use before filtering: channel, priority, region and the rest are "
            "free text, not enumerations, so a guessed value silently matches "
            "nothing. Counts include archived rows, so a value occurring only on "
            "archived activities is still discoverable. Multi-value columns are "
            "split into their individual members rather than listed as "
            "combinations.\n\n"
            f"Supported fields: {', '.join(queries.ENUMERABLE_FIELDS)}."
        )
    )
    def field_values(field: str, limit: int | None = None) -> dict[str, Any]:
        return read(lambda session: queries.field_values(session, field=field, limit=limit))

    @server.tool()
    def search_activities(
        query: str | None = None,
        channel: str | None = None,
        source_type: str | None = None,
        priority: str | None = None,
        min_priority_rank: int | None = None,
        lead: str | None = None,
        lead_team: str | None = None,
        partner_team: str | None = None,
        campaign: str | None = None,
        region: str | None = None,
        business_division: str | None = None,
        business_area: str | None = None,
        target_audience: str | None = None,
        audience: str | None = None,
        time_zone: str | None = None,
        strategic_objective: str | None = None,
        executive: str | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        end_after: str | None = None,
        end_before: str | None = None,
        max_lead_days: int | None = None,
        news_digest: bool | None = None,
        has_tracking_id: bool | None = None,
        locally_modified: bool | None = None,
        include_archived: bool = False,
        archived_only: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Find activities by text and/or filters; returns compact summaries.

        `query` matches the activity name, tracking id and description
        case-insensitively. Every other text filter is case-insensitive equality
        on a free-text column -- call field_values first, because a guessed value
        matches nothing and returns zero.

        Priority: two vocabularies are live at once (studio words, and numbered
        source labels where 1 is most urgent), so prefer `min_priority_rank`
        (0-4, higher is more urgent; 3 means "critical and high") over `priority`.

        `strategic_objective` and `executive` match one member of a multi-valued
        column; `executive` searches both executive columns.

        Windows: `start_after`/`start_before` filter start_date,
        `end_after`/`end_before` filter end_date; both take 'YYYY-MM-DD' or a
        full ISO timestamp. `max_lead_days` finds short-notice activities (days
        between creation and start).

        Archived activities are excluded unless `include_archived`; archiving is a
        source-system view-size workaround, not a relevance signal, so a true
        total needs `include_archived=True`. `archived_only` inspects just those.

        Returns at most 50 rows by default (200 hard cap) plus the true match
        count, so a broad search reports its own truncation instead of filling the
        context. Use get_activity for the full record of one row.
        """
        return read(
            lambda session: queries.search_activities(
                session,
                query=query,
                channel=channel,
                source_type=source_type,
                priority=priority,
                min_priority_rank=min_priority_rank,
                lead=lead,
                lead_team=lead_team,
                partner_team=partner_team,
                campaign=campaign,
                region=region,
                business_division=business_division,
                business_area=business_area,
                target_audience=target_audience,
                audience=audience,
                time_zone=time_zone,
                strategic_objective=strategic_objective,
                executive=executive,
                start_after=start_after,
                start_before=start_before,
                end_after=end_after,
                end_before=end_before,
                max_lead_days=max_lead_days,
                news_digest=news_digest,
                has_tracking_id=has_tracking_id,
                locally_modified=locally_modified,
                include_archived=include_archived,
                archived_only=archived_only,
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
        lead_team: str | None = None,
        lead: str | None = None,
        channel: str | None = None,
        region: str | None = None,
        business_division: str | None = None,
        campaign: str | None = None,
        min_priority_rank: int | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        group_by: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Activities that are not fully planned yet, worst first.

        Applies the studio's completeness rule: every activity needs name,
        description, channel, priority, strategic objectives, region, start and
        end date, time zone, lead and lead team; internal activities also need
        target audience, audience and business division. Both lead and lead_team
        are required -- there is no either-satisfies shortcut.

        Narrow it like a search: `min_priority_rank=3` finds the urgent gaps,
        `lead_team=` scopes it to one team. `group_by` (any enumerable column,
        e.g. lead_team) additionally reports complete/incomplete per group, worst
        group first -- that is how to answer "which team is behind" rather than
        "which records are incomplete".

        Returns per-activity missing fields plus a tally of which fields are
        missing most often. Pack/campaign linkage is deliberately NOT part of
        completeness: a standalone activity with no pack is fully planned.

        There is no `executive` filter here: to find incomplete executive
        activities, call search_activities with `executive=` to find them, then
        get_activity on each match to read `missing_required_fields` --
        search_activities' own rows are compact summaries and do not carry that
        field.
        """
        return read(
            lambda session: queries.planning_gaps(
                session,
                source_type=source_type,
                lead_team=lead_team,
                lead=lead,
                channel=channel,
                region=region,
                business_division=business_division,
                campaign=campaign,
                min_priority_rank=min_priority_rank,
                start_after=start_after,
                start_before=start_before,
                group_by=group_by,
                include_archived=include_archived,
                limit=limit,
            )
        )

    @server.tool()
    def activity_counts(
        dimension: str,
        source_type: str | None = None,
        channel: str | None = None,
        lead_team: str | None = None,
        region: str | None = None,
        business_division: str | None = None,
        campaign: str | None = None,
        min_priority_rank: int | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        """Activity volume grouped by one dimension, with optional filters.

        dimension is any filterable column, plus 'month', 'priority_rank', and
        the multi-value columns. 'month' buckets by start_date as 'YYYY-MM'
        ('unscheduled' when missing); rows with no value are grouped as
        'Unassigned' rather than dropped.

        Use 'priority_rank' rather than 'priority': two vocabularies are live at
        once (studio words, and numbered source labels where 1 is most urgent),
        so grouping the raw labels splits the same urgency across two spellings.
        Rank runs 0-4, higher is more urgent.

        Grouping a multi-value column (strategic_objectives, the executive
        columns) tallies individual members, so the total counts memberships and
        can exceed the activity count -- `counts_memberships` says when.
        """
        return read(
            lambda session: queries.activity_counts(
                session,
                dimension=dimension,
                source_type=source_type,
                channel=channel,
                lead_team=lead_team,
                region=region,
                business_division=business_division,
                campaign=campaign,
                min_priority_rank=min_priority_rank,
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
