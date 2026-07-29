"""Generate a synthetic activity dataset for local development and UX testing.

The Parquet snapshot importer (`pipeline.api.import_snapshot`) seeds from real
exported data. This script fills the same table with generated records instead,
so the studio can be exercised without any export at hand.

The generated set is deliberately *not* clean. Analytics and data-quality views
can only be verified against data that contains the things they are supposed to
find, so the generator plants a known number of defects and gaps and prints
what it planted. Treat that printout as the expected result of every view.

All content is organisation-neutral and synthetic: generic division, region and
audience names, no personal names, no production identifiers.

Usage:
    python pipeline/scripts/generate_seed.py --replace
    python pipeline/scripts/generate_seed.py --count 600 --seed 7 --replace
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.orm import Session

from pipeline.api.app import Activity, ActivityChange, Base, create_app
from pipeline.api.import_snapshot import normalize_record
from pipeline.api.setup_backend import (
    default_settings_path,
    load_backend_config,
    resolve_backend_database_url,
)


CHANNELS = ["Intranet", "Email", "Town Hall", "Digital Signage", "Manager Cascade", "Podcast"]
DIVISIONS = ["P&C", "GWM", "IB", "Group Functions"]
REGIONS = ["EMEA", "Americas", "APAC", "Switzerland"]
AUDIENCES = ["All Employees", "Managers", "Frontline Staff", "Technology Staff", "New Joiners"]
OBJECTIVES = ["Growth", "Efficiency", "Culture", "Risk & Control", "Client Focus"]
PRIORITIES = ["Low", "Medium", "High"]
TEAMS = ["Team A", "Team B", "Team C", "Team D"]
CAMPAIGNS = ["Digital Shift", "Culture 2026", "Service Excellence", "Way We Work"]

TOPICS = [
    "Leadership update", "Policy change", "System migration", "Town hall invitation",
    "Benefits update", "Security reminder", "Quarterly results", "Office move",
    "Training rollout", "Process simplification", "Recognition programme", "Survey launch",
]

# Categories that must stay empty so "white spaces" views have something to
# report. Nothing is ever generated for these.
#
# These are invisible to the studio: it builds its category lists from the data,
# so a value that was never used cannot be missed. They document the blind spot
# rather than test it.
EMPTY_REGION = "Switzerland"
EMPTY_AUDIENCE = "New Joiners"
EMPTY_CHANNEL = "Podcast"

# The case the coverage view *can* catch, and the realistic one: a category that
# the organisation used in the past but has nothing planned for. It exists in
# the portfolio, so it appears in the category list — at zero.
PAST_ONLY_AUDIENCE = "Frontline Staff"
PAST_ONLY_CHANNEL = "Digital Signage"


def _tracking_id(source_type: str, index: int, start: datetime, channel: str) -> str:
    prefix = "IC" if source_type == "internal" else "EC"
    return f"{prefix}-{start.year}-{index:04d}-{channel[:2].upper()}"


def build_records(count: int, seed: int, today: datetime) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    records: list[dict] = []
    planted = {
        "ohne_beschreibung": 0,
        "ohne_pack": 0,
        "kurzfristig": 0,
        "tracking_id_ungueltig": 0,
        "ohne_zielgruppe": 0,
    }

    regions = [r for r in REGIONS if r != EMPTY_REGION]
    audiences = [a for a in AUDIENCES if a != EMPTY_AUDIENCE]
    channels = [c for c in CHANNELS if c != EMPTY_CHANNEL]

    # Six months back, three months forward, so time series, "next 30 days" and
    # forward-load views all have something to show.
    first = today - timedelta(days=182)
    span = 182 + 92

    for index in range(1, count + 1):
        source_type = "internal" if rng.random() < 0.65 else "external"
        start = first + timedelta(days=rng.randrange(span), hours=rng.randrange(7, 18))
        end = start + timedelta(hours=rng.choice([1, 2, 4, 8, 24]))
        channel = rng.choice(channels)
        audience = rng.choice(audiences)

        # Keep the two retired categories strictly in the past, so the coverage
        # view lists them at zero instead of dropping them.
        if audience == PAST_ONLY_AUDIENCE or channel == PAST_ONLY_CHANNEL:
            start = first + timedelta(days=rng.randrange(0, 150), hours=rng.randrange(7, 18))
            end = start + timedelta(hours=rng.choice([1, 2, 4]))

        # Lead time: most healthy, a known slice deliberately short.
        if rng.random() < 0.18:
            created = start - timedelta(days=rng.randrange(0, 7))
            planted["kurzfristig"] += 1
        else:
            created = start - timedelta(days=rng.randrange(14, 70))

        pack = None
        campaign = None
        if rng.random() < 0.6:
            campaign = rng.choice(CAMPAIGNS)
            pack = f"CP-{CAMPAIGNS.index(campaign) + 1:02d}-{rng.randrange(1, 9):03d}"
        else:
            planted["ohne_pack"] += 1

        description = f"{rng.choice(TOPICS)} for {audience.lower()} across {rng.choice(regions)}."
        if rng.random() < 0.22:
            description = None
            planted["ohne_beschreibung"] += 1

        target_audience = audience
        if rng.random() < 0.08:
            target_audience = None
            planted["ohne_zielgruppe"] += 1

        records.append({
            "source_type": source_type,
            "tracking_id": _tracking_id(source_type, index, start, channel),
            "activity_name": f"{rng.choice(TOPICS)} {index}",
            "activity_description": description,
            "target_audience": target_audience,
            "business_division": rng.choice(DIVISIONS),
            "region": rng.choice(regions),
            "channel": channel,
            "lead_team": rng.choice(TEAMS),
            "lead": rng.choice(TEAMS),
            "start_date": start,
            "end_date": end,
            "priority": rng.choice(PRIORITIES),
            "strategic_objectives": rng.choice(OBJECTIVES),
            "campaign": campaign,
            "communication_pack_cpid": pack,
            "audience": str(rng.choice([250, 800, 1500, 4200, 12000])),
            "news_digest": rng.random() < 0.3 if source_type == "internal" else None,
            "time_zone": "Europe/Zurich",
            "source_created_at": created,
            "source_modified_at": created,
            "is_archive": False,
        })

    # Planted tracking-ID defects, so the data-quality view has exact targets.
    #
    # No duplicate is planted: activities.tracking_id carries a UNIQUE
    # constraint, so duplicates cannot exist in the first place. A view that
    # hunts for them would always report zero and give false reassurance —
    # the guarantee belongs in the schema documentation, not in a report.
    # (SQLite still permits several NULLs, so "missing" remains a real case.)
    if len(records) >= 6:
        records[4]["tracking_id"] = "not-a-tracking-id"
        records[5]["tracking_id"] = None
        planted["tracking_id_ungueltig"] = 2

    return records, planted


def write(database_url, records: list[dict], replace: bool) -> int:
    app = create_app(database_url)
    engine = app.state.engine
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if replace:
            session.query(ActivityChange).delete()
            session.query(Activity).delete()
            session.commit()
        activities, changes = [], []
        for record in records:
            activity_id = uuid.uuid4()
            # time_zone is a column on Activity but not in the importer's
            # ALLOWED_FIELDS, so normalize_record drops it silently. Set it
            # afterwards, otherwise every generated row counts as incomplete.
            time_zone = record.pop("time_zone", None)
            activities.append(
                Activity(
                    id=activity_id,
                    **normalize_record(record),
                    time_zone=time_zone,
                    created_by="generate_seed",
                )
            )
            changes.append(
                ActivityChange(activity_id=activity_id, actor="seed", change_type="created", version_to=1)
            )
        session.add_all(activities)
        session.add_all(changes)
        session.commit()
        return len(activities)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--seed", type=int, default=1, help="fixed, so runs are reproducible")
    parser.add_argument("--replace", action="store_true", help="delete existing activities first")
    parser.add_argument("--today", type=str, default=None, help="ISO date; defaults to now")
    args = parser.parse_args()

    today = datetime.fromisoformat(args.today) if args.today else datetime.now()
    records, planted = build_records(args.count, args.seed, today)

    config = load_backend_config(args.settings)
    written = write(resolve_backend_database_url(config), records, args.replace)

    print(f"{written} activities written (seed={args.seed}, today={today.date()})")
    print("Planted defects — every one of these must show up in the views:")
    for key, value in planted.items():
        print(f"  {key:24} {value}")

    # Counted from the finished records, not tallied while generating, and split
    # the way the studio splits it: target_audience is only required on internal
    # activities (analytics.js REQUIRED_INTERNAL), so the studio will report the
    # internal figure, not the total. Printing both stops the two numbers from
    # looking like a bug when they differ.
    #
    # These counts are valid for THIS run only. Changing any of the value lists
    # above shifts the random stream, so numbers printed by an earlier run do
    # not describe the current database.
    def _blank(field):
        return [r for r in records if not str(r.get(field) or "").strip()]

    print("Counted from the written records, comparable with the studio:")
    print(f"  activity_description     {len(_blank('activity_description'))}")
    internal_blank = [r for r in _blank("target_audience") if r["source_type"] == "internal"]
    print(f"  target_audience          {len(_blank('target_audience'))}"
          f"  (davon intern und damit pflichtig: {len(internal_blank)})")
    print("Used in the past, nothing planned — coverage must list these at zero:")
    print(f"  target_audience          {PAST_ONLY_AUDIENCE}")
    print(f"  channel                  {PAST_ONLY_CHANNEL}")
    print("Never used at all — invisible to the studio by construction:")
    print(f"  region                   {EMPTY_REGION}")
    print(f"  target_audience          {EMPTY_AUDIENCE}")
    print(f"  channel                  {EMPTY_CHANNEL}")


if __name__ == "__main__":
    main()
