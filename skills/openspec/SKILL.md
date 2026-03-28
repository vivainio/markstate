---
name: openspec
description: OpenSpec-style change workflow with markstate. Agree on proposal, design, and delta specs before implementation.
---

Lightweight OpenSpec-style change workflow using markstate.
Three phases: **speccing → implementing → done**.

```
openspec/
  flow.yml            ← shared flow definition (docs_root: changes)
  specs/              ← source of truth (domain specs, managed separately)
  changes/
    add-dark-mode/
      proposal.md     ← why and what
      design.md       ← technical approach
      specs/          ← delta specs (what changes in the source of truth)
        ui/spec.md
      tasks.md        ← implementation checklist (auto-created)
```

**When in doubt:** run `markstate status` to see the current phase and file states, then `markstate next` to see what transitions are available.

**Setup (once per project)**

```
mkdir -p openspec/changes
cp <markstate-examples>/openspec/flow.yml openspec/flow.yml
```

**Starting a new change**

```
mkdir openspec/changes/add-dark-mode
markstate focus add-dark-mode
markstate new proposal.md
markstate new design.md
```

**Phase 1 — Speccing**

Write `proposal.md` and `design.md` before accepting either.

- `proposal.md` — intent, scope, and out-of-scope
- `design.md` — technical approach and affected areas
- `specs/<domain>/spec.md` — delta specs describing what changes in the source of truth (ADDED/MODIFIED/REMOVED requirements). At least one is required. Create one per affected domain:

  ```
  markstate new specs/auth
  markstate new specs/ui
  ```

When ready to implement:

```
markstate do accept proposal.md
markstate do accept design.md
```

`tasks.md` is created automatically and the workflow advances to **implementing**.

**Phase 2 — Implementing**

Fill `tasks.md` with high-level work units — one checkbox per major concern:

```markdown
- [ ] Add theme context provider
- [ ] Create toggle component
- [ ] Wire up localStorage persistence
```

Read `tasks.md`, `design.md`, and any delta specs in `specs/`. For each unchecked item, **enter plan mode**, implement it, then mark it done (`- [ ]` → `- [x]`). Repeat until all items are checked.

**Phase 3 — Done**

When all tasks are checked, archive the change and merge delta specs into the source of truth under `openspec/specs/`.

**Reopening**

```
markstate do reopen proposal.md
markstate do reopen design.md
```

**Guardrails**

- Do NOT write code before both `proposal.md` and `design.md` are accepted
- Do NOT use `markstate set` to skip the acceptance gate
- Keep tasks high-level — plan sub-steps in plan mode, not as extra checkboxes
- Always create at least one delta spec — the gate requires `specs/*/spec.md` to be accepted
- When writing delta specs, use ADDED/MODIFIED/REMOVED sections — describe behavior, not implementation
