"""Public terminology tables; seeded codes require documented provenance."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class CodeDisplay(Base):
    __tablename__ = "code_display"
    __table_args__ = {"schema": "terminology"}

    system: Mapped[str] = mapped_column(String(200), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    lang: Mapped[str] = mapped_column(String(2), primary_key=True)
    display: Mapped[str] = mapped_column(String(240))


class MedProduct(Base):
    __tablename__ = "med_products"
    __table_args__ = {"schema": "terminology"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    strength: Mapped[str | None] = mapped_column(String(80))
    form: Mapped[str | None] = mapped_column(String(80))
    atc_code: Mapped[str | None] = mapped_column(String(16))
    atc_prefix: Mapped[str | None] = mapped_column(String(8))
    substances: Mapped[list[str]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(80))
    code_verified: Mapped[bool] = mapped_column(Boolean, default=False)
