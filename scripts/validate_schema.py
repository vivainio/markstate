"""Validate the versioned flow schema and every example flow."""

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "markstate" / "schema" / "v1" / "flow.schema.json"
PUBLISHED_SCHEMA_PATH = ROOT / "docs" / "schema" / "v1" / "flow.schema.json"


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if SCHEMA_PATH.read_bytes() != PUBLISHED_SCHEMA_PATH.read_bytes():
        raise SystemExit("bundled and published v1 schemas differ")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    flow_paths = sorted((ROOT / "examples").glob("**/flow.yml"))
    failures: list[str] = []
    for path in flow_paths:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            failures.append(f"{path.relative_to(ROOT)}:{location}: {error.message}")

    if failures:
        raise SystemExit("\n".join(failures))
    print(f"validated schema and {len(flow_paths)} example flows")


if __name__ == "__main__":
    main()
