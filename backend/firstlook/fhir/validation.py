"""Structural FHIR validation before encrypted storage and export."""

from __future__ import annotations

from typing import Any, cast

from fhir.resources.R4B.allergyintolerance import AllergyIntolerance
from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.consent import Consent
from fhir.resources.R4B.device import Device
from fhir.resources.R4B.deviceusestatement import DeviceUseStatement
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.medication import Medication
from fhir.resources.R4B.medicationstatement import MedicationStatement
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient
from pydantic import BaseModel, ValidationError

FHIR_MODELS = {
    "Patient": Patient,
    "AllergyIntolerance": AllergyIntolerance,
    "Condition": Condition,
    "MedicationStatement": MedicationStatement,
    "Medication": Medication,
    "Device": Device,
    "DeviceUseStatement": DeviceUseStatement,
    "Observation": Observation,
    "Consent": Consent,
    "DocumentReference": DocumentReference,
}


def validate_fhir_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """Reject unsupported or malformed resources without echoing clinical data."""
    rtype = resource.get("resourceType")
    model = FHIR_MODELS.get(rtype) if isinstance(rtype, str) else None
    if model is None:
        raise ValueError("unsupported FHIR resource type")
    try:
        parsed = cast(type[BaseModel], model).model_validate(resource)
        return parsed.model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        raise ValueError("invalid FHIR resource") from exc
