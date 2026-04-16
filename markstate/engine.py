"""State engine: evaluate conditions and execute transitions."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from markstate import frontmatter
from markstate.config import Condition, FlowConfig, Phase, ProducedDir, ProducedDoc, Transition, filtered_rglob


class TransitionError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


_ONCE_PREFIX = "once-"


def resolve_magic(value: str) -> str:
    """Expand magic field values: 'me', 'now', 'today'. Other values pass through."""
    if value == "me":
        try:
            return subprocess.run(
                ["git", "config", "user.name"], capture_output=True, text=True, check=True
            ).stdout.strip()
        except subprocess.CalledProcessError:
            return value
    if value == "now":
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if value == "today":
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return value


def apply_fields(doc: frontmatter.Document, fields: dict[str, str]) -> None:
    """Apply fields to doc's frontmatter. Magic values ('me', 'now', 'today') are expanded.

    A key prefixed with 'once-' writes to the unprefixed name only if that field
    is currently absent (e.g. 'once-first-accepted-at' sets 'first-accepted-at'
    the first time, but does not overwrite on later invocations).
    """
    for key, value in fields.items():
        resolved = resolve_magic(str(value))
        if key.startswith(_ONCE_PREFIX):
            actual = key[len(_ONCE_PREFIX):]
            if doc.get(actual) is None:
                doc.set(actual, resolved)
        else:
            doc.set(key, resolved)


def unset_keys(doc: frontmatter.Document, keys: list[str] | tuple[str, ...]) -> None:
    """Remove the listed keys from doc's frontmatter. Missing keys are silent no-ops."""
    for key in keys:
        doc.unset(key)


def current_phase(config: FlowConfig, directory: Path) -> Phase | None:
    """Return the first phase whose gates all pass but advance_when conditions don't all pass."""
    for phase in config.phases_for(directory):
        if not _all_pass(phase.gates, config, directory):
            continue
        if not _all_pass(phase.advance_when, config, directory):
            return phase
    return None


def check_gate(phase: Phase, config: FlowConfig, directory: Path) -> list[str]:
    """Return list of unmet gate conditions, empty if all pass."""
    return [describe_condition(c) for c in phase.gates if not _evaluate(c, config, directory)]


def do_transition(transition_name: str, target: Path, config: FlowConfig) -> tuple[str, str]:
    """Execute a named transition on target file. Returns (old_status, new_status)."""
    t = config.transition(transition_name)
    if t is None:
        raise TransitionError(
            f"unknown transition '{transition_name}'. Available: {config.transition_names()}"
        )

    doc = frontmatter.load(target)
    current = str(doc.get(config.status_field) or "")

    if current != t.from_state:
        raise TransitionError(
            f"cannot apply transition '{transition_name}' to '{target.name}': "
            f"expected status '{t.from_state}', got '{current}'"
        )

    doc.set(config.status_field, t.to_state)
    unset_keys(doc, t.unset_fields)
    apply_fields(doc, t.set_fields)
    doc.save()
    return current, t.to_state


def find_dir_template(config: FlowConfig, cwd: Path) -> tuple[Path, ProducedDir] | tuple[None, None]:
    """Find the dir template matching cwd by comparing its path relative to docs_root against all dir patterns."""
    if not cwd.is_relative_to(config.docs_root):
        return None, None
    rel = cwd.relative_to(config.docs_root)
    best: tuple[ProducedDir, int] | None = None
    for phase in config.phases:
        for entry in phase.produces:
            if isinstance(entry, ProducedDir) and rel.match(entry.glob_pattern):
                # Prefer the most specific (longest) pattern
                depth = entry.dir.count("/")
                if best is None or depth > best[1]:
                    best = (entry, depth)
    if best is None:
        return None, None
    entry = best[0]
    # base is the parent that the dir pattern is relative to (always docs_root)
    return config.docs_root, entry


def collect_dir_files(config: FlowConfig, dir_pattern: str) -> list[ProducedDoc]:
    """Collect all files from all phases that share the same dir pattern."""
    seen: set[str] = set()
    result: list[ProducedDoc] = []
    for phase in config.phases:
        for entry in phase.produces:
            if isinstance(entry, ProducedDir) and entry.dir == dir_pattern:
                for f in entry.files:
                    if f.file not in seen:
                        seen.add(f.file)
                        result.append(f)
    return result


