"""Pseudonymous wearable aggregates; raw device samples are not retained."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = {"schema": "telemetry"}

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(32))


class HourlyMetric(Base):
    __tablename__ = "hourly_metrics"
    __table_args__ = {"schema": "telemetry"}

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"), primary_key=True)
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class Baseline(Base):
    __tablename__ = "baselines"
    __table_args__ = {"schema": "telemetry"}

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"), primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    window_days: Mapped[int] = mapped_column(Integer, primary_key=True)
    median: Mapped[float] = mapped_column(Float)
    mad: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = {"schema": "telemetry"}

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"), primary_key=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32))
