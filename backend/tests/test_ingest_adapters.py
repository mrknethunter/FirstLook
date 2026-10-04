"""Import adapters accept source values only and enforce bounded templates."""

from io import BytesIO

import pytest
from firstlook.ingest.adapters import CsvActivity, JsonActivity, MetricSample, SyntheticIkp
from firstlook.ingest.processing import aggregate


def test_csv_and_json_use_same_activity_template() -> None:
    csv_data = b"timestamp,metric,value,unit\n2026-10-02T10:00:00Z,steps,100,count\n"
    json_data = (
        b'[{"timestamp":"2026-10-02T10:00:00Z","metric":"steps","value":100,"unit":"count"}]'
    )
    csv_adapter, json_adapter = CsvActivity(), JsonActivity()
    assert csv_adapter.sniff(csv_data[:100])
    assert json_adapter.sniff(json_data[:100])
    csv_item = list(csv_adapter.parse(BytesIO(csv_data)))[0]
    json_item = list(json_adapter.parse(BytesIO(json_data)))[0]
    assert isinstance(csv_item, MetricSample)
    assert csv_item == json_item


def test_activity_rejects_unknown_metric_and_nonfinite_value() -> None:
    with pytest.raises(ValueError):
        list(
            CsvActivity().parse(
                BytesIO(b"timestamp,metric,value,unit\n2026-10-02T10:00:00Z,diagnosis,1,count\n")
            )
        )
    with pytest.raises(ValueError):
        list(
            JsonActivity().parse(
                BytesIO(
                    b'[{"timestamp":"2026-10-02T10:00:00Z","metric":"steps","value":"NaN","unit":"count"}]'
                )
            )
        )


def test_daily_aggregation_uses_documented_metric_rules() -> None:
    data = (
        b"timestamp,metric,value,unit\n"
        b"2026-10-02T10:00:00Z,steps,100,count\n"
        b"2026-10-02T11:00:00Z,steps,200,count\n"
    )
    samples = list(CsvActivity().parse(BytesIO(data)))
    assert all(isinstance(item, MetricSample) for item in samples)
    assert aggregate(samples) == [{"day": "2026-10-02", "metric": "steps", "value": 300.0}]


def test_synthetic_ikp_uses_source_label_without_inventing_code() -> None:
    payload = (
        b'{"prescriptions":[{"name":"Synthetic example medicine"}],'
        b'"conditions":[{"name":"Synthetic example condition"}]}'
    )
    items = list(SyntheticIkp().parse(BytesIO(payload)))
    assert [item.section for item in items] == ["medications", "conditions"]
    medication = items[0].resource["medicationCodeableConcept"]
    assert medication["text"] == "Synthetic example medicine"
    assert "coding" not in medication
