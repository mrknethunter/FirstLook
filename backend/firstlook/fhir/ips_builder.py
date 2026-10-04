"""Build a document Bundle with the mandatory IPS sections."""

from __future__ import annotations

import copy
import html
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from fhir.resources.R4B.bundle import Bundle

from firstlook.rules.engine import ALLERGY_CLASS_URL, DEVICE_TYPE_URL, Flag

BASE = "https://firstlook-hy-demo.duckdns.org"
LOINC = "http://loinc.org"


@dataclass(frozen=True)
class PatientIdentity:
    given: str
    family: str
    birth_date: date | None
    gender: str | None
    age_band: str | None = None


def _opaque_id() -> str:
    return str(uuid4())


def _patient(
    identity: PatientIdentity, *, essentials: bool, show_sex: bool = False
) -> dict[str, Any]:
    patient: dict[str, Any] = {"resourceType": "Patient", "id": _opaque_id()}
    if essentials:
        initials = (
            ". ".join(part[0].upper() for part in (identity.given, identity.family) if part) + "."
        )
        patient["name"] = [{"text": initials}]
        if identity.birth_date or identity.age_band:
            if identity.birth_date:
                today = datetime.now(UTC).date()
                age = (
                    today.year
                    - identity.birth_date.year
                    - (
                        (today.month, today.day)
                        < (identity.birth_date.month, identity.birth_date.day)
                    )
                )
                decade = max(age // 10 * 10, 0)
                age_band = f"{decade}-{decade + 9}"
            else:
                age_band = identity.age_band or ""
            patient["extension"] = [
                {
                    "url": f"{BASE}/fhir/StructureDefinition/age-band",
                    "valueString": age_band,
                }
            ]
        if show_sex and identity.gender:
            patient["gender"] = identity.gender
    else:
        patient["name"] = [{"given": [identity.given], "family": identity.family}]
        if identity.birth_date:
            patient["birthDate"] = identity.birth_date.isoformat()
        else:
            # IPS requires birthDate; express the unknown value without guessing a date.
            patient["_birthDate"] = {
                "extension": [
                    {
                        "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                        "valueCode": "unknown",
                    }
                ]
            }
        if identity.gender:
            patient["gender"] = identity.gender
    return patient


def _rewrite_refs(value: Any, ids: dict[str, str], patient_id: str) -> Any:
    if isinstance(value, list):
        return [_rewrite_refs(item, ids, patient_id) for item in value]
    if isinstance(value, dict):
        rewritten = {}
        for key, item in value.items():
            if key == "reference" and isinstance(item, str):
                if item.startswith("Patient/"):
                    rewritten[key] = f"urn:uuid:{patient_id}"
                else:
                    old_id = item.rsplit("/", 1)[-1]
                    rewritten[key] = f"urn:uuid:{ids[old_id]}" if old_id in ids else item
            else:
                rewritten[key] = _rewrite_refs(item, ids, patient_id)
        return rewritten
    return value


def _export_resources(resources: list[dict[str, Any]], patient_id: str) -> list[dict[str, Any]]:
    """Re-key resources and omit private extensions without published FHIR definitions."""
    id_map = {str(item["id"]): _opaque_id() for item in resources if item.get("id")}
    exported = []
    for item in resources:
        copy_item = copy.deepcopy(item)
        old_id = str(copy_item.get("id", ""))
        copy_item["id"] = id_map.get(old_id, _opaque_id())
        extensions = [
            extension
            for extension in copy_item.get("extension", [])
            if not str(extension.get("url", "")).startswith(f"{BASE}/fhir/StructureDefinition/")
        ]
        if extensions:
            copy_item["extension"] = extensions
        else:
            copy_item.pop("extension", None)
        exported.append(_rewrite_refs(copy_item, id_map, patient_id))
    return exported


def _section(
    title: str, code: str, entries: list[dict[str, Any]], *, mandatory: bool
) -> dict[str, Any] | None:
    if not entries and not mandatory:
        return None
    section: dict[str, Any] = {
        "title": title,
        "code": {"coding": [{"system": LOINC, "code": code}]},
        "text": {"status": "generated", "div": _section_narrative(entries)},
    }
    if entries:
        section["entry"] = [{"reference": f"urn:uuid:{item['id']}"} for item in entries]
    else:
        section["emptyReason"] = {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/list-empty-reason",
                    "code": "unavailable",
                }
            ]
        }
    return section


