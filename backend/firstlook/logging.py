"""JSON file logging with an allowlist and defensive PHI redaction."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

# Deny by default: a caller cannot accidentally invent a PHI-bearing log field.
ALLOWED_KEYS = frozenset(
    {
        "ts",
        "level",
        "service",
        "event",
        "request_id",
        "actor_type",
        "actor_ref",
        "route",
        "status",
        "latency_ms",
        "tier",
    }
)
PATTERNS = (
    re.compile(r"shlink:/\S+", re.IGNORECASE),
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"\b\d{11}\b"),  # PESEL-shaped data
    re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)"),
)


def scrub_event(_: Any, __: str, event: MutableMapping[str, Any]) -> dict[str, Any]:
    """Drop dangerous fields and redact accidental secrets in remaining text."""
    clean: dict[str, Any] = {}
    for key, value in event.items():
        if key not in ALLOWED_KEYS:
            continue
        if isinstance(value, (dict, list, tuple)):
            continue
        if isinstance(value, str):
            for pattern in PATTERNS:
                value = pattern.sub("[redacted]", value)
        clean[key] = value
    return clean


def configure_logging(service: str, directory: Path, level: str = "INFO") -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / f"{service}.jsonl", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.add_log_level,
            scrub_event,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
