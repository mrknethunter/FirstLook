"""No HTTP route may be introduced without a named policy."""

from __future__ import annotations

import importlib

import httpx
import pytest
from firstlook.settings import get_settings
from starlette.routing import Route


def all_http_routes(items: object) -> list[Route]:
    """Expand FastAPI's included routers before checking policy metadata."""
    found: list[Route] = []
    for item in items:  # type: ignore[attr-defined]
        if isinstance(item, Route):
            found.append(item)
        elif hasattr(item, "original_router"):
            found.extend(all_http_routes(item.original_router.routes))
    return found


def test_all_routes_declare_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setenv("FL_LOG_DIR", str(tmp_path))
    get_settings.cache_clear()
    app = importlib.import_module("firstlook.main").app
    missing = [
        route.path
        for route in all_http_routes(app.routes)
        if not getattr(route.endpoint, "__fl_policy__", None)
    ]
    assert missing == []


@pytest.mark.asyncio
async def test_state_change_without_origin_or_csrf_is_denied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    monkeypatch.setenv("FL_LOG_DIR", str(tmp_path))
    get_settings.cache_clear()
    app = importlib.import_module("firstlook.main").app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://firstlook-hy-demo.duckdns.org"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.invalid", "password": "some value"}
        )
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert "nobody@example.invalid" not in response.text
