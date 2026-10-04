"""Owner-scoped encrypted profile operations and tier projections."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.audit.service import AuditInput, append_event
from firstlook.authz import AccessContext, AccessDenied, Action, require
from firstlook.crypto import (
    decrypt_patient_field,
    encrypt_patient_field,
    secret_key_from_hex,
    unwrap_dek,
)
from firstlook.db import app_sessions, set_patient_scope, vault_sessions
from firstlook.fhir.ips_builder import (
    PatientIdentity,
    build_essentials_bundle,
    build_ips_bundle,
)
from firstlook.fhir.validation import validate_fhir_resource
from firstlook.identity.service import Principal
from firstlook.profile.models import Contact, EssentialsSelection, Patient, Resource, VaultPerson
from firstlook.rules.engine import DEVICE_TYPE_URL, Flag, evaluate_flags, load_rules
from firstlook.settings import get_settings, read_secret
from firstlook.terminology.models import MedProduct

SECTION_TYPES = {
    "allergies": "AllergyIntolerance",
    "medications": "MedicationStatement",
    "conditions": "Condition",
    "devices": "Device",
}
RULES = load_rules(Path(__file__).resolve().parents[2] / "rules" / "emergency_v1.yaml")


@dataclass(frozen=True)
class ProfileData:
    patient_id: UUID
    identity: PatientIdentity
    resources: list[dict[str, Any]]
    flags: list[Flag]
    selected_ids: set[str]
    show_sex: bool


def _dek(patient: Patient) -> bytes:
    kek = secret_key_from_hex(read_secret(get_settings().fl_secret_dir / "fl_kek"))
    return unwrap_dek(kek, patient.dek_wrapped, patient.id, patient.dek_version, patient.kek_id)


def _context(principal: Principal) -> AccessContext:
    return AccessContext(
        actor_id=principal.user_id,
        role=principal.role,
        tenant=principal.tenant,
        org_id=principal.org_id,
        org_active=principal.org_active,
        mfa_passed=principal.mfa_passed,
    )


async def owner_patient(session: AsyncSession, principal: Principal) -> Patient:
    """Resolve the signed-in owner and set transaction-local patient RLS scope."""
    if principal.role != "patient":
        raise AccessDenied("access denied")
    patient_id = await session.scalar(
        text("SELECT clinical.patient_id_for_owner(:owner_id)"),
        {"owner_id": principal.user_id},
    )
    if patient_id is None:
        raise AccessDenied("access denied")
    await set_patient_scope(session, patient_id)
    patient = await session.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise AccessDenied("access denied")
    require(
        Action.EDIT_PROFILE,
        _context(principal),
        resource_tenant=principal.tenant,
        patient_id=patient.id,
        owner_user_id=patient.owner_user_id,
    )
    return patient


async def patient_identity(patient: Patient) -> PatientIdentity:
    """Read direct identifiers only through the vault connection and role."""
    dek = _dek(patient)
    async with vault_sessions()() as session:
        async with session.begin():
            await set_patient_scope(session, patient.id)
            person = await session.get(VaultPerson, patient.id)
            if person is None:
                return PatientIdentity("", "", None, None)

            def field(name: str, ciphertext: bytes | None) -> str:
                if ciphertext is None:
                    return ""
                return decrypt_patient_field(
                    dek, patient.id, uuid5(patient.id, name), 1, ciphertext
                ).decode("utf-8")

            birth = field("birth_date", person.birth_date_enc)
            return PatientIdentity(
                field("given", person.given_enc),
                field("family", person.family_enc),
                date.fromisoformat(birth) if birth else None,
                field("gender", person.gender_enc) or None,
                field("age_band", person.age_band_enc) or None,
            )


def _decode_resource(row: Resource, dek: bytes) -> dict[str, Any]:
    plaintext = decrypt_patient_field(dek, row.patient_id, row.id, row.version, row.fhir_enc)
    value: dict[str, Any] = json.loads(plaintext)
    return value


async def _resources(session: AsyncSession, patient: Patient) -> list[dict[str, Any]]:
    dek = _dek(patient)
    rows = (
        await session.scalars(
            select(Resource)
            .where(Resource.patient_id == patient.id, Resource.status != "deleted")
            .order_by(Resource.updated_at.desc())
        )
    ).all()
    return [_decode_resource(row, dek) for row in rows]


def _default_selection(resources: list[dict[str, Any]], flags: list[Flag]) -> set[str]:
    """Use the specified minimal defaults until the owner saves a selection."""

    def key_condition(item: dict[str, Any]) -> bool:
        return any(
            coding.get("system") == "http://hl7.org/fhir/sid/icd-10" and coding.get("code") == "E10"
            for coding in item.get("code", {}).get("coding", [])
        )

    def key_device(item: dict[str, Any]) -> bool:
        coded = any(
            coding.get("system") == "http://snomed.info/sct" and coding.get("code") == "14106009"
            for coding in item.get("type", {}).get("coding", [])
        )
        pump = any(
            extension.get("url") == DEVICE_TYPE_URL
            and extension.get("valueString") == "insulin_pump"
            for extension in item.get("extension", [])
        )
        return coded or pump

    selected = {
        str(item["id"])
        for item in resources
        if item.get("id")
        and (
            (item.get("resourceType") == "AllergyIntolerance" and item.get("criticality") == "high")
            or (item.get("resourceType") == "Condition" and key_condition(item))
            or (item.get("resourceType") == "Device" and key_device(item))
        )
    }
    selected.update(
        f"flag:{flag.rule_id}"
        for flag in flags
        if flag.show_in_essentials and flag.severity in {"critical", "high"}
    )
    return selected


async def _selection(
    session: AsyncSession, patient: Patient, resources: list[dict[str, Any]], flags: list[Flag]
) -> tuple[set[str], bool]:
    selection = await session.get(EssentialsSelection, patient.id)
    if selection is None:
        return _default_selection(resources, flags), False
    return set(selection.items), selection.show_sex


async def load_profile(principal: Principal) -> ProfileData:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            resources = await _resources(session, patient)
            flags = evaluate_flags(resources, RULES)
            selected, show_sex = await _selection(session, patient, resources, flags)
            identity = await patient_identity(patient)
            return ProfileData(patient.id, identity, resources, flags, selected, show_sex)


async def list_section(principal: Principal, section: str) -> list[dict[str, Any]]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            dek = _dek(patient)
            rows = (
                await session.scalars(
                    select(Resource)
                    .where(
                        Resource.patient_id == patient.id,
                        Resource.rtype == SECTION_TYPES[section],
                        Resource.status != "deleted",
                    )
                    .order_by(Resource.updated_at.desc())
                )
            ).all()
            return [
                {
                    "resource": _decode_resource(row, dek),
                    "provenance": {
                        "source": row.source,
                        "imported_at": row.imported_at.isoformat() if row.imported_at else None,
                        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
                        "updated_at": row.updated_at.isoformat(),
                    },
                }
                for row in rows
            ]


async def put_resource(
    principal: Principal, section: str, payload: dict[str, Any], resource_id: UUID | None = None
) -> dict[str, Any]:
    """Validate and seal a FHIR resource; never persist clinical codes in clear."""
    rtype = SECTION_TYPES[section]
    if payload.get("resourceType") != rtype or set(payload) & {
        "identifier",
        "contained",
        "text",
        "meta",
    }:
        raise ValueError("invalid profile resource")
    row_id = resource_id or uuid4()
    candidate = {**payload, "id": str(row_id)}
    if rtype in {"AllergyIntolerance", "Device"}:
        candidate["patient"] = {"reference": "Patient/self"}
    if rtype in {"MedicationStatement", "Condition"}:
        candidate["subject"] = {"reference": "Patient/self"}
    valid = validate_fhir_resource(candidate)
    now = datetime.now(UTC)
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            row = await session.get(Resource, row_id, with_for_update=True) if resource_id else None
            if resource_id and (row is None or row.patient_id != patient.id or row.rtype != rtype):
                raise AccessDenied("access denied")
            version = row.version + 1 if row else 1
            ciphertext = encrypt_patient_field(
                _dek(patient),
                patient.id,
                row_id,
                version,
                json.dumps(valid, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            )
            if row:
                row.fhir_enc = ciphertext
                row.version = version
                row.status = "active"
                row.updated_at = now
                row.confirmed_at = now
            else:
                session.add(
                    Resource(
                        id=row_id,
                        patient_id=patient.id,
                        rtype=rtype,
                        status="active",
                        version=version,
                        fhir_enc=ciphertext,
                        source="manual",
                        imported_at=None,
                        confirmed_at=now,
                        updated_at=now,
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
                    "profile.update" if row else "profile.create",
                    "profile_storage",
                    (section,),
                    None,
                    "allowed",
                ),
            )
    return valid


async def delete_resource(principal: Principal, section: str, resource_id: UUID) -> None:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            row = await session.get(Resource, resource_id, with_for_update=True)
            if row is None or row.patient_id != patient.id or row.rtype != SECTION_TYPES[section]:
                raise AccessDenied("access denied")
            row.status = "deleted"
            row.updated_at = datetime.now(UTC)
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "profile.delete",
                    "profile_storage",
                    (section,),
                    None,
                    "allowed",
                ),
            )


async def save_essentials(principal: Principal, items: set[str], show_sex: bool) -> dict[str, Any]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            resources = await _resources(session, patient)
            flags = evaluate_flags(resources, RULES)
            choices = {str(item["id"]) for item in resources if item.get("id")}
            choices.update(f"flag:{flag.rule_id}" for flag in flags if flag.show_in_essentials)
            if not items <= choices:
                raise ValueError("invalid Essentials selection")
            row = await session.get(EssentialsSelection, patient.id)
            if row is None:
                session.add(
                    EssentialsSelection(
                        patient_id=patient.id,
                        items=sorted(items),
                        show_sex=show_sex,
                        updated_at=datetime.now(UTC),
                    )
                )
            else:
                row.items = sorted(items)
                row.show_sex = show_sex
                row.updated_at = datetime.now(UTC)
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "essentials.update",
                    "essentials_content",
                    ("essentials",),
                    None,
                    "allowed",
                ),
            )
    return {"items": sorted(items), "show_sex": show_sex}


def profile_summary(data: ProfileData) -> dict[str, Any]:
    present = {str(item.get("resourceType")) for item in data.resources}
    return {
        "patient_id": str(data.patient_id),
        "name": {"given": data.identity.given, "family": data.identity.family},
        "birth_date": data.identity.birth_date.isoformat() if data.identity.birth_date else None,
        "sections": {section: rtype in present for section, rtype in SECTION_TYPES.items()},
        "flags": [
            {"id": flag.rule_id, "severity": flag.severity, "text_key": flag.text_key}
            for flag in data.flags
        ],
        "essentials": {"items": sorted(data.selected_ids), "show_sex": data.show_sex},
    }


def ips_for_owner(data: ProfileData) -> dict[str, Any]:
    return build_ips_bundle(data.identity, data.resources, data.flags)


def essentials_preview(data: ProfileData) -> dict[str, Any]:
    return build_essentials_bundle(
        data.identity, data.resources, data.selected_ids, data.flags, show_sex=data.show_sex
    )


async def resolve_medication_input(principal: Principal, payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve a chosen catalogue product or mark a free-text entry unresolved."""
    if "product_id" in payload:
        if set(payload) != {"product_id"}:
            raise ValueError("invalid medication product")
        try:
            product_id = UUID(str(payload["product_id"]))
        except ValueError as exc:
            raise ValueError("invalid medication product") from exc
        async with app_sessions()() as session:
            async with session.begin():
                await owner_patient(session, principal)
                product = await session.get(MedProduct, product_id)
                if product is None:
                    raise ValueError("invalid medication product")
                concept: dict[str, Any] = {"text": product.name}
                if product.atc_code and product.code_verified:
                    concept["coding"] = [
                        {"system": "http://www.whocc.no/atc", "code": product.atc_code}
                    ]
                return {
                    "resourceType": "MedicationStatement",
                    "status": "active",
                    "medicationCodeableConcept": concept,
                    "subject": {"reference": "Patient/self"},
                    "extension": [
                        {
                            "url": "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/active-substances",
                            "valueString": ", ".join(product.substances),
                        }
                    ],
                }
    if "free_text" in payload:
        if set(payload) != {"free_text"}:
            raise ValueError("invalid free-text medication")
        free_text = payload["free_text"]
        if not isinstance(free_text, str) or not 1 <= len(free_text.strip()) <= 200:
            raise ValueError("invalid free-text medication")
        return {
            "resourceType": "MedicationStatement",
            "status": "active",
            "medicationCodeableConcept": {"text": free_text.strip()},
            "subject": {"reference": "Patient/self"},
            "extension": [
                {
                    "url": "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/unresolved",
                    "valueBoolean": True,
                }
            ],
        }
    return payload