def _section_narrative(entries: list[dict[str, Any]]) -> str:
    """Build escaped XHTML required by IPS without adding clinical assertions."""
    xmlns = 'xmlns="http://www.w3.org/1999/xhtml"'
    if not entries:
        return f"<div {xmlns}><p>Information unavailable.</p></div>"
    labels = [f"<li>{html.escape(_resource_label(item))}</li>" for item in entries]
    return f"<div {xmlns}><ul>{''.join(labels)}</ul></div>"


def _resource_label(item: dict[str, Any]) -> str:
    if item["resourceType"] == "Patient":
        name = item.get("name", [{}])[0]
        return " ".join([*name.get("given", []), name.get("family", "")]).strip() or "Patient"
    if item["resourceType"] == "Organization":
        return str(item.get("name", "Organization"))
    if item["resourceType"] == "Composition":
        return str(item.get("title", "Composition"))
    code = item.get("code") or item.get("medicationCodeableConcept") or item.get("type") or {}
    label = code.get("text") or item.get("device", {}).get("display")
    if not label:
        label = next(
            (
                coding.get("display") or coding.get("code")
                for coding in code.get("coding", [])
                if coding.get("display") or coding.get("code")
            ),
            item["resourceType"],
        )
    return str(label)


def _resource_narrative(item: dict[str, Any]) -> dict[str, str]:
    """Generate a text-only XHTML summary; source labels are HTML escaped."""
    label = html.escape(_resource_label(item))
    return {
        "status": "generated",
        "div": f'<div xmlns="http://www.w3.org/1999/xhtml"><p>{label}</p></div>',
    }


def build_ips_bundle(
    identity: PatientIdentity,
    resources: list[dict[str, Any]],
    flags: list[Flag] | None = None,
) -> dict[str, Any]:
    """Build a current document; profile validation is a separate CI gate."""
    patient = _patient(identity, essentials=False)
    exported = _export_resources(resources, patient["id"])
    functional_ids = {
        exported_item["id"]
        for source_item, exported_item in zip(resources, exported, strict=True)
        if source_item["resourceType"] == "Observation"
        and any(
            extension.get("url") == f"{BASE}/fhir/StructureDefinition/functional-status"
            and extension.get("valueBoolean") is True
            for extension in source_item.get("extension", [])
        )
    }
    # IPS medical-device entries describe use and reference the underlying Device.
    device_uses = [
        {
            "resourceType": "DeviceUseStatement",
            "id": _opaque_id(),
            "status": "active",
            "subject": {"reference": f"urn:uuid:{patient['id']}"},
            "device": {
                "reference": f"urn:uuid:{device['id']}",
                "display": device.get("type", {}).get("text", "Device"),
            },
        }
        for device in exported
        if device["resourceType"] == "Device" and device.get("status") == "active"
    ]
    author = {
        "resourceType": "Organization",
        "id": _opaque_id(),
        "name": "FirstLook (demo)",
    }
    flag_resources = [
        {
            "resourceType": "Flag",
            "id": _opaque_id(),
            "status": "active",
            "code": {"text": flag.text_key},
            "subject": {"reference": f"urn:uuid:{patient['id']}"},
        }
        for flag in (flags or [])
    ]
    all_resources = exported + device_uses + flag_resources
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in all_resources:
        by_type.setdefault(item["resourceType"], []).append(item)
    functional = [item for item in by_type.get("Observation", []) if item["id"] in functional_ids]
    vitals = [item for item in by_type.get("Observation", []) if item not in functional]
    sections = [
        _section("Problems", "11450-4", by_type.get("Condition", []), mandatory=True),
        _section("Allergies", "48765-2", by_type.get("AllergyIntolerance", []), mandatory=True),
        _section("Medications", "10160-0", by_type.get("MedicationStatement", []), mandatory=True),
        _section(
            "Medical Devices",
            "46264-8",
            by_type.get("DeviceUseStatement", []),
            mandatory=False,
        ),
        _section("Alerts", "104605-1", flag_resources, mandatory=False),
        _section("Advance Directives", "42348-3", by_type.get("Consent", []), mandatory=False),
        _section("Vital Signs", "8716-3", vitals, mandatory=False),
        _section("Functional Status", "47420-5", functional, mandatory=False),
    ]
    now = datetime.now(UTC).isoformat()
    composition = {
        "resourceType": "Composition",
        "id": _opaque_id(),
        "meta": {
            "profile": ["http://hl7.org/fhir/uv/ips/StructureDefinition/Composition-uv-ips|2.0.1"]
        },
        "status": "final",
        "type": {"coding": [{"system": LOINC, "code": "60591-5"}]},
        "subject": {"reference": f"urn:uuid:{patient['id']}"},
        "date": now,
        "author": [{"reference": f"urn:uuid:{author['id']}"}],
        "title": "International Patient Summary",
        "section": [section for section in sections if section],
    }
    for item in [composition, patient, author, *all_resources]:
        item["text"] = _resource_narrative(item)
    bundle = {
        "resourceType": "Bundle",
        "type": "document",
        "meta": {"profile": ["http://hl7.org/fhir/uv/ips/StructureDefinition/Bundle-uv-ips|2.0.1"]},
        "identifier": {"system": f"{BASE}/fhir/ips", "value": _opaque_id()},
        "timestamp": now,
        "entry": [
            {"fullUrl": f"urn:uuid:{item['id']}", "resource": item}
            for item in [composition, patient, author, *all_resources]
        ],
    }
    Bundle.model_validate(bundle)
    return bundle


