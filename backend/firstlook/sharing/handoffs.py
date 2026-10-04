"""Responder pre-alerts and destination-facility handover access."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.audit.service import AuditInput, append_event
from firstlook.authz import AccessContext, AccessDenied, Action, require
from firstlook.baseline.service import summary as baseline_summary
from firstlook.crypto import decrypt_patient_field, encrypt_patient_field
from firstlook.db import app_sessions, set_patient_scope
from firstlook.fhir.ips_builder import build_ips_bundle
from firstlook.identity.models import Organisation, User
from firstlook.identity.service import Principal
from firstlook.profile.consents import has_consent
from firstlook.profile.models import Patient
from firstlook.profile.service import RULES, _dek, _resources, patient_identity
from firstlook.rules.engine import evaluate_flags
from firstlook.sharing.manifest import _notify
from firstlook.sharing.models import EmergencySession, Handoff, ShlLink


@dataclass(frozen=True)
class Prealert:
    facility_id: UUID
    eta_minutes: int
    priority: str
    observations: dict[str, str | float | int | None]
    notes: str | None


def _context(
    principal: Principal, *, emergency: UUID | None = None, handoff: Handoff | None = None
) -> AccessContext:
    return AccessContext(
        actor_id=principal.user_id,
        role=principal.role,
        tenant=principal.tenant,
        org_id=principal.org_id,
        org_active=principal.org_active,
        mfa_passed=principal.mfa_passed,
        emergency_patient_id=emergency,
        handover_patient_id=handoff.patient_id if handoff else None,
        handover_dest_org_id=handoff.to_facility_id if handoff else None,
    )


async def _responder_session(
    session: AsyncSession, principal: Principal, session_id: UUID
) -> tuple[EmergencySession, Patient]:
    """Resolve a capability-derived session; no professional patient search exists."""
    if principal.role != "responder" or principal.org_id is None:
        raise AccessDenied("access denied")
    patient_id = await session.scalar(
        text("SELECT sharing.patient_id_for_session(:id)"), {"id": session_id}
    )
    if patient_id is None:
        raise AccessDenied("access denied")
    await set_patient_scope(session, patient_id)
    emergency = await session.get(EmergencySession, session_id)
    patient = await session.get(Patient, patient_id)
    link = await session.get(ShlLink, emergency.link_id) if emergency else None
    owner = await session.get(User, patient.owner_user_id) if patient else None
    if (
        emergency is None
        or patient is None
        or owner is None
        or link is None
        or emergency.kind != "responder"
        or emergency.actor_user_id != principal.user_id
        or emergency.org_id != principal.org_id
        or emergency.ended_at is not None
        or emergency.expires_at <= datetime.now(UTC)
        or link.status != "active"
        or patient.deleted_at is not None
    ):
        raise AccessDenied("access denied")
    require(
        Action.CREATE_PREALERT,
        _context(principal, emergency=patient.id),
        resource_tenant=owner.tenant,
        patient_id=patient.id,
    )
    return emergency, patient


def _plain_observations(patient: Patient, handoff: Handoff) -> dict[str, str | float | int | None]:
    data = decrypt_patient_field(_dek(patient), patient.id, handoff.id, 1, handoff.observations_enc)
    return cast(dict[str, str | float | int | None], json.loads(data))


def _plain_notes(patient: Patient, handoff: Handoff) -> str | None:
    if handoff.notes_enc is None:
        return None
    return decrypt_patient_field(
        _dek(patient), patient.id, handoff.id, 2, handoff.notes_enc
    ).decode("utf-8")


async def create_handoff(
    principal: Principal, session_id: UUID, key: UUID, body: Prealert
) -> Handoff:
    """Create once for each client key, rejecting a changed retry payload."""
    async with app_sessions()() as session:
        async with session.begin():
            emergency, patient = await _responder_session(session, principal, session_id)
            # Serialise retries before checking the unique idempotency key.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:id)"),
                {"id": int.from_bytes(key.bytes[:8], "big", signed=True)},
            )
            if not await has_consent(session, patient.id, "ed_prealert"):
                raise AccessDenied("access denied")
            facility = await session.get(Organisation, body.facility_id)
            if (
                facility is None
                or facility.type != "ed"
                or not facility.active
                or facility.tenant != principal.tenant
            ):
                raise AccessDenied("access denied")
            existing = await session.scalar(
                select(Handoff)
                .where(Handoff.emergency_session_id == session_id, Handoff.idempotency_key == key)
                .with_for_update()
            )
            if existing is not None:
                if (
                    existing.to_facility_id != body.facility_id
                    or existing.eta_minutes != body.eta_minutes
                    or existing.priority != body.priority
                    or _plain_observations(patient, existing) != body.observations
                    or _plain_notes(patient, existing) != body.notes
                ):
                    raise ValueError("idempotency key reused with different input")
                return existing
            now = datetime.now(UTC)
            handoff_id = uuid4()
            dek = _dek(patient)
            handoff = Handoff(
                id=handoff_id,
                patient_id=patient.id,
                emergency_session_id=emergency.id,
                from_org_id=principal.org_id,
                to_facility_id=facility.id,
                priority=body.priority,
                eta_minutes=body.eta_minutes,
                observations_enc=encrypt_patient_field(
                    dek,
                    patient.id,
                    handoff_id,
                    1,
                    json.dumps(body.observations, sort_keys=True).encode("utf-8"),
                ),
                notes_enc=encrypt_patient_field(
                    dek, patient.id, handoff_id, 2, body.notes.encode("utf-8")
                )
                if body.notes
                else None,
                status="pre_alerted",
                idempotency_key=key,
                created_at=now,
                updated_at=now,
            )
            session.add(handoff)
            event = await append_event(
                session,
                AuditInput(
                    patient.id,
                    "responder",
                    principal.user_id,
                    principal.org_id,
                    "responder",
                    "T2",
                    "handoff.create",
                    "emergency",
                    ("observations", "handover"),
                    emergency.id,
                    "allowed",
                ),
            )
            await _notify(session, patient.id, event.seq)
            await session.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": f"fl_ed_{facility.id.hex}", "payload": str(handoff.id)},
            )
            return handoff


async def update_handoff(
    principal: Principal,
    session_id: UUID,
    handoff_id: UUID,
    *,
    eta_minutes: int | None = None,
    priority: str | None = None,
    observations: dict[str, str | float | int | None] | None = None,
    notes: str | None = None,
    update_notes: bool = False,
) -> Handoff:
    """Allow the originating responder to revise an open pre-alert."""
    async with app_sessions()() as session:
        async with session.begin():
            emergency, patient = await _responder_session(session, principal, session_id)
            handoff = await session.get(Handoff, handoff_id, with_for_update=True)
            if (
                handoff is None
                or handoff.emergency_session_id != emergency.id
                or handoff.from_org_id != principal.org_id
                or handoff.status not in {"pre_alerted", "acknowledged"}
            ):
                raise AccessDenied("access denied")
            if eta_minutes is not None:
                handoff.eta_minutes = eta_minutes
            if priority is not None:
                handoff.priority = priority
            if observations is not None:
                handoff.observations_enc = encrypt_patient_field(
                    _dek(patient),
                    patient.id,
                    handoff.id,
                    1,
                    json.dumps(observations, sort_keys=True).encode("utf-8"),
                )
            if update_notes:
                handoff.notes_enc = (
                    encrypt_patient_field(
                        _dek(patient), patient.id, handoff.id, 2, notes.encode("utf-8")
                    )
                    if notes
                    else None
                )
            handoff.updated_at = datetime.now(UTC)
            event = await append_event(
                session,
                AuditInput(
                    patient.id,
                    "responder",
                    principal.user_id,
                    principal.org_id,
                    "responder",
                    "T2",
                    "handoff.update",
                    "emergency",
                    ("observations", "handover"),
                    handoff.id,
                    "allowed",
                ),
            )
            await _notify(session, patient.id, event.seq)
            await session.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": f"fl_ed_{handoff.to_facility_id.hex}", "payload": str(handoff.id)},
            )
            return handoff


async def facilities(principal: Principal) -> list[Organisation]:
    if principal.role != "responder" or not principal.org_active or not principal.mfa_passed:
        raise AccessDenied("access denied")
    async with app_sessions()() as session:
        return list(
            (
                await session.scalars(
                    select(Organisation)
                    .where(
                        Organisation.type == "ed",
                        Organisation.tenant == principal.tenant,
                        Organisation.active.is_(True),
                    )
                    .order_by(Organisation.name)
                )
            ).all()
        )


async def _facility_handoff(
    session: AsyncSession, principal: Principal, handoff_id: UUID
) -> tuple[Handoff, Patient]:
    if (
        principal.role != "ed_staff"
        or principal.org_id is None
        or not principal.org_active
        or not principal.mfa_passed
    ):
        raise AccessDenied("access denied")
    await session.execute(
        text("SELECT set_config('firstlook.org_id', :org_id, true)"),
        {"org_id": str(principal.org_id)},
    )
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None or handoff.to_facility_id != principal.org_id:
        raise AccessDenied("access denied")
    if handoff.closed_at and handoff.closed_at + timedelta(hours=24) <= datetime.now(UTC):
        raise AccessDenied("access denied")
    await set_patient_scope(session, handoff.patient_id)
    patient = await session.get(Patient, handoff.patient_id)
    owner = await session.get(User, patient.owner_user_id) if patient else None
    if patient is None or owner is None or patient.deleted_at is not None:
        raise AccessDenied("access denied")
    require(
        Action.READ_HANDOVER,
        _context(principal, handoff=handoff),
        resource_tenant=owner.tenant,
        patient_id=patient.id,
    )
    return handoff, patient


async def board(principal: Principal) -> list[Handoff]:
    """List only handovers addressed to the current facility, ordered by ETA."""
    if (
        principal.role != "ed_staff"
        or principal.org_id is None
        or not principal.org_active
        or not principal.mfa_passed
    ):
        raise AccessDenied("access denied")
    async with app_sessions()() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('firstlook.org_id', :org_id, true)"),
                {"org_id": str(principal.org_id)},
            )
            rows = list(
                (
                    await session.scalars(
                        select(Handoff)
                        .where(
                            Handoff.to_facility_id == principal.org_id,
                            Handoff.status.not_in(("closed", "cancelled")),
                        )
                        .order_by(Handoff.eta_minutes, Handoff.created_at)
                        .limit(100)
                    )
                ).all()
            )
            for row in rows:
                _, patient = await _facility_handoff(session, principal, row.id)
                event = await append_event(
                    session,
                    AuditInput(
                        patient.id,
                        "ed_staff",
                        principal.user_id,
                        principal.org_id,
                        "ed_staff",
                        "T3",
                        "handoff.board_read",
                        "treatment",
                        ("handover",),
                        row.id,
                        "allowed",
                    ),
                )
                await _notify(session, patient.id, event.seq)
            return rows


async def handoff_detail(principal: Principal, handoff_id: UUID) -> dict[str, object]:
    async with app_sessions()() as session:
        async with session.begin():
            handoff, patient = await _facility_handoff(session, principal, handoff_id)
            identity = await patient_identity(patient)
            resources = await _resources(session, patient)
            flags = evaluate_flags(resources, RULES)
            bundle = build_ips_bundle(identity, resources, flags)
            event = await append_event(
                session,
                AuditInput(
                    patient.id,
                    "ed_staff",
                    principal.user_id,
                    principal.org_id,
                    "ed_staff",
                    "T3",
                    "handoff.read",
                    "treatment",
                    ("ips", "flags", "baseline", "observations", "handover"),
                    handoff.id,
                    "allowed",
                ),
            )
            await _notify(session, patient.id, event.seq)
            return {
                "id": str(handoff.id),
                "status": handoff.status,
                "priority": handoff.priority,
                "eta_minutes": handoff.eta_minutes,
                "observations": _plain_observations(patient, handoff),
                "notes": _plain_notes(patient, handoff),
                "ips": bundle,
                "baseline": await baseline_summary(session, patient.id),
            }


def next_status(current: str, action: str) -> str:
    """Use the specified linear state machine with cancellation before closure."""
    transitions = {
        ("pre_alerted", "ack"): "acknowledged",
        ("acknowledged", "arrive"): "arrived",
        ("arrived", "close"): "closed",
        ("pre_alerted", "cancel"): "cancelled",
        ("acknowledged", "cancel"): "cancelled",
    }
    try:
        return transitions[(current, action)]
    except KeyError as exc:
        raise ValueError("invalid handover transition") from exc


async def transition(principal: Principal, handoff_id: UUID, action: str) -> Handoff:
    if principal.org_id is None:
        raise AccessDenied("access denied")
    async with app_sessions()() as session:
        async with session.begin():
            handoff, patient = await _facility_handoff(session, principal, handoff_id)
            await session.refresh(handoff, with_for_update=True)
            handoff.status = next_status(handoff.status, action)
            handoff.updated_at = datetime.now(UTC)
            if handoff.status in {"closed", "cancelled"}:
                handoff.closed_at = handoff.updated_at
            event = await append_event(
                session,
                AuditInput(
                    patient.id,
                    "ed_staff",
                    principal.user_id,
                    principal.org_id,
                    "ed_staff",
                    "T3",
                    f"handoff.{action}",
                    "treatment",
                    ("handover",),
                    handoff.id,
                    "allowed",
                ),
            )
            await _notify(session, patient.id, event.seq)
            await session.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": f"fl_ed_{principal.org_id.hex}", "payload": str(handoff.id)},
            )
            return handoff
