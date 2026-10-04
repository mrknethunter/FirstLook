"""FastAPI application and operational endpoints."""

from __future__ import annotations

import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.responses import Response
from starlette.routing import Route

from firstlook.authz import AccessDenied, route_policy
from firstlook.baseline.router import demo_router as sync_router
from firstlook.baseline.router import patient_router as baseline_router
from firstlook.crypto import secret_key_from_hex
from firstlook.db import app_engine
from firstlook.identity.router import CSRF_COOKIE, SESSION_COOKIE, auth_router, me_router
from firstlook.identity.security import csrf_matches, session_csrf_token
from firstlook.ingest.router import router as import_router
from firstlook.logging import configure_logging
from firstlook.profile.router import router as profile_router
from firstlook.settings import get_settings, read_secret, require_runtime_secrets
from firstlook.sharing.event_router import ed_events, patient_events
from firstlook.sharing.handoff_router import ed_router, responder_router
from firstlook.sharing.manifest_router import router as manifest_router
from firstlook.sharing.router import demo_router
from firstlook.sharing.router import patient_router as link_router
from firstlook.terminology.router import router as terminology_router

settings = get_settings()
configure_logging("api", settings.fl_log_dir, settings.fl_log_level)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    require_runtime_secrets(settings)
    yield
    await app_engine().dispose()


app = FastAPI(
    title="FirstLook",
    version="0.1.0",
    docs_url="/api/docs" if settings.fl_openapi_enabled else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.fl_openapi_enabled else None,
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(link_router)
app.include_router(demo_router)
app.include_router(manifest_router)
app.include_router(responder_router)
app.include_router(ed_router)
app.include_router(ed_events)
app.include_router(patient_events)
app.include_router(sync_router)
app.include_router(baseline_router)
app.include_router(import_router)
app.include_router(profile_router)
app.include_router(terminology_router)
for internal_route in app.routes:
    if isinstance(internal_route, Route) and internal_route.path in {
        "/api/docs",
        "/api/docs/oauth2-redirect",
        "/api/openapi.json",
    }:
        route_policy("public.docs")(internal_route.endpoint)


def problem(status: int, title: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "instance": request_id},
        media_type="application/problem+json",
    )


@app.exception_handler(HTTPException)
async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = request.state.request_id
    titles = {
        400: "Invalid request",
        401: "Authentication required",
        403: "Access denied",
        404: "Not found",
        429: "Too many requests",
    }
    return problem(exc.status_code, titles.get(exc.status_code, "Request failed"), request_id)


@app.exception_handler(AccessDenied)
async def access_problem(request: Request, _: AccessDenied) -> JSONResponse:
    return problem(403, "Access denied", request.state.request_id)


@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, _: RequestValidationError) -> JSONResponse:
    return problem(422, "Invalid request", request.state.request_id)


@app.middleware("http")
async def request_envelope(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id", "")
    try:
        request_id = str(UUID(request_id))
    except (ValueError, AttributeError):
        request_id = secrets.token_hex(12)
    request.state.request_id = request_id
    response: Response
    try:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            manifest_request = request.method == "POST" and request.url.path.startswith(
                "/api/shl/m/"
            )
            declared_length = request.headers.get("content-length", "0")
            try:
                too_large = manifest_request and int(declared_length) > 4096
            except ValueError:
                too_large = manifest_request
            session_token = request.cookies.get(SESSION_COOKIE)
            if too_large:
                response = problem(413, "Manifest request too large", request_id)
            elif manifest_request and not session_token and origin is None:
                # Native generic SHL clients carry no browser session, so CSRF does not apply.
                response = await call_next(request)
            elif origin != str(settings.fl_public_base_url).rstrip("/"):
                response = problem(403, "Access denied", request_id)
            else:
                csrf_cookie = request.cookies.get(CSRF_COOKIE)
                csrf_header = request.headers.get("x-csrf-token")
                if session_token:
                    pepper = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_pepper"))
                    expected = session_csrf_token(pepper, session_token)
                else:
                    expected = csrf_cookie or ""
                response = (
                    await call_next(request)
                    if csrf_matches(expected, csrf_cookie, csrf_header)
                    else problem(403, "Access denied", request_id)
                )
        else:
            response = await call_next(request)
    except Exception:
        log.error("request.failed", request_id=request_id, route="unmatched", status=500)
        response = problem(500, "Internal server error", request_id)
    route = request.scope.get("route")
    route_template = getattr(route, "path", "unmatched")
    response.headers["X-Request-ID"] = request_id
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    log.info(
        "http.request",
        service="api",
        request_id=request_id,
        route=f"{request.method} {route_template}",
        status=response.status_code,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
    return response


@app.get("/healthz")
@route_policy("public.health")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
@route_policy("public.ready")
async def readyz() -> JSONResponse:
    try:
        async with app_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ok"})
