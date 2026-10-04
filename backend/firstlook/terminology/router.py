"""Owner-only catalogue search over documented medication entries."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from firstlook.authz import route_policy
from firstlook.db import app_sessions
from firstlook.identity.router import current_principal
from firstlook.identity.service import Principal
from firstlook.profile.service import owner_patient
from firstlook.terminology.models import CodeDisplay, MedProduct

router = APIRouter(prefix="/api/v1/terminology", tags=["terminology"])


def preferred_language(header: str) -> str:
    """Select a supported language from an Accept-Language preference list."""
    ranked: list[tuple[float, int, str]] = []
    for index, item in enumerate(header.split(",")):
        parts = item.strip().split(";")
        language = parts[0].split("-", 1)[0].lower()
        if language not in {"en", "pl", "it"}:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.strip().startswith("q="):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0.0
        if 0 < quality <= 1:
            ranked.append((quality, -index, language))
    return max(ranked)[2] if ranked else "en"


@router.get("/display")
@route_policy("public.terminology.display")
async def display_code(
    request: Request,
    system: Annotated[str, Query(min_length=8, max_length=200)],
    code: Annotated[str, Query(min_length=1, max_length=80)],
) -> dict[str, str | None]:
    """Return only curated code labels; unknown codes retain their original display."""
    language = preferred_language(request.headers.get("accept-language", ""))
    async with app_sessions()() as session:
        display = await session.get(CodeDisplay, (system, code, language))
        return {
            "system": system,
            "code": code,
            "language": language,
            "display": display.display if display else None,
        }


@router.get("/medications")
@route_policy("patient.terminology.medications")
async def search_medications(
    principal: Annotated[Principal, Depends(current_principal)],
    q: Annotated[str, Query(min_length=2, max_length=80)],
) -> list[dict[str, Any]]:
    """Search a small curated catalogue; literal wildcard characters stay literal."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    async with app_sessions()() as session:
        async with session.begin():
            await owner_patient(session, principal)
            rows = (
                await session.scalars(
                    select(MedProduct)
                    .where(MedProduct.name.ilike(f"%{escaped}%", escape="\\"))
                    .order_by(MedProduct.name)
                    .limit(20)
                )
            ).all()
            return [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "strength": row.strength,
                    "form": row.form,
                    "atc_code": row.atc_code,
                    "substances": row.substances,
                    "source": row.source,
                    "code_verified": row.code_verified,
                }
                for row in rows
            ]
