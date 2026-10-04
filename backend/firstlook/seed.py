"""One-time synthetic demo seed using the mounted credential secret."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.audit.service import AuditInput, append_event
from firstlook.baseline.models import DailyMetric, HourlyMetric, SyncState
from firstlook.baseline.service import METRICS, recompute
from firstlook.crypto import (
    decrypt_system_field,
    encrypt_system_field,
    lookup_hmac,
    secret_key_from_hex,
)
from firstlook.db import app_sessions, set_patient_scope
from firstlook.demo_credentials import DEMO_DOMAIN, DemoCredential, load_demo_credentials
from firstlook.fhir.ips_builder import PatientIdentity
from firstlook.identity.models import Membership, Organisation, Session, User
from firstlook.identity.security import hash_password, verify_password
from firstlook.identity.service import Principal, register_patient
from firstlook.profile.consents import save_consent
from firstlook.profile.demo_model import DemoPersona
from firstlook.profile.models import Patient
from firstlook.profile.service import owner_patient, put_resource, save_identity
from firstlook.settings import get_settings, read_secret
from firstlook.sharing.service import issue_link


def _patient_principal(user_id: UUID) -> Principal:
    return Principal(user_id, "demo", "patient", None, False, True, "en", "system", bytes(32))


async def _seed_patient(
    persona: str,
    identity: PatientIdentity,
    resources: list[tuple[str, dict[str, Any]]],
    locale: str,
    credential: DemoCredential,
) -> None:
    email, password = credential.email, credential.password
    user_id = await register_patient(email, password, locale, True)
    principal = _patient_principal(user_id)
    await save_identity(principal, identity)
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            for kind in ("essentials_content", "ed_prealert", "wearable_baseline"):
                await save_consent(session, patient, principal, kind, True)
    for section, resource in resources:
        await put_resource(principal, section, resource)
    await issue_link(principal, kind="emergency")
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            session.add(DemoPersona(persona=persona, patient_id=patient.id))


def _anna_resources() -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "allergies",
            {
                "resourceType": "AllergyIntolerance",
                "language": "pl",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                            "code": "active",
                        }
                    ]
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                            "code": "confirmed",
                        }
                    ]
                },
                "category": ["medication"],
                "criticality": "high",
                "code": {"text": "penicylina"},
                "reaction": [
                    {
                        "description": "Anafilaksja (2009)",
                        "manifestation": [{"text": "anafilaksja"}],
                    }
                ],
                "extension": [
                    {
                        "url": "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/allergy-class",
                        "valueString": "penicillin",
                    }
                ],
            },
        ),
        (
            "conditions",
            {
                "resourceType": "Condition",
                "language": "pl",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
                "code": {"text": "migotanie przedsionków"},
            },
        ),
        (
            "conditions",
            {
                "resourceType": "Condition",
                "language": "pl",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
                "code": {"text": "cukrzyca typu 2"},
            },
        ),
        (
            "medications",
            {
                "resourceType": "MedicationStatement",
                "status": "active",
                "medicationCodeableConcept": {
                    "coding": [{"system": "http://www.whocc.no/atc", "code": "B01AF02"}],
                    "text": "apixaban",
                },
            },
        ),
        (
            "medications",
            {
                "resourceType": "MedicationStatement",
                "status": "active",
                "medicationCodeableConcept": {
                    "coding": [{"system": "http://www.whocc.no/atc", "code": "A10BA02"}],
                    "text": "metformin",
                },
            },
        ),
        (
            "devices",
            {
                "resourceType": "Device",
                "status": "active",
                "type": {"coding": [{"system": "http://snomed.info/sct", "code": "14106009"}]},
                "note": [{"text": "Implanted in 2021 (synthetic patient)."}],
            },
        ),
    ]


def _marco_resources() -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "allergies",
            {
                "resourceType": "AllergyIntolerance",
                "language": "it",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                            "code": "active",
                        }
                    ]
                },
                "category": ["medication"],
                "criticality": "high",
                "code": {
                    "coding": [{"system": "http://www.whocc.no/atc", "code": "M01AE01"}],
                    "text": "ibuprofene",
                },
            },
        ),
        (
            "conditions",
            {
                "resourceType": "Condition",
                "language": "it",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
                "code": {
                    "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "E10"}],
                    "text": "diabete di tipo 1",
                },
            },
        ),
        (
            "medications",
            {
                "resourceType": "MedicationStatement",
                "language": "it",
                "status": "active",
                "medicationCodeableConcept": {"text": "insulina (formulazione non specificata)"},
                "extension": [
                    {
                        "url": "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/atc-prefix",
                        "valueString": "A10A",
                    }
                ],
            },
        ),
        (
            "devices",
            {
                "resourceType": "Device",
                "status": "active",
                "type": {"text": "pompa per insulina"},
                "extension": [
                    {
                        "url": "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/device-type",
                        "valueString": "insulin_pump",
                    }
                ],
            },
        ),
    ]


async def _seed_professionals(
    judge_tables: int, credentials_by_label: dict[str, DemoCredential]
) -> None:
    settings = get_settings()
    kek = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_kek"))
    pepper = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_pepper"))
    async with app_sessions()() as session:
        async with session.begin():
            ems = Organisation(
                id=uuid4(),
                name="ZRM Kraków (demo)",
                type="ems",
                facility_code="ZRM-KRK-DEMO",
                tenant="demo",
                active=True,
            )
            ed = Organisation(
                id=uuid4(),
                name="SOR Kraków Centrum (demo)",
                type="ed",
                facility_code="SOR-KRK-DEMO",
                tenant="demo",
                active=True,
            )
            session.add_all((ems, ed))
            await session.flush()
            pending_memberships: list[Membership] = []
            for table in range(1, judge_tables + 1):
                for role, org in (("responder", ems), ("ed_staff", ed)):
                    credential = credentials_by_label[f"{role}_{table}"]
                    email, password = credential.email, credential.password
                    user_id = uuid4()
                    session.add(
                        User(
                            id=user_id,
                            email_hmac=lookup_hmac(pepper, "email", email.casefold()),
                            email_enc=encrypt_system_field(kek, user_id, "email", email.encode()),
                            password_hash=await asyncio.to_thread(hash_password, password),
                            locale="pl",
                            theme="system",
                            kind="professional",
                            tenant="demo",
                            status="active",
                            created_at=datetime.now(UTC),
                        )
                    )
                    pending_memberships.append(
                        Membership(user_id=user_id, org_id=org.id, role=role, active=True)
                    )
            # No ORM relationship links these mapped classes. Flush parent rows
            # explicitly so PostgreSQL checks each membership FK after its user exists.
            await session.flush()
            session.add_all(pending_memberships)


async def _demo_seed_state() -> tuple[set[str], int]:
    """Read only the demo marker and professional count for safe seed resume."""
    async with app_sessions()() as session:
        personas = set(await session.scalars(select(DemoPersona.persona)))
        professional_count = await session.scalar(
            select(func.count())
            .select_from(Membership)
            .join(Organisation, Membership.org_id == Organisation.id)
            .where(
                Organisation.tenant == "demo",
                Membership.role.in_(("responder", "ed_staff")),
            )
        )
    return personas, int(professional_count or 0)


async def _apply_user_credential(
    session: AsyncSession,
    user: User,
    credential: DemoCredential,
    kek: bytes,
    pepper: bytes,
) -> bool:
    """Update a demo login only when it differs and revoke its old sessions."""
    current_email = decrypt_system_field(kek, user.id, "email", user.email_enc).decode("utf-8")
    changed = False
    if current_email.casefold() != credential.email:
        user.email_hmac = lookup_hmac(pepper, "email", credential.email)
        user.email_enc = encrypt_system_field(
            kek, user.id, "email", credential.email.encode("utf-8")
        )
        changed = True
    if not await asyncio.to_thread(verify_password, user.password_hash, credential.password):
        user.password_hash = await asyncio.to_thread(hash_password, credential.password)
        changed = True
    if changed:
        await session.execute(
            update(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    return changed


async def _sync_patient_credential(persona: str, credential: DemoCredential) -> None:
    """Apply the fixed demo login to an existing synthetic patient."""
    settings = get_settings()
    kek = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_kek"))
    pepper = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_pepper"))
    async with app_sessions()() as session:
        async with session.begin():
            patient_id = await session.scalar(
                select(DemoPersona.patient_id).where(DemoPersona.persona == persona)
            )
            if patient_id is None:
                raise RuntimeError("demo persona missing during seed recovery")
            await set_patient_scope(session, patient_id)
            owner_id = await session.scalar(
                select(Patient.owner_user_id).where(Patient.id == patient_id)
            )
            if owner_id is None:
                raise RuntimeError("demo patient missing during seed recovery")
            user = await session.get(User, owner_id)
            if user is None or user.tenant != "demo" or user.kind != "patient":
                raise RuntimeError("demo user missing during seed recovery")
            if await _apply_user_credential(session, user, credential, kek, pepper):
                await append_event(
                    session,
                    AuditInput(
                        patient_id=patient_id,
                        actor_type="system",
                        actor_id=None,
                        org_id=None,
                        role=None,
                        tier=None,
                        action="account.demo_credential_sync",
                        purpose="demo_credential_sync",
                        categories=("credentials",),
                        session_ref=None,
                        outcome="allowed",
                    ),
                )


def _professional_label(
    role: str, email: str, credentials_by_label: dict[str, DemoCredential]
) -> str | None:
    """Resolve both the old generated and the new fixed demo usernames."""
    normalized = email.casefold()
    for label, credential in credentials_by_label.items():
        if label.startswith(f"{role}_") and normalized == credential.email:
            return label
    old_pattern = rf"{re.escape(role)}-(\d+)-[0-9a-f]{{6}}@{re.escape(DEMO_DOMAIN)}"
    match = re.fullmatch(old_pattern, normalized)
    return f"{role}_{match.group(1)}" if match is not None else None


async def _sync_professional_credentials(
    judge_tables: int, credentials_by_label: dict[str, DemoCredential]
) -> None:
    """Map existing demo professionals by role/table and apply fixed logins."""
    settings = get_settings()
    kek = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_kek"))
    pepper = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_pepper"))
    expected = {
        f"{role}_{table}"
        for table in range(1, judge_tables + 1)
        for role in ("responder", "ed_staff")
    }
    matched: set[str] = set()
    async with app_sessions()() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    select(User, Membership, Organisation)
                    .join(Membership, Membership.user_id == User.id)
                    .join(Organisation, Membership.org_id == Organisation.id)
                    .where(
                        User.tenant == "demo",
                        Organisation.tenant == "demo",
                        Membership.active.is_(True),
                    )
                )
            ).all()
            for user, membership, org in rows:
                if user.kind != "professional" or user.status != "active":
                    raise RuntimeError("demo professional account is inconsistent")
                if org.type != ("ems" if membership.role == "responder" else "ed"):
                    raise RuntimeError("demo professional organisation is inconsistent")
                old_email = decrypt_system_field(kek, user.id, "email", user.email_enc).decode(
                    "utf-8"
                )
                label = _professional_label(membership.role, old_email, credentials_by_label)
                if label not in expected or label in matched:
                    raise RuntimeError("demo professional mapping is inconsistent")
                matched.add(label)
                await _apply_user_credential(
                    session, user, credentials_by_label[label], kek, pepper
                )
            if matched != expected:
                raise RuntimeError("demo professional count is inconsistent")


def _synthetic_values(persona: str, index: int) -> dict[str, float]:
    """Deterministic fictional device readings for the jury demo, not medical norms."""
    variation = (index * 7) % 11
    if persona == "marco":
        return {
            "steps": float(7600 + (index % 7) * 300 + variation * 30),
            "active_energy": float(380 + (index % 7) * 18 + variation),
            "resting_hr": float(55 + index % 5),
            "hr_min": float(47 + index % 5),
            "hr_max": float(140 + index % 9),
            "sleep_minutes": float(420 + (index % 6) * 15),
        }
    return {
        "steps": float(3800 + (index % 7) * 180 + variation * 20),
        "active_energy": float(200 + (index % 7) * 10 + variation),
        "resting_hr": float(67 + index % 6),
        "hr_min": float(58 + index % 5),
        "hr_max": float(108 + index % 8),
        "sleep_minutes": float(390 + (index % 6) * 20),
    }


async def _seed_telemetry(persona: str) -> None:
    """Insert 365 fictional days and 14 days of hourly activity for baseline demos."""
    async with app_sessions()() as session:
        async with session.begin():
            patient_id = await session.scalar(
                select(DemoPersona.patient_id).where(DemoPersona.persona == persona)
            )
            if patient_id is None:
                raise RuntimeError("demo persona missing")
            await set_patient_scope(session, patient_id)
            today = datetime.now(UTC).date()
            for offset in range(365, 0, -1):
                day = today - timedelta(days=offset)
                values = _synthetic_values(persona, 365 - offset)
                for metric, value in values.items():
                    session.add(
                        DailyMetric(
                            patient_id=patient_id,
                            day=day,
                            metric=metric,
                            value=value,
                            unit=METRICS[metric],
                            source="synthetic_demo",
                        )
                    )
                if offset <= 14:
                    weights = [
                        3 if 7 <= hour <= 9 else 1 if 6 <= hour <= 22 else 0 for hour in range(24)
                    ]
                    total_weight = sum(weights)
                    for hour, weight in enumerate(weights):
                        for metric in ("steps", "active_energy"):
                            session.add(
                                HourlyMetric(
                                    patient_id=patient_id,
                                    hour=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
                                    metric=metric,
                                    value=values[metric] * weight / total_weight,
                                )
                            )
            session.add(
                SyncState(
                    patient_id=patient_id,
                    last_sync_at=datetime.now(UTC) - timedelta(days=1),
                    last_activity_at=datetime.now(UTC) - timedelta(days=1),
                    source="synthetic_demo",
                )
            )
            await session.flush()
            await recompute(session, patient_id, today)


async def seed() -> None:
    settings = get_settings()
    if settings.fl_env != "demo" or not settings.fl_demo_tenant_enabled:
        raise SystemExit("demo seed requires the demo tenant")
    credentials = load_demo_credentials(
        settings.fl_secret_dir / "demo_credentials", settings.fl_demo_judge_tables
    )
    personas, professional_count = await _demo_seed_state()
    expected_professionals = 2 * settings.fl_demo_judge_tables
    if personas == {"anna", "marco"} and professional_count == expected_professionals:
        await _sync_patient_credential("anna", credentials["patient_anna"])
        await _sync_patient_credential("marco", credentials["patient_marco"])
        await _sync_professional_credentials(settings.fl_demo_judge_tables, credentials)
        print("Demo accounts ready. Use the mounted demo credential file for judge cards.")
        return
    if personas not in (set(), {"anna", "marco"}) or professional_count:
        raise RuntimeError("demo seed state is inconsistent; inspect it before retrying")
    if personas:
        # The previous run committed both synthetic patients before the
        # professional transaction failed. Keep their profiles and links.
        await _sync_patient_credential("anna", credentials["patient_anna"])
        await _sync_patient_credential("marco", credentials["patient_marco"])
    else:
        await _seed_patient(
            "anna",
            PatientIdentity("Anna", "Kowalska", None, "female", "70-79"),
            _anna_resources(),
            "pl",
            credentials["patient_anna"],
        )
        await _seed_patient(
            "marco",
            PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male"),
            _marco_resources(),
            "it",
            credentials["patient_marco"],
        )
        await _seed_telemetry("anna")
        await _seed_telemetry("marco")
    await _seed_professionals(settings.fl_demo_judge_tables, credentials)
    print("Demo accounts ready. Use the mounted demo credential file for judge cards.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
