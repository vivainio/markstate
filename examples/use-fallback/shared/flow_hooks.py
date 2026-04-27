"""Default hook for the shared flow.

Loaded automatically when a project's flow.yml `use:`s this directory's
flow.yml and the project does not ship its own flow_hooks.py.
"""

from markstate import TransitionContext


def on_transition(ctx: TransitionContext) -> None:
    ctx.frontmatter["stamped-by"] = "shared"
