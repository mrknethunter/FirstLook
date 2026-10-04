"""Typed runtime settings and secret-file access."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from firstlook.crypto import secret_key_from_hex


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fl_env: Literal["demo", "production"] = "production"
    fl_public_base_url: HttpUrl = HttpUrl("https://firstlook-hy-demo.duckdns.org")
    fl_supported_locales: str = "en,pl,it"
    fl_log_dir: Path = Path("/var/log/firstlook")
    fl_upload_dir: Path = Path("/data/uploads")
    fl_log_level: str = "INFO"
    fl_secret_dir: Path = Path("/run/secrets")
    fl_demo_tenant_enabled: bool = False
    fl_openapi_enabled: bool = False
    fl_breakglass_link_limit: int = Field(default=3, ge=1)
    fl_breakglass_ip_limit: int = Field(default=10, ge=1)
    fl_session_ttl_patient_minutes: int = Field(default=30, ge=1)
    fl_session_ttl_professional_hours: int = Field(default=12, ge=1)
    fl_session_ttl_breakglass_minutes: int = Field(default=15, ge=1)
    fl_demo_judge_tables: int = Field(default=3, ge=1, le=30)

    @model_validator(mode="after")
    def reject_insecure_production(self) -> Settings:
        """Refuse demo capabilities or weakened limits in a production process."""
        if str(self.fl_public_base_url).rstrip("/") != "https://firstlook-hy-demo.duckdns.org":
            raise ValueError("FL_PUBLIC_BASE_URL must use the approved HTTPS demo domain")
        if self.fl_env == "production" and (
            self.fl_demo_tenant_enabled
            or self.fl_openapi_enabled
            or self.fl_breakglass_link_limit != 3
            or self.fl_breakglass_ip_limit != 10
        ):
            raise ValueError("production refuses demo settings")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def read_secret(path: Path) -> str:
    """Read a mounted secret without ever including its content in an error."""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"required secret file missing: {path.name}") from exc
    if not value:
        raise RuntimeError(f"required secret file empty: {path.name}")
    return value


def require_runtime_secrets(settings: Settings) -> None:
    """Fail start-up when the API lacks any of its root secrets."""
    for role in ("app", "vault"):
        url = make_url(read_secret(settings.fl_secret_dir / f"fl_db_{role}"))
        if (
            url.username != f"fl_{role}"
            or url.host != "db"
            or not url.password
            or len(url.password) < 24
            or url.password.casefold() in {"password", "changeme", "secret"}
        ):
            raise RuntimeError(f"invalid fl_db_{role} secret")
    kek = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_kek"))
    pepper = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_pepper"))
    if kek == pepper or len(set(kek)) < 8 or len(set(pepper)) < 8:
        raise RuntimeError("insecure root secret")
