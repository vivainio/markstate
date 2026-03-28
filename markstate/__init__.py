"""markstate — markdown document status tracking."""

from markstate.config import (
    FlowConfig,
    Phase,
    Transition,
    Condition,
    ProducedDoc,
    ProducedDir,
    find_and_load,
)
from markstate.engine import (
    TransitionError,
    TaskNotFoundError,
    current_phase,
    check_gate,
    do_transition,
    next_transitions,
    status,
    next_task,
    check_task,
)
from markstate.frontmatter import Document, load as load_document

__all__ = [
    # config
    "FlowConfig",
    "Phase",
    "Transition",
    "Condition",
    "ProducedDoc",
    "ProducedDir",
    "find_and_load",
    # engine
    "TransitionError",
    "TaskNotFoundError",
    "current_phase",
    "check_gate",
    "do_transition",
    "next_transitions",
    "status",
    "next_task",
    "check_task",
    # frontmatter
    "Document",
    "load_document",
]
