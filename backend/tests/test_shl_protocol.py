import base64
import json
from uuid import uuid4

from firstlook.identity.security import hash_passcode, verify_password
from firstlook.sharing.protocol import (
    b64url,
    encrypt_bundle,
    manifest_hash,
    manifest_identifier,
    viewer_url,
)
from jwcrypto import jwe, jwk


def test_emergency_shl_payload_has_fragment_key_and_flag_l() -> None:
    link_id, key, pepper = uuid4(), bytes(range(32)), bytes(range(32, 64))
    url = viewer_url(link_id, key, pepper, flag="L", label="FirstLook emergency profile")
    assert url.startswith("https://firstlook-hy-demo.duckdns.org/s#shlink:/")
    encoded = url.split("#shlink:/", 1)[1]
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    identifier = manifest_identifier(link_id, key, pepper)
    assert payload["url"].endswith(identifier)
    assert payload["key"] == b64url(key)
    assert payload["flag"] == "L"
    assert "exp" not in payload
    assert len(manifest_hash(identifier)) == 32
    assert key.hex() not in url.split("#", 1)[0]


def test_jwe_round_trip_uses_dir_a256gcm() -> None:
    key = bytes(range(32))
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    compact = encrypt_bundle(bundle, key)
    protected = json.loads(base64.urlsafe_b64decode(compact.split(".")[0] + "=="))
    assert protected == {"alg": "dir", "enc": "A256GCM", "cty": "application/fhir+json"}
    decrypted = jwe.JWE()
    decrypted.deserialize(compact, key=jwk.JWK(kty="oct", k=b64url(key)))
    assert json.loads(decrypted.payload) == bundle


def test_six_digit_clinician_passcode_uses_argon2id() -> None:
    stored = hash_passcode("123456")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "123456")
    assert not verify_password(stored, "123457")
