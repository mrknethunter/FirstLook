"""Synthetic seed facts must remain parseable FHIR resources."""

from collections.abc import Iterable
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from typing import Self
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from firstlook import seed as seed_module
from firstlook.crypto import encrypt_system_field, lookup_hmac
from firstlook.demo_credentials import DemoCredential
from firstlook.fhir.ips_builder import PatientIdentity, build_ips_bundle
from firstlook.fhir.validation import validate_fhir_resource
from firstlook.identity.models import Membership, User
from firstlook.identity.security import hash_password, verify_password
from firstlook.rules.engine import evaluate_flags, load_rules
from firstlook.seed import _anna_resources, _marco_resources


def _credential_book() -> dict[str, DemoCredential]:
    return {
        label: DemoCredential(f"{label}@firstlook-hy-demo.duckdns.org", label * 4)
        for label in ("patient_anna", "patient_marco", "responder_1", "ed_staff_1")
    }


def _demo_settings() -> SimpleNamespace:
    return SimpleNamespace(
        fl_env="demo",
        fl_demo_tenant_enabled=True,
        fl_demo_judge_tables=1,
        fl_secret_dir=Path("."),
    )


def test_existing_professional_labels_map_only_to_their_role_and_table() -> None:
    book = _credential_book()
    assert (
        seed_module._professional_label(
            "responder", "responder-1-a1b2c3@firstlook-hy-demo.duckdns.org", book
        )
        == "responder_1"
    )
    assert (
        seed_module._professional_label("ed_staff", book["ed_staff_1"].email, book) == "ed_staff_1"
    )
    assert seed_module._professional_label("responder", book["ed_staff_1"].email, book) is None


@pytest.mark.asyncio
async def test_fixed_credential_sync_is_idempotent_and_revokes_changed_sessions() -> None:
    user_id = uuid4()
    kek, pepper = bytes(range(32)), bytes(range(32, 64))
    original_email = "old.demo@firstlook-hy-demo.duckdns.org"
    original_password = token_hex(12)
    user = User(
        id=user_id,
        email_hmac=lookup_hmac(pepper, "email", original_email),
        email_enc=encrypt_system_field(kek, user_id, "email", original_email.encode()),
        password_hash=hash_password(original_password),
        kind="patient",
        tenant="demo",
        status="active",
    )
    session = AsyncMock()

    assert not await seed_module._apply_user_credential(
        session, user, DemoCredential(original_email, original_password), kek, pepper
    )
    session.execute.assert_not_awaited()

    fixed = DemoCredential("anna.demo@firstlook-hy-demo.duckdns.org", token_hex(12))
    assert await seed_module._apply_user_credential(session, user, fixed, kek, pepper)
    assert user.email_hmac == lookup_hmac(pepper, "email", fixed.email)
    assert verify_password(user.password_hash, fixed.password)
    session.execute.assert_awaited_once()


def test_synthetic_persona_resources_are_structurally_valid() -> None:
    for section, item in [*_anna_resources(), *_marco_resources()]:
        resource = {**item, "id": str(uuid4())}
        if section in {"allergies", "devices"}:
            resource["patient"] = {"reference": "Patient/self"}
        else:
            resource["subject"] = {"reference": "Patient/self"}
        assert validate_fhir_resource(resource)["resourceType"] == item["resourceType"]


def test_marco_ips_contains_documented_critical_items() -> None:
    resources = []
    for section, item in _marco_resources():
        resource = {**item, "id": str(uuid4())}
        if section in {"allergies", "devices"}:
            resource["patient"] = {"reference": "Patient/self"}
        else:
            resource["subject"] = {"reference": "Patient/self"}
        resources.append(validate_fhir_resource(resource))
    rules = load_rules(Path(__file__).resolve().parents[1] / "rules" / "emergency_v1.yaml")
    flags = evaluate_flags(resources, rules)
    bundle = build_ips_bundle(
        PatientIdentity("Marco", "Rossi", None, "male", "30-39"), resources, flags
    )
    assert bundle["entry"][0]["resource"]["section"][0]["entry"]
    assert {flag.rule_id for flag in flags} == {"med.insulin", "device.insulin_pump"}


