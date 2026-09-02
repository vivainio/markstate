"""Validate Markstate flow documents against the bundled schema."""

import json
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from markstate.config import CONFIG_FILENAME, HIDDEN_CONFIG_PATH, resolve_glob_reference

SCHEMA_VERSION = "v1"


def find_flow_path(start: Path | None = None) -> Path:
    """Find the nearest visible or hidden flow file."""
    origin = (start or Path.cwd()).resolve()
    for directory in [origin, *origin.parents]:
        for name in (CONFIG_FILENAME, HIDDEN_CONFIG_PATH):
            candidate = directory / name
            if candidate.exists():
                return candidate
    raise FileNotFoundError(f"{CONFIG_FILENAME} not found in {origin} or any parent")


def load_schema() -> dict[str, Any]:
    """Load the current bundled flow schema."""
    resource = files("markstate").joinpath("schema", SCHEMA_VERSION, "flow.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def discover_flow_chain(
    start: Path, variables: dict[str, str] | None = None
) -> tuple[list[Path], list[str]]:
    """Find every flow reached through use and redirect references."""
    overrides = variables or {}
    paths: list[Path] = []
    problems: list[str] = []
    visiting: set[Path] = set()
    visited: set[Path] = set()

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in visiting:
            problems.append(f"{path}: reference cycle")
            return
        if path in visited:
            return
        if not path.is_file():
            problems.append(f"{path}: referenced flow not found")
            return
        visiting.add(path)
        visited.add(path)
        paths.append(path)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            visiting.remove(path)
            return
        if not isinstance(loaded, dict):
            visiting.remove(path)
            return

        reference = loaded.get("redirect") or loaded.get("use")
        target = _selected_reference(reference, loaded.get("$variables"), overrides)
        if target is not None:
            visit(resolve_glob_reference(path, target))
        elif reference is not None:
            problems.append(f"{path}: cannot resolve use/redirect target from supplied variables")
        visiting.remove(path)

    visit(start)
    return paths, problems


def _selected_reference(reference: Any, definitions: Any, overrides: dict[str, str]) -> str | None:
    if isinstance(reference, str):
        return reference
    if not isinstance(reference, dict):
        return None
    name = reference.get("$select")
    cases = reference.get("cases")
    if not isinstance(name, str) or not isinstance(cases, dict):
        return None
    value = overrides.get(name)
    if value is None and isinstance(definitions, dict):
        definition = definitions.get(name)
        if isinstance(definition, dict) and "default" in definition:
            value = str(definition["default"])
    target = cases.get(value) if value is not None else None
    return target if isinstance(target, str) else None


def validate_flow(path: Path) -> list[str]:
    """Return human-readable schema errors for one flow file."""
    # Keep jsonschema and its dependencies off the normal CLI startup path.
    from markstate._schema_runner import validate  # noqa: PLC0415

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"invalid YAML: {error}"]

    with tempfile.TemporaryDirectory() as temp_dir:
        document_path = Path(temp_dir) / "flow.json"
        document_path.write_text(json.dumps(document), encoding="utf-8")
        schema_path = files("markstate").joinpath("schema", SCHEMA_VERSION, "flow.schema.json")
        return validate(Path(str(schema_path)), document_path)
