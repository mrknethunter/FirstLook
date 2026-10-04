"""Owner baseline view and demo-only device sync."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException

from firstlook.audit.service import AuditInput, append_event
from firstlook.authz import AccessDenied, route_policy
from firstlook.baseline.models import DailyMetric, HourlyMetric, SyncState
from firstlook.baseline.service import METRICS, recompute, summary
from firstlook.db import app_sessions
from firstlook.identity.router import current_principal
from firstlook.identity.service import Principal
from firstlook.profile.consents import has_consent
from firstlook.profile.demo_model import DemoPersona
from firstlook.profile.service import owner_patient
from firstlook.seed import _synthetic_values
from firstlook.settings import get_settings

patient_router = APIRouter(prefix="/api/v1/patients/me", tags=["baseline"])
demo_router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
Owner = Annotated[Principal, Depends(current_principal)]


def _partial_day_demo_values(persona: str, hour: int) -> dict[str, float]:
    """Produce cumulative synthetic activity without fractional step counts."""
    values = _synthetic_values(persona, 365)
    weights = [3 if 7 <= h <= 9 else 1 if 6 <= h <= 22 else 0 for h in range(24)]
    fraction = max(0.01, sum(weights[: hour + 1]) / sum(weights))
    values["steps"] = float(round(values["steps"] * fraction))
    values["active_energy"] = round(values["active_energy"] * fraction, 1)
    return values


@patient_router.get("/baseline")
@route_policy("patient.baseline.read")
async def baseline(
    principal: Owner, window: Literal[7, 30, 365] | None = None
) -> dict[str, object]:
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            view = await summary(session, patient.id)
            if window is not None:
                view["metrics"] = [
                    item
                    for item in cast(list[dict[str, object]], view["metrics"])
                    if isinstance(item, dict) and item.get("window_days") == window
                ]
            return view


@demo_router.post("/sync/{persona}")
@route_policy("demo.device_sync")
async def sync(persona: Literal["anna", "marco"], principal: Owner) -> dict[str, str]:
    """Synthetic owner-triggered sample; disabled outside the demo tenant."""
    settings = get_settings()
    if settings.fl_env != "demo" or not settings.fl_demo_tenant_enabled:
        raise HTTPException(status_code=404)
    async with app_sessions()() as session:
        async with session.begin():
            patient = await owner_patient(session, principal)
            person = await session.get(DemoPersona, persona)
            if person is None or person.patient_id != patient.id:
                raise AccessDenied("access denied")
            if not await has_consent(session, patient.id, "wearable_baseline"):
                raise AccessDenied("access denied")
            now = datetime.now(UTC)
            values = _partial_day_demo_values(persona, now.hour)
            for metric, value in values.items():
                row = await session.get(DailyMetric, (patient.id, now.date(), metric))
                if row is None:
                    row = DailyMetric(patient_id=patient.id, day=now.date(), metric=metric)
                    session.add(row)
                row.value = value
                row.unit = METRICS[metric]
                row.source = "demo_simulator"
                if metric in {"steps", "active_energy"}:
                    hour = now.replace(minute=0, second=0, microsecond=0)
                    sample = await session.get(HourlyMetric, (patient.id, hour, metric))
                    if sample is None:
                        sample = HourlyMetric(patient_id=patient.id, hour=hour, metric=metric)
                        session.add(sample)
                    sample.value = value
            state = await session.get(SyncState, patient.id)
            if state is None:
                state = SyncState(patient_id=patient.id)
                session.add(state)
            state.last_sync_at = now
            state.last_activity_at = now - timedelta(minutes=4)
            state.source = "demo_simulator"
            await recompute(session, patient.id, now.date())
            await append_event(
                session,
                AuditInput(
                    patient.id,
                    "patient",
                    principal.user_id,
                    None,
                    "patient",
                    "owner",
                    "device.sync_simulated",
                    "wearable_baseline",
                    ("telemetry",),
                    None,
                    "allowed",
                ),
            )
    return {"status": "synced"}
