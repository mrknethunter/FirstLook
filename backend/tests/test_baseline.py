"""Personal robust range boundaries and synthetic fixture coverage."""

import pytest
from fhir.resources.R4B.bundle import Bundle
from firstlook.baseline.router import _partial_day_demo_values
from firstlook.baseline.service import as_fhir_bundle, classify_today, robust_range
from firstlook.seed import _synthetic_values


def test_coverage_threshold_and_median_mad_ignore_outlier() -> None:
    assert robust_range([5.0] * 4, 7) is None
    result = robust_range([5.0, 5.0, 6.0, 6.0, 7.0, 1000.0], 7)
    assert result is not None
    assert result.n == 6
    assert result.median == 6.0
    assert result.mad == 1.0
    assert result.low == pytest.approx(3.0348)
    assert result.high == pytest.approx(8.9652)
    assert classify_today(9.0, result)[0] == "above"


def test_partial_day_activity_uses_hour_fraction() -> None:
    result = robust_range([100.0] * 30, 30)
    assert result is not None
    assert classify_today(50.0, result, 0.5)[0] == "within"
    assert classify_today(50.0, result, 1.0)[0] == "below"


def test_invalid_wearable_values_fail_closed() -> None:
    with pytest.raises(ValueError):
        robust_range([float("nan")] * 7, 7)
    result = robust_range([1.0] * 7, 7)
    assert result is not None
    with pytest.raises(ValueError):
        classify_today(1.0, result, 0.0)


def test_synthetic_histories_cover_specified_metrics() -> None:
    for persona in ("anna", "marco"):
        days = [_synthetic_values(persona, index) for index in range(365)]
        assert len(days) == 365
        assert set(days[0]) == {
            "steps",
            "active_energy",
            "resting_hr",
            "hr_min",
            "hr_max",
            "sleep_minutes",
        }
        assert all(value >= 0 for day in days for value in day.values())


def test_demo_sync_never_creates_fractional_steps() -> None:
    for persona in ("anna", "marco"):
        for hour in range(24):
            values = _partial_day_demo_values(persona, hour)
            assert values["steps"].is_integer()
            assert values["steps"] >= 0


def test_baseline_bundle_contains_all_windows_and_recent_series() -> None:
    view = {
        "metrics": [
            {
                "metric": "steps",
                "unit": "count",
                "window_days": window,
                "low": 10.0,
                "high": 30.0,
                "today": 20.0,
                "classification": "within",
                "hour_fraction": 0.5,
            }
            for window in (7, 30, 365)
        ],
        "series": [{"day": "2026-10-02", "metric": "steps", "value": 19.0}],
        "last_sync_at": "2026-10-04T08:00:00+00:00",
        "last_activity_at": "2026-10-04T07:56:00+00:00",
    }
    bundle = as_fhir_bundle(view)
    assert len(bundle["entry"]) == 4
    assert Bundle.model_validate(bundle).type == "collection"
    metric_extensions = bundle["entry"][0]["resource"]["extension"]
    extension_by_name = {item["url"].rsplit("/", 1)[-1]: item for item in metric_extensions}
    assert extension_by_name["baseline-last-sync-at"]["valueDateTime"] == view["last_sync_at"]
    assert (
        extension_by_name["baseline-last-activity-at"]["valueDateTime"] == view["last_activity_at"]
    )
    assert extension_by_name["baseline-classification"]["valueCode"] == "within"
    assert extension_by_name["baseline-hour-fraction"]["valueDecimal"] == 0.5