async def save_identity(principal: Principal, identity: PatientIdentity) -> None:
    """Keep direct identifiers in the vault role and emit a profile audit event."""
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            dek = _dek(patient)

            def seal(name: str, value: str | None) -> bytes | None:
                if not value:
                    return None
                return encrypt_patient_field(
                    dek, patient.id, uuid5(patient.id, name), 1, value.encode("utf-8")
                )

            async with vault_sessions()() as vault:
                async with vault.begin():
                    await set_patient_scope(vault, patient.id)
                    person = await vault.get(VaultPerson, patient.id)
                    if person is None:
                        person = VaultPerson(patient_id=patient.id)
                        vault.add(person)
                    person.given_enc = seal("given", identity.given)
                    person.family_enc = seal("family", identity.family)
                    person.birth_date_enc = seal(
                        "birth_date",
                        identity.birth_date.isoformat() if identity.birth_date else None,
                    )
                    person.gender_enc = seal("gender", identity.gender)
                    person.age_band_enc = seal("age_band", identity.age_band)
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "identity.update",
                    "profile_storage",
                    ("identity",),
                    None,
                    "allowed",
                ),
            )


async def list_contacts(principal: Principal) -> list[dict[str, Any]]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            dek = _dek(patient)
            rows = (
                await session.scalars(select(Contact).where(Contact.patient_id == patient.id))
            ).all()
            return [
                {
                    "id": str(row.id),
                    **json.loads(decrypt_patient_field(dek, patient.id, row.id, 1, row.data_enc)),
                    "notify_on_access": row.notify_on_access,
                }
                for row in rows
            ]


