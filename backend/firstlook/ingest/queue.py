"""Transactional PostgreSQL queue using SKIP LOCKED and identifier-only payloads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.ingest.models import Job


def enqueue(
    session: AsyncSession, kind: str, identifier: UUID, *, patient_id: UUID | None = None
) -> Job:
    if kind not in {"import.parse", "baseline.recompute", "reminder.reconfirm"}:
        raise ValueError("unsupported job kind")
    payload = {"id": str(identifier)}
    if patient_id is not None:
        payload["patient_id"] = str(patient_id)
    job = Job(
        id=uuid4(),
        kind=kind,
        payload=payload,
        status="pending",
        attempts=0,
        run_after=datetime.now(UTC),
    )
    session.add(job)
    return job


async def claim(session: AsyncSession, worker_id: str) -> Job | None:
    """Claim one due job without blocking peers; caller commits the claim."""
    now = datetime.now(UTC)
    job = await session.scalar(
        select(Job)
        .where(
            or_(
                and_(Job.status == "pending", Job.run_after <= now),
                and_(Job.status == "running", Job.locked_at < now - timedelta(minutes=5)),
            )
        )
        .order_by(Job.run_after)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.locked_at = datetime.now(UTC)
    return job


async def finish(session: AsyncSession, job_id: UUID, *, error_code: str | None = None) -> None:
    job = await session.get(Job, job_id, with_for_update=True)
    if job is None:
        return
    job.locked_by = None
    job.locked_at = None
    if error_code is None:
        job.status = "done"
        job.last_error = None
    elif job.attempts >= 3:
        job.status = "failed"
        job.last_error = error_code[:80]
    else:
        job.status = "pending"
        job.last_error = error_code[:80]
        job.run_after = datetime.now(UTC) + timedelta(seconds=2**job.attempts)
