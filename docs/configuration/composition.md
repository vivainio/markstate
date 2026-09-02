# Shared and scoped flows

## Share defaults with `use`

```yaml
use: ../shared/flow.yml
docs_root: project-docs
```

The referenced flow provides defaults and the local file overrides them. If the
project has no `flow_hooks.py`, hooks beside the shared flow are used as a
fallback.

### Load a flow from an installed agent skill

Skills can distribute their workflow definition, templates, hooks, and agent
instructions as one versioned unit:

```text
~/.claude/skills/my-workflow/
├── SKILL.md
└── resources/
    ├── flow.yml
    ├── flow_hooks.py
    └── proposal-template.md
```

The project needs only a small importing flow:

```yaml
use: ~/.claude/skills/my-workflow/resources/flow.yml
docs_root: project-docs
```

Markstate expands `~`, imports the skill's phases and transitions, applies the
project's local overrides, and falls back to the skill's `flow_hooks.py` when
the project does not provide one. Updating the installed skill updates its flow
and agent guidance together.

Every environment that runs the project must install the skill at the same
path. For self-contained or hermetic builds, keep the shared flow in the
repository instead.

### Match a version-numbered install with a wildcard

Plugin managers often keep an installed skill under a version-numbered
directory and bump that directory on update, e.g.

```text
~/.claude/plugins/cache/<marketplace>/<plugin>/0.3.4/skills/<skill>/resources/flow.yml
```

Since the exact version segment isn't known ahead of time (and changes on
every update), `use:` accepts glob wildcards (`*`, `?`, `[...]`) in place of
it:

```yaml
use: ~/.claude/plugins/cache/<marketplace>/<plugin>/*/skills/<skill>/resources/flow.yml
```

When the pattern matches more than one installed version, markstate picks
the highest one using a version-aware sort (numeric runs compare as
integers, so `0.10.0` sorts after `0.9.0` rather than before it, unlike a
plain string sort). A pattern that matches nothing is an error, same as a
plain `use:` path that doesn't exist.

`redirect:` (below) accepts the same wildcards and version-aware selection.

## Hooks

A `flow_hooks.py` file beside a `flow.yml` can observe and veto transitions.
Markstate imports it and calls `on_transition` after a transition's `set:` /
`unset:` fields are applied, but before the document is saved — so a hook can
still adjust frontmatter, and any change it makes is persisted along with the
rest of the transition.

```python
# flow_hooks.py
from markstate import HookAbort, TransitionContext


def on_transition(ctx: TransitionContext) -> None:
    if ctx.to_state == "accepted" and ctx.frontmatter.get("block-accept"):
        raise HookAbort(f"{ctx.doc_path.name}: cannot accept while 'block-accept' is set")
    ctx.frontmatter["accepted-via-hook"] = True
```

`TransitionContext` carries:

| field         | type              | meaning                                 |
| ------------- | ----------------- | ---------------------------------------- |
| `doc_path`    | `Path`            | the document being transitioned          |
| `frontmatter` | `dict[str, object]` | live frontmatter; mutate it in place   |
| `transition`  | `str`             | the transition's name                    |
| `from_state`  | `str`             | status before the transition             |
| `to_state`    | `str`             | status after the transition              |
| `config`      | `FlowConfig`      | the resolved flow, for reading elsewhere |

Raise `HookAbort` to cleanly veto a transition — the document is left
untouched and the CLI prints `error: <message>` and exits non-zero. Any other
exception propagates with its traceback, since that indicates a bug in the
hook rather than a rule violation. Only `on_transition` is called today;
there is no pre-transition or post-save hook.

### Resolution order with `use`

Markstate looks for `flow_hooks.py` next to the project's `flow.yml` first,
falling back to the file beside the `use:` target if the project doesn't ship
one — as described [above](#share-defaults-with-use). This is a whole-file
fallback, not a per-function merge: if the project provides its own
`flow_hooks.py`, that file's `on_transition` (or its absence) is used
entirely, even if it doesn't define every hook the shared file does.

## Forward with `redirect`

```yaml
redirect: ../docs-repo/flow.yml
```

Use redirect stubs when several source repositories share one authoritative
flow. Relative paths are resolved from the file containing `redirect`.

Like `use:`, `redirect:` accepts glob wildcards and resolves a
version-numbered match to the newest one — see
[Match a version-numbered install with a wildcard](#match-a-version-numbered-install-with-a-wildcard).

## Scope phases to directory trees

```yaml
phases:
  - name: drafting
    scope: changes/
  - name: implementing
    scope: changes/
  - name: planning
    scope: plans/
  - name: plans-done
    scope: plans/
```

A directory under `changes/` sees the first track, while one under `plans/`
sees the second. Unscoped phases apply everywhere.

## Reuse YAML fragments

Markstate ignores unknown top-level keys, so a scratch `_anchors` key can hold
YAML anchors:

```yaml
_anchors:
  acceptance: &acceptance
    accepted-at: now
    accepted-by: me

transitions:
  - name: accept
    from: draft
    to: accepted
    set: *acceptance
```
