"""Owner-controlled encrypted import upload, preview and atomic commit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select

from firstlook.audit.service import AuditInput, append_event
from firstlook.authz import AccessDenied
from firstlook.baseline.models import DailyMetric
from firstlook.baseline.service import METRICS
from firstlook.crypto import decrypt_patient_field, encrypt_patient_field
from firstlook.db import app_sessions
from firstlook.fhir.validation import validate_fhir_resource
from firstlook.identity.service import Principal
from firstlook.ingest.adapters import ADAPTERS, ImportKind
from firstlook.ingest.models import ImportFile
from firstlook.ingest.queue import enqueue
from firstlook.profile.consents import has_consent
from firstlook.profile.models import Resource
from firstlook.profile.service import _dek, owner_patient
from firstlook.settings import get_settings

MAX_UPLOAD = 20 * 1024 * 1024


def _upload_path(import_id: UUID) -> Path:
    """Use only a server-generated UUID as a file name beneath the fixed upload root."""
    directory = get_settings().fl_upload_dir
    return directory / f"{import_id.hex}.enc"


async def upload(principal: Principal, kind: ImportKind, content: bytes) -> UUID:
    """Stage ciphertext and queue parsing; no profile resource is written yet."""
    if not 0 < len(content) <= MAX_UPLOAD or not ADAPTERS[kind].sniff(content[:4096]):
        raise ValueError("unsupported or oversized import")
    import_id = uuid4()
    path = _upload_path(import_id)
    async with app_sessions()() as session:
        try:
            async with session.begin():
                patient = await owner_patient(session, principal)
                if not await has_consent(session, patient.id, "profile_storage"):
                    raise AccessDenied("access denied")
                recent = await session.scalar(
                    select(func.count())
                    .select_from(ImportFile)
                    .where(
                        ImportFile.patient_id == patient.id,
                        ImportFile.created_at >= datetime.now(UTC) - timedelta(hours=1),
                    )
                )
                if (recent or 0) >= 10:
                    raise ValueError("import limit reached")
                ciphertext = encrypt_patient_field(_dek(patient), patient.id, import_id, 1, content)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as handle:
                    handle.write(ciphertext)
                now = datetime.now(UTC)
                session.add(
                    ImportFile(
                        id=import_id,
                        patient_id=patient.id,
                        storage_path=str(path),
                        kind=kind,
                        status="pending",
                        created_at=now,
                        # One-minute sweeps retain a margin below the 24-hour hard limit.
                        expires_at=now + timedelta(hours=23, minutes=58),
                    )
                )
                enqueue(session, "import.parse", import_id, patient_id=patient.id)
                await append_event(
                    session,
                    AuditInput(
                        patient.id,
                        "patient",
                        principal.user_id,
                        None,
                        "patient",
                        "owner",
                        "import.upload",
                        "profile_storage",
                        ("import",),
                        None,
                        "allowed",
                    ),
                )
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return import_id


def _unseal(
    patient_id: UUID, import_id: UUID, version: int, ciphertext: bytes, dek: bytes
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(decrypt_patient_field(dek, patient_id, import_id, version, ciphertext)),
    )


async def import_status(principal: Principal, import_id: UUID) -> dict[str, Any]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            row = await session.get(ImportFile, import_id)
            if row is None or row.patient_id != patient.id:
                raise AccessDenied("access denied")
            dek = _dek(patient)
            preview = (
                _unseal(patient.id, row.id, 2, row.preview_enc, dek) if row.preview_enc else None
            )
            report = _unseal(patient.id, row.id, 3, row.report_enc, dek) if row.report_enc else None
            return {"id": str(row.id), "status": row.status, "preview": preview, "report": report}


async def commit_import(principal: Principal, import_id: UUID) -> dict[str, int]:
    """Apply the patient's reviewed preview in a single transaction."""
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            row = await session.get(ImportFile, import_id, with_for_update=True)
            if row is None or row.patient_id != patient.id:
                raise AccessDenied("access denied")
            if row.status != "parsed" or row.preview_enc is None:
                raise ValueError("import is not ready")
            if row.expires_at <= datetime.now(UTC):
                raise ValueError("import preview expired")
            if not await has_consent(session, patient.id, "profile_storage"):
                raise AccessDenied("access denied")
            preview = _unseal(patient.id, row.id, 2, row.preview_enc, _dek(patient))
            if preview.get("metrics") and not await has_consent(
                session, patient.id, "wearable_baseline"
            ):
                raise AccessDenied("access denied")
            now = datetime.now(UTC)
            metrics = preview.get("metrics", [])
            resources = preview.get("resources", [])
            for item in metrics:
                day = datetime.fromisoformat(item["day"]).date()
                metric = item["metric"]
                current = await session.get(DailyMetric, (patient.id, day, metric))
                if current is None:
                    current = DailyMetric(patient_id=patient.id, day=day, metric=metric)
                    session.add(current)
                current.value = item["value"]
                current.unit = METRICS[metric]
                current.source = row.kind
            for item in resources:
                resource_id = uuid4()
                candidate = {**item["resource"], "id": str(resource_id)}
                valid = validate_fhir_resource(candidate)
                session.add(
                    Resource(
                        id=resource_id,
                        patient_id=patient.id,
                        rtype=valid["resourceType"],
                        status="active",
                        version=1,
                        fhir_enc=encrypt_patient_field(
                            _dek(patient),
                            patient.id,
                            resource_id,
                            1,
                            json.dumps(valid, separators=(",", ":")).encode("utf-8"),
                        ),
                        source="portal" if row.kind == "synthetic_ikp" else row.kind,
                        imported_at=now,
                        confirmed_at=None,
                        updated_at=now,
                    )
                )
            row.status = "committed"
            row.committed_at = now
            enqueue(session, "baseline.recompute", patient.id)
            enqueue(session, "reminder.reconfirm", patient.id)
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "import.commit",
                    "profile_storage",
                    ("import", "telemetry", "profile"),
                    None,
                    "allowed",
                ),
            )
            return {"metrics": len(metrics), "resources": len(resources)}
