"""Load and validate flow.yml, walking up from cwd to find it."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


CONFIG_FILENAME = "flow.yml"


@dataclass
class Move:
    name: str
    from_state: str
    to_state: str


@dataclass
class Condition:
    file: str | None = None
    glob: str | None = None
    status: str | None = None
    all_status: str | None = None


@dataclass
class Phase:
    name: str
    produces: list[str] = field(default_factory=list)
    gates: list[Condition] = field(default_factory=list)
    advance_when: list[Condition] = field(default_factory=list)


@dataclass
class FlowConfig:
    root: Path
    status_field: str
    phases: list[Phase]
    moves: list[Move]

    def move(self, name: str) -> Move | None:
        return next((m for m in self.moves if m.name == name), None)

    def phase(self, name: str) -> Phase | None:
        return next((p for p in self.phases if p.name == name), None)

    def move_names(self) -> list[str]:
        return [m.name for m in self.moves]


def find_and_load(start: Path | None = None) -> FlowConfig:
    """Walk up from start (default: cwd) to find flow.yml and load it."""
    path = _find(start or Path.cwd())
    if path is None:
        raise FileNotFoundError(f"{CONFIG_FILENAME} not found in {start or Path.cwd()} or any parent")
    return _load(path)


def _find(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.exists():
            return candidate
    return None


def _load(path: Path) -> FlowConfig:
    raw = yaml.safe_load(path.read_text())

    phases = [_parse_phase(p) for p in raw.get("phases", [])]
    moves = [_parse_move(m) for m in raw.get("moves", [])]

    return FlowConfig(
        root=path.parent,
        status_field=raw.get("status_field", "status"),
        phases=phases,
        moves=moves,
    )


def _parse_phase(raw: dict) -> Phase:
    return Phase(
        name=raw["name"],
        produces=raw.get("produces", []),
        gates=[_parse_condition(c) for c in raw.get("gates", [])],
        advance_when=[_parse_condition(c) for c in raw.get("advance_when", [])],
    )


def _parse_move(raw: dict) -> Move:
    return Move(
        name=raw["name"],
        from_state=raw["from"],
        to_state=raw["to"],
    )


def _parse_condition(raw: dict) -> Condition:
    return Condition(
        file=raw.get("file"),
        glob=raw.get("glob"),
        status=raw.get("status"),
        all_status=raw.get("all_status"),
    )