def next_transitions(config: FlowConfig, directory: Path) -> list[dict[str, object]]:
    """Return actionable next steps: applicable transitions on existing docs, and missing produced docs."""
    results = []

    for path in filtered_rglob(directory, "*.md", config.exclude_dirs):
        doc = frontmatter.load(path)
        current = str(doc.get(config.status_field) or "")
        if not current:
            continue
        applicable = [t.name for t in config.transitions if t.from_state == current]
        if applicable:
            results.append({
                "file": str(path.relative_to(directory)),
                "status": current,
                "transitions": applicable,
                "missing": False,
            })

    # Show missing files from the current dir template (if inside one)
    _, dir_entry = find_dir_template(config, directory)
    if dir_entry:
        all_files = collect_dir_files(config, dir_entry.dir)
        for f in all_files:
            if not (directory / f.file).exists():
                results.append({
                    "file": f.file,
                    "status": None,
                    "transitions": [],
                    "missing": True,
                })

    # Show missing produced docs/dirs from the current phase
    phase = current_phase(config, directory)
    if phase:
        for entry in phase.produces:
            if isinstance(entry, ProducedDoc) and not dir_entry:
                if not (directory / entry.file).exists():
                    results.append({
                        "file": entry.file,
                        "status": None,
                        "transitions": [],
                        "missing": True,
                    })
            elif isinstance(entry, ProducedDir) and entry.dir != (dir_entry.dir if dir_entry else None):
                existing = list(config.docs_root.glob(entry.glob_pattern))
                under_dir = [d for d in existing if d.is_dir() and d.is_relative_to(directory)]
                if not under_dir:
                    results.append({
                        "file": entry.dir,
                        "status": None,
                        "transitions": [],
                        "missing": True,
                        "hint": f"markstate new {entry.dir}",
                    })

    return results


def status(config: FlowConfig, directory: Path) -> dict[str, object]:
    """Return a status summary for the given directory."""
    phase = current_phase(config, directory)
    return {
        "current_phase": phase.name if phase else None,
        "phases": [
            {
                "name": p.name,
                "gates_pass": _all_pass(p.gates, config, directory),
                "complete": (
                    _all_pass(p.gates, config, directory)
                    and _all_pass(p.advance_when, config, directory)
                ),
            }
            for p in config.phases_for(directory)
        ],
    }


def _tasks_all_done(done: int, total: int) -> bool:
    return total > 0 and done == total


def _all_pass(conditions: list[Condition], config: FlowConfig, directory: Path) -> bool:
    return all(_evaluate(c, config, directory) for c in conditions)


def _status_matches(actual: str, expected: str | list[str]) -> bool:
    """Check if actual status matches expected (single string or list of strings)."""
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def _evaluate(condition: Condition, config: FlowConfig, directory: Path) -> bool:
    if condition.file is not None and condition.status is not None:
        path = directory / condition.file
        if not path.exists():
            return False
        doc = frontmatter.load(path)
        return _status_matches(str(doc.get(config.status_field) or ""), condition.status)

    if condition.glob is not None and condition.all_status is not None:
        paths = list(directory.glob(condition.glob))
        if not paths:
            return False
        return all(
            _status_matches(str(frontmatter.load(p).get(config.status_field) or ""), condition.all_status)
            for p in paths
        )

    if condition.file is not None and condition.tasks is not None:
        path = directory / condition.file
        if not path.exists():
            return False
        return _tasks_all_done(*frontmatter.count_tasks(path.read_text(encoding="utf-8")))

    if condition.glob is not None and condition.tasks is not None:
        paths = list(directory.glob(condition.glob))
        if not paths:
            return False
        return all(_tasks_all_done(*frontmatter.count_tasks(p.read_text(encoding="utf-8"))) for p in paths)

    return False


def find_entered_phase(config: FlowConfig, directory: Path) -> Phase | None:
    """Return the last phase whose entry gates are satisfied (may already be complete)."""
    entered = None
    for phase in config.phases_for(directory):
        if _all_pass(phase.gates, config, directory):
            entered = phase
    return entered


def next_task(config: FlowConfig, directory: Path) -> dict | None:
    """Return the first unchecked task found in any .md file under directory."""
    for path in filtered_rglob(directory, "*.md", config.exclude_dirs):
        task = frontmatter.next_unchecked_task(path.read_text(encoding="utf-8"))
        if task:
            return {"file": str(path.relative_to(directory)), "task": task}
    return None


def check_task(substring: str, config: FlowConfig, directory: Path) -> dict:
    """Check off the first unchecked task matching substring.

    Returns {"file", "task", "done", "total"}.
    Raises TaskNotFoundError if no match.
    """
    for path in filtered_rglob(directory, "*.md", config.exclude_dirs):
        result = frontmatter.check_task(path.read_text(encoding="utf-8"), substring)
        if result:
            new_text, task_text = result
            path.write_text(new_text, encoding="utf-8")
            done, total = frontmatter.count_tasks(new_text)
            return {
                "file": str(path.relative_to(directory)),
                "task": task_text,
                "done": done,
                "total": total,
            }
    raise TaskNotFoundError(f"no unchecked task matching '{substring}'")


def _describe_status(status: str | list[str]) -> str:
    if isinstance(status, list):
        return " or ".join(f"'{s}'" for s in status)
    return f"'{status}'"


def describe_condition(condition: Condition) -> str:
    if condition.file and condition.status:
        return f"{condition.file} must have status {_describe_status(condition.status)}"
    if condition.glob and condition.all_status:
        return f"all files matching '{condition.glob}' must have status {_describe_status(condition.all_status)}"
    if condition.file and condition.tasks:
        return f"all tasks in {condition.file} must be done"
    if condition.glob and condition.tasks:
        return f"all tasks in files matching '{condition.glob}' must be done"
    return str(condition)
