"""SMART Health Link v1 payloads and compact JWE files."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from jwcrypto import jwe, jwk

from firstlook.settings import get_settings

CONTENT_TYPE = "application/fhir+json;fhirVersion=4.0.1"


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def manifest_identifier(link_id: UUID, key: bytes, pepper: bytes) -> str:
    """Re-derive a 256-bit random-looking ID without persisting a usable URL."""
    if len(key) != 32 or len(pepper) != 32:
        raise ValueError("invalid SHL key material")
    digest = hmac.digest(pepper, b"firstlook:manifest:v1:" + link_id.bytes + key, "sha256")
    return b64url(digest)


def manifest_hash(identifier: str) -> bytes:
    if len(identifier) != 43 or not identifier.isascii():
        raise ValueError("invalid manifest identifier")
    return hashlib.sha256(identifier.encode("ascii")).digest()


def viewer_url(
    link_id: UUID,
    key: bytes,
    pepper: bytes,
    *,
    flag: str,
    label: str,
    exp: datetime | None = None,
) -> str:
    """Put all SHL material in the URL fragment, never in a request path/query."""
    if flag not in {"L", "P"} or len(label) > 80:
        raise ValueError("invalid SHL metadata")
    public_base = str(get_settings().fl_public_base_url).rstrip("/")
    identifier = manifest_identifier(link_id, key, pepper)
    manifest_url = f"{public_base}/api/shl/m/{identifier}"
    if len(manifest_url) > 128:
        raise ValueError("manifest URL too long")
    payload: dict[str, Any] = {
        "url": manifest_url,
        "key": b64url(key),
        "flag": flag,
        "label": label,
        "v": 1,
    }
    if exp:
        payload["exp"] = int(exp.timestamp())
    encoded = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{public_base}/s#shlink:/{encoded}"


def encrypt_bundle(bundle: dict[str, Any], key: bytes) -> str:
    """Embed a FHIR JSON Bundle as JWE compact, dir/A256GCM."""
    if len(key) != 32:
        raise ValueError("invalid SHL key")
    plaintext = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = {"alg": "dir", "enc": "A256GCM", "cty": "application/fhir+json"}
    envelope = jwe.JWE(plaintext, protected=json.dumps(header, separators=(",", ":")))
    envelope.add_recipient(jwk.JWK(kty="oct", k=b64url(key)))
    return str(envelope.serialize(compact=True))
