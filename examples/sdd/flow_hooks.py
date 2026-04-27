"""Hooks for the sdd example flow.

Demonstrates two things:
  1. Stamping a frontmatter field from a hook (the change is persisted
     by the engine when the transition commits).
  2. Vetoing a transition by raising HookAbort — the file is left
     untouched and the CLI prints a clean error.
"""

from markstate import HookAbort, TransitionContext


def on_transition(ctx: TransitionContext):
    if ctx.to_state == "accepted":
        # Honor an opt-in veto flag for testing the abort path.
        if ctx.frontmatter.get("block-accept"):
            raise HookAbort(
                f"{ctx.doc_path.name}: cannot accept while 'block-accept' is set"
            )
        ctx.frontmatter["accepted-via-hook"] = True
