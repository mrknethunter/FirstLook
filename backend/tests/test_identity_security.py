import pyotp
import pytest
from firstlook.crypto import new_dek
from firstlook.identity.security import (
    PASSWORD_HASHER,
    csrf_matches,
    hash_password,
    new_session_token,
    new_totp_secret,
    session_csrf_token,
    verify_password,
    verify_totp,
)


def test_password_policy_and_argon2id() -> None:
    with pytest.raises(ValueError):
        hash_password("short")
    with pytest.raises(ValueError):
        hash_password("password12345")
    stored = hash_password("a long uncommon phrase 2026")
    assert stored.startswith("$argon2id$")
    assert PASSWORD_HASHER.check_needs_rehash(stored) is False
    assert verify_password(stored, "a long uncommon phrase 2026")
    assert not verify_password(stored, "wrong")
    assert not verify_password(None, "wrong")


def test_session_csrf_is_bound_to_token() -> None:
    pepper = new_dek()
    token = new_session_token()
    csrf = session_csrf_token(pepper, token)
    assert csrf_matches(csrf, csrf, csrf)
    assert not csrf_matches(csrf, csrf, session_csrf_token(pepper, new_session_token()))


def test_totp_round_trip() -> None:
    secret = new_totp_secret()
    assert verify_totp(secret, pyotp.TOTP(secret).now())
    assert not verify_totp(secret, "not-six-digits")
