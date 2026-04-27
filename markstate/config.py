"""Load and validate flow.yml, walking up from cwd to find it."""

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import yaml


def _to_glob(pattern: str) -> str:
    """Convert a dir pattern with <name> placeholders to a glob pattern."""
    return re.sub(r"<[^>]+>", "*", pattern)


CONFIG_FILENAME = "flow.yml"
HIDDEN_CONFIG_PATH = ".markstate/flow.yml"
HOOKS_FILENAME = "flow_hooks.py"


@dataclass
class Transition:
    name: str
    from_state: str
    to_state: str
    set_fields: dict[str, str] = field(default_factory=dict)
    unset_fields: list[str] = field(default_factory=list)
    require_set: list[str] = field(default_factory=list)
    gates: list["Condition"] = field(default_factory=list)


@dataclass
class Condition:
    file: str | None = None
    glob: str | None = None
    status: str | list[str] | None = None
    all_status: str | list[str] | None = None
    tasks: str | None = None  # "all_done"


@dataclass
class ProducedDoc:
    file: str
    template: str | None = None
    auto: bool = False
    set_fields: dict[str, str] = field(default_factory=dict)
    unset_fields: list[str] = field(default_factory=list)


@dataclass
class ProducedDir:
    dir: str
    files: list[ProducedDoc] = field(default_factory=list)

    @property
    def glob_pattern(self) -> str:
        return _to_glob(self.dir)


@dataclass
class Phase:
    name: str
    description: str | None = None
    scope: str | None = None
    produces: list[ProducedDoc | ProducedDir] = field(default_factory=list)
    gates: list[Condition] = field(default_factory=list)
    advance_when: list[Condition] = field(default_factory=list)


_DEFAULT_EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv"}


def filtered_rglob(directory: Path, pattern: str, exclude_dirs: set[str] | None = None) -> list[Path]:
    """Like Path.rglob but skips excluded directory names."""
    if exclude_dirs is None:
        exclude_dirs = _DEFAULT_EXCLUDE_DIRS
    return sorted(
        p for p in directory.rglob(pattern)
        if not (exclude_dirs & set(p.relative_to(directory).parts))
    )


