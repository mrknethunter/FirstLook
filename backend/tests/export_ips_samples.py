"""Export the two synthetic seed personas for the official IPS validator gate."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from firstlook.fhir.ips_builder import PatientIdentity, build_ips_bundle
from firstlook.rules.engine import evaluate_flags, load_rules
from firstlook.seed import _anna_resources, _marco_resources


def _prepared(resources: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Apply the same subject reference that profile storage adds before validation."""
    result = []
    for _, payload in resources:
        item = {**payload, "id": str(uuid4())}
        field = "patient" if item["resourceType"] in {"AllergyIntolerance", "Device"} else "subject"
        item[field] = {"reference": "Patient/self"}
        result.append(item)
    return result


def main(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = (
        (
            "anna",
            PatientIdentity("Anna", "Kowalska", None, "female", "70-79"),
            _anna_resources(),
        ),
        (
            "marco",
            PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male"),
            _marco_resources(),
        ),
        (
            "empty",
            PatientIdentity("Marco", "Rossi", date(1992, 3, 14), "male"),
            [],
        ),
    )
    rules = load_rules(Path(__file__).resolve().parents[1] / "rules" / "emergency_v1.yaml")
    for name, identity, resources in cases:
        prepared = _prepared(resources)
        bundle = build_ips_bundle(identity, prepared, evaluate_flags(prepared, rules))
        (output_dir / f"{name}.json").write_text(
            json.dumps(bundle, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