def _safe_t1_resource(item: dict[str, Any]) -> dict[str, Any] | None:
    """Drop all free text and identifiers from T1 clinical resource projections."""
    rtype = item.get("resourceType")
    if rtype == "AllergyIntolerance":
        coding = _safe_codings(item.get("code", {}).get("coding", []))
        allergy_class = [
            extension["valueString"]
            for extension in item.get("extension", [])
            if extension.get("url") == ALLERGY_CLASS_URL
            and extension.get("valueString") == "penicillin"
        ]
        if not coding and not allergy_class:
            return None
        code = {"coding": coding} if coding else {"text": "penicillin"}
        safe = {"resourceType": rtype, "code": code}
        if item.get("criticality") in {"low", "high", "unable-to-assess"}:
            safe["criticality"] = item["criticality"]
        return safe
    if rtype == "Condition":
        coding = _safe_codings(item.get("code", {}).get("coding", []))
        if not coding:
            return None
        return {"resourceType": rtype, "code": {"coding": coding}}
    if rtype == "Device":
        coding = _safe_codings(item.get("type", {}).get("coding", []))
        types = [
            extension["valueString"]
            for extension in item.get("extension", [])
            if extension.get("url") == DEVICE_TYPE_URL
            and extension.get("valueString") == "insulin_pump"
        ]
        if not coding and not types:
            return None
        safe_type = {"coding": coding} if coding else {"text": "insulin pump"}
        return {"resourceType": rtype, "type": safe_type}
    if rtype == "Flag" and item.get("code", {}).get("text", "").startswith("flags."):
        return {"resourceType": rtype, "status": "active", "code": item["code"]}
    return None


def _safe_codings(codings: Any) -> list[dict[str, str]]:
    """Carry known code systems only; never copy patient-controlled display text into T1."""
    allowed_systems = {
        "http://www.whocc.no/atc",
        "http://snomed.info/sct",
        "http://hl7.org/fhir/sid/icd-10",
    }
    if not isinstance(codings, list):
        return []
    return [
        {"system": coding["system"], "code": coding["code"]}
        for coding in codings
        if isinstance(coding, dict)
        and coding.get("system") in allowed_systems
        and isinstance(coding.get("code"), str)
        and re.fullmatch(r"[A-Za-z0-9.\-]{1,24}", coding["code"])
    ]


def build_essentials_bundle(
    identity: PatientIdentity,
    resources: list[dict[str, Any]],
    selected_ids: set[str],
    flags: list[Flag],
    *,
    show_sex: bool = False,
) -> dict[str, Any]:
    """Return only patient-selected, structured T1 content with opaque export IDs."""
    patient = _patient(identity, essentials=True, show_sex=show_sex)
    selected = []
    for item in resources:
        if str(item.get("id")) in selected_ids:
            safe = _safe_t1_resource(item)
            if safe:
                selected.append(safe)
    for flag in flags:
        if flag.show_in_essentials and f"flag:{flag.rule_id}" in selected_ids:
            selected.append(
                {"resourceType": "Flag", "status": "active", "code": {"text": flag.text_key}}
            )
    exported = _export_resources(selected, patient["id"])
    for item in exported:
        if item["resourceType"] == "Flag":
            item["subject"] = {"reference": f"Patient/{patient['id']}"}
        if item["resourceType"] == "AllergyIntolerance":
            item["patient"] = {"reference": f"Patient/{patient['id']}"}
        if item["resourceType"] == "Condition":
            item["subject"] = {"reference": f"Patient/{patient['id']}"}
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "meta": {"tag": [{"system": f"{BASE}/fhir/CodeSystem/tier", "code": "T1-essentials"}]},
        "entry": [{"resource": item} for item in [patient, *exported]],
    }
    Bundle.model_validate(bundle)
    return bundle
