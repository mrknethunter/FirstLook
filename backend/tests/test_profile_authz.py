"""The shared owner repository gate protects every /patients/me route."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from firstlook.authz import AccessDenied
from firstlook.identity.service import Principal
from firstlook.profile.models import Patient
from firstlook.profile.service import _default_selection, owner_patient
from firstlook.rules.engine import Flag


@pytest.mark.asyncio
async def test_professional_cannot_resolve_owner_profile() -> None:
    session = AsyncMock()
    principal = Principal(uuid4(), "demo", "responder", uuid4(), True, True, "pl", "system", b"")
    with pytest.raises(AccessDenied):
        await owner_patient(session, principal)
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_owner_id_is_denied_even_after_id_resolution() -> None:
    patient_id = uuid4()
    principal = Principal(uuid4(), "demo", "patient", None, False, True, "pl", "system", b"")
    session = AsyncMock()
    session.scalar.return_value = patient_id
    session.get.return_value = Patient(
        id=patient_id, owner_user_id=uuid4(), dek_wrapped=b"", dek_version=1, kek_id="file-v1"
    )
    with pytest.raises(AccessDenied):
        await owner_patient(session, principal)


def test_essentials_defaults_exclude_uncoded_conditions() -> None:
    resources = [
        {"resourceType": "Condition", "id": "private-condition", "code": {"text": "rare note"}},
        {
            "resourceType": "AllergyIntolerance",
            "id": "critical-allergy",
            "criticality": "high",
        },
    ]
    flag = Flag("med.insulin", "high", "flags.insulin", ("source",), True)
    selected = _default_selection(resources, [flag])
    assert selected == {"critical-allergy", "flag:med.insulin"}