@dataclass
class FlowConfig:
    root: Path
    docs_root: Path
    status_field: str
    phases: list[Phase]
    transitions: list[Transition]
    exclude_dirs: set[str] = field(default_factory=lambda: set(_DEFAULT_EXCLUDE_DIRS))
    hook_dirs: tuple[Path, ...] = ()
    _hooks_module: ModuleType | None | bool = False  # False = not yet loaded

    def __post_init__(self) -> None:
        if not self.hook_dirs:
            self.hook_dirs = (self.root,)

    def load_hook(self, name: str):
        """Return the named callable from flow_hooks.py.

        Searches each directory in `hook_dirs` (project flow.yml first,
        any `use:` target last) and returns the first hook found.
        """
        if self._hooks_module is False:
            self._hooks_module = self._import_hooks_module()
        if self._hooks_module is None:
            return None
        return getattr(self._hooks_module, name, None)

    def _import_hooks_module(self) -> ModuleType | None:
        for d in self.hook_dirs:
            hooks_path = d / HOOKS_FILENAME
            if not hooks_path.exists():
                continue
            spec = importlib.util.spec_from_file_location(
                f"markstate_flow_hooks_{id(self)}", hooks_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        return None

    def transition(self, name: str) -> Transition | None:
        return next((t for t in self.transitions if t.name == name), None)

    def phase(self, name: str) -> Phase | None:
        return next((p for p in self.phases if p.name == name), None)

    def transition_names(self) -> list[str]:
        return [t.name for t in self.transitions]

    def phases_for(self, directory: Path) -> list[Phase]:
        """Return phases whose scope matches directory (relative to docs_root).

        A phase with no scope applies to all directories.
        A phase with scope "changes/" applies to directories whose relative
        path starts with "changes/" (prefix match on path components).
        """
        try:
            rel = directory.relative_to(self.docs_root)
        except ValueError:
            return self.phases
        rel_parts = rel.parts
        result = []
        for p in self.phases:
            if p.scope is None:
                result.append(p)
                continue
            scope_parts = Path(p.scope).parts
            if rel_parts[: len(scope_parts)] == scope_parts:
                result.append(p)
        return result


def find_and_load(start: Path | None = None) -> FlowConfig:
    """Walk up from start (default: cwd) to find flow.yml and load it."""
    path = _find(start or Path.cwd())
    if path is None:
        raise FileNotFoundError(f"{CONFIG_FILENAME} not found in {start or Path.cwd()} or any parent")
    return _load(path)


def find_flow_target(start: Path | None = None) -> Path:
    """Walk up from start to find flow.yml, follow any redirect chain,
    and return the Path of the final real flow file.

    Files with ``use:`` are returned as-is (they are the anchor, not a
    redirect).

    Raises FileNotFoundError if no flow.yml is found upward from start.
    Raises ValueError if redirects cycle.
    """
    path = _find(start or Path.cwd())
    if path is None:
        raise FileNotFoundError(f"{CONFIG_FILENAME} not found in {start or Path.cwd()} or any parent")
    seen: set[Path] = set()
    while True:
        resolved = path.resolve()
        if resolved in seen:
            raise ValueError(f"redirect cycle involving {resolved}")
        seen.add(resolved)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        redirect = raw.get("redirect")
        if not redirect:
            return path
        path = (path.parent / redirect).resolve()


def has_use(path: Path) -> bool:
    """Return True if the flow file at *path* contains a ``use:`` directive."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return "use" in raw


def _find(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        for name in (CONFIG_FILENAME, HIDDEN_CONFIG_PATH):
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def _load(path: Path) -> FlowConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "redirect" in raw:
        target = (path.parent / raw["redirect"]).resolve()
        return _load(target)

    config_dir = path.parent
    hook_dirs: tuple[Path, ...] = (config_dir,)

    if "use" in raw:
        use_path = Path(raw["use"]).expanduser()
        if not use_path.is_absolute():
            use_path = (config_dir / use_path).resolve()
        base = yaml.safe_load(use_path.read_text(encoding="utf-8"))
        # Local keys override the imported definition
        merged = {**base, **{k: v for k, v in raw.items() if k != "use"}}
        # Fall back to hooks beside the use: target if the project has none
        use_dir = use_path.parent
        if use_dir != config_dir:
            hook_dirs = (config_dir, use_dir)
    else:
        merged = raw

    phases = [_parse_phase(p) for p in merged.get("phases", [])]
    transitions = [_parse_transition(t) for t in merged.get("transitions", [])]

    docs_root_raw = merged.get("docs_root")
    if docs_root_raw is not None:
        docs_root = (config_dir / docs_root_raw).resolve()
    else:
        docs_root = config_dir

    exclude_dirs = set(_DEFAULT_EXCLUDE_DIRS)
    extra = merged.get("exclude_dirs")
    if extra:
        exclude_dirs.update(extra)

    return FlowConfig(
        root=config_dir,
        docs_root=docs_root,
        status_field=merged.get("status_field", "status"),
        phases=phases,
        transitions=transitions,
        exclude_dirs=exclude_dirs,
        hook_dirs=hook_dirs,
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
        description=raw.get("description"),
        scope=raw.get("scope"),
        produces=produces,
        gates=[_parse_condition(c) for c in raw.get("gates", [])],
        advance_when=[_parse_condition(c) for c in raw.get("advance_when", [])],
    )


def _parse_produced_doc(raw: str | dict) -> ProducedDoc:
    if isinstance(raw, str):
        return ProducedDoc(file=raw)
    return ProducedDoc(
        file=raw["file"],
        template=raw.get("template"),
        auto=raw.get("auto", False),
        set_fields=dict(raw.get("set") or {}),
        unset_fields=list(raw.get("unset") or []),
    )


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
        set_fields=dict(raw.get("set") or {}),
        unset_fields=list(raw.get("unset") or []),
        require_set=list(raw.get("require_set") or []),
        gates=[_parse_condition(c) for c in raw.get("gates") or []],
    )


def _parse_condition(raw: dict) -> Condition:
    return Condition(
        file=raw.get("file"),
        glob=raw.get("glob"),
        status=raw.get("status"),
        all_status=raw.get("all_status"),
        tasks=raw.get("tasks"),
    )
