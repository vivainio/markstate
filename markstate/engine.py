"""State engine: evaluate conditions and execute transitions."""

from pathlib import Path

from markstate import frontmatter
from markstate.config import Condition, FlowConfig, Phase, ProducedDir, ProducedDoc, Transition


class TransitionError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


def current_phase(config: FlowConfig, directory: Path) -> Phase | None:
    """Return the first phase whose gates all pass but advance_when conditions don't all pass."""
    for phase in config.phases:
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
    doc.save()
    return current, t.to_state


def find_dir_template(config: FlowConfig, cwd: Path) -> tuple[Path, ProducedDir] | tuple[None, None]:
    """Walk up from cwd toward config.docs_root to find a matching dir template."""
    if not cwd.is_relative_to(config.docs_root):
        return None, None
    candidate = cwd
    while candidate != config.docs_root:
        task_dir = candidate.parent
        rel = cwd.relative_to(task_dir)
        for phase in config.phases:
            for entry in phase.produces:
                if isinstance(entry, ProducedDir) and rel.match(entry.dir):
                    return task_dir, entry
        candidate = task_dir
    return None, None


def next_transitions(config: FlowConfig, directory: Path) -> list[dict[str, object]]:
    """Return actionable next steps: applicable transitions on existing docs, and missing produced docs."""
    results = []

    for path in sorted(directory.rglob("*.md")):
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

    task_dir, dir_entry = find_dir_template(config, directory)
    if dir_entry:
        for f in dir_entry.files:
            if not (directory / f.file).exists():
                results.append({
                    "file": f.file,
                    "status": None,
                    "transitions": [],
                    "missing": True,
                })
    else:
        phase = current_phase(config, directory)
        if phase:
            for doc in phase.produces:
                if isinstance(doc, ProducedDoc) and not (directory / doc.file).exists():
                    results.append({
                        "file": doc.file,
                        "status": None,
                        "transitions": [],
                        "missing": True,
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
                "complete": _all_pass(p.advance_when, config, directory),
            }
            for p in config.phases
        ],
    }


def _tasks_all_done(done: int, total: int) -> bool:
    return total > 0 and done == total


def _all_pass(conditions: list[Condition], config: FlowConfig, directory: Path) -> bool:
    return all(_evaluate(c, config, directory) for c in conditions)


def _evaluate(condition: Condition, config: FlowConfig, directory: Path) -> bool:
    if condition.file is not None and condition.status is not None:
        path = directory / condition.file
        if not path.exists():
            return False
        doc = frontmatter.load(path)
        return str(doc.get(config.status_field) or "") == condition.status

    if condition.glob is not None and condition.all_status is not None:
        paths = list(directory.glob(condition.glob))
        if not paths:
            return False
        return all(
            str(frontmatter.load(p).get(config.status_field) or "") == condition.all_status
            for p in paths
        )

    if condition.file is not None and condition.tasks is not None:
        path = directory / condition.file
        if not path.exists():
            return False
        return _tasks_all_done(*frontmatter.count_tasks(path.read_text()))

    if condition.glob is not None and condition.tasks is not None:
        paths = list(directory.glob(condition.glob))
        if not paths:
            return False
        return all(_tasks_all_done(*frontmatter.count_tasks(p.read_text())) for p in paths)

    return False


def find_entered_phase(config: FlowConfig, directory: Path) -> Phase | None:
    """Return the last phase whose entry gates are satisfied (may already be complete)."""
    entered = None
    for phase in config.phases:
        if _all_pass(phase.gates, config, directory):
            entered = phase
    return entered


def next_task(config: FlowConfig, directory: Path) -> dict | None:
    """Return the first unchecked task found in any .md file under directory."""
    for path in sorted(directory.rglob("*.md")):
        task = frontmatter.next_unchecked_task(path.read_text())
        if task:
            return {"file": str(path.relative_to(directory)), "task": task}
    return None


def check_task(substring: str, config: FlowConfig, directory: Path) -> dict:
    """Check off the first unchecked task matching substring.

    Returns {"file", "task", "done", "total"}.
    Raises TaskNotFoundError if no match.
    """
    for path in sorted(directory.rglob("*.md")):
        result = frontmatter.check_task(path.read_text(), substring)
        if result:
            new_text, task_text = result
            path.write_text(new_text)
            done, total = frontmatter.count_tasks(new_text)
            return {
                "file": str(path.relative_to(directory)),
                "task": task_text,
                "done": done,
                "total": total,
            }
    raise TaskNotFoundError(f"no unchecked task matching '{substring}'")


def describe_condition(condition: Condition) -> str:
    if condition.file and condition.status:
        return f"{condition.file} must have status '{condition.status}'"
    if condition.glob and condition.all_status:
        return f"all files matching '{condition.glob}' must have status '{condition.all_status}'"
    if condition.file and condition.tasks:
        return f"all tasks in {condition.file} must be done"
    if condition.glob and condition.tasks:
        return f"all tasks in files matching '{condition.glob}' must be done"
    return str(condition)
