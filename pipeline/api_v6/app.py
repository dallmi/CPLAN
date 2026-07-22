"""Local database API for CPLAN Planning Studio V6."""

from __future__ import annotations

import os
import re
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence, get_args
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, status
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
from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, func, select, update
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .database import backend_from_url, create_cplan_engine, ensure_schema


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    bod_geb: Mapped[str | None] = mapped_column(Text, nullable=True)
    communication_pack: Mapped[str | None] = mapped_column(Text, nullable=True)
    communication_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


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
    communication_pack: str | None = None
    communication_ref: str | None = None
    author: str | None = None
    author_email: str | None = None
    audience: str | None = None
    source_created_at: datetime | None = None
    source_modified_at: datetime | None = None
    is_archive: bool = False

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        if self.source_type == "external" and self.news_digest is not None:
            raise ValueError("news_digest is only valid for internal activities")
        return self


class ActivityCreate(ActivityFields):
    @model_validator(mode="before")
    @classmethod
    def normalize_blank_strings_before_validation(cls, data: Any) -> Any:
        return normalize_blank_strings(cls, data)

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

    id: uuid.UUID
    tracking_id: str | None = Field(default=None, max_length=160)
    version: int
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


ZURICH = ZoneInfo("Europe/Zurich")
STANDALONE_PACK_PREFIX = "STA-0000000"
_CPID_PATTERN = re.compile(r"^[A-Z0-9]+-[0-9]+$")
MAX_TRACKING_ID_GENERATION_ATTEMPTS = 10_000


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
    return alphabetic[:3].upper() or "GEN"


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


def create_app(database_url: str | URL | None = None) -> FastAPI:
    resolved_url = database_url or os.environ.get("CPLAN_DATABASE_URL")
    if not resolved_url:
        raise RuntimeError(
            "CPLAN database is not configured; use setup_backend or set CPLAN_DATABASE_URL"
        )
    backend = backend_from_url(resolved_url)
    engine = create_cplan_engine(resolved_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        ensure_schema(engine, Base.metadata)
        yield
        engine.dispose()

    app = FastAPI(title="CPLAN Planning Studio V6 API", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine

    @app.get("/api/health")
    def health():
        with Session(engine) as session:
            session.execute(select(1))
        return {"status": "ok", "database": backend}

    @app.post("/api/activities", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
    def create_activity(payload: ActivityCreate):
        with Session(engine) as session:
            tracking_id = _generate_unique_tracking_id(session, payload)
            activity = Activity(**payload.model_dump(), tracking_id=tracking_id)
            session.add(activity)
            session.commit()
            session.refresh(activity)
            return activity

    @app.get("/api/activities", response_model=ActivityList)
    def list_activities():
        with Session(engine) as session:
            items = list(session.scalars(select(Activity).order_by(Activity.start_date, Activity.id)))
            return {"items": items, "total": len(items)}

    @app.patch("/api/activities/{activity_id}", response_model=ActivityRead)
    def update_activity(activity_id: uuid.UUID, payload: ActivityPatch):
        values = payload.model_dump(exclude={"version"}, exclude_unset=True)
        with Session(engine) as session:
            current = session.get(Activity, activity_id)
            if current is None:
                raise HTTPException(status_code=404, detail={"code": "not_found"})
            if current.version != payload.version:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "version_conflict", "expected_version": payload.version},
                )

            resulting_start = as_utc(values.get("start_date", current.start_date))
            resulting_end = as_utc(values.get("end_date", current.end_date))
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
            session.commit()
            session.refresh(updated)
            return updated

    dashboard_dir = Path(__file__).resolve().parents[1] / "dashboard-v6-postgres"
    app.mount("/", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")
    return app


def create_environment_app() -> FastAPI:
    """Create the ASGI app from an explicitly supplied environment URL."""
    database_url = os.environ.get("CPLAN_DATABASE_URL")
    if not database_url and os.environ.get("CPLAN_DB_PASSWORD"):
        database_url = URL.create(
            "postgresql+psycopg",
            username=os.environ.get("CPLAN_DB_USER", "cplan"),
            password=os.environ["CPLAN_DB_PASSWORD"],
            host=os.environ.get("CPLAN_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("CPLAN_DB_PORT", "5432")),
            database=os.environ.get("CPLAN_DB_NAME", "cplan"),
        )
    return create_app(database_url)
