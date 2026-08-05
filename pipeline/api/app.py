"""Local database API for CPLAN Studio."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence, get_args
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, Uuid, delete as sqlalchemy_delete, func, select, text, update
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .auth import (
    AuthSettings,
    auth_settings_from_environment,
    create_session_token,
    verify_credentials,
)
from .database import backend_from_url, create_cplan_engine, database_url_from_environment, ensure_schema
from .session import CurrentUser, build_session_dependencies
from .views import ensure_analysis_views


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def stringify_change_value(value: Any) -> str | None:
    """Render a field value for storage in `ActivityChange.old_value`/`new_value`.

    Shared by every writer (create, patch, sync, seed) so history entries are
    stringified identically regardless of which code path wrote them: `None`
    stays `NULL` (not the string `"None"`), datetimes render as UTC ISO with a
    trailing `Z` (matching `ActivityRead`'s own JSON serialization), booleans
    render as the lowercase JSON-style literal (`'true'`/`'false'`, not
    Python's `str(bool)` capitalization), everything else via plain `str()`.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = as_utc(value)
        return normalized.isoformat().replace("+00:00", "Z") if normalized else None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _optional_str_field_names(model_fields: dict[str, Any]) -> set[str]:
    """Names of fields declared as `str | None` (i.e. optional strings).

    `activity_name` is excluded even though `ActivityPatch` types it as
    `str | None` (to allow omission on PATCH) — its `min_length=1` constraint
    must keep rejecting an explicit empty string rather than have it
    silently normalized to `None`.
    """
    names = set()
    for name, field in model_fields.items():
        if name == "activity_name":
            continue
        args = get_args(field.annotation)
        if str in args and type(None) in args:
            names.add(name)
    return names


def normalize_blank_strings(cls: type[BaseModel], data: Any) -> Any:
    """Model-validator body: turn ""/whitespace-only input into None for optional str fields.

    Shared by ActivityCreate and ActivityPatch so blank-string input (e.g. a
    PATCH clearing a field via `"channel": ""`) is treated the same as an
    explicit `null`, and stored as NULL rather than an empty string.
    """
    if not isinstance(data, dict):
        return data
    optional_str_fields = _optional_str_field_names(cls.model_fields)
    for key, value in data.items():
        if key in optional_str_fields and isinstance(value, str) and value.strip() == "":
            data[key] = None
    return data


class Base(DeclarativeBase):
    pass


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        # Tracking IDs must be unique among studio-generated rows (legacy_sp_id IS NULL).
        # Legacy-imported rows (legacy_sp_id set) are exempt: the source system
        # genuinely contains duplicate tracking IDs, so a table-wide unique
        # constraint would break import_snapshot seeding.
        Index(
            "ix_activities_tracking_id_v6_unique",
            "tracking_id",
            unique=True,
            sqlite_where=text("legacy_sp_id IS NULL"),
            postgresql_where=text("legacy_sp_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    legacy_sp_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    tracking_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    activity_name: Mapped[str] = mapped_column(String(500), nullable=False)
    activity_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    extended_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_division: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_area: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    partner_team: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_team: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    news_digest: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    priority: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategic_objectives: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign_ltid: Mapped[str | None] = mapped_column(Text, nullable=True)
    communication_pack_cpid: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Holds GEB *and* GEB-1 level people, mixed, with no level marker -- the
    # column name is the source's, not a claim about who is on it. Labelled
    # "GEB/GEB-1" everywhere it is shown.
    bod_geb: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The source's separate "other executives" field -- counted separately
    # everywhere, and not the complement of bod_geb.
    other_executives: Mapped[str | None] = mapped_column(Text, nullable=True)
    communication_pack: Mapped[str | None] = mapped_column(Text, nullable=True)
    communication_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who/what created this row: "studio" for API-created rows (Task 5 switches
    # this to the logged-in username), "cplan_sync" for mirrored/seeded rows.
    # Never settable by clients -- absent from ActivityCreate/Fields/Patch.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Set to `version` after every sync write (insert or update) by sync_snapshot.py;
    # never touched by the UI PATCH endpoint. NULL means "never synced" (either a
    # studio-created row, or a legacy row imported before this column existed). A row is
    # locally dirty iff `version > synced_version` — see sync_snapshot.py.
    synced_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SyncRun(Base):
    """One row per `sync_snapshot.py` run: counts + a capped JSON detail blob.

    Never written by the UI or the import_snapshot one-time seeder — only by the
    daily sync job. `GET /api/sync-runs/latest` reads the most recent row.
    """

    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Both a Python-side default (used by every ORM insert, so `GET
    # /api/sync-runs/latest` can order by it with microsecond resolution — SQLite's
    # CURRENT_TIMESTAMP, which server_default=func.now() renders to, only has
    # second-level precision and would tie two same-second runs) and a server
    # default (so a row inserted outside the ORM still gets a sensible timestamp).
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    snapshot_path: Mapped[str] = mapped_column(Text, nullable=False)
    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflicts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vanished: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    local_only: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_no_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)


def serialize_sync_run(run: "SyncRun | None") -> dict[str, Any]:
    """The wire shape of a sync run, for `GET /api/sync-runs/latest`.

    Module-level rather than inline in the endpoint because the standalone
    snapshot build (`pipeline/scripts/build_studio_standalone.py`) embeds the
    same value for the same studio code to render. Two hand-written shapes for
    one payload would drift the first time a counter is added here.

    `None` means no sync has ever run — reported as a status, not an error, so
    the studio's reconciliation card can tell "never synced" apart from
    "could not ask".
    """
    if run is None:
        return {"status": "never_synced"}
    return {
        "ran_at": as_utc(run.ran_at).isoformat().replace("+00:00", "Z"),
        "snapshot_path": run.snapshot_path,
        "created": run.created,
        "updated": run.updated,
        "unchanged": run.unchanged,
        "conflicts": run.conflicts,
        "vanished": run.vanished,
        "local_only": run.local_only,
        "skipped_no_id": run.skipped_no_id,
        "details": json.loads(run.details) if run.details else None,
    }


class ActivityChange(Base):
    """One row per field-level change, written in the same transaction as the
    data change it records: a `created` row (one per activity, `field` NULL)
    from `POST /api/activities` (actor `studio`), `import_snapshot.seed_records`
    (actor `seed`), and new mirror rows in `sync_snapshot` (actor `sync`); one
    `updated` row per changed field from `PATCH /api/activities/{id}` (actor
    `studio`) and from mirror updates in `sync_snapshot` (actor `sync`).

    No FK constraint to `activities.id` — kept delete-free and SQLite-friendly,
    matching this codebase's existing preference (see `Activity.legacy_sp_id`)
    for plain indexed columns over enforced relationships.
    """

    __tablename__ = "activity_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_to: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ActivityFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["internal", "external"]
    legacy_sp_id: int | None = None
    activity_name: str = Field(min_length=1, max_length=500)
    activity_description: str | None = None
    target_audience: str | None = None
    extended_audience: str | None = None
    business_division: str | None = None
    business_area: str | None = None
    region: str | None = None
    channel: str | None = None
    partner_team: str | None = None
    lead_team: str | None = None
    lead: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    time_zone: str | None = None
    news_digest: bool | None = None
    priority: str | None = None
    strategic_objectives: str | None = None
    campaign: str | None = None
    campaign_ltid: str | None = None
    communication_pack_cpid: str | None = None
    bod_geb: str | None = None
    other_executives: str | None = None
    communication_pack: str | None = None
    communication_ref: str | None = None
    author: str | None = None
    author_email: str | None = None
    audience: str | None = None
    source_created_at: datetime | None = None
    source_modified_at: datetime | None = None
    is_archive: bool = False


class ActivityCreate(ActivityFields):
    @model_validator(mode="before")
    @classmethod
    def normalize_blank_strings_before_validation(cls, data: Any) -> Any:
        return normalize_blank_strings(cls, data)

    @model_validator(mode="after")
    def validate_dates(self):
        # Input-side rule only: read models must describe persisted data, not
        # police it, so this stays on ActivityCreate rather than the shared
        # ActivityFields base (ActivityRead no longer inherits it — see
        # ActivityRead below, and PATCH enforces its own resulting-values
        # checks directly in the route).
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        if self.source_type == "external" and self.news_digest is not None:
            raise ValueError("news_digest is only valid for internal activities")
        return self

    @field_validator("start_date", "end_date", "source_created_at", "source_modified_at")
    @classmethod
    def normalize_datetime_to_utc(cls, value: datetime | None):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime values must include a timezone offset")
        return value.astimezone(timezone.utc)


class ActivityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    activity_name: str | None = Field(default=None, min_length=1, max_length=500)
    activity_description: str | None = None
    target_audience: str | None = None
    extended_audience: str | None = None
    business_division: str | None = None
    business_area: str | None = None
    region: str | None = None
    channel: str | None = None
    partner_team: str | None = None
    lead_team: str | None = None
    lead: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    time_zone: str | None = None
    news_digest: bool | None = None
    priority: str | None = None
    strategic_objectives: str | None = None
    campaign: str | None = None
    campaign_ltid: str | None = None
    communication_pack_cpid: str | None = None
    bod_geb: str | None = None
    other_executives: str | None = None
    communication_pack: str | None = None
    communication_ref: str | None = None
    audience: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_blank_strings_before_validation(cls, data: Any) -> Any:
        return normalize_blank_strings(cls, data)

    @field_validator("activity_name")
    @classmethod
    def require_activity_name_when_supplied(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("activity_name cannot be null")
        return value

    @field_validator("start_date", "end_date")
    @classmethod
    def normalize_datetime_to_utc(cls, value: datetime | None):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime values must include a timezone offset")
        return value.astimezone(timezone.utc)


class ActivityRead(ActivityFields):
    model_config = ConfigDict(from_attributes=True)

    # Relax the input-side constraints inherited from ActivityFields: this is a
    # read model describing persisted data, not policing it. Legacy rows
    # (e.g. inserted directly via import_snapshot's ORM path, bypassing
    # pydantic) may carry an empty activity_name or a value/length that
    # would never pass create/patch validation, and SQLite does not enforce
    # column lengths at all — such rows must still serialize with a 200
    # instead of 500ing the whole GET /api/activities response.
    activity_name: str
    id: uuid.UUID
    tracking_id: str | None = None
    version: int
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "start_date", "end_date", "source_created_at", "source_modified_at", "created_at", "updated_at",
        when_used="json",
    )
    def serialize_datetime(self, value: datetime | None):
        if value is None:
            return None
        return as_utc(value).isoformat().replace("+00:00", "Z")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def planning_lead_days(self) -> int | None:
        """Whole days between the reference timestamp and `start_date`.

        `reference` is `source_created_at` when set, else `created_at`.
        Negative values are returned as-is (a start date before the
        reference) — analytics consumers exclude them themselves.
        """
        if self.start_date is None:
            return None
        reference = self.source_created_at or self.created_at
        delta = self.start_date - reference
        return round(delta.total_seconds() / 86400)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tracking_pack_id(self) -> str | None:
        """The cluster/pack portion of `tracking_id` (its first two `-`-separated parts)."""
        if not self.tracking_id:
            return None
        parts = self.tracking_id.split("-")
        if len(parts) < 2:
            return None
        return f"{parts[0]}-{parts[1]}"


class ActivityList(BaseModel):
    items: list[ActivityRead]
    total: int


class ActivityBatchCreate(BaseModel):
    items: list[ActivityCreate] = Field(min_length=1, max_length=50)


class ActivityChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: uuid.UUID
    changed_at: datetime
    actor: str
    change_type: str
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    version_from: int | None = None
    version_to: int | None = None

    @field_serializer("changed_at", when_used="json")
    def serialize_changed_at(self, value: datetime):
        return as_utc(value).isoformat().replace("+00:00", "Z")


class ActivityChangeList(BaseModel):
    items: list[ActivityChangeRead]
    total: int


ZURICH = ZoneInfo("Europe/Zurich")
STANDALONE_PACK_PREFIX = "STA-0000000"
_CPID_PATTERN = re.compile(r"^[A-Z0-9]+-[0-9]+$")
MAX_TRACKING_ID_GENERATION_ATTEMPTS = 10_000
MAX_TRACKING_ID_COMMIT_RETRIES = 5


def _pack_prefix(communication_pack_cpid: str | None) -> str:
    if communication_pack_cpid and _CPID_PATTERN.match(communication_pack_cpid):
        return communication_pack_cpid
    return STANDALONE_PACK_PREFIX


def _next_activity_number(existing_tracking_ids: Sequence[str]) -> int:
    max_number = 0
    for tracking_id in existing_tracking_ids:
        parts = tracking_id.split("-")
        if len(parts) >= 4 and parts[3].isdigit():
            max_number = max(max_number, int(parts[3]))
    return max_number + 1


def _channel_abbr(channel: str | None, existing: Sequence[tuple[str | None, str]]) -> str:
    if not channel or not channel.strip():
        return "GEN"
    votes: Counter[str] = Counter()
    for existing_channel, tracking_id in existing:
        if existing_channel != channel:
            continue
        parts = tracking_id.split("-")
        if len(parts) == 5:
            votes[parts[4]] += 1
    if votes:
        return votes.most_common(1)[0][0]
    alphabetic = "".join(char for char in channel if char.isalpha())
    abbr = alphabetic[:3].upper()
    # The format contract requires 2-4 letters; a channel with fewer than 2
    # alphabetic characters (e.g. "5G") falls back to the generic abbreviation.
    return abbr if len(abbr) >= 2 else "GEN"


def generate_tracking_id(
    existing: Sequence[tuple[str | None, str]],
    *,
    communication_pack_cpid: str | None,
    start_date: datetime | None,
    channel: str | None,
) -> str:
    """Build the next server-generated tracking ID.

    `existing` holds the `(channel, tracking_id)` pairs of every activity
    that already carries a tracking_id — used both to derive the next
    activity number (across all pack prefixes) and the per-channel
    abbreviation majority vote. Pure/unit-testable without a database.
    """
    pack_prefix = _pack_prefix(communication_pack_cpid)
    reference = start_date.astimezone(ZURICH) if start_date else datetime.now(ZURICH)
    date_part = reference.strftime("%y%m%d")
    activity_number = _next_activity_number([tracking_id for _, tracking_id in existing])
    channel_abbr = _channel_abbr(channel, existing)
    return f"{pack_prefix}-{date_part}-{activity_number:07d}-{channel_abbr}"


def _increment_activity_number(tracking_id: str) -> str:
    parts = tracking_id.split("-")
    parts[3] = f"{int(parts[3]) + 1:07d}"
    return "-".join(parts)


def _generate_unique_tracking_id(session: Session, payload: ActivityCreate) -> str:
    """Fast-path uniqueness check: read-then-check against the current session's view.

    This narrows the odds of a collision but cannot fully close a race between
    two concurrent requests (both can pass this SELECT before either commits).
    The `ix_activities_tracking_id_v6_unique` partial unique index is the real
    guarantee; `create_activity` catches the resulting `IntegrityError` and
    retries with an incremented activity number as the concurrency backstop.
    """
    existing = [
        (channel, tracking_id)
        for channel, tracking_id in session.execute(
            select(Activity.channel, Activity.tracking_id).where(Activity.tracking_id.isnot(None))
        ).all()
    ]
    tracking_id = generate_tracking_id(
        existing,
        communication_pack_cpid=payload.communication_pack_cpid,
        start_date=payload.start_date,
        channel=payload.channel,
    )
    attempts = 0
    while session.scalar(select(Activity.id).where(Activity.tracking_id == tracking_id)) is not None:
        attempts += 1
        if attempts > MAX_TRACKING_ID_GENERATION_ATTEMPTS:
            raise HTTPException(status_code=500, detail={"code": "tracking_id_generation_exhausted"})
        tracking_id = _increment_activity_number(tracking_id)
    return tracking_id


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=63)  # Postgres identifier limit
    password: str


def create_app(database_url: str | URL | None = None, auth_settings: AuthSettings | None = None) -> FastAPI:
    resolved_url = database_url or os.environ.get("CPLAN_DATABASE_URL")
    if not resolved_url:
        raise RuntimeError(
            "CPLAN database is not configured; use setup_backend or set CPLAN_DATABASE_URL"
        )
    backend = backend_from_url(resolved_url)
    engine = create_cplan_engine(resolved_url)

    auth = auth_settings if auth_settings is not None else auth_settings_from_environment()
    if backend != "postgresql":
        auth = None  # roles are Postgres-only; SQLite stays the solo-mode fallback

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        ensure_schema(engine, Base.metadata)
        ensure_analysis_views(engine)
        yield
        engine.dispose()

    app = FastAPI(title="CPLAN Studio API", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine

    current_user, db_session = build_session_dependencies(engine, auth)

    @app.exception_handler(ProgrammingError)
    async def insufficient_privilege_handler(request: Request, exc: ProgrammingError):
        if getattr(exc.orig, "sqlstate", None) == "42501":
            return JSONResponse(status_code=403, content={"detail": {"code": "forbidden"}})
        raise exc

    @app.post("/api/login")
    def login(payload: LoginPayload, response: Response):
        if auth is None:
            return {"username": "studio"}
        if not verify_credentials(resolved_url, payload.username, payload.password):
            raise HTTPException(status_code=401, detail={"code": "invalid_credentials"})
        response.set_cookie(
            auth.cookie_name,
            create_session_token(auth, payload.username),
            max_age=auth.max_age_seconds,
            httponly=True,
            samesite="lax",
        )
        return {"username": payload.username}

    @app.post("/api/logout")
    def logout(response: Response):
        if auth is not None:
            response.delete_cookie(auth.cookie_name)
        return {"status": "ok"}

    @app.get("/api/me")
    def me(user: CurrentUser = Depends(current_user), session: Session = Depends(db_session)):
        if user.db_role is None:
            return {"username": user.username, "role": "editor", "auth": False}
        flags = session.execute(
            text(
                "SELECT pg_has_role(current_user, 'cplan_admin', 'member') AS is_admin, "
                "pg_has_role(current_user, 'cplan_editor', 'member') AS is_editor, "
                "pg_has_role(current_user, 'cplan_contributor', 'member') AS is_contributor"
            )
        ).one()
        role = (
            "admin" if flags.is_admin
            else "editor" if flags.is_editor
            else "contributor" if flags.is_contributor
            else "viewer"
        )
        return {"username": user.username, "role": role, "auth": True}

    @app.get("/api/health")
    def health():
        with Session(engine) as session:
            session.execute(select(1))
        return {"status": "ok", "database": backend}

    @app.post("/api/activities", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
    def create_activity(
        payload: ActivityCreate,
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        tracking_id = _generate_unique_tracking_id(session, payload)
        activity_fields = payload.model_dump()
        attempts = 0
        while True:
            # Generated explicitly (rather than relying on the column's
            # Python-side default, which SQLAlchemy only populates onto the
            # instance at flush time) so the id is known up front to link
            # the ActivityChange row -- there is no FK, so both rows must
            # be added to the same session/transaction before either is
            # committed, and both are discarded together on a tracking-id
            # collision retry.
            activity_id = uuid.uuid4()
            activity = Activity(
                id=activity_id, **activity_fields, tracking_id=tracking_id, created_by=user.username
            )
            session.add(activity)
            session.add(
                ActivityChange(
                    activity_id=activity_id,
                    actor=user.username,
                    change_type="created",
                    version_to=1,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                # Concurrency backstop: another request committed the same
                # tracking_id after our fast-path SELECT check passed.
                session.rollback()
                attempts += 1
                if attempts > MAX_TRACKING_ID_COMMIT_RETRIES:
                    raise HTTPException(
                        status_code=500, detail={"code": "tracking_id_generation_exhausted"}
                    )
                tracking_id = _increment_activity_number(tracking_id)
                continue
            session.refresh(activity)
            return activity

    @app.post("/api/activities/batch", response_model=ActivityList, status_code=status.HTTP_201_CREATED)
    def create_activities_batch(
        payload: ActivityBatchCreate,
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        """Create a communication pack's activities in one atomic transaction.

        Tracking IDs are generated sequentially inside the batch: each
        generated (channel, tracking_id) pair is appended to `existing`
        before the next item is processed, so activity numbers within the
        pack are consecutive and cannot collide with each other.
        """
        commit_attempts = 0
        while True:
            existing = [
                (channel, tracking_id)
                for channel, tracking_id in session.execute(
                    select(Activity.channel, Activity.tracking_id).where(Activity.tracking_id.isnot(None))
                ).all()
            ]
            created: list[Activity] = []
            for item in payload.items:
                tracking_id = generate_tracking_id(
                    existing,
                    communication_pack_cpid=item.communication_pack_cpid,
                    start_date=item.start_date,
                    channel=item.channel,
                )
                taken = {existing_tracking_id for _, existing_tracking_id in existing}
                generation_attempts = 0
                while (
                    tracking_id in taken
                    or session.scalar(select(Activity.id).where(Activity.tracking_id == tracking_id))
                    is not None
                ):
                    generation_attempts += 1
                    if generation_attempts > MAX_TRACKING_ID_GENERATION_ATTEMPTS:
                        raise HTTPException(
                            status_code=500, detail={"code": "tracking_id_generation_exhausted"}
                        )
                    tracking_id = _increment_activity_number(tracking_id)
                existing.append((item.channel, tracking_id))
                activity_id = uuid.uuid4()
                activity = Activity(
                    id=activity_id, **item.model_dump(), tracking_id=tracking_id, created_by=user.username
                )
                session.add(activity)
                session.add(
                    ActivityChange(
                        activity_id=activity_id,
                        actor=user.username,
                        change_type="created",
                        version_to=1,
                    )
                )
                created.append(activity)
            try:
                session.commit()
            except IntegrityError:
                # Concurrency backstop mirroring create_activity: a
                # concurrent request committed one of our tracking_ids
                # after the fast-path SELECT passed. All-or-nothing:
                # roll back the whole batch and regenerate every ID.
                session.rollback()
                commit_attempts += 1
                if commit_attempts > MAX_TRACKING_ID_COMMIT_RETRIES:
                    raise HTTPException(
                        status_code=500, detail={"code": "tracking_id_generation_exhausted"}
                    )
                continue
            for activity in created:
                session.refresh(activity)
            return {"items": created, "total": len(created)}

    @app.get("/api/activities", response_model=ActivityList)
    def list_activities(
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        items = list(session.scalars(select(Activity).order_by(Activity.start_date, Activity.id)))
        return {"items": items, "total": len(items)}

    @app.patch("/api/activities/{activity_id}", response_model=ActivityRead)
    def update_activity(
        activity_id: uuid.UUID,
        payload: ActivityPatch,
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        values = payload.model_dump(exclude={"version"}, exclude_unset=True)
        current = session.get(Activity, activity_id)
        if current is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        if current.version != payload.version:
            raise HTTPException(
                status_code=409,
                detail={"code": "version_conflict", "expected_version": payload.version},
            )

        if user.db_role is not None:
            may_edit_all = session.execute(
                text(
                    "SELECT pg_has_role(current_user, 'cplan_editor', 'member') "
                    "OR pg_has_role(current_user, 'cplan_admin', 'member')"
                )
            ).scalar_one()
            if not may_edit_all and current.created_by != user.username:
                raise HTTPException(status_code=403, detail={"code": "forbidden_not_owner"})

        # Only re-validate the resulting date range when the patch itself
        # touches a date field. A legacy row can already carry
        # end_date < start_date (import_snapshot inserts via the ORM,
        # bypassing this validation); an unrelated edit — e.g. channel
        # only — must not be blocked by a pre-existing invalid range it
        # never asked to change.
        if "start_date" in values or "end_date" in values:
            resulting_start = as_utc(values.get("start_date", current.start_date))
            resulting_end = as_utc(values.get("end_date", current.end_date))
        else:
            resulting_start = resulting_end = None
        if resulting_start and resulting_end and resulting_end < resulting_start:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_date_range", "message": "end_date cannot be before start_date"},
            )
        resulting_news_digest = values.get("news_digest", current.news_digest)
        if current.source_type == "external" and resulting_news_digest is not None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_source_field",
                    "message": "news_digest is only valid for internal activities",
                },
            )

        # Captured before "version"/"updated_at" bookkeeping is added to
        # `values` below: one ActivityChange row per key the client actually
        # patched (exclude_unset), not per field that happens to differ --
        # this is a UI edit trail, not a diff report (contrast with
        # sync_snapshot's writer, which reuses its existing diffing since
        # it always applies every mirrored field regardless of whether the
        # source changed it).
        changed_fields = list(values.keys())
        old_values = {field_name: getattr(current, field_name) for field_name in changed_fields}
        version_from = current.version
        version_to = current.version + 1

        values["version"] = Activity.version + 1
        values["updated_at"] = func.now()
        statement = (
            update(Activity)
            .where(Activity.id == activity_id, Activity.version == payload.version)
            .values(**values)
            .returning(Activity)
        )
        updated = session.execute(statement).scalar_one_or_none()
        if updated is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "version_conflict", "expected_version": payload.version},
            )
        for field_name in changed_fields:
            session.add(
                ActivityChange(
                    activity_id=activity_id,
                    actor=user.username,
                    change_type="updated",
                    field=field_name,
                    old_value=stringify_change_value(old_values[field_name]),
                    new_value=stringify_change_value(getattr(updated, field_name)),
                    version_from=version_from,
                    version_to=version_to,
                )
            )
        session.commit()
        session.refresh(updated)
        return updated

    @app.delete("/api/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_activity(
        activity_id: uuid.UUID,
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        current = session.get(Activity, activity_id)
        if current is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        snapshot = json.dumps(
            {"tracking_id": current.tracking_id, "activity_name": current.activity_name}
        )
        # Missing DELETE grant (everyone but admin) raises 42501 here -> the
        # global handler turns it into a clean 403 before any audit row exists.
        result = session.execute(sqlalchemy_delete(Activity).where(Activity.id == activity_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        session.add(
            ActivityChange(
                activity_id=activity_id,
                actor=user.username,
                change_type="deleted",
                old_value=snapshot,
                version_from=current.version,
            )
        )
        session.commit()

    @app.get("/api/activities/{activity_id}/changes", response_model=ActivityChangeList)
    def list_activity_changes(
        activity_id: uuid.UUID,
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        if session.scalar(select(Activity.id).where(Activity.id == activity_id)) is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        items = list(
            session.scalars(
                select(ActivityChange)
                .where(ActivityChange.activity_id == activity_id)
                .order_by(ActivityChange.changed_at.desc(), ActivityChange.id.desc())
            )
        )
        return {"items": items, "total": len(items)}

    @app.get("/api/sync-runs/latest")
    def latest_sync_run(
        user: CurrentUser = Depends(current_user),
        session: Session = Depends(db_session),
    ):
        run = session.scalar(select(SyncRun).order_by(SyncRun.ran_at.desc()))
        return serialize_sync_run(run)

    dashboard_dir = Path(__file__).resolve().parents[1] / "studio"

    class NoCacheStaticFiles(StaticFiles):
        """Serve the studio without HTTP caching.

        Stale assets are this deployment's recurring failure mode -- the whole
        check.ps1 preflight exists because hand-copied files silently lag behind.
        The browser's own cache reintroduces the same class of bug from the other
        side: app.js and analytics.js keep running a previous version while the
        server already serves the new one, and nothing on screen says so.

        The studio is a local, single-user deployment served from disk, so the
        bandwidth these headers cost is irrelevant next to the confidence that
        what renders is what shipped.
        """

        def is_not_modified(self, response_headers, request_headers):  # noqa: D102
            return False

        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-store, must-revalidate"
            # MutableHeaders has no pop(); deleting a missing key raises.
            for header in ("etag", "last-modified"):
                if header in response.headers:
                    del response.headers[header]
            return response

    app.mount("/", NoCacheStaticFiles(directory=dashboard_dir, html=True), name="dashboard")
    return app


def create_environment_app() -> FastAPI:
    """Create the ASGI app from an explicitly supplied environment URL."""
    return create_app(database_url_from_environment())
