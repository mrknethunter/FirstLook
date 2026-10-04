"""Versioned, immediately effective patient consent decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.audit.service import AuditInput, append_event
from firstlook.baseline.models import Baseline, DailyMetric, HourlyMetric, SyncState
from firstlook.identity.service import Principal
from firstlook.profile.models import Consent, Patient

CONSENT_TYPES = {
    "profile_storage",
    "wearable_baseline",
    "essentials_content",
    "ed_prealert",
    "clinician_sharing",
    "emergency_contact_notification",
}


async def latest_consents(session: AsyncSession, patient_id: object) -> dict[str, bool]:
    """Read append-only decisions in time order after patient RLS scope is set."""
    rows = (
        await session.scalars(
            select(Consent).where(Consent.patient_id == patient_id).order_by(Consent.ts, Consent.id)
        )
    ).all()
    return {row.type: row.granted for row in rows}


async def has_consent(session: AsyncSession, patient_id: object, kind: str) -> bool:
    if kind not in CONSENT_TYPES:
        return False
    return (await latest_consents(session, patient_id)).get(kind, False)


async def save_consent(
    session: AsyncSession, patient: Patient, principal: Principal, kind: str, granted: bool
) -> None:
    if kind not in CONSENT_TYPES:
        raise ValueError("unknown consent type")
    if kind == "profile_storage" and not granted:
        raise ValueError("use account deletion to withdraw profile storage")
    if kind == "wearable_baseline" and not granted:
        for table in (DailyMetric, HourlyMetric, Baseline, SyncState):
            await session.execute(delete(table).where(table.patient_id == patient.id))
    session.add(
        Consent(
            id=uuid4(),
            patient_id=patient.id,
            type=kind,
            granted=granted,
            policy_version="1",
            ts=datetime.now(UTC),
        )
    )
    await append_event(
        session,
        AuditInput(
            patient.id,
            "patient",
            principal.user_id,
            None,
            "patient",
            "owner",
            "consent.update",
            kind,
            ("consent",),
            None,
            "allowed",
        ),
    )
