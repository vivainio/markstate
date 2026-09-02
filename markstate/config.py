"""Load and validate flow.yml, walking up from cwd to find it."""

import difflib
import glob as glob_module
import importlib.util
import re
import subprocess
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import yaml


def _resolve_relative(flow_path: Path, rel: str) -> Path:
    """Resolve a relative path from a flow.yml.

    Tries the naive resolution first (relative to ``flow_path.parent``). If
    that target doesn't exist and ``flow_path`` is inside a linked git
    worktree, retries against the equivalent directory in the main working
    tree -- so ``../foo`` works when authored against the main checkout
    layout but executed from a worktree at e.g. ``.worktrees/feat/``.
    """
    parent = flow_path.parent
    naive = (parent / rel).resolve()
    if naive.exists():
        return naive
    anchor = _main_worktree_anchor(parent)
    if anchor is None:
        return naive
    return (anchor / rel).resolve()


_GLOB_MAGIC = re.compile(r"[*?\[]")


def _has_glob_magic(pattern: str) -> bool:
    return bool(_GLOB_MAGIC.search(pattern))


def _natural_sort_key(text: str) -> list[int | str]:
    """Split *text* into digit/non-digit runs so digit runs compare
    numerically -- e.g. ``1.10.0`` sorts after ``1.9.0`` rather than before
    it, as a plain string comparison would."""
    return [int(chunk) if chunk.isdigit() else chunk for chunk in re.split(r"(\d+)", text)]


def resolve_glob_reference(flow_path: Path, reference: str) -> Path:
    """Resolve a ``use:`` or ``redirect:`` reference to a concrete flow file
    path.

    *reference* may contain glob wildcards (``*``, ``?``, ``[...]``) to cover
    version-numbered install directories -- e.g. installed Claude Code
    skills/plugins that keep several versions side by side, such as
    ``~/.claude/skills/my-workflow-*/resources/flow.yml``. When the pattern
    matches more than one existing file, the candidates are ranked with a
    natural/version-aware sort (see ``_natural_sort_key``) and the
    highest-ranked one wins.

    A reference without wildcards resolves exactly as a plain path (and is
    not required to exist -- the caller checks that).  A wildcarded
    reference that matches nothing also returns a (non-existent) path built
    from the pattern, so callers can report it the same way.
    """
    expanded = Path(reference).expanduser()
    if not _has_glob_magic(str(expanded)):
        if expanded.is_absolute():
            return expanded
        return _resolve_relative(flow_path, str(expanded))

    full_pattern = str(expanded) if expanded.is_absolute() else str(flow_path.parent / expanded)
    matches = [Path(m) for m in glob_module.glob(full_pattern, recursive=True) if Path(m).is_file()]
    if not matches:
        return Path(full_pattern)
    return max(matches, key=lambda p: _natural_sort_key(str(p)))


def resolve_reference_candidates(flow_path: Path, reference: str | list[Any]) -> list[Path]:
    """Resolve a ``use:``/``redirect:`` reference to its candidate paths.

    *reference* is either a single path (see ``resolve_glob_reference``) or a
    list of candidate paths -- e.g. one install location per source (a
    Claude Code plugin cache, a manually installed skill under
    ``~/.claude/skills``) -- each resolved the same way. The list is
    returned in the given order; picking a winner is the caller's job.
    """
    items = reference if isinstance(reference, list) else [reference]
    return [resolve_glob_reference(flow_path, str(item)) for item in items]


def resolve_reference(flow_path: Path, reference: str | list[Any]) -> Path:
    """Resolve a ``use:``/``redirect:`` reference to one concrete path: the
    first candidate that exists, or the last candidate if none do (so a
    caller that just checks ``.exists()`` still gets something sensible to
    report)."""
    candidates = resolve_reference_candidates(flow_path, reference)
    return next((c for c in candidates if c.exists()), candidates[-1])


def _resolve_required_reference(
    flow_path: Path, reference: str | list[Any], directive: str
) -> Path:
    """Resolve a ``use:``/``redirect:`` reference, raising ``FlowConfigError``
    if no candidate exists. The first existing candidate wins; with a list
    reference, all resolved candidates are named in the error when none
    exist. *directive* (``"use"`` or ``"redirect"``) labels the error."""
    candidates = resolve_reference_candidates(flow_path, reference)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if len(candidates) > 1:
        tried = ", ".join(str(c) for c in candidates)
        raise FlowConfigError(
            f"none of the {directive} candidates were found (referenced from {flow_path}): {tried}"
        )
    raise FlowConfigError(
        f"{directive} target not found: {candidates[0]} (referenced from {flow_path})"
    )


