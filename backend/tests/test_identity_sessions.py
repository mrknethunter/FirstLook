from pathlib import Path

import pytest
from fastapi.responses import JSONResponse
from firstlook.crypto import new_dek
from firstlook.identity.router import _set_auth_cookies
from firstlook.identity.service import login_is_throttled
from firstlook.settings import get_settings


def test_login_throttling_boundaries() -> None:
    assert not login_is_throttled(9, 49)
    assert login_is_throttled(10, 0)
    assert login_is_throttled(0, 50)


def test_session_cookie_attributes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "fl_pepper").write_text(new_dek().hex())
    monkeypatch.setenv("FL_SECRET_DIR", str(secret_dir))
    get_settings.cache_clear()
    response = JSONResponse({})
    _set_auth_cookies(response, "a" * 43)
    cookies = [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]
    session_cookie = next(value for value in cookies if value.startswith("__Host-fl_session="))
    assert "HttpOnly" in session_cookie
    assert "Secure" in session_cookie
    assert "SameSite=strict" in session_cookie
    assert "Path=/" in session_cookie
    assert "Domain=" not in session_cookie
    get_settings.cache_clear()
