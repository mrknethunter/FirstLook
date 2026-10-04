from datetime import date

from firstlook.fhir.ips_builder import PatientIdentity, build_essentials_bundle, build_ips_bundle
from firstlook.fhir.validation import validate_fhir_resource
from firstlook.rules.engine import Flag


def test_ips_has_mandatory_sections_and_empty_reasons() -> None:
    identity = PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male")
    bundle = build_ips_bundle(identity, [])
    assert bundle["type"] == "document"
    composition = bundle["entry"][0]["resource"]
    assert [section["code"]["coding"][0]["code"] for section in composition["section"]] == [
        "11450-4",
        "48765-2",
        "10160-0",
    ]
    assert all("emptyReason" in section for section in composition["section"])


def test_essentials_strips_identifiers_and_uncontrolled_free_text() -> None:
    identity = PatientIdentity("Anna", "Kowalska", date(1952, 1, 1), "female")
    resources = [
        {
            "resourceType": "AllergyIntolerance",
            "id": "unsafe-note",
            "criticality": "high",
            "code": {"text": "Anna Kowalska, call +48 123456789"},
            "patient": {"reference": "Patient/internal"},
            "note": [{"text": "call daughter"}],
        }
    ]
    bundle = build_essentials_bundle(
        identity,
        resources,
        {"unsafe-note", "flag:med.anticoagulant"},
        [Flag("med.anticoagulant", "critical", "flags.anticoagulant", ("med-1",), True)],
    )
    rendered = str(bundle)
    assert "Kowalska" not in rendered
    assert "123456789" not in rendered
    assert "call daughter" not in rendered
    assert "birthDate" not in rendered
    assert len(bundle["entry"]) == 2  # pseudonymised Patient and code-based Flag


def test_supported_fhir_resource_is_structurally_validated() -> None:
    allergy = validate_fhir_resource(
        {
            "resourceType": "AllergyIntolerance",
            "patient": {"reference": "Patient/example"},
            "code": {"text": "penicillin"},
            "criticality": "high",
        }
    )
    assert allergy["resourceType"] == "AllergyIntolerance"


def test_essentials_carries_codes_without_uncontrolled_displays() -> None:
    identity = PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male")
    resources = [
        {
            "resourceType": "AllergyIntolerance",
            "id": "allergy-1",
            "criticality": "high",
            "code": {
                "coding": [
                    {
                        "system": "http://www.whocc.no/atc",
                        "code": "M01AE01",
                        "display": "Marco Rossi private note",
                    }
                ]
            },
        }
    ]
    bundle = build_essentials_bundle(identity, resources, {"allergy-1"}, [])
    rendered = str(bundle)
    assert "M01AE01" in rendered
    assert "private note" not in rendered
    assert "Rossi" not in rendered
    assert "1992-03-14" not in rendered


def test_essentials_flag_can_be_deselected() -> None:
    identity = PatientIdentity("Marco", "Rossi", None, None, "30-39")
    flag = Flag("insulin", "critical", "flags.insulin", ("source",), True)
    bundle = build_essentials_bundle(identity, [], set(), [flag])
    assert len(bundle["entry"]) == 1
    assert bundle["entry"][0]["resource"]["extension"][0]["valueString"] == "30-39"


def test_ips_references_use_per_export_opaque_urns() -> None:
    identity = PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male")
    resources = [
        {
            "resourceType": "Condition",
            "id": "internal-condition",
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "E10"}]},
            "subject": {"reference": "Patient/internal"},
        }
    ]
    bundle = build_ips_bundle(identity, resources)
    rendered = str(bundle)
    assert "internal-condition" not in rendered
    assert "Patient/internal" not in rendered
    composition = bundle["entry"][0]["resource"]
    section_ref = composition["section"][0]["entry"][0]["reference"]
    assert any(entry["fullUrl"] == section_ref for entry in bundle["entry"])


def test_ips_device_section_and_narrative_are_safe() -> None:
    identity = PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male")
    device = {
        "resourceType": "Device",
        "id": "internal-device",
        "status": "active",
        "patient": {"reference": "Patient/self"},
        "type": {"text": "<script>untrusted</script>"},
        "extension": [
            {
                "url": "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/device-type",
                "valueString": "insulin_pump",
            }
        ],
    }
    bundle = build_ips_bundle(identity, [device])
    composition = bundle["entry"][0]["resource"]
    section = next(
        item for item in composition["section"] if item["code"]["coding"][0]["code"] == "46264-8"
    )
    assert section["text"]["div"].startswith('<div xmlns="http://www.w3.org/1999/xhtml">')
    assert len(section["entry"]) == 1
    device_use = next(
        item["resource"]
        for item in bundle["entry"]
        if item["resource"]["resourceType"] == "DeviceUseStatement"
    )
    assert section["entry"][0]["reference"] == f"urn:uuid:{device_use['id']}"
    assert "&lt;script&gt;" in device_use["text"]["div"]
    exported_device = next(
        item["resource"] for item in bundle["entry"] if item["resource"]["resourceType"] == "Device"
    )
    assert "extension" not in exported_device


def test_ips_unknown_birth_date_uses_data_absent_reason() -> None:
    bundle = build_ips_bundle(PatientIdentity("Anna", "Kowalska", None, "female", "70-79"), [])
    patient = bundle["entry"][1]["resource"]
    assert "birthDate" not in patient
    assert patient["_birthDate"]["extension"][0] == {
        "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
        "valueCode": "unknown",
    }


def test_ips_classifies_functional_observation_before_private_extension_removal() -> None:
    observation = {
        "resourceType": "Observation",
        "id": "functional-observation",
        "status": "final",
        "code": {"text": "Synthetic functional observation"},
        "subject": {"reference": "Patient/self"},
        "extension": [
            {
                "url": "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/functional-status",
                "valueBoolean": True,
            }
        ],
    }
    bundle = build_ips_bundle(
        PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male"), [observation]
    )
    sections = bundle["entry"][0]["resource"]["section"]
    codes = [section["code"]["coding"][0]["code"] for section in sections]
    assert "47420-5" in codes
    assert "8716-3" not in codes
    exported = next(
        item["resource"]
        for item in bundle["entry"]
        if item["resource"]["resourceType"] == "Observation"
    )
    assert "extension" not in exported
