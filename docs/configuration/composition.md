# Shared and scoped flows

## Share defaults with `use`

```yaml
use: ../shared/flow.yml
docs_root: project-docs
```

The referenced flow provides defaults and the local file overrides them. If the
project has no `flow_hooks.py`, hooks beside the shared flow are used as a
fallback.

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

