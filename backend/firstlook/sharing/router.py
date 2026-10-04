"""Owner link lifecycle and the stable demo entry API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from firstlook.authz import route_policy
from firstlook.identity.router import current_principal
from firstlook.identity.service import Principal
from firstlook.sharing import service
from firstlook.sharing.carriers import CarrierKind, render_carrier

patient_router = APIRouter(prefix="/api/v1/patients/me/links", tags=["links"])
demo_router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
Owner = Annotated[Principal, Depends(current_principal)]


class LinkIssueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["emergency", "clinician"]
    passcode: str | None = Field(default=None, max_length=64)
    expires_at: datetime | None = None


class LinkOut(BaseModel):
    id: UUID
    kind: str
    status: str
    label: str
    expires_at: datetime | None
    url: str | None


@patient_router.get("", response_model=list[LinkOut])
@route_policy("patient.links.read")
async def links(principal: Owner) -> list[LinkOut]:
    return [LinkOut.model_validate(item.__dict__) for item in await service.list_links(principal)]


@patient_router.post("", status_code=201, response_model=LinkOut)
@route_policy("patient.links.issue")
async def issue(body: LinkIssueInput, principal: Owner) -> LinkOut:
    try:
        item = await service.issue_link(
            principal, kind=body.kind, passcode=body.passcode, expires_at=body.expires_at
        )
    except ValueError as exc:
        raise HTTPException(status_code=422) from exc
    return LinkOut.model_validate(item.__dict__)


@patient_router.post("/{link_id}/rotate", response_model=LinkOut)
@route_policy("patient.links.rotate")
async def rotate(link_id: UUID, principal: Owner) -> LinkOut:
    try:
        item = await service.rotate_link(principal, link_id)
    except ValueError as exc:
        raise HTTPException(status_code=409) from exc
    return LinkOut.model_validate(item.__dict__)


@patient_router.get("/{link_id}/carriers/{kind}")
@route_policy("patient.links.carrier")
async def carrier(link_id: UUID, kind: CarrierKind, principal: Owner) -> Response:
    try:
        url = await service.carrier_url(principal, link_id)
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    payload, media_type = render_carrier(url, kind)
    headers = (
        {"Content-Disposition": 'attachment; filename="firstlook-cards.pdf"'}
        if kind == "cards.pdf"
        else {}
    )
    return Response(content=payload, media_type=media_type, headers=headers)


@patient_router.delete("/{link_id}", status_code=204)
@route_policy("patient.links.revoke")
async def revoke(link_id: UUID, principal: Owner) -> None:
    await service.revoke_link(principal, link_id)


@demo_router.get("/entry")
@route_policy("demo.entry")
async def demo_entry() -> dict[str, str]:
    try:
        return {"viewer_url": await service.demo_entry()}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=404) from exc
