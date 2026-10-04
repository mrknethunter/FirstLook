from pathlib import Path

from firstlook.rules.engine import (
    ALLERGY_CLASS_URL,
    ATC_PREFIX_URL,
    DEVICE_TYPE_URL,
    evaluate_flags,
    load_rules,
)


def test_seeded_rule_inputs_are_deterministic_and_source_linked() -> None:
    rules = load_rules(Path(__file__).parents[1] / "rules" / "emergency_v1.yaml")
    resources = [
        {
            "resourceType": "MedicationStatement",
            "id": "med-1",
            "extension": [{"url": ATC_PREFIX_URL, "valueString": "B01AF"}],
        },
        {
            "resourceType": "Device",
            "id": "dev-1",
            "extension": [{"url": DEVICE_TYPE_URL, "valueString": "insulin_pump"}],
        },
        {
            "resourceType": "AllergyIntolerance",
            "id": "allergy-1",
            "extension": [{"url": ALLERGY_CLASS_URL, "valueString": "penicillin"}],
        },
    ]
    flags = evaluate_flags(resources, rules)
    assert [flag.rule_id for flag in flags] == [
        "med.anticoagulant",
        "allergy.penicillin",
        "device.insulin_pump",
    ]
    assert flags[0].source_ids == ("med-1",)
    assert all(flag.show_in_essentials for flag in flags)
