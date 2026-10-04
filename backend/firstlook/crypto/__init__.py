"""Envelope encryption and one-way identifiers.

Ciphertext format is a 96-bit nonce followed by AES-256-GCM output. AAD always
includes the owning row and version; decryption fails closed on mismatches.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
KEY_BYTES = 32


def secret_key_from_hex(value: str) -> bytes:
    """Decode a file secret and reject the wrong key length without echoing it."""
    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("invalid secret key encoding") from exc
    if len(key) != KEY_BYTES:
        raise ValueError("invalid secret key length")
    return key


def new_dek() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    if len(key) != KEY_BYTES:
        raise ValueError("invalid encryption key length")
    nonce = secrets.token_bytes(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _open(key: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    if len(key) != KEY_BYTES or len(ciphertext) < NONCE_BYTES + 16:
        raise ValueError("invalid ciphertext")
    return AESGCM(key).decrypt(ciphertext[:NONCE_BYTES], ciphertext[NONCE_BYTES:], aad)


def _dek_aad(patient_id: UUID, version: int, kek_id: str) -> bytes:
    return f"dek:{patient_id}:{version}:{kek_id}".encode("ascii")


def wrap_dek(kek: bytes, dek: bytes, patient_id: UUID, version: int, kek_id: str) -> bytes:
    """Wrap a patient DEK under a versioned KEK."""
    if len(dek) != KEY_BYTES:
        raise ValueError("invalid data key length")
    return _seal(kek, dek, _dek_aad(patient_id, version, kek_id))


def unwrap_dek(kek: bytes, wrapped: bytes, patient_id: UUID, version: int, kek_id: str) -> bytes:
    """Unwrap only if the patient, DEK version and KEK identifier match."""
    return _open(kek, wrapped, _dek_aad(patient_id, version, kek_id))


def rewrap_dek(
    old_kek: bytes,
    new_kek: bytes,
    wrapped: bytes,
    patient_id: UUID,
    version: int,
    old_kek_id: str,
    new_kek_id: str,
) -> bytes:
    """Rotate a KEK without exposing the DEK outside this process."""
    dek = unwrap_dek(old_kek, wrapped, patient_id, version, old_kek_id)
    return wrap_dek(new_kek, dek, patient_id, version, new_kek_id)


def encrypt_patient_field(
    dek: bytes,
    patient_id: UUID,
    object_id: UUID,
    version: int,
    plaintext: bytes,
) -> bytes:
    """Bind encrypted FHIR or contact content to its patient, row and version."""
    aad = f"patient:{patient_id}:object:{object_id}:version:{version}".encode("ascii")
    return _seal(dek, plaintext, aad)


def decrypt_patient_field(
    dek: bytes,
    patient_id: UUID,
    object_id: UUID,
    version: int,
    ciphertext: bytes,
) -> bytes:
    aad = f"patient:{patient_id}:object:{object_id}:version:{version}".encode("ascii")
    return _open(dek, ciphertext, aad)


def encrypt_system_field(kek: bytes, user_id: UUID, field: str, plaintext: bytes) -> bytes:
    """Encrypt pre-patient identity data under the server KEK with field AAD."""
    return _seal(kek, plaintext, f"user:{user_id}:{field}".encode("ascii"))


def decrypt_system_field(kek: bytes, user_id: UUID, field: str, ciphertext: bytes) -> bytes:
    return _open(kek, ciphertext, f"user:{user_id}:{field}".encode("ascii"))


def lookup_hmac(pepper: bytes, purpose: str, value: str) -> bytes:
    """Pseudonymise an equality lookup with purpose separation."""
    if len(pepper) != KEY_BYTES:
        raise ValueError("invalid pepper length")
    return hmac.digest(pepper, f"{purpose}:{value}".encode(), "sha256")


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()
