from datetime import UTC, datetime
from uuid import uuid4

from firstlook.audit.service import (
    ZERO_HASH,
    AuditInput,
    build_payload,
    event_hash,
    verify_chain,
)


def test_audit_chain_detects_tampering_and_reordering() -> None:
    event = AuditInput(
        patient_id=uuid4(),
        actor_type="responder",
        actor_id=uuid4(),
        org_id=uuid4(),
        role="responder",
        tier="T2",
        action="profile.read",
        purpose="emergency",
        categories=("allergies", "medications"),
        session_ref=uuid4(),
        outcome="allowed",
    )
    first_payload = build_payload(event, datetime.now(UTC))
    first_hash = event_hash(ZERO_HASH, first_payload)
    second_payload = {**first_payload, "action": "handover.create"}
    second_hash = event_hash(first_hash, second_payload)
    chain = [(ZERO_HASH, first_hash, first_payload), (first_hash, second_hash, second_payload)]
    assert verify_chain(chain)
    assert not verify_chain(reversed(chain))
    assert not verify_chain([(ZERO_HASH, first_hash, {**first_payload, "tier": "T1"})])
