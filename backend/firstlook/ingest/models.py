"""Identifier-only jobs and encrypted, short-lived import staging."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = {"schema": "ops"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(80))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(80))


class ImportFile(Base):
    __tablename__ = "import_files"
    __table_args__ = {"schema": "ops"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    storage_path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preview_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    report_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