async def add_contact(principal: Principal, contact: dict[str, Any]) -> dict[str, Any]:
    """Enforce the five-contact cap inside a patient-scoped transaction."""
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            await session.refresh(patient, with_for_update=True)
            rows = (
                await session.scalars(select(Contact.id).where(Contact.patient_id == patient.id))
            ).all()
            if len(rows) >= 5:
                raise ValueError("contact limit reached")
            row_id = uuid4()
            notify = bool(contact.pop("notify_on_access", False))
            session.add(
                Contact(
                    id=row_id,
                    patient_id=patient.id,
                    data_enc=encrypt_patient_field(
                        _dek(patient),
                        patient.id,
                        row_id,
                        1,
                        json.dumps(contact, separators=(",", ":")).encode("utf-8"),
                    ),
                    notify_on_access=notify,
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
                    "contact.create",
                    "profile_storage",
                    ("contacts",),
                    None,
                    "allowed",
                ),
            )
    return {"id": str(row_id), **contact, "notify_on_access": notify}


async def delete_contact(principal: Principal, contact_id: UUID) -> None:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            row = await session.get(Contact, contact_id, with_for_update=True)
            if row is None or row.patient_id != patient.id:
                raise AccessDenied("access denied")
            await session.delete(row)
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "contact.delete",
                    "profile_storage",
                    ("contacts",),
                    None,
                    "allowed",
                ),
            )
