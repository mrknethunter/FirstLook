"""Public account entry points and session-bound identity routes."""

from __future__ import annotations

import secrets
from typing import Annotated, Literal
from uuid import UUID

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from firstlook.authz import route_policy
from firstlook.crypto import secret_key_from_hex
from firstlook.identity import service
from firstlook.identity.security import session_csrf_token
from firstlook.settings import get_settings, read_secret

SESSION_COOKIE = "__Host-fl_session"
CSRF_COOKIE = "__Host-fl_csrf"

auth_router = APIRouter(prefix="/api/v1/auth", tags=["identity"])
me_router = APIRouter(prefix="/api/v1", tags=["identity"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    locale: Literal["en", "pl", "it"] = "en"
    profile_storage_consent: bool


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    org_id: UUID | None = None


class MfaVerifyRequest(StrictModel):
    code: str = Field(min_length=6, max_length=64)


def _set_auth_cookies(response: JSONResponse, token: str) -> None:
    pepper = secret_key_from_hex(read_secret(get_settings().fl_secret_dir / "fl_pepper"))
    csrf = session_csrf_token(pepper, token)
    response.set_cookie(
        SESSION_COOKIE, token, secure=True, httponly=True, samesite="strict", path="/"
    )
    response.set_cookie(CSRF_COOKIE, csrf, secure=True, httponly=False, samesite="strict", path="/")


def _client_meta(request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    return ip, request.headers.get("user-agent", "")[:256]


async def current_principal(request: Request) -> service.Principal:
    try:
        return await service.load_principal(request.cookies.get(SESSION_COOKIE))
    except service.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="authentication required") from exc


@auth_router.get("/csrf")
@route_policy("public.csrf")
async def csrf_token(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        pepper = secret_key_from_hex(read_secret(get_settings().fl_secret_dir / "fl_pepper"))
        csrf = session_csrf_token(pepper, token)
    else:
        csrf = secrets.token_urlsafe(32)
    response = JSONResponse({"csrf_token": csrf})
    response.set_cookie(CSRF_COOKIE, csrf, secure=True, httponly=False, samesite="strict", path="/")
    return response


@auth_router.post("/register", status_code=201)
@route_policy("public.register")
async def register(body: RegisterRequest) -> JSONResponse:
    try:
        user_id = await service.register_patient(
            str(body.email), body.password, body.locale, body.profile_storage_consent
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content={"user_id": str(user_id), "status": "created"})


@auth_router.post("/login")
@route_policy("public.login")
async def login(request: Request, body: LoginRequest) -> JSONResponse:
    ip, user_agent = _client_meta(request)
    try:
        result = await service.login(str(body.email), body.password, ip, user_agent, body.org_id)
    except service.LoginThrottled as exc:
        raise HTTPException(status_code=429, detail="login temporarily unavailable") from exc
    except service.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="invalid credentials") from exc
    previous_token = request.cookies.get(SESSION_COOKIE)
    if previous_token:
        await service.logout(previous_token)
    response = JSONResponse(
        {"mfa_required": result.mfa_required, "mfa_setup_required": result.mfa_setup_required}
    )
    _set_auth_cookies(response, result.token)
    return response


@auth_router.post("/mfa/setup")
@route_policy("session.mfa_setup")
async def mfa_setup(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    try:
        principal = await service.load_principal(token, allow_pending_mfa=True)
        if token is None:
            raise service.AuthenticationError("authentication required")
        secret = await service.setup_mfa(token, principal)
    except service.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="MFA setup unavailable") from exc
    uri = pyotp.TOTP(secret).provisioning_uri(name=str(principal.user_id), issuer_name="FirstLook")
    return JSONResponse({"secret": secret, "provisioning_uri": uri})


@auth_router.post("/mfa/verify")
@route_policy("session.mfa_verify")
async def mfa_verify(request: Request, body: MfaVerifyRequest) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=401, detail="authentication required")
    ip, user_agent = _client_meta(request)
    try:
        result = await service.verify_mfa_login(token, body.code, ip, user_agent)
    except service.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="invalid verification code") from exc
    response = JSONResponse({"mfa_required": False, "recovery_codes": list(result.recovery_codes)})
    _set_auth_cookies(response, result.token)
    return response


@auth_router.post("/logout")
@route_policy("session.logout")
async def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await service.logout(token)
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@me_router.get("/me")
@route_policy("session.me")
async def me(
    principal: Annotated[service.Principal, Depends(current_principal)],
) -> dict[str, str | bool | None]:
    return {
        "user_id": str(principal.user_id),
        "tenant": principal.tenant,
        "role": principal.role,
        "org_id": str(principal.org_id) if principal.org_id else None,
        "mfa_passed": principal.mfa_passed,
        "locale": principal.locale,
        "theme": principal.theme,
    }
