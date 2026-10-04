"""Patient-only profile, IPS and Essentials API routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from firstlook.authz import route_policy
from firstlook.db import app_sessions
from firstlook.fhir.ips_builder import PatientIdentity
from firstlook.identity.router import current_principal
from firstlook.identity.service import Principal
from firstlook.profile import service
from firstlook.profile.consents import CONSENT_TYPES, latest_consents, save_consent

router = APIRouter(prefix="/api/v1/patients/me", tags=["profile"])
Section = Literal["allergies", "medications", "conditions", "devices"]
Owner = Annotated[Principal, Depends(current_principal)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityInput(StrictModel):
    given: str = Field(min_length=1, max_length=100)
    family: str = Field(min_length=1, max_length=100)
    birth_date: date | None = None
    gender: Literal["male", "female", "other", "unknown"] | None = None
    age_band: str | None = Field(default=None, pattern=r"^\d{1,3}-\d{1,3}$")


class EssentialsInput(StrictModel):
    items: set[str] = Field(max_length=200)
    show_sex: bool = False


class ContactInput(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    relationship: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=5, max_length=32)
    preferred_language: Literal["en", "pl", "it"]
    notify_on_access: bool = False


class ConsentInput(StrictModel):
    granted: bool


def _invalid(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail="invalid profile data")


@router.get("")
@route_policy("patient.profile.read")
async def profile(principal: Owner) -> dict[str, Any]:
    return service.profile_summary(await service.load_profile(principal))


@router.put("/identity")
@route_policy("patient.identity.write")
async def update_identity(body: IdentityInput, principal: Owner) -> dict[str, str]:
    await service.save_identity(
        principal,
        PatientIdentity(body.given, body.family, body.birth_date, body.gender, body.age_band),
    )
    return {"status": "saved"}


@router.get("/consents")
@route_policy("patient.consents.read")
async def consents(principal: Owner) -> dict[str, bool]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await service.owner_patient(session, principal)
            return await latest_consents(session, patient.id)


@router.put("/consents/{kind}")
@route_policy("patient.consents.write")
async def update_consent(kind: str, body: ConsentInput, principal: Owner) -> dict[str, str | bool]:
    if kind not in CONSENT_TYPES:
        raise HTTPException(status_code=404)
    async with app_sessions()() as session:
        async with session.begin():
            patient = await service.owner_patient(session, principal)
            try:
                await save_consent(session, patient, principal, kind, body.granted)
            except ValueError as exc:
                raise _invalid(exc) from exc
    return {"kind": kind, "granted": body.granted}


@router.get("/ips")
@route_policy("patient.ips.read")
async def ips(principal: Owner) -> dict[str, Any]:
    return service.ips_for_owner(await service.load_profile(principal))


@router.get("/essentials")
@route_policy("patient.essentials.read")
async def essentials(principal: Owner) -> dict[str, Any]:
    data = await service.load_profile(principal)
    return {"items": sorted(data.selected_ids), "show_sex": data.show_sex}


@router.put("/essentials")
@route_policy("patient.essentials.write")
async def update_essentials(body: EssentialsInput, principal: Owner) -> dict[str, Any]:
    try:
        return await service.save_essentials(principal, body.items, body.show_sex)
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.get("/essentials/preview")
@route_policy("patient.essentials.preview")
async def preview_essentials(principal: Owner) -> dict[str, Any]:
    return service.essentials_preview(await service.load_profile(principal))


@router.get("/contacts")
@route_policy("patient.contacts.read")
async def contacts(principal: Owner) -> list[dict[str, Any]]:
    return await service.list_contacts(principal)


@router.post("/contacts", status_code=201)
@route_policy("patient.contacts.create")
async def create_contact(body: ContactInput, principal: Owner) -> dict[str, Any]:
    try:
        return await service.add_contact(principal, body.model_dump())
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.delete("/contacts/{contact_id}", status_code=204)
@route_policy("patient.contacts.delete")
async def remove_contact(contact_id: UUID, principal: Owner) -> None:
    await service.delete_contact(principal, contact_id)


@router.get("/{section}")
@route_policy("patient.section.read")
async def list_resources(section: Section, principal: Owner) -> list[dict[str, Any]]:
    return await service.list_section(principal, section)


@router.post("/{section}", status_code=201)
@route_policy("patient.section.create")
async def create_resource(
    section: Section, body: dict[str, Any], principal: Owner
) -> dict[str, Any]:
    try:
        if section == "medications":
            body = await service.resolve_medication_input(principal, body)
        return await service.put_resource(principal, section, body)
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.put("/{section}/{resource_id}")
@route_policy("patient.section.update")
async def update_resource(
    section: Section, resource_id: UUID, body: dict[str, Any], principal: Owner
) -> dict[str, Any]:
    try:
        if section == "medications":
            body = await service.resolve_medication_input(principal, body)
        return await service.put_resource(principal, section, body, resource_id)
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.delete("/{section}/{resource_id}", status_code=204)
@route_policy("patient.section.delete")
async def remove_resource(section: Section, resource_id: UUID, principal: Owner) -> None:
    await service.delete_resource(principal, section, resource_id)
