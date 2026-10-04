"""Responder and ED routes without patient search or broad identifiers."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from firstlook.authz import route_policy
from firstlook.identity.router import current_principal
from firstlook.identity.service import Principal
from firstlook.sharing import handoffs
from firstlook.sharing.models import Handoff

responder_router = APIRouter(prefix="/api/v1", tags=["responder"])
ed_router = APIRouter(prefix="/api/v1/ed", tags=["ed"])
Actor = Annotated[Principal, Depends(current_principal)]


class Observations(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    heart_rate: float | None = None
    blood_pressure: str | None = Field(default=None, max_length=32)
    spo2: float | None = None
    respiratory_rate: float | None = None
    temperature: float | None = None
    glucose: float | None = None
    gcs: int | None = None
    avpu: Literal["A", "V", "P", "U"] | None = None


class PrealertInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_id: UUID
    eta_minutes: int = Field(ge=0, le=1440)
    priority: Literal["red", "orange", "yellow", "green"]
    observations: Observations
    notes: str | None = Field(default=None, max_length=2000)


class PrealertPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eta_minutes: int | None = Field(default=None, ge=0, le=1440)
    priority: Literal["red", "orange", "yellow", "green"] | None = None
    observations: Observations | None = None
    notes: str | None = Field(default=None, max_length=2000)


class HandoffOut(BaseModel):
    id: UUID
    status: str
    priority: str
    eta_minutes: int
    facility_id: UUID


def _view(item: Handoff) -> HandoffOut:
    return HandoffOut(
        id=item.id,
        status=item.status,
        priority=item.priority,
        eta_minutes=item.eta_minutes,
        facility_id=item.to_facility_id,
    )


@responder_router.get("/facilities")
@route_policy("responder.facilities.list")
async def facilities(principal: Actor, type: Literal["ed"] = "ed") -> list[dict[str, str]]:
    del type
    rows = await handoffs.facilities(principal)
    return [{"id": str(row.id), "name": row.name} for row in rows]


@responder_router.post("/handoffs", status_code=201, response_model=HandoffOut)
@route_policy("responder.handoff.create")
async def create_handoff(
    body: PrealertInput,
    principal: Actor,
    emergency_session: Annotated[UUID, Header(alias="FL-Emergency-Session")],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> HandoffOut:
    try:
        result = await handoffs.create_handoff(
            principal,
            emergency_session,
            idempotency_key,
            handoffs.Prealert(
                body.facility_id,
                body.eta_minutes,
                body.priority,
                body.observations.model_dump(exclude_none=True),
                body.notes,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409) from exc
    return _view(result)


@responder_router.patch("/handoffs/{handoff_id}", response_model=HandoffOut)
@route_policy("responder.handoff.update")
async def update_handoff(
    handoff_id: UUID,
    body: PrealertPatch,
    principal: Actor,
    emergency_session: Annotated[UUID, Header(alias="FL-Emergency-Session")],
) -> HandoffOut:
    if not body.model_fields_set:
        raise HTTPException(status_code=422)
    return _view(
        await handoffs.update_handoff(
            principal,
            emergency_session,
            handoff_id,
            eta_minutes=body.eta_minutes,
            priority=body.priority,
            observations=(
                body.observations.model_dump(exclude_none=True)
                if body.observations is not None
                else None
            ),
            notes=body.notes,
            update_notes="notes" in body.model_fields_set,
        )
    )


@ed_router.get("/board", response_model=list[HandoffOut])
@route_policy("ed.board.read")
async def board(principal: Actor) -> list[HandoffOut]:
    return [_view(item) for item in await handoffs.board(principal)]


@ed_router.get("/handoffs/{handoff_id}")
@route_policy("ed.handoff.read")
async def detail(handoff_id: UUID, principal: Actor) -> dict[str, object]:
    return await handoffs.handoff_detail(principal, handoff_id)


@ed_router.post("/handoffs/{handoff_id}/{action}", response_model=HandoffOut)
@route_policy("ed.handoff.transition")
async def transition(
    handoff_id: UUID,
    action: Literal["ack", "arrive", "close", "cancel"],
    principal: Actor,
) -> HandoffOut:
    try:
        return _view(await handoffs.transition(principal, handoff_id, action))
    except ValueError as exc:
        raise HTTPException(status_code=409) from exc
