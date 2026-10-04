"""Tiered SHL manifest resolution with consent, limits, audit and JWE."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select, text, update

from firstlook.audit.service import AuditInput, append_event
from firstlook.authz import AccessContext, Action, require
from firstlook.baseline.service import as_fhir_bundle
from firstlook.baseline.service import summary as baseline_summary
from firstlook.crypto import encrypt_patient_field, lookup_hmac
from firstlook.db import app_sessions, set_patient_scope
from firstlook.fhir.ips_builder import build_essentials_bundle, build_ips_bundle
from firstlook.identity.models import User
from firstlook.identity.security import verify_password
from firstlook.identity.service import Principal
from firstlook.profile.consents import has_consent
from firstlook.profile.models import Patient
from firstlook.profile.service import RULES, _dek, _resources, _selection, patient_identity
from firstlook.rules.engine import evaluate_flags
from firstlook.settings import get_settings
from firstlook.sharing.models import (
    BreakglassAccess,
    EmergencySession,
    ManifestLookup,
    Notification,
    ShlLink,
)
from firstlook.sharing.protocol import CONTENT_TYPE, encrypt_bundle, manifest_hash
from firstlook.sharing.service import _pepper, link_key

LOOKUP_LOCK = 718_230_911
BREAKGLASS_LOCK = 718_230_912
log = structlog.get_logger()


@dataclass(frozen=True)
class ManifestInput:
    recipient: str | None
    embedded_length_max: int | None
    fl_mode: str | None
    fl_reason: str | None
    fl_acknowledge: bool
    passcode: str | None


@dataclass(frozen=True)
class ManifestResult:
    files: list[dict[str, str]]
    status: str
    emergency_session_id: UUID | None


class ManifestFailure(Exception):
    def __init__(self, status: int, title: str, remaining_attempts: int | None = None):
        super().__init__(title)
        self.status = status
        self.title = title
        self.remaining_attempts = remaining_attempts


def breakglass_limit_reached(
    link_count: int, ip_count: int, link_limit: int, ip_limit: int
) -> bool:
    """Deny the next session at either inclusive configured hourly cap."""
    return link_count >= link_limit or ip_count >= ip_limit


async def _lookup_patient(identifier: str, ip_hash: bytes) -> tuple[UUID, bytes]:
    """Count unknown capability probes without exposing revoked or expired state."""
    try:
        hashed = manifest_hash(identifier)
    except ValueError:
        hashed = None
    patient_id: UUID | None = None
    rate_limited = False
    async with app_sessions()() as session:
        async with session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": LOOKUP_LOCK})
            if hashed is not None:
                patient_id = await session.scalar(
                    text("SELECT sharing.patient_id_for_manifest(:hash)"), {"hash": hashed}
                )
            if patient_id is None:
                count = await session.scalar(
                    select(func.count())
                    .select_from(ManifestLookup)
                    .where(
                        ManifestLookup.ip_hash == ip_hash,
                        ManifestLookup.known.is_(False),
                        ManifestLookup.ts >= datetime.now(UTC) - timedelta(minutes=10),
                    )
                )
                rate_limited = (count or 0) >= 30
            session.add(
                ManifestLookup(
                    id=uuid4(),
                    ip_hash=ip_hash,
                    known=patient_id is not None,
                    ts=datetime.now(UTC),
                )
            )
    if rate_limited:
        raise ManifestFailure(429, "Too many manifest requests")
    if patient_id is None or hashed is None:
        raise ManifestFailure(404, "Not found")
    return patient_id, hashed


def _breakglass_reason(body: ManifestInput) -> str:
    if not body.fl_acknowledge:
        raise ManifestFailure(403, "Emergency access requires explicit acknowledgement")
    reason = body.fl_reason or body.recipient or ""
    if not 10 <= len(reason.strip()) <= 280:
        raise ManifestFailure(403, "Emergency access requires a reason of 10 to 280 characters")
    return reason.strip()


async def _check_breakglass_limit(session: object, link_id: UUID, ip_hash: bytes) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    await session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": BREAKGLASS_LOCK})
    since = datetime.now(UTC) - timedelta(hours=1)
    link_count = await session.scalar(
        select(func.count())
        .select_from(BreakglassAccess)
        .where(
            BreakglassAccess.link_id == link_id,
            BreakglassAccess.ts >= since,
        )
    )
    ip_count = await session.scalar(
        select(func.count())
        .select_from(BreakglassAccess)
        .where(
            BreakglassAccess.ip_hash == ip_hash,
            BreakglassAccess.ts >= since,
        )
    )
    settings = get_settings()
    if breakglass_limit_reached(
        link_count or 0,
        ip_count or 0,
        settings.fl_breakglass_link_limit,
        settings.fl_breakglass_ip_limit,
    ):
        raise ManifestFailure(429, "Emergency access limit reached")


async def _notify(session: object, patient_id: UUID, event_seq: int) -> None:
    """Notify in the audit transaction; a delivery failure cannot block emergency care."""
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    try:
        async with session.begin_nested():
            session.add(
                Notification(
                    id=uuid4(),
                    patient_id=patient_id,
                    event_seq=event_seq,
                    channel="in_app",
                    status="pending",
                    created_at=datetime.now(UTC),
                )
            )
            await session.flush()
            await session.execute(
                text("SELECT pg_notify(:channel, :event_seq)"),
                {"channel": f"fl_patient_{patient_id.hex}", "event_seq": str(event_seq)},
            )
    except Exception:
        # The tamper-evident audit event remains the durable source for replay.
        log.warning("notification.delivery_failed")


async def resolve_manifest(
    identifier: str,
    body: ManifestInput,
    principal: Principal | None,
    source_ip: str,
) -> ManifestResult:
    """Resolve capability to the minimal tier the caller is authorised to see."""
    ip_hash = lookup_hmac(_pepper(), "manifest-ip", source_ip)
    patient_id, hashed = await _lookup_patient(identifier, ip_hash)
    failure: ManifestFailure | None = None
    result: ManifestResult | None = None
    async with app_sessions()() as session:
        async with session.begin():
            await set_patient_scope(session, patient_id)
            link = await session.scalar(
                select(ShlLink).where(ShlLink.manifest_id_hash == hashed).with_for_update()
            )
            patient = await session.get(Patient, patient_id)
            owner = await session.get(User, patient.owner_user_id) if patient else None
            if (
                link is None
                or patient is None
                or owner is None
                or owner.tenant != get_settings().fl_env
                or patient.deleted_at is not None
                or link.status != "active"
                or (link.exp is not None and link.exp <= datetime.now(UTC))
            ):
                raise ManifestFailure(404, "Not found")
            if link.kind == "emergency" and not await has_consent(
                session, patient.id, "essentials_content"
            ):
                raise ManifestFailure(404, "Not found")
            if link.kind == "clinician" and not await has_consent(
                session, patient.id, "clinician_sharing"
            ):
                raise ManifestFailure(404, "Not found")

            key = link_key(patient, link)
            now = datetime.now(UTC)
            session_id: UUID | None = None
            reason_enc: bytes | None = None
            actor_type: str
            actor_id: UUID | None
            org_id: UUID | None
            role: str
            tier: str
            categories: tuple[str, ...]
            if link.kind == "clinician":
                if link.passcode_failures >= 5:
                    failure = ManifestFailure(401, "Passcode unavailable", 0)
                elif not body.passcode:
                    failure = ManifestFailure(401, "Passcode required", 5 - link.passcode_failures)
                elif not await asyncio.to_thread(
                    verify_password, link.passcode_hash, body.passcode
                ):
                    failures = await session.scalar(
                        update(ShlLink)
                        .where(ShlLink.id == link.id, ShlLink.passcode_failures < 5)
                        .values(passcode_failures=ShlLink.passcode_failures + 1)
                        .returning(ShlLink.passcode_failures)
                    )
                    failure = ManifestFailure(
                        401, "Passcode required or incorrect", max(5 - (failures or 5), 0)
                    )
                if failure is None:
                    context = AccessContext(
                        actor_id=None,
                        role="clinician_share",
                        tenant=owner.tenant,
                        clinician_share_patient_id=patient.id,
                    )
                    require(
                        Action.READ_FULL,
                        context,
                        resource_tenant=owner.tenant,
                        patient_id=patient.id,
                    )
                actor_type, actor_id, org_id, role, tier = (
                    "clinician_share",
                    None,
                    None,
                    "clinician_share",
                    "T4",
                )
                categories = ("ips",)
                if failure is not None:
                    await append_event(
                        session,
                        AuditInput(
                            patient.id,
                            "clinician_share",
                            None,
                            None,
                            "clinician_share",
                            "T4",
                            "share.passcode_denied",
                            "clinician_share",
                            (),
                            None,
                            "denied",
                        ),
                    )
            elif principal is None:
                if body.fl_mode == "responder":
                    raise ManifestFailure(401, "Responder sign-in required")
                reason = _breakglass_reason(body)
                await _check_breakglass_limit(session, link.id, ip_hash)
                context = AccessContext(
                    actor_id=None,
                    role="break_glass",
                    tenant=owner.tenant,
                    breakglass_patient_id=patient.id,
                )
                require(
                    Action.READ_ESSENTIALS,
                    context,
                    resource_tenant=owner.tenant,
                    patient_id=patient.id,
                )
                session_id = uuid4()
                reason_enc = encrypt_patient_field(
                    _dek(patient), patient.id, session_id, 1, reason.encode("utf-8")
                )
                actor_type, actor_id, org_id, role, tier = (
                    "break_glass",
                    None,
                    None,
                    "break_glass",
                    "T1",
                )
                categories = ("essentials",)
            elif principal.role == "responder":
                context = AccessContext(
                    actor_id=principal.user_id,
                    role=principal.role,
                    tenant=principal.tenant,
                    org_id=principal.org_id,
                    org_active=principal.org_active,
                    mfa_passed=principal.mfa_passed,
                    emergency_patient_id=patient.id,
                )
                require(
                    Action.READ_FULL, context, resource_tenant=owner.tenant, patient_id=patient.id
                )
                session_id = uuid4()
                actor_type, actor_id, org_id, role, tier = (
                    "responder",
                    principal.user_id,
                    principal.org_id,
                    "responder",
                    "T2",
                )
                categories = ("ips", "baseline")
            else:
                raise ManifestFailure(
                    403, "Use an authorised responder account or emergency access"
                )

            if failure is None:
                identity = await patient_identity(patient)
                resources = await _resources(session, patient)
                flags = evaluate_flags(resources, RULES)
                if tier == "T1":
                    selected, show_sex = await _selection(session, patient, resources, flags)
                    bundle = build_essentials_bundle(
                        identity, resources, selected, flags, show_sex=show_sex
                    )
                else:
                    bundle = build_ips_bundle(identity, resources, flags)
                files = [{"contentType": CONTENT_TYPE, "embedded": encrypt_bundle(bundle, key)}]
                if tier == "T2":
                    baseline = as_fhir_bundle(await baseline_summary(session, patient.id))
                    files.append(
                        {"contentType": CONTENT_TYPE, "embedded": encrypt_bundle(baseline, key)}
                    )
                if body.embedded_length_max and any(
                    len(file["embedded"]) > body.embedded_length_max for file in files
                ):
                    raise ManifestFailure(413, "Embedded length limit exceeded")
                if session_id is not None:
                    duration = (
                        timedelta(minutes=get_settings().fl_session_ttl_breakglass_minutes)
                        if tier == "T1"
                        else timedelta(hours=2)
                    )
                    session.add(
                        EmergencySession(
                            id=session_id,
                            link_id=link.id,
                            patient_id=patient.id,
                            kind="break_glass" if tier == "T1" else "responder",
                            actor_user_id=actor_id,
                            org_id=org_id,
                            reason_enc=reason_enc,
                            ip_hash=ip_hash,
                            created_at=now,
                            expires_at=now + duration,
                        )
                    )
                    if tier == "T1":
                        session.add(
                            BreakglassAccess(id=uuid4(), link_id=link.id, ip_hash=ip_hash, ts=now)
                        )
                audit = await append_event(
                    session,
                    AuditInput(
                        patient.id,
                        actor_type,
                        actor_id,
                        org_id,
                        role,
                        tier,
                        "profile.read",
                        "emergency" if link.kind == "emergency" else "clinician_share",
                        categories,
                        session_id,
                        "allowed",
                        reason_enc,
                    ),
                )
                await _notify(session, patient.id, audit.seq)
                result = ManifestResult(
                    files,
                    "can-change" if link.kind == "emergency" else "finalized",
                    session_id if tier == "T2" else None,
                )
    if failure is not None:
        raise failure
    if result is None:
        raise ManifestFailure(500, "Manifest unavailable")
    return result
