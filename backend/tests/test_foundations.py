"""Checks for production settings and PHI-free application logs."""

from pathlib import Path

import pytest
from firstlook.crypto import new_dek
from firstlook.logging import scrub_event
from firstlook.settings import Settings, require_runtime_secrets
from pydantic import ValidationError


def test_production_refuses_demo_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(fl_env="production", fl_demo_tenant_enabled=True)
    with pytest.raises(ValidationError):
        Settings(fl_env="production", fl_breakglass_link_limit=50)


def test_demo_limits_remain_bounded() -> None:
    settings = Settings(
        fl_env="demo",
        fl_demo_tenant_enabled=True,
        fl_breakglass_link_limit=50,
        fl_breakglass_ip_limit=100,
    )
    assert settings.fl_breakglass_link_limit == 50
    assert settings.fl_breakglass_ip_limit == 100


def test_scrubber_removes_secret_fields_and_patterns() -> None:
    event = scrub_event(
        None,
        "info",
        {
            "email": "anna@example.invalid",
            "key": "secret",
            "unplanned_field": "patient notes",
            "route": "POST /api/shl/m/{manifestId}",
            "event": "shlink:/abc anna@example.invalid 44051401359 +48 123 456 789",
        },
    )
    assert "email" not in event and "key" not in event
    assert "unplanned_field" not in event
    assert "shlink:/" not in event["event"]
    assert "anna@example.invalid" not in event["event"]
    assert "44051401359" not in event["event"]
    assert "+48 123 456 789" not in event["event"]
    assert "{manifestId}" in event["route"]


def test_runtime_rejects_default_root_secret(tmp_path: Path) -> None:
    for role in ("app", "vault"):
        (tmp_path / f"fl_db_{role}").write_text(
            f"postgresql+psycopg://fl_{role}:{'a' * 48}@db:5432/firstlook"
        )
    (tmp_path / "fl_kek").write_text(bytes(32).hex())
    (tmp_path / "fl_pepper").write_text(new_dek().hex())
    with pytest.raises(RuntimeError, match="insecure root secret"):
        require_runtime_secrets(Settings(fl_secret_dir=tmp_path))
