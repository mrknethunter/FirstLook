"""Default-deny access decisions and explicit route policy metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar
from uuid import UUID

F = TypeVar("F", bound=Callable[..., Any])


class Action(StrEnum):
    EDIT_PROFILE = "edit_profile"
    MANAGE_LINKS = "manage_links"
    MANAGE_CONSENTS = "manage_consents"
    READ_ESSENTIALS = "read_essentials"
    READ_FULL = "read_full"
    READ_BASELINE = "read_baseline"
    CREATE_PREALERT = "create_prealert"
    READ_HANDOVER = "read_handover"
    READ_INTERVENTIONS = "read_interventions"
    READ_ACCESS_HISTORY = "read_access_history"
    MANAGE_MEMBERS = "manage_members"


@dataclass(frozen=True)
class AccessContext:
    actor_id: UUID | None
    role: str
    tenant: str
    org_id: UUID | None = None
    org_active: bool = False
    mfa_passed: bool = False
    emergency_patient_id: UUID | None = None
    breakglass_patient_id: UUID | None = None
    handover_patient_id: UUID | None = None
    handover_dest_org_id: UUID | None = None
    clinician_share_patient_id: UUID | None = None
    purpose: str = ""


class AccessDenied(PermissionError):
    """A policy denied an action; HTTP handlers map this to a generic 403."""


def allowed(
    action: Action,
    context: AccessContext,
    *,
    resource_tenant: str,
    patient_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    target_org_id: UUID | None = None,
) -> bool:
    """Decide by role, ownership, capability, tenant, MFA and facility context."""
    if context.tenant != resource_tenant:
        return False
    owner = (
        context.role == "patient"
        and context.actor_id is not None
        and context.actor_id == owner_user_id
        and patient_id is not None
    )
    if owner:
        return action in {
            Action.EDIT_PROFILE,
            Action.MANAGE_LINKS,
            Action.MANAGE_CONSENTS,
            Action.READ_ESSENTIALS,
            Action.READ_FULL,
            Action.READ_BASELINE,
            Action.READ_HANDOVER,
            Action.READ_INTERVENTIONS,
            Action.READ_ACCESS_HISTORY,
        }
    if action == Action.MANAGE_MEMBERS:
        return (
            context.role == "org_admin"
            and context.mfa_passed
            and context.org_active
            and context.org_id is not None
            and context.org_id == target_org_id
        )
    if patient_id is None:
        return False
    if context.role == "break_glass":
        return action == Action.READ_ESSENTIALS and context.breakglass_patient_id == patient_id
    if context.role == "responder":
        return (
            context.mfa_passed
            and context.org_active
            and context.emergency_patient_id == patient_id
            and action
            in {
                Action.READ_ESSENTIALS,
                Action.READ_FULL,
                Action.READ_BASELINE,
                Action.CREATE_PREALERT,
                Action.READ_HANDOVER,
            }
        )
    if context.role == "ed_staff":
        return (
            context.mfa_passed
            and context.org_active
            and context.org_id is not None
            and context.org_id == context.handover_dest_org_id
            and context.handover_patient_id == patient_id
            and action
            in {
                Action.READ_ESSENTIALS,
                Action.READ_FULL,
                Action.READ_BASELINE,
                Action.READ_HANDOVER,
                Action.READ_INTERVENTIONS,
            }
        )
    if context.role in {"clinician", "clinician_share"}:
        return (
            context.clinician_share_patient_id == patient_id
            and action in {Action.READ_ESSENTIALS, Action.READ_FULL}
            and (context.role == "clinician_share" or context.mfa_passed)
        )
    return False


def require(
    action: Action,
    context: AccessContext,
    *,
    resource_tenant: str,
    patient_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    target_org_id: UUID | None = None,
) -> None:
    """Fail closed if any required object relationship is absent or mismatched."""
    if not allowed(
        action,
        context,
        resource_tenant=resource_tenant,
        patient_id=patient_id,
        owner_user_id=owner_user_id,
        target_org_id=target_org_id,
    ):
        raise AccessDenied("access denied")


def route_policy(name: str) -> Callable[[F], F]:
    """Tag a route with its explicit policy for inventory checking."""

    def decorate(function: F) -> F:
        setattr(function, "__fl_policy__", name)  # noqa: B010 - route metadata
        return function

    return decorate
