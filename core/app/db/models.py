from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NotificationRaw(Base):
    __tablename__ = "notifications_raw"
    __table_args__ = (
        Index("uq_notifications_dedupe_key", "dedupe_key", unique=True),
        Index("ix_notifications_created_at", "created_at"),
        Index("ix_notifications_timestamp", "timestamp"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, default="default")
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_processed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    dedupe_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(Text, nullable=True)


class EventLog(Base):
    __tablename__ = "events_log"
    __table_args__ = (
        Index("ix_events_timestamp", "timestamp"),
        Index("ix_events_source_type", "source", "event_type"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0)


class DeviceState(Base):
    __tablename__ = "device_states"

    entity_id: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    attributes_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    last_changed: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SensorHistory(Base):
    __tablename__ = "sensor_history"
    __table_args__ = (
        Index("ix_sensor_history_entity_id", "entity_id", "id"),
        Index("ix_sensor_history_observed_at", "observed_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes_json: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ha_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TelemetryGap(Base):
    __tablename__ = "telemetry_gaps"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class TelemetryCheckpoint(Base):
    __tablename__ = "telemetry_checkpoint"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