def _main_worktree_anchor(parent: Path) -> Path | None:
    """If ``parent`` is inside a linked git worktree, return the equivalent
    directory under the main working tree; otherwise None."""
    try:
        result = subprocess.run(
            ["git", "-C", str(parent), "rev-parse", "--show-toplevel", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        return None
    toplevel = Path(lines[0]).resolve()
    common_dir = Path(lines[1])
    if not common_dir.is_absolute():
        common_dir = (toplevel / common_dir).resolve()
    else:
        common_dir = common_dir.resolve()
    if common_dir.name != ".git":
        return None
    main_root = common_dir.parent
    if main_root == toplevel:
        return None
    try:
        rel = parent.resolve().relative_to(toplevel)
    except ValueError:
        return None
    return main_root / rel


def _to_glob(pattern: str) -> str:
    """Convert a dir pattern with <name> placeholders to a glob pattern."""
    return re.sub(r"<[^>]+>", "*", pattern)


CONFIG_FILENAME = "flow.yml"
HIDDEN_CONFIG_PATH = ".markstate/flow.yml"
HOOKS_FILENAME = "flow_hooks.py"


class FlowConfigError(Exception):
    """Raised when a discovered flow.yml cannot be loaded."""


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


def filtered_rglob(
    directory: Path, pattern: str, exclude_dirs: set[str] | None = None
) -> list[Path]:
    """Like Path.rglob but skips excluded directory names."""
    if exclude_dirs is None:
        exclude_dirs = _DEFAULT_EXCLUDE_DIRS
    return sorted(
        p
        for p in directory.rglob(pattern)
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

    def load_hook(self, name: str) -> Callable[..., object] | None:
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
            if spec is None or spec.loader is None:
                raise FlowConfigError(f"cannot load hooks module: {hooks_path}")
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


def find_and_load(start: Path | None = None, variables: dict[str, str] | None = None) -> FlowConfig:
    """Walk up from start (default: cwd) to find flow.yml and load it."""
    path = _find(start or Path.cwd())
    if path is None:
        raise FileNotFoundError(
            f"{CONFIG_FILENAME} not found in {start or Path.cwd()} or any parent"
        )
    overrides = variables or {}
    known: set[str] = set()
    config = _load(path, overrides, known)
    _validate_variable_names(overrides, known)
    return config


def find_flow_target(start: Path | None = None, variables: dict[str, str] | None = None) -> Path:
    """Walk up from start to find flow.yml, follow any redirect chain,
    and return the Path of the final real flow file.

    Files with ``use:`` are returned as-is (they are the anchor, not a
    redirect).

    Raises FileNotFoundError if no flow.yml is found upward from start.
    Raises ValueError if redirects cycle.
    """
    path = _find(start or Path.cwd())
    if path is None:
        raise FileNotFoundError(
            f"{CONFIG_FILENAME} not found in {start or Path.cwd()} or any parent"
        )
    seen: set[Path] = set()
    overrides = variables or {}
    known: set[str] = set()
    while True:
        resolved = path.resolve()
        if resolved in seen:
            raise ValueError(f"redirect cycle involving {resolved}")
        seen.add(resolved)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise FlowConfigError(f"flow must be a mapping: {path}")
        raw = _resolve_selects(loaded, overrides, path, known)
        redirect = raw.get("redirect")
        if not redirect:
            _validate_variable_names(overrides, known)
            return path
        path = _resolve_required_reference(path, redirect, "redirect")


def find_flow_target_best_effort(
    start: Path | None = None, variables: dict[str, str] | None = None
) -> Path | None:
    """Like find_flow_target, but never raises: follows the redirect chain as
    far as it can be resolved with *variables*, and returns the deepest flow
    file reached. On a hop that would need a variable it doesn't have, a
    broken redirect target, or a cycle, resolution just stops at that hop's
    flow file instead of failing.

    Returns None only if no flow.yml is found upward from start.
    """
    path = _find(start or Path.cwd())
    if path is None:
        return None
    seen: set[Path] = set()
    overrides = variables or {}
    known: set[str] = set()
    while True:
        resolved = path.resolve()
        if resolved in seen:
            return path
        seen.add(resolved)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return path
        if not isinstance(loaded, dict):
            return path
        try:
            raw = _resolve_selects(loaded, overrides, path, known)
        except FlowConfigError:
            return path
        redirect = raw.get("redirect")
        if not redirect:
            return path
        target = resolve_reference(path, redirect)
        if not target.exists():
            return path
        path = target


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


def _load(path: Path, variables: dict[str, str], known: set[str]) -> FlowConfig:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise FlowConfigError(f"flow must be a mapping: {path}")
    raw = _resolve_selects(loaded, variables, path, known)
    if "redirect" in raw:
        target = _resolve_required_reference(path, raw["redirect"], "redirect")
        return _load(target, variables, known)

    config_dir = path.parent
    hook_dirs: tuple[Path, ...] = (config_dir,)

    if "use" in raw:
        use_path = _resolve_required_reference(path, raw["use"], "use")
        loaded_base = yaml.safe_load(use_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded_base, dict):
            raise FlowConfigError(f"flow must be a mapping: {use_path}")
        base = _resolve_selects(loaded_base, variables, use_path, known)
        # Local keys override the imported definition
        merged = {**base, **{k: v for k, v in raw.items() if k != "use"}}
        # Fall back to hooks beside the use: target if the project has none
        use_dir = use_path.parent
        if use_dir != config_dir:
            hook_dirs = (config_dir, use_dir)
    else:
        merged = raw

    phases = [_parse_phase(cast(dict[str, Any], p)) for p in merged.get("phases", [])]
    transitions = [
        _parse_transition(cast(dict[str, Any], t)) for t in merged.get("transitions", [])
    ]

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


def _resolve_selects(
    raw: dict[str, Any], overrides: dict[str, str], path: Path, known: set[str]
) -> dict[str, Any]:
    """Resolve markstate expressions in one parsed flow document."""
    document = deepcopy(raw)
    definitions = document.pop("$variables", {})
    if not isinstance(definitions, dict):
        raise FlowConfigError(f"$variables must be a mapping in {path}")
    known.update(str(name) for name in definitions)

    values: dict[str, str] = {}
    for name, definition in definitions.items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            raise FlowConfigError(f"each $variables entry must be a mapping in {path}")
        if name in overrides:
            value = overrides[name]
        elif "default" in definition:
            value = str(definition["default"])
        elif definition.get("required", False):
            raise FlowConfigError(f"missing required variable '{name}' in {path}")
        else:
            continue
        allowed = definition.get("values")
        if allowed is not None:
            if not isinstance(allowed, list):
                raise FlowConfigError(f"values for variable '{name}' must be a list in {path}")
            allowed_values = [str(item) for item in allowed]
            if value not in allowed_values:
                choices = ", ".join(allowed_values)
                raise FlowConfigError(
                    f"invalid value '{value}' for variable '{name}' in {path}; "
                    f"expected one of: {choices}"
                )
        values[name] = value

    values.update({name: value for name, value in overrides.items() if name not in definitions})
    resolved = _resolve_value(document, values, path)
    if not isinstance(resolved, dict):
        raise FlowConfigError(f"resolved flow must be a mapping: {path}")
    return resolved


def _validate_variable_names(overrides: dict[str, str], known: set[str]) -> None:
    unknown = sorted(set(overrides) - known)
    if not unknown:
        return
    name = unknown[0]
    message = f"unknown variable '{name}'"
    suggestion = difflib.get_close_matches(name, sorted(known), n=1)
    if suggestion:
        message += f"; did you mean '{suggestion[0]}'?"
    if known:
        message += f"; known variables: {', '.join(sorted(known))}"
    else:
        message += "; this flow declares no variables"
    raise FlowConfigError(message)


def _resolve_value(value: Any, variables: dict[str, str], path: Path) -> Any:
    if isinstance(value, list):
        return [_resolve_value(item, variables, path) for item in value]
    if not isinstance(value, dict):
        return value
    if "$select" not in value:
        return {key: _resolve_value(item, variables, path) for key, item in value.items()}
    if set(value) != {"$select", "cases"}:
        raise FlowConfigError(
            f"$select expression must contain exactly '$select' and 'cases' in {path}"
        )
    name = value["$select"]
    cases = value["cases"]
    if not isinstance(name, str) or not isinstance(cases, dict):
        raise FlowConfigError(f"$select must name a variable and cases must be a mapping in {path}")
    if name not in variables:
        raise FlowConfigError(f"no value supplied for variable '{name}' in {path}")
    selected = variables[name]
    if selected not in cases:
        choices = ", ".join(str(item) for item in cases)
        raise FlowConfigError(
            f"no case '{selected}' in $select for '{name}' in {path}; expected one of: {choices}"
        )
    return _resolve_value(cases[selected], variables, path)


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
