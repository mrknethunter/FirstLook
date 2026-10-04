"""Worker-side parsing, bounded previews and retention cleanup."""

from __future__ import annotations

import io
import json
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select, text

from firstlook.audit.service import AuditInput, append_event
from firstlook.baseline.models import DailyMetric, HourlyMetric
from firstlook.baseline.service import recompute
from firstlook.crypto import decrypt_patient_field, encrypt_patient_field
from firstlook.db import set_patient_scope, worker_sessions
from firstlook.ingest.adapters import ADAPTERS, ImportKind, MetricSample, ResourceItem
from firstlook.ingest.models import ImportFile
from firstlook.ingest.service import _upload_path
from firstlook.profile.models import Patient
from firstlook.profile.service import _dek
from firstlook.sharing.manifest import _notify


def aggregate(samples: list[MetricSample]) -> list[dict[str, Any]]:
    """Reduce source rows by UTC day with explicit metric-specific operations."""
    groups: dict[tuple[date, str], list[float]] = defaultdict(list)
    for sample in samples:
        groups[(sample.timestamp.astimezone(UTC).date(), sample.metric)].append(sample.value)
    values: list[dict[str, Any]] = []
    for (day, metric), observations in sorted(groups.items()):
        if metric in {"steps", "active_energy", "sleep_minutes"}:
            value = sum(observations)
        elif metric == "hr_min":
            value = min(observations)
        elif metric == "hr_max":
            value = max(observations)
        else:
            value = statistics.median(observations)
        values.append({"day": day.isoformat(), "metric": metric, "value": value})
    return values


def _safe_path(import_id: UUID, recorded: str) -> Path:
    """Refuse a DB-stored path that differs from the server-generated upload name."""
    expected = _upload_path(import_id).resolve()
    if Path(recorded).resolve() != expected:
        raise ValueError("invalid import path")
    return expected


async def parse_import(import_id: UUID, patient_id: UUID) -> None:
    """Parse without profile writes; delete raw ciphertext once preview persists."""
    async with worker_sessions()() as session:
        async with session.begin():
            await set_patient_scope(session, patient_id)
            row = await session.get(ImportFile, import_id)
            patient = await session.get(Patient, patient_id)
            if row is None or patient is None or row.patient_id != patient_id:
                raise ValueError("import unavailable")
            if row.status != "pending":
                return
            if row.expires_at <= datetime.now(UTC):
                raise ValueError("import expired")
            path = _safe_path(import_id, row.storage_path)
            kind = row.kind
            dek = _dek(patient)
    raw = path.read_bytes()
    plaintext = decrypt_patient_field(dek, patient_id, import_id, 1, raw)
    samples: list[MetricSample] = []
    resources: list[dict[str, Any]] = []
    report: dict[str, Any] = {"errors": [], "warnings": []}
    try:
        for item in ADAPTERS[cast(ImportKind, kind)].parse(io.BytesIO(plaintext)):
            if isinstance(item, MetricSample):
                samples.append(item)
            elif isinstance(item, ResourceItem):
                resources.append({"section": item.section, "resource": item.resource})
    except (ValueError, UnicodeError, TypeError, KeyError):
        report["errors"] = [{"code": "invalid_record", "message": "Import validation failed"}]
    except Exception:
        # Parser libraries may report arbitrary source text in exceptions.
        report["errors"] = [{"code": "invalid_format", "message": "Import validation failed"}]
    metrics = aggregate(samples) if not report["errors"] else []
    if report["errors"]:
        resources = []
    preview: dict[str, Any] = {
        "metrics": metrics,
        "resources": resources,
        "metric_count": len(metrics),
        "resource_count": len(resources),
        "date_range": [metrics[0]["day"], metrics[-1]["day"]] if metrics else None,
        "source": kind,
    }
    async with worker_sessions()() as session:
        async with session.begin():
            await set_patient_scope(session, patient_id)
            row = await session.get(ImportFile, import_id, with_for_update=True)
            if row is None or row.patient_id != patient_id or row.status != "pending":
                raise ValueError("import unavailable")
            existing = (
                (
                    await session.scalars(
                        select(DailyMetric).where(
                            DailyMetric.patient_id == patient_id,
                            DailyMetric.day >= date.fromisoformat(metrics[0]["day"]),
                            DailyMetric.day <= date.fromisoformat(metrics[-1]["day"]),
                        )
                    )
                ).all()
                if metrics
                else []
            )
            keys = {(item.day.isoformat(), item.metric) for item in existing}
            updates = sum((item["day"], item["metric"]) in keys for item in metrics)
            preview["add_count"] = len(metrics) - updates + len(resources)
            preview["update_count"] = updates
            preview["conflict_count"] = 0
            row.preview_enc = encrypt_patient_field(
                dek,
                patient_id,
                import_id,
                2,
                json.dumps(preview, separators=(",", ":")).encode("utf-8"),
            )
            row.report_enc = encrypt_patient_field(
                dek,
                patient_id,
                import_id,
                3,
                json.dumps(report, separators=(",", ":")).encode("utf-8"),
            )
            row.status = "failed" if report["errors"] else "parsed"
            row.parsed_at = datetime.now(UTC)
    path.unlink(missing_ok=True)


async def recompute_patient(patient_id: UUID) -> None:
    async with worker_sessions()() as session:
        async with session.begin():
            await set_patient_scope(session, patient_id)
            await recompute(session, patient_id)
            await session.execute(
                delete(HourlyMetric).where(
                    HourlyMetric.patient_id == patient_id,
                    HourlyMetric.hour
                    < datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=14),
                )
            )


async def remind_patient(patient_id: UUID) -> None:
    async with worker_sessions()() as session:
        async with session.begin():
            await set_patient_scope(session, patient_id)
            event = await append_event(
                session,
                AuditInput(
                    patient_id,
                    "system",
                    None,
                    None,
                    None,
                    None,
                    "profile.reconfirm_due",
                    "profile_freshness",
                    ("profile",),
                    None,
                    "allowed",
                ),
            )
            await _notify(session, patient_id, event.seq)


async def sweep_expired() -> int:
    """Remove unfinished ciphertext no later than its 24-hour expiry."""
    async with worker_sessions()() as session:
        rows = (
            await session.execute(text("SELECT id, patient_id FROM ops.expired_imports()"))
        ).all()
    deleted = 0
    for raw_import_id, raw_patient_id in rows:
        import_id = cast(UUID, raw_import_id)
        patient_id = cast(UUID, raw_patient_id)
        async with worker_sessions()() as session:
            async with session.begin():
                await set_patient_scope(session, patient_id)
                row = await session.get(ImportFile, import_id, with_for_update=True)
                if row is None or row.status == "committed":
                    continue
                _safe_path(row.id, row.storage_path).unlink(missing_ok=True)
                row.status = "expired"
                deleted += 1
    return deleted
