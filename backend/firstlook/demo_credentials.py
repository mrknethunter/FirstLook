"""Stable, demo-only logins loaded from a mounted secret file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from firstlook.identity.security import validate_password

DEMO_DOMAIN = "firstlook-hy-demo.duckdns.org"


@dataclass(frozen=True)
class DemoCredential:
    email: str
    password: str


def demo_labels(judge_tables: int) -> tuple[str, ...]:
    """Return the exact patient and professional accounts for this demo."""
    labels = ["patient_anna", "patient_marco"]
    for table in range(1, judge_tables + 1):
        labels.extend((f"responder_{table}", f"ed_staff_{table}"))
    return tuple(labels)


def _email_for(label: str) -> str:
    if label.startswith("patient_"):
        local = f"{label.removeprefix('patient_')}.demo"
    elif label.startswith("responder_"):
        local = f"responder.t{label.removeprefix('responder_')}"
    else:
        local = f"ed.t{label.removeprefix('ed_staff_')}"
    return f"{local}@{DEMO_DOMAIN}"


def load_demo_credentials(path: Path, judge_tables: int) -> dict[str, DemoCredential]:
    """Validate the mounted TSV without echoing passwords or file contents."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("demo credential secret is missing") from exc
    expected = set(demo_labels(judge_tables))
    credentials: dict[str, DemoCredential] = {}
    passwords: set[str] = set()
    for line in content.splitlines():
        fields = line.split("\t")
        if len(fields) != 2:
            raise RuntimeError("invalid demo credential secret")
        label, password = fields
        if label not in expected or label in credentials or password in passwords:
            raise RuntimeError("invalid demo credential secret")
        try:
            validate_password(password)
        except ValueError as exc:
            raise RuntimeError("invalid demo credential secret") from exc
        credentials[label] = DemoCredential(_email_for(label), password)
        passwords.add(password)
    if set(credentials) != expected:
        raise RuntimeError("demo credential secret does not match judge tables")
    return credentials
