"""Worker entry point for imports, baseline jobs and retention cleanup."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import structlog
from sqlalchemy import text

from firstlook.db import worker_engine, worker_sessions
from firstlook.ingest.processing import (
    parse_import,
    recompute_patient,
    remind_patient,
    sweep_expired,
)
from firstlook.ingest.queue import claim, enqueue, finish
from firstlook.logging import configure_logging
from firstlook.settings import get_settings, read_secret


async def run() -> None:
    settings = get_settings()
    read_secret(settings.fl_secret_dir / "fl_db_worker")
    read_secret(settings.fl_secret_dir / "fl_kek")
    configure_logging("worker", settings.fl_log_dir, settings.fl_log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    structlog.get_logger().info("worker.started", service="worker")
    worker_id = f"worker-{id(stop)}"
    next_sweep = datetime.now(UTC)
    next_baseline = datetime.now(UTC)
    while not stop.is_set():
        now = datetime.now(UTC)
        if now >= next_sweep:
            await sweep_expired()
            next_sweep = now + timedelta(minutes=1)
        if now >= next_baseline:
            async with worker_sessions()() as session:
                async with session.begin():
                    patient_ids = cast(
                        list[UUID],
                        list(
                            (await session.execute(text("SELECT clinical.active_patient_ids()")))
                            .scalars()
                            .all()
                        ),
                    )
                    for patient_id in patient_ids:
                        enqueue(session, "baseline.recompute", patient_id)
            next_baseline = now + timedelta(hours=24)
        async with worker_sessions()() as session:
            async with session.begin():
                job = await claim(session, worker_id)
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
            continue
        try:
            identifier = UUID(job.payload["id"])
            if job.kind == "import.parse":
                await parse_import(identifier, UUID(job.payload["patient_id"]))
            elif job.kind == "baseline.recompute":
                await recompute_patient(identifier)
            elif job.kind == "reminder.reconfirm":
                await remind_patient(identifier)
            else:
                raise ValueError("unsupported job")
            error_code = None
        except Exception:
            structlog.get_logger().warning("worker.job_failed", service="worker", kind=job.kind)
            error_code = "internal"
        async with worker_sessions()() as session:
            async with session.begin():
                await finish(session, job.id, error_code=error_code)
    await worker_engine().dispose()


if __name__ == "__main__":
    asyncio.run(run())
