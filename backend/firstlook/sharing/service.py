"""Owner-controlled SMART Health Link lifecycle."""

from __future__ import annotations

import asyncio
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.audit.service import AuditInput, append_event
from firstlook.authz import AccessDenied
from firstlook.crypto import (
    decrypt_patient_field,
    encrypt_patient_field,
    secret_key_from_hex,
)
from firstlook.db import app_sessions, set_patient_scope
from firstlook.identity.security import hash_passcode
from firstlook.identity.service import Principal
from firstlook.profile.consents import has_consent
from firstlook.profile.demo_model import DemoPersona
from firstlook.profile.models import Patient
from firstlook.profile.service import _dek, owner_patient
from firstlook.settings import get_settings, read_secret
from firstlook.sharing.models import EmergencySession, ShlLink
from firstlook.sharing.protocol import manifest_hash, manifest_identifier, viewer_url


@dataclass(frozen=True)
class LinkView:
    id: UUID
    kind: str
    status: str
    label: str
    expires_at: datetime | None
    url: str | None


def _pepper() -> bytes:
    return secret_key_from_hex(read_secret(get_settings().fl_secret_dir / "fl_pepper"))


def link_key(patient: Patient, link: ShlLink) -> bytes:
    """Unwrap only for a patient-scoped link and reject row/key substitution."""
    if patient.id != link.patient_id:
        raise AccessDenied("access denied")
    return decrypt_patient_field(_dek(patient), patient.id, link.id, 1, link.key_enc)


def link_url(patient: Patient, link: ShlLink) -> str:
    """Rebuild a URL from encrypted key material while keeping only its hash in SQL."""
    key = link_key(patient, link)
    pepper = _pepper()
    identifier = manifest_identifier(link.id, key, pepper)
    if not hmac.compare_digest(manifest_hash(identifier), link.manifest_id_hash):
        raise ValueError("invalid link state")
    return viewer_url(link.id, key, pepper, flag=link.flags, label=link.label, exp=link.exp)


def _view(patient: Patient, link: ShlLink) -> LinkView:
    return LinkView(
        link.id,
        link.kind,
        link.status,
        link.label,
        link.exp,
        link_url(patient, link) if link.status == "active" else None,
    )


async def _new_link(
    patient: Patient,
    kind: str,
    passcode: str | None,
    expires_at: datetime | None,
) -> ShlLink:
    if kind not in {"emergency", "clinician"}:
        raise ValueError("invalid link kind")
    if kind == "emergency":
        if passcode is not None or expires_at is not None:
            raise ValueError("emergency links do not take a passcode or expiry")
    else:
        if passcode is None or not re.fullmatch(r"[0-9]{6,64}", passcode):
            raise ValueError("clinician passcode must contain at least six digits")
        now = datetime.now(UTC)
        if expires_at is None or not timedelta(hours=1) <= expires_at - now <= timedelta(days=7):
            raise ValueError("clinician share expiry outside allowed range")
    link_id = uuid4()
    key = secrets.token_bytes(32)
    identifier = manifest_identifier(link_id, key, _pepper())
    return ShlLink(
        id=link_id,
        patient_id=patient.id,
        kind=kind,
        manifest_id_hash=manifest_hash(identifier),
        key_enc=encrypt_patient_field(_dek(patient), patient.id, link_id, 1, key),
        flags="L" if kind == "emergency" else "P",
        label="FirstLook emergency profile" if kind == "emergency" else "FirstLook clinician share",
        exp=expires_at,
        passcode_hash=await asyncio.to_thread(hash_passcode, passcode) if passcode else None,
        passcode_failures=0,
        status="active",
        created_at=datetime.now(UTC),
    )


