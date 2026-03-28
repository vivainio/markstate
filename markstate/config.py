"""Load and validate flow.yml, walking up from cwd to find it."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


CONFIG_FILENAME = "flow.yml"


@dataclass
class Transition:
    name: str
    from_state: str
    to_state: str


@dataclass
class Condition:
    file: str | None = None
    glob: str | None = None
    status: str | None = None
    all_status: str | None = None
    tasks: str | None = None  # "all_done"


@dataclass
class ProducedDoc:
    file: str
    template: str | None = None
    auto: bool = False


@dataclass
class ProducedDir:
    dir: str
    files: list[ProducedDoc] = field(default_factory=list)


@dataclass
class Phase:
    name: str
    produces: list[ProducedDoc | ProducedDir] = field(default_factory=list)
    gates: list[Condition] = field(default_factory=list)
    advance_when: list[Condition] = field(default_factory=list)


@dataclass
class FlowConfig:
    root: Path
    docs_root: Path
    status_field: str
    phases: list[Phase]
    transitions: list[Transition]

    def transition(self, name: str) -> Transition | None:
        return next((t for t in self.transitions if t.name == name), None)

    def phase(self, name: str) -> Phase | None:
        return next((p for p in self.phases if p.name == name), None)

    def transition_names(self) -> list[str]:
        return [t.name for t in self.transitions]


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
    transitions = [_parse_transition(t) for t in raw.get("transitions", [])]

    config_dir = path.parent
    docs_root_raw = raw.get("docs_root")
    if docs_root_raw is not None:
        docs_root = (config_dir / docs_root_raw).resolve()
    else:
        docs_root = config_dir

    return FlowConfig(
        root=config_dir,
        docs_root=docs_root,
        status_field=raw.get("status_field", "status"),
        phases=phases,
        transitions=transitions,
    )


def _parse_phase(raw: dict) -> Phase:
    produces = []
    for p in raw.get("produces", []):
        if isinstance(p, str) or (isinstance(p, dict) and "file" in p):
            produces.append(_parse_produced_doc(p))
        elif isinstance(p, dict) and "dir" in p:
            produces.append(_parse_produced_dir(p))
    return Phase(
        name=raw["name"],
        produces=produces,
        gates=[_parse_condition(c) for c in raw.get("gates", [])],
        advance_when=[_parse_condition(c) for c in raw.get("advance_when", [])],
    )


def _parse_produced_doc(raw: str | dict) -> ProducedDoc:
    if isinstance(raw, str):
        return ProducedDoc(file=raw)
    return ProducedDoc(file=raw["file"], template=raw.get("template"), auto=raw.get("auto", False))


def _parse_produced_dir(raw: dict) -> ProducedDir:
    return ProducedDir(
        dir=raw["dir"],
        files=[_parse_produced_doc(f) for f in raw.get("files", [])],
    )


def _parse_transition(raw: dict) -> Transition:
    return Transition(
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
        tasks=raw.get("tasks"),
    )
