"""Append-only audit event mapping."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Identity, LargeBinary, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class AuditEvent(Base):
    __tablename__ = "events"
    __table_args__ = {"schema": "audit"}

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    patient_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    org_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    role: Mapped[str | None] = mapped_column(String(24))
    tier: Mapped[str | None] = mapped_column(String(8))
    action: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(80))
    reason_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    categories: Mapped[list[str]] = mapped_column(JSONB)
    session_ref: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    outcome: Mapped[str] = mapped_column(String(16))
    canonical: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    hash: Mapped[bytes] = mapped_column(LargeBinary(32))
