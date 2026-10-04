from uuid import uuid4

import pytest
from firstlook.authz import AccessContext, AccessDenied, Action, allowed, require

PATIENT = uuid4()
OWNER = uuid4()
ORG = uuid4()
OTHER_ORG = uuid4()


@pytest.mark.parametrize(
    ("role", "action", "relationship", "expected"),
    [
        ("patient", Action.EDIT_PROFILE, "owner", True),
        ("patient", Action.READ_ACCESS_HISTORY, "foreign", False),
        ("break_glass", Action.READ_ESSENTIALS, "breakglass", True),
        ("break_glass", Action.READ_FULL, "breakglass", False),
        ("responder", Action.READ_FULL, "emergency", True),
        ("responder", Action.CREATE_PREALERT, "emergency", True),
        ("responder", Action.READ_FULL, "foreign", False),
        ("responder", Action.READ_ACCESS_HISTORY, "emergency", False),
        ("ed_staff", Action.READ_FULL, "handover", True),
        ("ed_staff", Action.READ_INTERVENTIONS, "handover", True),
        ("ed_staff", Action.READ_FULL, "wrong_facility", False),
        ("clinician_share", Action.READ_FULL, "share", True),
        ("clinician_share", Action.READ_BASELINE, "share", False),
        ("org_admin", Action.READ_FULL, "handover", False),
        ("org_admin", Action.MANAGE_MEMBERS, "org", True),
        ("org_admin", Action.MANAGE_MEMBERS, "wrong_org", False),
    ],
)
def test_policy_matrix(role: str, action: Action, relationship: str, expected: bool) -> None:
    context = AccessContext(
        actor_id=OWNER if role == "patient" else uuid4(),
        role=role,
        tenant="demo",
        org_id=ORG,
        org_active=True,
        mfa_passed=True,
        emergency_patient_id=PATIENT if relationship == "emergency" else None,
        breakglass_patient_id=PATIENT if relationship == "breakglass" else None,
        handover_patient_id=PATIENT if relationship in {"handover", "wrong_facility"} else None,
        handover_dest_org_id=OTHER_ORG if relationship == "wrong_facility" else ORG,
        clinician_share_patient_id=PATIENT if relationship == "share" else None,
    )
    actual = allowed(
        action,
        context,
        patient_id=PATIENT,
        owner_user_id=OWNER if relationship == "owner" else uuid4(),
        resource_tenant="demo",
        target_org_id=OTHER_ORG if relationship == "wrong_org" else ORG,
    )
    assert actual is expected


def test_tenant_mfa_and_missing_context_fail_closed() -> None:
    responder = AccessContext(
        actor_id=uuid4(),
        role="responder",
        tenant="demo",
        org_id=ORG,
        org_active=True,
        mfa_passed=False,
        emergency_patient_id=PATIENT,
    )
    assert not allowed(Action.READ_FULL, responder, patient_id=PATIENT, resource_tenant="demo")
    with pytest.raises(AccessDenied):
        require(Action.READ_FULL, responder, patient_id=PATIENT, resource_tenant="production")
    assert not allowed(
        Action.READ_FULL,
        AccessContext(None, "unknown", "demo"),
        patient_id=PATIENT,
        resource_tenant="demo",
    )
