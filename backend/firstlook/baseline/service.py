"""Median/MAD baselines and consent-gated wearable projections."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.baseline.models import Baseline, DailyMetric, HourlyMetric, SyncState
from firstlook.profile.consents import has_consent

METRICS = {
    "steps": "count",
    "active_energy": "kcal",
    "resting_hr": "beats/min",
    "hr_min": "beats/min",
    "hr_max": "beats/min",
    "sleep_minutes": "min",
}
WINDOWS = (7, 30, 365)
CODE_SYSTEM = "https://firstlook-hy-demo.duckdns.org/fhir/CodeSystem/wearable-metric"
BASELINE_EXTENSION = "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-"


@dataclass(frozen=True)
class RobustRange:
    median: float
    mad: float
    low: float
    high: float
    n: int


def robust_range(values: list[float], window_days: int) -> RobustRange | None:
    """Compute the specified 60%-coverage median/MAD range; never infer a norm."""
    if window_days not in WINDOWS or len(values) < math.ceil(0.6 * window_days):
        return None
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("invalid wearable value")
    middle = statistics.median(values)
    mad = statistics.median(abs(value - middle) for value in values)
    sigma = 1.4826 * mad
    return RobustRange(middle, mad, max(0.0, middle - 2 * sigma), middle + 2 * sigma, len(values))


def classify_today(value: float, normal: RobustRange, fraction: float = 1.0) -> tuple[str, float]:
    """Compare cumulative partial-day metrics to the same hourly baseline fraction."""
    if not math.isfinite(value) or value < 0 or not 0 < fraction <= 1:
        raise ValueError("invalid wearable comparison")
    low, high = normal.low * fraction, normal.high * fraction
    median = normal.median * fraction
    sigma = 1.4826 * normal.mad * fraction
    status = "below" if value < low else "above" if value > high else "within"
    return status, (value - median) / max(sigma, 1.0)


async def recompute(session: AsyncSession, patient_id: UUID, today: date | None = None) -> None:
    """Replace all personal windows from daily aggregates ending yesterday."""
    today = today or datetime.now(UTC).date()
    rows = (
        await session.scalars(
            select(DailyMetric).where(
                DailyMetric.patient_id == patient_id,
                DailyMetric.day >= today - timedelta(days=365),
                DailyMetric.day < today,
            )
        )
    ).all()
    for metric in METRICS:
        for window in WINDOWS:
            start = today - timedelta(days=window)
            values = [row.value for row in rows if row.metric == metric and row.day >= start]
            result = robust_range(values, window)
            key = (patient_id, metric, window)
            record = await session.get(Baseline, key)
            if result is None:
                if record is not None:
                    await session.delete(record)
                continue
            if record is None:
                record = Baseline(patient_id=patient_id, metric=metric, window_days=window)
                session.add(record)
            record.median = result.median
            record.mad = result.mad
            record.low = result.low
            record.high = result.high
            record.n = result.n
            record.computed_at = datetime.now(UTC)


async def _hour_fraction(
    session: AsyncSession, patient_id: UUID, metric: str, now: datetime
) -> float | None:
    if metric not in {"steps", "active_energy"}:
        return 1.0
    since = now - timedelta(days=14)
    rows = (
        await session.scalars(
            select(HourlyMetric).where(
                HourlyMetric.patient_id == patient_id,
                HourlyMetric.metric == metric,
                HourlyMetric.hour >= since,
                HourlyMetric.hour < datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC),
            )
        )
    ).all()
    by_day: dict[date, tuple[float, float]] = {}
    for row in rows:
        day = row.hour.date()
        elapsed, total = by_day.get(day, (0.0, 0.0))
        by_day[day] = (
            elapsed + (row.value if row.hour.hour <= now.hour else 0.0),
            total + row.value,
        )
    fractions = [elapsed / total for elapsed, total in by_day.values() if total > 0]
    return min(1.0, max(0.01, statistics.median(fractions))) if fractions else None


async def summary(
    session: AsyncSession, patient_id: UUID, now: datetime | None = None
) -> dict[str, object]:
    """Return only consented aggregates, with explicit indicative provenance."""
    if not await has_consent(session, patient_id, "wearable_baseline"):
        return {"status": "not_consented", "metrics": []}
    now = now or datetime.now(UTC)
    baselines = (
        await session.scalars(select(Baseline).where(Baseline.patient_id == patient_id))
    ).all()
    today_rows = (
        await session.scalars(
            select(DailyMetric).where(
                DailyMetric.patient_id == patient_id, DailyMetric.day == now.date()
            )
        )
    ).all()
    series_rows = (
        await session.scalars(
            select(DailyMetric)
            .where(
                DailyMetric.patient_id == patient_id,
                DailyMetric.day >= now.date() - timedelta(days=7),
                DailyMetric.day < now.date(),
            )
            .order_by(DailyMetric.day)
        )
    ).all()
    state = await session.get(SyncState, patient_id)
    today_values = {row.metric: row.value for row in today_rows}
    result: list[dict[str, object]] = []
    fractions: dict[str, float | None] = {}
    for row in baselines:
        value = today_values.get(row.metric)
        if value is not None and row.metric not in fractions:
            fractions[row.metric] = await _hour_fraction(session, patient_id, row.metric, now)
        fraction = fractions.get(row.metric)
        normal = RobustRange(row.median, row.mad, row.low, row.high, row.n)
        comparison = (
            classify_today(value, normal, fraction) if value is not None and fraction else None
        )
        result.append(
            {
                "metric": row.metric,
                "unit": METRICS[row.metric],
                "window_days": row.window_days,
                "median": row.median,
                "mad": row.mad,
                "low": row.low,
                "high": row.high,
                "n": row.n,
                "today": value,
                "classification": comparison[0] if comparison else "insufficient_data",
                "z_today": comparison[1] if comparison else None,
                "hour_fraction": fraction if row.metric in {"steps", "active_energy"} else None,
            }
        )
    return {
        "status": "available" if result else "insufficient_data",
        "label": "indicative, from consumer device",
        "last_sync_at": state.last_sync_at.isoformat() if state and state.last_sync_at else None,
        "last_activity_at": state.last_activity_at.isoformat()
        if state and state.last_activity_at
        else None,
        "metrics": result,
        "series": [
            {"day": row.day.isoformat(), "metric": row.metric, "value": row.value}
            for row in series_rows
        ],
    }


def as_fhir_bundle(view: dict[str, object]) -> dict[str, object]:
    """Represent personal ranges and the recent series as informational Observations."""
    entries: list[dict[str, object]] = []
    for item in cast(list[dict[str, object]], view.get("metrics", [])):
        metric = str(item["metric"])
        unit = str(item["unit"])
        observation: dict[str, object] = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": CODE_SYSTEM, "code": metric}], "text": metric},
            "extension": [
                {
                    "url": BASELINE_EXTENSION + "window-days",
                    "valueInteger": item["window_days"],
                },
                {
                    "url": BASELINE_EXTENSION + "classification",
                    "valueCode": item.get("classification", "insufficient_data"),
                },
            ],
            "referenceRange": [
                {
                    "low": {"value": item["low"], "unit": unit},
                    "high": {"value": item["high"], "unit": unit},
                    "text": (
                        f"Personal {item['window_days']}-day range; "
                        "indicative, from consumer device"
                    ),
                }
            ],
            "note": [{"text": "Informational only; not a clinical measurement."}],
        }
        if item["today"] is not None:
            observation["valueQuantity"] = {"value": item["today"], "unit": unit}
        if item.get("hour_fraction") is not None:
            cast(list[dict[str, object]], observation["extension"]).append(
                {
                    "url": BASELINE_EXTENSION + "hour-fraction",
                    "valueDecimal": item["hour_fraction"],
                }
            )
        for key in ("last_sync_at", "last_activity_at"):
            if view.get(key):
                cast(list[dict[str, object]], observation["extension"]).append(
                    {"url": BASELINE_EXTENSION + key.replace("_", "-"), "valueDateTime": view[key]}
                )
        entries.append({"resource": observation})
    for item in cast(list[dict[str, object]], view.get("series", [])):
        metric = str(item["metric"])
        entries.append(
            {
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {"coding": [{"system": CODE_SYSTEM, "code": metric}], "text": metric},
                    "effectiveDateTime": item["day"],
                    "valueQuantity": {"value": item["value"], "unit": METRICS[metric]},
                    "note": [{"text": "Synthetic or patient-imported consumer device aggregate."}],
                }
            }
        )
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}
