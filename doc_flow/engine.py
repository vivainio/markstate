"""State engine: evaluate conditions and execute moves."""

from pathlib import Path

from doc_flow import frontmatter
from doc_flow.config import Condition, FlowConfig, Move, Phase


class MoveError(Exception):
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
    return [_describe(c) for c in phase.gates if not _evaluate(c, config, directory)]


def do_move(move_name: str, target: Path, config: FlowConfig) -> tuple[str, str]:
    """Execute a named move on target file. Returns (old_status, new_status)."""
    move = config.move(move_name)
    if move is None:
        raise MoveError(f"unknown move '{move_name}'. Available: {config.move_names()}")

    doc = frontmatter.load(target)
    current = str(doc.get(config.status_field) or "")

    if current != move.from_state:
        raise MoveError(
            f"cannot apply move '{move_name}' to '{target.name}': "
            f"expected status '{move.from_state}', got '{current}'"
        )

    doc.set(config.status_field, move.to_state)
    doc.save()
    return current, move.to_state


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

    return False


def _describe(condition: Condition) -> str:
    if condition.file and condition.status:
        return f"{condition.file} must have status '{condition.status}'"
    if condition.glob and condition.all_status:
        return f"all files matching '{condition.glob}' must have status '{condition.all_status}'"
    return str(condition)
