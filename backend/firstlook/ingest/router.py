"""Authenticated patient import staging endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from firstlook.authz import route_policy
from firstlook.identity.router import current_principal
from firstlook.identity.service import Principal
from firstlook.ingest.adapters import ImportKind
from firstlook.ingest.service import MAX_UPLOAD, commit_import, import_status, upload

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])
Owner = Annotated[Principal, Depends(current_principal)]


@router.post("", status_code=202)
@route_policy("patient.import.upload")
async def create_import(
    request: Request,
    principal: Owner,
    kind: Annotated[ImportKind, Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, str]:
    form = await request.form()
    if set(form) != {"kind", "file"}:
        raise HTTPException(status_code=422)
    content = await file.read(MAX_UPLOAD + 1)
    await file.close()
    try:
        import_id = await upload(principal, kind, content)
    except ValueError as exc:
        raise HTTPException(status_code=422) from exc
    return {"id": str(import_id), "status": "pending"}


@router.get("/{import_id}")
@route_policy("patient.import.read")
async def status(import_id: UUID, principal: Owner) -> dict[str, object]:
    return await import_status(principal, import_id)


@router.post("/{import_id}/commit")
@route_policy("patient.import.commit")
async def commit(import_id: UUID, principal: Owner) -> dict[str, int]:
    try:
        return await commit_import(principal, import_id)
    except ValueError as exc:
        raise HTTPException(status_code=409) from exc
