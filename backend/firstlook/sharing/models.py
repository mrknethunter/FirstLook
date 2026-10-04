"""SHL capability and emergency workflow rows."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class ShlLink(Base):
    __tablename__ = "shl_links"
    __table_args__ = {"schema": "sharing"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    kind: Mapped[str] = mapped_column(String(16))
    manifest_id_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    key_enc: Mapped[bytes] = mapped_column(LargeBinary)
    flags: Mapped[str] = mapped_column(String(4))
    label: Mapped[str] = mapped_column(String(80))
    exp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    passcode_hash: Mapped[str | None] = mapped_column(Text)
    passcode_failures: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmergencySession(Base):
    __tablename__ = "emergency_sessions"
    __table_args__ = {"schema": "sharing"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    link_id: Mapped[UUID] = mapped_column(ForeignKey("sharing.shl_links.id"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    kind: Mapped[str] = mapped_column(String(16))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("identity.users.id"))
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("identity.organisations.id"))
    reason_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    ip_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Handoff(Base):
    __tablename__ = "handoffs"
    __table_args__ = {"schema": "sharing"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    emergency_session_id: Mapped[UUID] = mapped_column(ForeignKey("sharing.emergency_sessions.id"))
    from_org_id: Mapped[UUID] = mapped_column(ForeignKey("identity.organisations.id"))
    to_facility_id: Mapped[UUID] = mapped_column(ForeignKey("identity.organisations.id"))
    priority: Mapped[str] = mapped_column(String(8))
    eta_minutes: Mapped[int] = mapped_column(Integer)
    observations_enc: Mapped[bytes] = mapped_column(LargeBinary)
    notes_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {"schema": "audit"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    event_seq: Mapped[int] = mapped_column(ForeignKey("audit.events.seq"))
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ManifestLookup(Base):
    __tablename__ = "manifest_lookups"
    __table_args__ = {"schema": "ops"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    ip_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    known: Mapped[bool] = mapped_column(Boolean)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BreakglassAccess(Base):
    __tablename__ = "breakglass_accesses"
    __table_args__ = {"schema": "ops"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    link_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    ip_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
