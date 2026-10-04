"""Identity tables; direct identifiers are encrypted before persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "identity"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    email_hmac: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    email_enc: Mapped[bytes] = mapped_column(LargeBinary)
    password_hash: Mapped[str] = mapped_column(Text)
    mfa_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_pending_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    locale: Mapped[str] = mapped_column(String(2), default="en")
    theme: Mapped[str] = mapped_column(String(8), default="system")
    kind: Mapped[str] = mapped_column(String(16))
    tenant: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Organisation(Base):
    __tablename__ = "organisations"
    __table_args__ = {"schema": "identity"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16))
    facility_code: Mapped[str | None] = mapped_column(String(80), unique=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    tenant: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = {"schema": "identity"}

    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("identity.organisations.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "identity"}

    id_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("identity.users.id"))
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("identity.organisations.id"))
    kind: Mapped[str] = mapped_column(String(16))
    mfa_passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    ua_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = {"schema": "identity"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    email_hmac: Mapped[bytes] = mapped_column(LargeBinary(32))
    ip_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    failed: Mapped[bool] = mapped_column(Boolean)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MfaRecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"
    __table_args__ = {"schema": "identity"}

    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"))
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
