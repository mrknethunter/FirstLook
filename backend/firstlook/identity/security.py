"""Password, TOTP and session-bound CSRF primitives."""

from __future__ import annotations

import hmac
import re
import secrets

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from firstlook.crypto import lookup_hmac

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=2, hash_len=32)
COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password123",
        "password1234",
        "password12345",
        "qwerty123",
        "qwerty12345",
        "123456789012",
        "1234567890ab",
        "letmein12345",
        "adminadmin123",
        "welcome12345",
        "iloveyou1234",
        "firstlook123",
    }
)
SIMPLE_RUN = re.compile(r"(password|qwerty|123456|letmein|iloveyou)", re.IGNORECASE)
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def validate_password(password: str) -> None:
    """Apply the minimum policy before expensive Argon2id hashing."""
    if not 12 <= len(password) <= 128:
        raise ValueError("password must contain 12 to 128 characters")
    lowered = password.casefold()
    if lowered in COMMON_PASSWORDS or SIMPLE_RUN.search(lowered):
        raise ValueError("choose a less common password")


def hash_password(password: str) -> str:
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def hash_passcode(passcode: str) -> str:
    """Hash a numeric SHL passcode with Argon2id under its distinct length rule."""
    if not re.fullmatch(r"[0-9]{6,64}", passcode):
        raise ValueError("passcode must contain at least six digits")
    return PASSWORD_HASHER.hash(passcode)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Run Argon2id even for unknown accounts to reduce enumeration timing."""
    try:
        return (
            bool(PASSWORD_HASHER.verify(stored_hash or DUMMY_HASH, password))
            and stored_hash is not None
        )
    except VerificationError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_csrf_token(pepper: bytes, session_token: str) -> str:
    """Derive a CSRF token bound to the opaque server-side session."""
    return lookup_hmac(pepper, "csrf", session_token).hex()


def csrf_matches(expected: str, cookie: str | None, header: str | None) -> bool:
    return bool(
        cookie
        and header
        and hmac.compare_digest(cookie, header)
        and hmac.compare_digest(expected, header)
    )


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    """Allow one adjacent time step for clock skew; only six numeric digits."""
    return bool(re.fullmatch(r"\d{6}", code)) and bool(
        pyotp.TOTP(secret).verify(code, valid_window=1)
    )
