"""Stateless SHL clients cannot bypass acknowledgement or browser Origin checks."""

from __future__ import annotations

import importlib

import httpx
import pytest
from firstlook.settings import get_settings
from firstlook.sharing.manifest import ManifestFailure


@pytest.mark.asyncio
async def test_stateless_manifest_receives_clear_acknowledgement_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("FL_LOG_DIR", str(tmp_path))
    get_settings.cache_clear()
    module = importlib.import_module("firstlook.sharing.manifest_router")

    async def denied(*args: object, **kwargs: object) -> None:
        raise ManifestFailure(403, "Emergency access requires explicit acknowledgement")

    monkeypatch.setattr(module, "resolve_manifest", denied)
    app = importlib.import_module("firstlook.main").app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://firstlook-hy-demo.duckdns.org"
    ) as client:
        response = await client.post("/api/shl/m/" + "a" * 43, json={"recipient": "Emergency"})
        cross_site = await client.post(
            "/api/shl/m/" + "a" * 43,
            json={"recipient": "Emergency"},
            headers={"origin": "https://attacker.example"},
        )
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert "acknowledgement" in response.json()["title"]
    assert cross_site.status_code == 403
    assert cross_site.json()["title"] == "Access denied"