async def issue_link(
    principal: Principal,
    *,
    kind: str,
    passcode: str | None = None,
    expires_at: datetime | None = None,
) -> LinkView:
    """Issue one live emergency link or a time-bound clinician share."""
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            await session.refresh(patient, with_for_update=True)
            consent = "essentials_content" if kind == "emergency" else "clinician_sharing"
            if not await has_consent(session, patient.id, consent):
                raise AccessDenied("consent required")
            if kind == "emergency":
                current = await session.scalar(
                    select(ShlLink).where(
                        ShlLink.patient_id == patient.id,
                        ShlLink.kind == "emergency",
                        ShlLink.status == "active",
                    )
                )
                if current is not None:
                    return _view(patient, current)
            link = await _new_link(patient, kind, passcode, expires_at)
            session.add(link)
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "link.issue",
                    "sharing",
                    ("link",),
                    None,
                    "allowed",
                ),
            )
            return _view(patient, link)


async def list_links(principal: Principal) -> list[LinkView]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            rows = (
                await session.scalars(
                    select(ShlLink)
                    .where(ShlLink.patient_id == patient.id)
                    .order_by(ShlLink.created_at.desc())
                )
            ).all()
            return [_view(patient, row) for row in rows]


async def carrier_url(principal: Principal, link_id: UUID) -> str:
    """Release a carrier capability only to its patient owner while active."""
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            link = await session.get(ShlLink, link_id)
            if link is None or link.patient_id != patient.id:
                raise AccessDenied("access denied")
            if link.status != "active" or (link.exp and link.exp <= datetime.now(UTC)):
                raise ValueError("link is not active")
            return link_url(patient, link)


async def rotate_link(principal: Principal, link_id: UUID) -> LinkView:
    """Revoke the old emergency capability and issue its replacement atomically."""
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            await session.refresh(patient, with_for_update=True)
            link = await session.get(ShlLink, link_id, with_for_update=True)
            if link is None or link.patient_id != patient.id or link.kind != "emergency":
                raise AccessDenied("access denied")
            if link.status != "active":
                raise ValueError("link is not active")
            link.status = "revoked"
            link.revoked_at = datetime.now(UTC)
            await _end_link_sessions(session, patient.id, link.id)
            await session.flush()
            replacement = await _new_link(patient, "emergency", None, None)
            session.add(replacement)
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "link.rotate",
                    "sharing",
                    ("link",),
                    None,
                    "allowed",
                ),
            )
            return _view(patient, replacement)


async def _end_link_sessions(session: AsyncSession, patient_id: UUID, link_id: UUID) -> None:
    rows = (
        await session.scalars(
            select(EmergencySession).where(
                EmergencySession.patient_id == patient_id,
                EmergencySession.link_id == link_id,
                EmergencySession.ended_at.is_(None),
            )
        )
    ).all()
    for row in rows:
        row.ended_at = datetime.now(UTC)


async def revoke_link(principal: Principal, link_id: UUID) -> None:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            link = await session.get(ShlLink, link_id, with_for_update=True)
            if link is None or link.patient_id != patient.id:
                raise AccessDenied("access denied")
            if link.status == "active":
                link.status = "revoked"
                link.revoked_at = datetime.now(UTC)
                await _end_link_sessions(session, patient.id, link.id)
                await append_event(
                    session,
                    AuditInput(
                        patient.id,
                        "patient",
                        principal.user_id,
                        None,
                        "patient",
                        "owner",
                        "link.revoke",
                        "sharing",
                        ("link",),
                        None,
                        "allowed",
                    ),
                )


async def demo_entry() -> str:
    """Return the current Marco capability in JSON only, never in Location."""
    settings = get_settings()
    if settings.fl_env != "demo" or not settings.fl_demo_tenant_enabled:
        raise AccessDenied("demo is unavailable")
    async with app_sessions()() as session:
        async with session.begin():
            patient_id = await session.scalar(
                select(DemoPersona.patient_id).where(DemoPersona.persona == "marco")
            )
            if patient_id is None:
                raise ValueError("demo entry unavailable")
            await set_patient_scope(session, patient_id)
            patient = await session.get(Patient, patient_id)
            link = await session.scalar(
                select(ShlLink).where(
                    ShlLink.patient_id == patient_id,
                    ShlLink.kind == "emergency",
                    ShlLink.status == "active",
                )
            )
            if patient is None or link is None:
                raise ValueError("demo entry unavailable")
            return link_url(patient, link)
