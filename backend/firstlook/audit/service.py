"""Tamper-evident, append-only audit records in the caller's transaction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.audit.models import AuditEvent
from firstlook.db import set_patient_scope

ZERO_HASH = bytes(32)
CHAIN_LOCK_ID = 718_230_910


@dataclass(frozen=True)
class AuditInput:
    patient_id: UUID
    actor_type: str
    actor_id: UUID | None
    org_id: UUID | None
    role: str | None
    tier: str | None
    action: str
    purpose: str
    categories: tuple[str, ...]
    session_ref: UUID | None
    outcome: str
    reason_enc: bytes | None = None


def canonical_bytes(value: dict[str, Any]) -> bytes:
    """Make hash input independent of dictionary insertion order and whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def event_hash(previous: bytes, payload: dict[str, Any]) -> bytes:
    if len(previous) != 32:
        raise ValueError("invalid audit predecessor")
    return hashlib.sha256(previous + canonical_bytes(payload)).digest()


def build_payload(event: AuditInput, timestamp: datetime) -> dict[str, Any]:
    return {
        "ts": timestamp.astimezone(UTC).isoformat(),
        "patient_id": str(event.patient_id),
        "actor_type": event.actor_type,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "org_id": str(event.org_id) if event.org_id else None,
        "role": event.role,
        "tier": event.tier,
        "action": event.action,
        "purpose": event.purpose,
        "categories": list(event.categories),
        "session_ref": str(event.session_ref) if event.session_ref else None,
        "outcome": event.outcome,
        "reason_enc": event.reason_enc.hex() if event.reason_enc else None,
    }


async def append_event(session: AsyncSession, event: AuditInput) -> AuditEvent:
    """Serialise chain writers and insert alongside the protected business operation."""
    await set_patient_scope(session, event.patient_id)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": CHAIN_LOCK_ID}
    )
    predecessor = await session.scalar(text("SELECT audit.last_hash()"))
    if predecessor is None:
        predecessor = ZERO_HASH
    timestamp = datetime.now(UTC)
    payload = build_payload(event, timestamp)
    record = AuditEvent(
        ts=timestamp,
        patient_id=event.patient_id,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        org_id=event.org_id,
        role=event.role,
        tier=event.tier,
        action=event.action,
        purpose=event.purpose,
        reason_enc=event.reason_enc,
        categories=list(event.categories),
        session_ref=event.session_ref,
        outcome=event.outcome,
        canonical=payload,
        prev_hash=predecessor,
        hash=event_hash(predecessor, payload),
    )
    session.add(record)
    await session.flush()
    return record


def verify_chain(records: Iterable[tuple[bytes, bytes, dict[str, Any]]]) -> bool:
    """Verify an ordered export of (prev_hash, hash, canonical payload)."""
    previous = ZERO_HASH
    for claimed_previous, claimed_hash, payload in records:
        if claimed_previous != previous or event_hash(previous, payload) != claimed_hash:
            return False
        previous = claimed_hash
    return True
