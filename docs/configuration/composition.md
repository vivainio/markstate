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

## Forward with `redirect`

```yaml
redirect: ../docs-repo/flow.yml
```

Use redirect stubs when several source repositories share one authoritative
flow. Relative paths are resolved from the file containing `redirect`.

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
