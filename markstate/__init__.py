"""markstate — markdown document status tracking."""

from markstate.config import (
    Condition,
    FlowConfig,
    Phase,
    ProducedDir,
    ProducedDoc,
    Transition,
    find_and_load,
)
from markstate.engine import (
    HookAbort,
    TaskNotFoundError,
    TransitionContext,
    TransitionError,
    check_gate,
    check_task,
    current_phase,
    do_transition,
    next_task,
    next_transitions,
    status,
)
from markstate.frontmatter import Document
from markstate.frontmatter import load as load_document

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
    "HookAbort",
    "TransitionContext",
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
