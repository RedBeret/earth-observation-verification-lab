"""SQLAlchemy engine, sessions, and integration models."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from terrawatch.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Scene(Base):
    __tablename__ = "scenes"

    scene_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    capture_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    crs: Mapped[str | None] = mapped_column(String(64))
    bbox: Mapped[list[float] | None] = mapped_column(JSONB)
    footprint: Mapped[Any | None] = mapped_column(Geometry("POLYGON", srid=4326))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[list[float] | None] = mapped_column(JSONB)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    stac_item: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    processing_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    processing_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TelemetryEventRecord(Base):
    __tablename__ = "telemetry_events"

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    processing_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Correlation(Base):
    __tablename__ = "correlations"
    __table_args__ = (
        UniqueConstraint("scene_id", "event_id", "algorithm_version"),
        Index("ix_correlations_event_id", "event_id"),
    )

    correlation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.scene_id"), nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("telemetry_events.event_id"), nullable=False
    )
    spatial_match: Mapped[bool] = mapped_column(Boolean, nullable=False)
    temporal_delta_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    event_id: Mapped[str] = mapped_column(
        ForeignKey("telemetry_events.event_id"), primary_key=True
    )
    algorithm_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluated_scenes: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_correlation_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(96), nullable=False)
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessingAttempt(Base):
    __tablename__ = "processing_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeadLetter(Base):
    __tablename__ = "dead_letters"
    __table_args__ = (UniqueConstraint("message_id", "service"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(96), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    error_type: Mapped[str] = mapped_column(String(128), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recoverable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def create_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = create_engine(
        database_url or get_settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


SessionFactory = create_session_factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_ready() -> tuple[bool, str]:
    try:
        with SessionFactory() as session:
            version = session.execute(text("SELECT PostGIS_Version()")).scalar_one()
        return True, str(version)
    except Exception as error:
        return False, type(error).__name__
