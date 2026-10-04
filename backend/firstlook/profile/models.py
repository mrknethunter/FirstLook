"""Patient key envelope and versioned consent mappings."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from firstlook.db_models import Base


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = {"schema": "clinical"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), unique=True)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary)
    dek_version: Mapped[int] = mapped_column(Integer, default=1)
    kek_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = {"schema": "clinical"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    type: Mapped[str] = mapped_column(String(40))
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(String(24))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = {"schema": "clinical"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    rtype: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    fhir_enc: Mapped[bytes] = mapped_column(LargeBinary)
    source: Mapped[str] = mapped_column(String(32))
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = {"schema": "clinical"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    data_enc: Mapped[bytes] = mapped_column(LargeBinary)
    notify_on_access: Mapped[bool] = mapped_column(Boolean, default=False)


class EssentialsSelection(Base):
    __tablename__ = "essentials_selection"
    __table_args__ = {"schema": "clinical"}

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"), primary_key=True)
    items: Mapped[list[str]] = mapped_column(JSONB)
    show_sex: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Confirmation(Base):
    __tablename__ = "confirmations"
    __table_args__ = {"schema": "clinical"}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("clinical.patients.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sections: Mapped[list[str]] = mapped_column(JSONB)


class VaultPerson(Base):
    __tablename__ = "persons"
    __table_args__ = {"schema": "vault"}

    patient_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    given_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    family_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    birth_date_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    national_id_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    address_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    gender_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    age_band_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    preferred_language: Mapped[str | None] = mapped_column(String(2))
