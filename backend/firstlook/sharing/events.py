"""Owner access history and subject-bound PostgreSQL notification streams."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date

import psycopg
from psycopg import sql
from sqlalchemy import select

from firstlook.audit.models import AuditEvent
from firstlook.authz import AccessDenied
from firstlook.db import app_sessions
from firstlook.identity.service import Principal, load_principal
from firstlook.profile.service import owner_patient
from firstlook.settings import get_settings, read_secret
from firstlook.sharing.models import Notification


def _public_event(row: AuditEvent) -> dict[str, object]:
    """Keep ciphertext, direct identifiers and internal hash-chain data off the wire."""
    return {
        "seq": row.seq,
        "time": row.ts.isoformat(),
        "actor_type": row.actor_type,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "org_id": str(row.org_id) if row.org_id else None,
        "role": row.role,
        "tier": row.tier,
        "action": row.action,
        "purpose": row.purpose,
        "categories": row.categories,
        "outcome": row.outcome,
    }


async def access_history(
    principal: Principal,
    *,
    tier: str | None = None,
    since: date | None = None,
    before: date | None = None,
    after_seq: int = 0,
) -> list[dict[str, object]]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            query = select(AuditEvent).where(
                AuditEvent.patient_id == patient.id,
                AuditEvent.actor_type != "patient",
                AuditEvent.seq > after_seq,
            )
            if tier:
                query = query.where(AuditEvent.tier == tier)
            if since:
                query = query.where(AuditEvent.ts >= since)
            if before:
                query = query.where(AuditEvent.ts < before)
            rows = (await session.scalars(query.order_by(AuditEvent.seq.desc()).limit(100))).all()
            return [_public_event(row) for row in rows]


async def notification_ids(principal: Principal, after_seq: int) -> list[int]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            rows = (
                await session.scalars(
                    select(Notification.event_seq)
                    .where(
                        Notification.patient_id == patient.id, Notification.event_seq > after_seq
                    )
                    .order_by(Notification.event_seq)
                    .limit(100)
                )
            ).all()
            return list(rows)


def _sse(event: str, identifier: str, payload: dict[str, str | int]) -> str:
    data = json.dumps(payload, separators=(",", ":"))
    return f"id: {identifier}\nevent: {event}\ndata: {data}\n\n"


async def listen_events(
    channel: str, *, token: str, principal: Principal, last_id: int = 0, patient: bool
) -> AsyncIterator[str]:
    """LISTEN on one owner or facility channel; recheck the login on each heartbeat."""
    if patient:
        if principal.role != "patient":
            raise AccessDenied("access denied")
        async with app_sessions()() as session:
            async with session.begin():
                owner = await owner_patient(session, principal)
                expected = f"fl_patient_{owner.id.hex}"
    else:
        if principal.role != "ed_staff" or principal.org_id is None or not principal.org_active:
            raise AccessDenied("access denied")
        expected = f"fl_ed_{principal.org_id.hex}"
    if channel != expected:
        raise AccessDenied("access denied")
    dsn = read_secret(get_settings().fl_secret_dir / "fl_db_app").replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as connection:
        await connection.execute(sql.SQL("LISTEN {}").format(sql.Identifier(expected)))
        if patient:
            for event_seq in await notification_ids(principal, last_id):
                yield _sse("access", str(event_seq), {"event_seq": event_seq})
                last_id = event_seq
        while True:
            renewed = await load_principal(token)
            if (
                renewed.user_id != principal.user_id
                or renewed.role != principal.role
                or renewed.org_id != principal.org_id
            ):
                raise AccessDenied("access denied")
            received = False
            async for notification in connection.notifies(timeout=15, stop_after=1):
                renewed = await load_principal(token)
                if (
                    renewed.user_id != principal.user_id
                    or renewed.role != principal.role
                    or renewed.org_id != principal.org_id
                ):
                    raise AccessDenied("access denied")
                received = True
                if patient:
                    try:
                        event_seq = int(notification.payload)
                    except ValueError:
                        continue
                    if event_seq > last_id:
                        yield _sse("access", str(event_seq), {"event_seq": event_seq})
                        last_id = event_seq
                else:
                    yield _sse("refresh", notification.payload, {"event": "refresh"})
            if not received:
                yield ": heartbeat\n\n"
