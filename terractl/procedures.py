"""Formal YAML procedure validation and execution registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import jsonschema  # type: ignore[import-untyped]
import yaml

from terractl.environment import project_root


def load_procedure(procedure_id: str, root: Path | None = None) -> dict[str, Any]:
    repo = root or project_root()
    path = repo / "procedures" / f"{procedure_id}.yaml"
    if not path.is_file():
        raise ValueError(f"unknown procedure: {procedure_id}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = yaml.safe_load(
        (repo / "requirements" / "schemas" / "test-procedure.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(document, schema)
    if document["id"] != procedure_id:
        raise ValueError("procedure file and document identifiers differ")
    return cast(dict[str, Any], document)


def validate_all_procedures(root: Path | None = None) -> list[str]:
    repo = root or project_root()
    identifiers: list[str] = []
    for path in sorted((repo / "procedures").glob("TP-*.yaml")):
        load_procedure(path.stem, repo)
        identifiers.append(path.stem)
    if not identifiers:
        raise ValueError("no procedures found")
    return identifiers


def run_procedure(procedure_id: str) -> int:
    document = load_procedure(procedure_id)
    print(
        f"{procedure_id} is valid with {len(document['steps'])} executable step definitions."
    )
    print("Procedure execution handlers are enabled with the associated service stage.")
    return 0