@pytest.mark.asyncio
async def test_professionals_are_flushed_before_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An FK-checking session catches the original membership-before-user failure."""

    class ForeignKeyCheckingSession:
        def __init__(self) -> None:
            self.pending_users: list[User] = []
            self.persisted_users: set[object] = set()
            self.memberships: list[Membership] = []

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            await self.flush()

        def begin(self) -> Self:
            return self

        def add(self, item: object) -> None:
            if isinstance(item, User):
                self.pending_users.append(item)
            if isinstance(item, Membership):
                assert item.user_id in self.persisted_users
                self.memberships.append(item)

        def add_all(self, items: Iterable[object]) -> None:
            for item in items:
                self.add(item)

        async def flush(self) -> None:
            self.persisted_users.update(user.id for user in self.pending_users)
            self.pending_users.clear()

    session = ForeignKeyCheckingSession()
    monkeypatch.setattr(seed_module, "app_sessions", lambda: lambda: session)
    monkeypatch.setattr(
        seed_module,
        "get_settings",
        lambda: SimpleNamespace(fl_secret_dir=Path(".")),
    )
    monkeypatch.setattr(seed_module, "read_secret", lambda _path: "00" * 32)
    monkeypatch.setattr(seed_module, "hash_password", lambda _password: "hashed")

    await seed_module._seed_professionals(1, _credential_book())

    assert {membership.role for membership in session.memberships} == {"responder", "ed_staff"}


@pytest.mark.asyncio
async def test_partial_seed_recovers_existing_patients_without_duplicate_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        seed_module,
        "get_settings",
        _demo_settings,
    )
    book = _credential_book()
    monkeypatch.setattr(seed_module, "load_demo_credentials", lambda _path, _tables: book)
    monkeypatch.setattr(
        seed_module,
        "_demo_seed_state",
        AsyncMock(return_value=({"anna", "marco"}, 0)),
    )
    recover = AsyncMock()
    professionals = AsyncMock()
    create_patient = AsyncMock()
    seed_telemetry = AsyncMock()
    monkeypatch.setattr(seed_module, "_sync_patient_credential", recover)
    monkeypatch.setattr(seed_module, "_seed_professionals", professionals)
    monkeypatch.setattr(seed_module, "_seed_patient", create_patient)
    monkeypatch.setattr(seed_module, "_seed_telemetry", seed_telemetry)

    await seed_module.seed()

    assert recover.await_count == 2
    professionals.assert_awaited_once_with(1, book)
    create_patient.assert_not_awaited()
    seed_telemetry.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_seed_does_not_rotate_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        seed_module,
        "get_settings",
        _demo_settings,
    )
    monkeypatch.setattr(
        seed_module, "load_demo_credentials", lambda _path, _tables: _credential_book()
    )
    monkeypatch.setattr(
        seed_module, "_demo_seed_state", AsyncMock(return_value=({"anna", "marco"}, 2))
    )
    sync_patient = AsyncMock()
    sync_professional = AsyncMock()
    professionals = AsyncMock()
    monkeypatch.setattr(seed_module, "_sync_patient_credential", sync_patient)
    monkeypatch.setattr(seed_module, "_sync_professional_credentials", sync_professional)
    monkeypatch.setattr(seed_module, "_seed_professionals", professionals)

    await seed_module.seed()

    assert sync_patient.await_count == 2
    sync_professional.assert_awaited_once()
    professionals.assert_not_awaited()


@pytest.mark.asyncio
async def test_inconsistent_seed_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        seed_module,
        "get_settings",
        _demo_settings,
    )
    monkeypatch.setattr(
        seed_module, "load_demo_credentials", lambda _path, _tables: _credential_book()
    )
    monkeypatch.setattr(
        seed_module, "_demo_seed_state", AsyncMock(return_value=({"anna", "marco"}, 1))
    )
    recover = AsyncMock()
    monkeypatch.setattr(seed_module, "_sync_patient_credential", recover)

    with pytest.raises(RuntimeError, match="inconsistent"):
        await seed_module.seed()

    recover.assert_not_awaited()
