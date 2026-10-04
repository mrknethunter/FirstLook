"""Public SMART Health Link manifest endpoint with server-selected tiers."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from firstlook.authz import AccessDenied, route_policy
from firstlook.identity.router import SESSION_COOKIE
from firstlook.identity.service import AuthenticationError, load_principal
from firstlook.sharing.manifest import ManifestFailure, ManifestInput, resolve_manifest
from firstlook.terminology.router import preferred_language

router = APIRouter(prefix="/api/shl/m", tags=["shl"])


class ManifestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    recipient: str | None = Field(default=None, max_length=280)
    passcode: str | None = Field(default=None, max_length=64)
    embedded_length_max: int | None = Field(
        default=None, alias="embeddedLengthMax", ge=1000, le=2_000_000
    )
    fl_mode: Literal["break_glass", "responder"] | None = None
    fl_reason: str | None = Field(default=None, max_length=280)
    fl_acknowledge: bool = False


TRANSLATIONS = {
    "Emergency access requires explicit acknowledgement": {
        "pl": "Dostęp awaryjny wymaga wyraźnego potwierdzenia",
        "it": "L'accesso di emergenza richiede una conferma esplicita",
    },
    "Emergency access requires a reason of 10 to 280 characters": {
        "pl": "Dostęp awaryjny wymaga uzasadnienia od 10 do 280 znaków",
        "it": "L'accesso di emergenza richiede una motivazione di 10–280 caratteri",
    },
    "Use an authorised responder account or emergency access": {
        "pl": "Użyj konta ratownika lub dostępu awaryjnego",
        "it": "Usa un account di soccorritore o l'accesso di emergenza",
    },
}


def _problem(request: Request, error: ManifestFailure) -> JSONResponse:
    language = preferred_language(request.headers.get("accept-language", ""))
    title = TRANSLATIONS.get(error.title, {}).get(language, error.title)
    content: dict[str, str | int] = {
        "type": "about:blank",
        "title": title,
        "status": error.status,
        "instance": request.state.request_id,
    }
    if error.remaining_attempts is not None:
        content["remainingAttempts"] = error.remaining_attempts
    return JSONResponse(
        status_code=error.status, content=content, media_type="application/problem+json"
    )


@router.post("/{manifest_id}")
@route_policy("shl.manifest.resolve")
async def manifest(request: Request, manifest_id: str, body: ManifestBody) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    try:
        principal = await load_principal(token) if token else None
    except AuthenticationError:
        return _problem(request, ManifestFailure(401, "Authentication required"))
    source_ip = request.client.host if request.client else "unknown"
    try:
        resolved = await resolve_manifest(
            manifest_id,
            ManifestInput(
                body.recipient,
                body.embedded_length_max,
                body.fl_mode,
                body.fl_reason,
                body.fl_acknowledge,
                body.passcode,
            ),
            principal,
            source_ip,
        )
    except ManifestFailure as exc:
        return _problem(request, exc)
    except AccessDenied:
        return _problem(
            request, ManifestFailure(403, "Use an authorised responder account or emergency access")
        )
    response = JSONResponse({"files": resolved.files, "status": resolved.status})
    if resolved.emergency_session_id is not None:
        response.headers["FL-Emergency-Session"] = str(resolved.emergency_session_id)
    return response
