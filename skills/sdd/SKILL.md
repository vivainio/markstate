---
name: sdd
description: Spec-driven development with markstate. Write a proposal, write a spec, implement tasks in plan mode, complete.
---

Minimal spec-driven development workflow using markstate.
Each change lives in its own directory with a `flow.yml` tracking four phases:
**drafting → speccing → implementing → done**.

**When in doubt:** run `markstate status` to see the current phase and file states, then `markstate next` to see what transitions are available.

**Setup (once per project)**

```
mkdir specs
cp <markstate-examples>/sdd/flow.yml flow.yml   # or sdd/flow.yml if keeping it contained
```

**Starting a new spec**

```
mkdir specs/PROJ-123.add-auth
markstate focus PROJ-123.add-auth
```

**Phase 1 — Drafting**

Create the proposal document:

```
markstate new proposal.md
```

Fill in the **Problem** and **Solution** sections. Keep it brief — the proposal captures intent, not design. When satisfied:

```
markstate do accept proposal.md
```

`spec.md` is created automatically and the workflow advances to **speccing**.

**Phase 2 — Speccing**

`spec.md` is auto-created. Fill in the **Functional requirements** and **Technical design** sections. When ready:

```
markstate do accept spec.md
```

`tasks.md` is created automatically and the workflow advances to **implementing**.

**Phase 3 — Implementing**

`tasks.md` is auto-created. Fill it with **high-level work units** — one checkbox per major concern, not granular steps:

```markdown
- [ ] Add authentication middleware
- [ ] Write integration tests for the login flow
- [ ] Update API documentation
```

Read `tasks.md` and `spec.md`. For each unchecked item, **enter plan mode**, implement it, then mark it done (`- [ ]` → `- [x]`). Repeat until all items are checked.

**Phase 4 — Done**

When `(complete)` is reported, the spec is finished.

**Reopening**

```
markstate do reopen proposal.md
markstate do reopen spec.md
```

**Guardrails**

- Do NOT modify `flow.yml` unless explicitly asked
- Do NOT use `markstate set` to skip acceptance gates
- Keep tasks high-level — plan sub-steps in plan mode, not as extra checkboxes in `tasks.md`
- Do NOT write code outside of plan mode during the implementing phase
