"""Access history and authenticated subject-bound SSE endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from firstlook.authz import AccessDenied, route_policy
from firstlook.db import app_sessions
from firstlook.identity.router import SESSION_COOKIE, current_principal
from firstlook.identity.service import Principal
from firstlook.profile.service import owner_patient
from firstlook.sharing.events import access_history, listen_events

patient_events = APIRouter(prefix="/api/v1/patients/me", tags=["access"])
ed_events = APIRouter(prefix="/api/v1/ed", tags=["ed"])
Owner = Annotated[Principal, Depends(current_principal)]


@patient_events.get("/access-log")
@route_policy("patient.access_log.read")
async def access_log(
    principal: Owner,
    tier: Literal["T1", "T2", "T3", "T4"] | None = None,
    since: date | None = None,
    before: date | None = None,
    after_seq: int = 0,
) -> list[dict[str, object]]:
    return await access_history(
        principal, tier=tier, since=since, before=before, after_seq=after_seq
    )


@patient_events.get("/notifications/stream")
@route_policy("patient.notifications.stream")
async def patient_stream(
    request: Request,
    principal: Owner,
    last_event_id: Annotated[int, Header(alias="Last-Event-ID", ge=0)] = 0,
) -> StreamingResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise AccessDenied("access denied")
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            channel = f"fl_patient_{patient.id.hex}"
    return StreamingResponse(
        listen_events(
            channel, token=token, principal=principal, last_id=last_event_id, patient=True
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


@ed_events.get("/board/stream")
@route_policy("ed.board.stream")
async def ed_stream(request: Request, principal: Owner) -> StreamingResponse:
    if principal.role != "ed_staff" or principal.org_id is None or not principal.org_active:
        raise AccessDenied("access denied")
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise AccessDenied("access denied")
    return StreamingResponse(
        listen_events(
            f"fl_ed_{principal.org_id.hex}", token=token, principal=principal, patient=False
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
