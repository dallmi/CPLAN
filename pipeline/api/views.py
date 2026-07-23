"""Read-only Postgres SQL views for ad-hoc analysis via pgAdmin.

Postgres-only by design: their entire purpose is to give pgAdmin users
ready-made analysis (`cplan -> Schemas -> public -> Views`) without
restructuring how the data is stored. SQLite users already have the
studio's own analytics (`pipeline/studio/analytics.js`); `ensure_analysis_views`
is a clean no-op on that dialect.

Idempotency: every view is (re)created with `CREATE OR REPLACE VIEW`, so this
runs safely on every app startup, including against a database that already
has all views current. A view renamed or removed from `ANALYSIS_VIEWS` in a
later version is *not* dropped from an existing database by this function --
stale views are left behind (accepted trade-off; `DROP VIEW` is a manual
pgAdmin/psql step if cleanup is ever wanted). `CREATE OR REPLACE VIEW` itself
also cannot reorder, rename or drop an existing view's columns -- only append
new ones at the end -- so a future edit that does any of those needs an
explicit `DROP VIEW` before this function's next run recreates it.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

# name -> SELECT body (no trailing semicolon). Every view name is prefixed
# `v_`. Columns are verified against the current ORM models in
# `pipeline/api/app.py` (Activity, SyncRun, ActivityChange) -- nothing here
# is invented.
ANALYSIS_VIEWS: dict[str, str] = {
    "v_activity_overview": """
        -- The working set for ad-hoc filtering: one row per activity, the
        -- columns most commonly filtered/sorted on in pgAdmin.
        SELECT
            id,
            tracking_id,
            activity_name,
            source_type,
            channel,
            priority,
            start_date,
            end_date,
            lead,
            lead_team,
            campaign,
            is_archive,
            version,
            updated_at
        FROM activities
    """,
    "v_activities_by_month": """
        -- Volume by calendar month and source.
        SELECT
            date_trunc('month', start_date) AS month,
            source_type,
            count(*) AS count
        FROM activities
        GROUP BY date_trunc('month', start_date), source_type
    """,
    "v_activities_by_channel": """
        -- Volume by channel and source; activities without a channel are
        -- grouped under 'Unassigned' rather than dropped.
        SELECT
            coalesce(channel, 'Unassigned') AS channel,
            source_type,
            count(*) AS count
        FROM activities
        GROUP BY coalesce(channel, 'Unassigned'), source_type
    """,
    "v_planning_completeness": """
        -- Mirrors REQUIRED_FIELDS in pipeline/studio/analytics.js (Task 7):
        -- activity_name, start_date, channel, lead_team (lead_team OR lead),
        -- target_audience, priority, strategic_objectives, activity_description.
        -- A field is "missing" when NULL or an empty/whitespace-only string
        -- (no such concept for the start_date timestamp -- missing means NULL
        -- there). activity_name is required at write time and is not flagged
        -- here; lead_team is only missing when both lead_team and lead are
        -- empty (either one satisfies the requirement). is_complete is the
        -- AND of all seven "not missing" checks below.
        WITH flagged AS (
            SELECT
                id,
                tracking_id,
                activity_name,
                (activity_description IS NULL OR trim(activity_description) = '') AS missing_description,
                (channel IS NULL OR trim(channel) = '') AS missing_channel,
                (priority IS NULL OR trim(priority) = '') AS missing_priority,
                (target_audience IS NULL OR trim(target_audience) = '') AS missing_target_audience,
                (
                    (lead_team IS NULL OR trim(lead_team) = '')
                    AND (lead IS NULL OR trim(lead) = '')
                ) AS missing_lead_team,
                (start_date IS NULL) AS missing_start_date,
                (strategic_objectives IS NULL OR trim(strategic_objectives) = '') AS missing_pillars
            FROM activities
        )
        SELECT
            id,
            tracking_id,
            activity_name,
            missing_description,
            missing_channel,
            missing_priority,
            missing_target_audience,
            missing_lead_team,
            missing_start_date,
            missing_pillars,
            NOT (
                missing_description
                OR missing_channel
                OR missing_priority
                OR missing_target_audience
                OR missing_lead_team
                OR missing_start_date
                OR missing_pillars
            ) AS is_complete
        FROM flagged
    """,
    "v_lead_times": """
        -- Matches ActivityRead.planning_lead_days in pipeline/api/app.py:
        -- whole days between start_date and coalesce(source_created_at,
        -- created_at). NULL start_date propagates to a NULL lead_days,
        -- same as the API returning None. Rounding note: Postgres numeric
        -- round() rounds an exact half-day away from zero, while Python's
        -- round() rounds it to the nearest even integer -- the two can
        -- disagree by one day only in that exact-.5 edge case.
        SELECT
            id,
            tracking_id,
            activity_name,
            start_date,
            coalesce(source_created_at, created_at) AS reference,
            round(
                (
                    extract(epoch FROM (start_date - coalesce(source_created_at, created_at))) / 86400
                )::numeric
            )::integer AS lead_days
        FROM activities
    """,
    "v_pack_overview": """
        -- pack_id is the CLUSTER-PACKNUM prefix of tracking_id (its first two
        -- '-'-separated segments), matching ActivityRead.tracking_pack_id.
        SELECT
            split_part(tracking_id, '-', 1) || '-' || split_part(tracking_id, '-', 2) AS pack_id,
            count(*) AS activity_count,
            min(start_date) AS earliest_start_date,
            max(start_date) AS latest_start_date,
            count(DISTINCT channel) AS channel_count
        FROM activities
        GROUP BY split_part(tracking_id, '-', 1) || '-' || split_part(tracking_id, '-', 2)
    """,
    "v_sync_history": """
        -- One row per pipeline/api/sync_snapshot.py run.
        SELECT
            ran_at,
            created,
            updated,
            unchanged,
            conflicts,
            vanished,
            local_only,
            skipped_no_id
        FROM sync_runs
    """,
    "v_change_log": """
        -- Every field-level change, joined to its activity for context.
        -- Newest-first ordering is left to the consumer's own ORDER BY,
        -- not baked into the view.
        SELECT
            ac.changed_at,
            ac.actor,
            ac.change_type,
            ac.field,
            ac.old_value,
            ac.new_value,
            a.tracking_id,
            a.activity_name
        FROM activity_changes ac
        JOIN activities a ON ac.activity_id = a.id
    """,
}


def ensure_analysis_views(engine: Engine) -> None:
    """Create/refresh every view in `ANALYSIS_VIEWS`; a clean no-op on non-Postgres engines.

    Intended to run in the app lifespan right after `ensure_schema` on every
    startup. All views are (re)created in a single transaction via `CREATE OR
    REPLACE VIEW`, so a failure partway through leaves none of them changed.
    """
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        for name, select_body in ANALYSIS_VIEWS.items():
            connection.execute(text(f"CREATE OR REPLACE VIEW {name} AS {select_body}"))
