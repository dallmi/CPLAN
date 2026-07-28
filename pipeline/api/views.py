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
        -- Variant-aware completeness, mirroring analytics.js
        -- planningCompleteness() -- the single studio/dashboard authority since
        -- the completeness unification, so is_complete here matches exactly
        -- what the studio shows for the same row (readiness badge, Drafts KPI,
        -- filter, create/edit drawer).
        --
        -- Every activity needs the 11 common fields (activity_name, channel,
        -- priority, strategic_objectives, activity_description, region,
        -- start_date, end_date, time_zone, lead, lead_team). Internal
        -- activities additionally need target_audience, audience and
        -- business_division; those internal-only flags are always false for
        -- external rows (not required there). lead and lead_team are BOTH
        -- required -- no either-satisfies shortcut.
        --
        -- A text field is "missing" when NULL, empty/whitespace-only, or the
        -- literal string 'None'/'null' (mirroring analytics.js empty(), which
        -- guards against Python str(None) leaking in from the sync). Date
        -- fields (start_date, end_date) are missing only when NULL.
        -- activity_name is NOT NULL at write time so its flag is always false,
        -- kept for a faithful mirror. is_complete is the AND of every
        -- applicable "not missing" check below.
        WITH flagged AS (
            SELECT
                id,
                tracking_id,
                activity_name,
                source_type,
                (activity_name IS NULL OR trim(activity_name) = '' OR activity_name IN ('None', 'null')) AS missing_activity_name,
                (activity_description IS NULL OR trim(activity_description) = '' OR activity_description IN ('None', 'null')) AS missing_description,
                (channel IS NULL OR trim(channel) = '' OR channel IN ('None', 'null')) AS missing_channel,
                (priority IS NULL OR trim(priority) = '' OR priority IN ('None', 'null')) AS missing_priority,
                (strategic_objectives IS NULL OR trim(strategic_objectives) = '' OR strategic_objectives IN ('None', 'null')) AS missing_pillars,
                (region IS NULL OR trim(region) = '' OR region IN ('None', 'null')) AS missing_region,
                (start_date IS NULL) AS missing_start_date,
                (end_date IS NULL) AS missing_end_date,
                (time_zone IS NULL OR trim(time_zone) = '' OR time_zone IN ('None', 'null')) AS missing_time_zone,
                (lead IS NULL OR trim(lead) = '' OR lead IN ('None', 'null')) AS missing_lead,
                (lead_team IS NULL OR trim(lead_team) = '' OR lead_team IN ('None', 'null')) AS missing_lead_team,
                (source_type = 'internal' AND (target_audience IS NULL OR trim(target_audience) = '' OR target_audience IN ('None', 'null'))) AS missing_target_audience,
                (source_type = 'internal' AND (audience IS NULL OR trim(audience) = '' OR audience IN ('None', 'null'))) AS missing_audience,
                (source_type = 'internal' AND (business_division IS NULL OR trim(business_division) = '' OR business_division IN ('None', 'null'))) AS missing_business_division
            FROM activities
        )
        SELECT
            id,
            tracking_id,
            activity_name,
            source_type,
            missing_activity_name,
            missing_description,
            missing_channel,
            missing_priority,
            missing_pillars,
            missing_region,
            missing_start_date,
            missing_end_date,
            missing_time_zone,
            missing_lead,
            missing_lead_team,
            missing_target_audience,
            missing_audience,
            missing_business_division,
            NOT (
                missing_activity_name
                OR missing_description
                OR missing_channel
                OR missing_priority
                OR missing_pillars
                OR missing_region
                OR missing_start_date
                OR missing_end_date
                OR missing_time_zone
                OR missing_lead
                OR missing_lead_team
                OR missing_target_audience
                OR missing_audience
                OR missing_business_division
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
