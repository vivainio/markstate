"""Isolated JSON Schema runner launched by ``markstate validate``."""

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


def _specific_errors(error: ValidationError) -> list[ValidationError]:
    """Return the deepest useful errors hidden by oneOf wrappers."""
    leaves: list[ValidationError] = []

    def collect(item: ValidationError) -> None:
        if not item.context:
            leaves.append(item)
            return
        for child in item.context:
            collect(child)

    collect(error)
    depth = max((len(item.absolute_path) for item in leaves), default=0)
    deepest = [item for item in leaves if len(item.absolute_path) == depth]
    non_type_paths = {tuple(item.absolute_path) for item in deepest if item.validator != "type"}
    return [
        item
        for item in deepest
        if item.validator != "type" or tuple(item.absolute_path) not in non_type_paths
    ]


def validate(schema_path: Path, document_path: Path) -> list[str]:
    schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
    document: Any = json.loads(document_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = [
        specific
        for error in validator.iter_errors(document)
        for specific in _specific_errors(error)
    ]
    errors.sort(key=lambda error: list(error.absolute_path))
    result: list[str] = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        result.append(f"{location}: {error.message}")
    return result


def main() -> None:
    errors = validate(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(errors))


if __name__ == "__main__":
    main()
