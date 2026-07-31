"""Requirements and verification traceability validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from terractl.environment import project_root


@dataclass
class TraceabilityResult:
    requirements: int = 0
    mapped_requirements: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        complete = self.requirements > 0 and self.requirements == self.mapped_requirements
        return not self.errors and complete


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def validate_traceability(root: Path | None = None) -> TraceabilityResult:
    repo = root or project_root()
    result = TraceabilityResult()
    requirements_doc = _load_yaml(repo / "requirements" / "system-requirements.yaml")
    matrix_doc = _load_yaml(repo / "requirements" / "verification-matrix.yaml")
    requirements = requirements_doc.get("requirements", [])
    mappings = matrix_doc.get("mappings", [])
    if not isinstance(requirements, list) or not isinstance(mappings, list):
        result.errors.append("requirements and mappings must be lists")
        return result

    requirement_ids: set[str] = set()
    procedure_ids = {path.stem for path in (repo / "procedures").glob("TP-*.yaml")}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            result.errors.append("requirement entries must be objects")
            continue
        identifier = str(requirement.get("id", ""))
        if not identifier:
            result.errors.append("requirement without an id")
            continue
        if identifier in requirement_ids:
            result.errors.append(f"duplicate requirement id: {identifier}")
        requirement_ids.add(identifier)
        for field_name in (
            "statement",
            "rationale",
            "verification_method",
            "procedure_ids",
            "automated_tests",
            "status",
            "evidence_location",
        ):
            if field_name not in requirement:
                result.errors.append(f"{identifier} missing {field_name}")

    mapped_ids: set[str] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            result.errors.append("mapping entries must be objects")
            continue
        identifier = str(mapping.get("requirement_id", ""))
        if identifier not in requirement_ids:
            result.errors.append(f"mapping references unknown requirement: {identifier}")
            continue
        mapped_ids.add(identifier)
        activities = mapping.get("verification_activities", [])
        if not isinstance(activities, list) or not activities:
            result.errors.append(f"{identifier} has no verification activity")
        for procedure in mapping.get("procedure_ids", []):
            if procedure not in procedure_ids:
                result.errors.append(f"{identifier} references missing procedure: {procedure}")

    missing = requirement_ids - mapped_ids
    stale = mapped_ids - requirement_ids
    result.errors.extend(f"unmapped requirement: {identifier}" for identifier in sorted(missing))
    result.errors.extend(f"stale mapping: {identifier}" for identifier in sorted(stale))
    result.requirements = len(requirement_ids)
    result.mapped_requirements = len(mapped_ids)
    return result
