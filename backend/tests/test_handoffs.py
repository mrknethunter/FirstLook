"""Handover state, data validation and object-level policy boundaries."""

from uuid import uuid4

import pytest
from firstlook.authz import AccessContext, Action, allowed
from firstlook.sharing.handoff_router import PrealertInput
from firstlook.sharing.handoffs import next_status
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("current", "action", "expected"),
    [
        ("pre_alerted", "ack", "acknowledged"),
        ("acknowledged", "arrive", "arrived"),
        ("arrived", "close", "closed"),
        ("pre_alerted", "cancel", "cancelled"),
        ("acknowledged", "cancel", "cancelled"),
    ],
)
def test_valid_handover_transitions(current: str, action: str, expected: str) -> None:
    assert next_status(current, action) == expected


@pytest.mark.parametrize(
    ("current", "action"),
    [("pre_alerted", "close"), ("arrived", "ack"), ("closed", "cancel")],
)
def test_invalid_handover_transitions_fail_closed(current: str, action: str) -> None:
    with pytest.raises(ValueError):
        next_status(current, action)


def test_prealert_rejects_mass_assignment_and_invalid_observations() -> None:
    base = {
        "facility_id": str(uuid4()),
        "eta_minutes": 12,
        "priority": "orange",
        "observations": {"heart_rate": 80},
    }
    assert PrealertInput.model_validate(base).priority == "orange"
    with pytest.raises(ValidationError):
        PrealertInput.model_validate({**base, "patient_id": str(uuid4())})
    with pytest.raises(ValidationError):
        PrealertInput.model_validate({**base, "observations": {"heart_rate": float("inf")}})


def test_ed_policy_denies_foreign_facility_and_patient() -> None:
    patient, destination, other_facility = uuid4(), uuid4(), uuid4()
    context = AccessContext(
        actor_id=uuid4(),
        role="ed_staff",
        tenant="demo",
        org_id=other_facility,
        org_active=True,
        mfa_passed=True,
        handover_patient_id=patient,
        handover_dest_org_id=destination,
    )
    assert not allowed(Action.READ_HANDOVER, context, resource_tenant="demo", patient_id=patient)
    assert not allowed(Action.READ_FULL, context, resource_tenant="demo", patient_id=uuid4())
