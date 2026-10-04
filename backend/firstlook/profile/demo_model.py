"""Synthetic persona lookup used only inside the demo tenant."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class DemoPersona(Base):
    __tablename__ = "demo_personas"
    __table_args__ = {"schema": "ops"}

    persona: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("clinical.patients.id"))
