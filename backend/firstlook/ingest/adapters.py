"""Bounded CSV/JSON activity and synthetic IKP import adapters."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Literal, Protocol

import ijson  # type: ignore[import-untyped]

from firstlook.baseline.service import METRICS
from firstlook.fhir.validation import validate_fhir_resource

MAX_RECORDS = 100_000
ImportKind = Literal["activity_csv", "activity_json", "synthetic_ikp"]


@dataclass(frozen=True)
class MetricSample:
    timestamp: datetime
    metric: str
    value: float
    unit: str


@dataclass(frozen=True)
class ResourceItem:
    section: str
    resource: dict[str, Any]


ParsedItem = MetricSample | ResourceItem


class ImportAdapter(Protocol):
    kind: ImportKind

    def sniff(self, head: bytes) -> bool: ...

    def parse(self, stream: BinaryIO) -> Iterator[ParsedItem]: ...


def _sample(raw: dict[str, Any]) -> MetricSample:
    if set(raw) != {"timestamp", "metric", "value", "unit"}:
        raise ValueError("activity row must have timestamp, metric, value, unit")
    timestamp = datetime.fromisoformat(str(raw["timestamp"]).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    metric = str(raw["metric"])
    if metric not in METRICS:
        raise ValueError("unsupported metric")
    unit = str(raw["unit"])
    if unit != METRICS[metric]:
        raise ValueError("unsupported unit")
    value = float(raw["value"])
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid metric value")
    return MetricSample(timestamp, metric, value, unit)


class CsvActivity:
    kind: ImportKind = "activity_csv"

    def sniff(self, head: bytes) -> bool:
        return (
            head.removeprefix(b"\xef\xbb\xbf").startswith(b"timestamp,metric,value,unit")
            and b"\x00" not in head
        )

    def parse(self, stream: BinaryIO) -> Iterator[ParsedItem]:
        reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
        if reader.fieldnames != ["timestamp", "metric", "value", "unit"]:
            raise ValueError("invalid CSV header")
        for count, row in enumerate(reader, start=1):
            if count > MAX_RECORDS:
                raise ValueError("too many records")
            yield _sample(row)


class JsonActivity:
    kind: ImportKind = "activity_json"

    def sniff(self, head: bytes) -> bool:
        return head.lstrip().startswith(b"[") and b"\x00" not in head

    def parse(self, stream: BinaryIO) -> Iterator[ParsedItem]:
        for count, row in enumerate(ijson.items(stream, "item"), start=1):
            if count > MAX_RECORDS:
                raise ValueError("too many records")
            if not isinstance(row, dict):
                raise ValueError("activity item must be an object")
            yield _sample(row)


class SyntheticIkp:
    kind: ImportKind = "synthetic_ikp"

    def sniff(self, head: bytes) -> bool:
        return head.lstrip().startswith(b"{") and b"\x00" not in head

    def parse(self, stream: BinaryIO) -> Iterator[ParsedItem]:
        """Map source-provided labels/codes; never infer a medical code."""
        for section, prefix in (
            ("medications", "prescriptions.item"),
            ("conditions", "conditions.item"),
        ):
            stream.seek(0)
            for count, item in enumerate(ijson.items(stream, prefix), start=1):
                if count > MAX_RECORDS:
                    raise ValueError("too many records")
                if not isinstance(item, dict):
                    raise ValueError("portal item must be an object")
                name = item.get("name")
                if not isinstance(name, str) or not 1 <= len(name) <= 200:
                    raise ValueError("portal item needs a source label")
                coded: dict[str, Any] = {"text": name}
                system, code = item.get("system"), item.get("code")
                if system is not None or code is not None:
                    if not isinstance(system, str) or not isinstance(code, str) or not code:
                        raise ValueError("portal code needs a system and value")
                    coded["coding"] = [{"system": system, "code": code}]
                if section == "medications":
                    resource = {
                        "resourceType": "MedicationStatement",
                        "status": "active",
                        "medicationCodeableConcept": coded,
                        "subject": {"reference": "Patient/self"},
                    }
                else:
                    resource = {
                        "resourceType": "Condition",
                        "clinicalStatus": {"text": "active"},
                        "code": coded,
                        "subject": {"reference": "Patient/self"},
                    }
                yield ResourceItem(section, validate_fhir_resource(resource))


ADAPTERS: dict[ImportKind, ImportAdapter] = {
    "activity_csv": CsvActivity(),
    "activity_json": JsonActivity(),
    "synthetic_ikp": SyntheticIkp(),
}
