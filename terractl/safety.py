"""Safety boundaries and credential-aware redaction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from terrawatch.constants import PROJECT_LABEL, PROJECT_LABEL_VALUE

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key)\b"
            r"(\s*[:=]\s*)([^\s,;\"']+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED PRIVATE KEY]",
    ),
    (
        re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:\s/@]+:)([^@\s/]+)(@)"),
        r"\1[REDACTED]\3",
    ),
    (re.compile(r"\b(?:gh[opurs]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"), "[REDACTED]"),
)


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Redact strings recursively without corrupting structured serialization."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def assert_project_identity(labels: dict[str, str], expected_compose_project: str) -> None:
    if labels.get(PROJECT_LABEL) != PROJECT_LABEL_VALUE:
        raise ValueError("container does not carry the TerraWatch project label")
    if labels.get("com.docker.compose.project") != expected_compose_project:
        raise ValueError("container belongs to a different Compose project")


def safe_artifact_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    allowed = root.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ValueError("artifact path escapes the project artifact root")
    return resolved
