from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from firstlook.crypto import (
    decrypt_patient_field,
    encrypt_patient_field,
    lookup_hmac,
    new_dek,
    rewrap_dek,
    secret_key_from_hex,
    unwrap_dek,
    wrap_dek,
)


def test_envelope_round_trip_and_row_binding() -> None:
    patient_id, other_patient, row_id = uuid4(), uuid4(), uuid4()
    kek, dek = new_dek(), new_dek()
    wrapped = wrap_dek(kek, dek, patient_id, 1, "file-v1")
    assert unwrap_dek(kek, wrapped, patient_id, 1, "file-v1") == dek
    with pytest.raises(InvalidTag):
        unwrap_dek(kek, wrapped, other_patient, 1, "file-v1")

    sealed = encrypt_patient_field(dek, patient_id, row_id, 3, b"private")
    assert decrypt_patient_field(dek, patient_id, row_id, 3, sealed) == b"private"
    with pytest.raises(InvalidTag):
        decrypt_patient_field(dek, patient_id, uuid4(), 3, sealed)
    with pytest.raises(InvalidTag):
        decrypt_patient_field(dek, patient_id, row_id, 4, sealed)


def test_kek_rotation_and_purpose_separation() -> None:
    patient_id = uuid4()
    old_kek, new_kek, dek = new_dek(), new_dek(), new_dek()
    wrapped = wrap_dek(old_kek, dek, patient_id, 1, "old")
    rotated = rewrap_dek(old_kek, new_kek, wrapped, patient_id, 1, "old", "new")
    assert unwrap_dek(new_kek, rotated, patient_id, 1, "new") == dek
    pepper = new_dek()
    assert lookup_hmac(pepper, "email", "a@example.invalid") != lookup_hmac(
        pepper, "log", "a@example.invalid"
    )
    assert secret_key_from_hex(new_kek.hex()) == new_kek
