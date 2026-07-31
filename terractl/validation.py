"""Repository-wide static validation."""

from __future__ import annotations

import json

import jsonschema  # type: ignore[import-untyped]

from terractl.environment import project_root
from terractl.procedures import validate_all_procedures
from terractl.traceability import validate_traceability


def validate_repository() -> dict[str, object]:
    root = project_root()
    schema_dir = root / "requirements" / "schemas"
    schemas = sorted(schema_dir.glob("*.json"))
    for schema_path in schemas:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    procedures = validate_all_procedures(root)
    traceability = validate_traceability(root)
    if not traceability.passed:
        raise ValueError("; ".join(traceability.errors))
    return {
        "schemas": len(schemas),
        "procedures": procedures,
        "requirements": traceability.requirements,
        "passed": True,
    }
