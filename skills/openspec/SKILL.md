---
name: openspec
description: OpenSpec-style change workflow with markstate. Agree on proposal and design before implementation.
---

Lightweight change workflow using markstate.
Each change lives in its own subdirectory under `changes/`, sharing one `flow.yml`.
Three phases: **speccing → implementing → done**.

**When in doubt:** run `markstate status` to see the current phase and file states, then `markstate next` to see what transitions are available.

**Setup (once per project)**

```
mkdir changes
cp <markstate-examples>/openspec/flow.yml changes/flow.yml
```

**Starting a new change**

```
mkdir changes/add-dark-mode
markstate focus changes/add-dark-mode
markstate new proposal.md
markstate new design.md
```

**Phase 1 — Speccing**

Write both documents before accepting either. The goal is to agree on what and how before any code is written.

- `proposal.md` — what we're building and why; what's out of scope
- `design.md` — technical approach; affected files, modules, or APIs

When both are ready:

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

Read `tasks.md` and `design.md`. For each unchecked item, **enter plan mode**, implement it, then mark it done (`- [ ]` → `- [x]`). Repeat until all items are checked.

**Phase 3 — Done**

When all tasks are checked, the change is complete.

**Reopening**

```
markstate do reopen proposal.md
markstate do reopen design.md
```

**Guardrails**

- Do NOT write code before both `proposal.md` and `design.md` are accepted
- Do NOT use `markstate set` to skip the acceptance gate
- Keep tasks high-level — plan sub-steps in plan mode, not as extra checkboxes
