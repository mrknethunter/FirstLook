"""Evaluate reviewable YAML rules against decrypted FHIR data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ATC_PREFIX_URL = "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/atc-prefix"
DEVICE_TYPE_URL = "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/device-type"
ALLERGY_CLASS_URL = "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/allergy-class"


class RuleMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_atc_prefix: list[str] = Field(default_factory=list)
    device_snomed: list[str] = Field(default_factory=list)
    device_type: list[str] = Field(default_factory=list)
    allergy_class: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_a_match(self) -> RuleMatch:
        if not any(
            (self.medication_atc_prefix, self.device_snomed, self.device_type, self.allergy_class)
        ):
            raise ValueError("rule has no matching criterion")
        return self


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)
    severity: Literal["critical", "high", "moderate", "info"]
    match: RuleMatch
    text_key: str
    show_in_essentials: bool = False


@dataclass(frozen=True)
class Flag:
    rule_id: str
    severity: str
    text_key: str
    source_ids: tuple[str, ...]
    show_in_essentials: bool


def load_rules(path: Path) -> tuple[Rule, ...]:
    """Load static reviewed rules; reject unknown fields before serving requests."""
    parsed: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, list):
        raise ValueError("rules file must contain a list")
    rules = tuple(Rule.model_validate(item) for item in parsed)
    if len({rule.id for rule in rules}) != len(rules):
        raise ValueError("duplicate rule identifier")
    return rules


def _extension(resource: dict[str, Any], url: str) -> list[str]:
    values: list[str] = []
    for item in resource.get("extension", []):
        if (
            isinstance(item, dict)
            and item.get("url") == url
            and isinstance(item.get("valueString"), str)
        ):
            values.append(item["valueString"])
    return values


def _codes(resource: dict[str, Any], field: str, system: str) -> list[str]:
    coded = resource.get(field)
    if not isinstance(coded, dict):
        return []
    return [
        item["code"]
        for item in coded.get("coding", [])
        if isinstance(item, dict)
        and item.get("system") == system
        and isinstance(item.get("code"), str)
    ]


def _matches(rule: Rule, resource: dict[str, Any]) -> bool:
    rtype = resource.get("resourceType")
    match = rule.match
    if rtype == "MedicationStatement" and match.medication_atc_prefix:
        prefixes = _extension(resource, ATC_PREFIX_URL)
        prefixes.extend(_codes(resource, "medicationCodeableConcept", "http://www.whocc.no/atc"))
        return any(
            value.startswith(prefix) for value in prefixes for prefix in match.medication_atc_prefix
        )
    if rtype == "Device":
        if match.device_type and set(_extension(resource, DEVICE_TYPE_URL)) & set(
            match.device_type
        ):
            return True
        if match.device_snomed:
            return bool(
                set(_codes(resource, "type", "http://snomed.info/sct")) & set(match.device_snomed)
            )
    if rtype == "AllergyIntolerance" and match.allergy_class:
        return bool(set(_extension(resource, ALLERGY_CLASS_URL)) & set(match.allergy_class))
    return False


def evaluate_flags(resources: list[dict[str, Any]], rules: tuple[Rule, ...]) -> list[Flag]:
    """Return source-linked informational flags, sorted by severity."""
    ranking = {"critical": 0, "high": 1, "moderate": 2, "info": 3}
    flags = []
    for rule in rules:
        source_ids = tuple(
            str(resource["id"])
            for resource in resources
            if resource.get("id") and _matches(rule, resource)
        )
        if source_ids:
            flags.append(
                Flag(rule.id, rule.severity, rule.text_key, source_ids, rule.show_in_essentials)
            )
    return sorted(flags, key=lambda flag: (ranking[flag.severity], flag.rule_id))
