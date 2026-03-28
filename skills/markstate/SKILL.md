---
name: markstate
description: Use the markstate CLI to navigate focus, check document status, apply moves, and work through checkbox tasks in a flow.yml-defined workflow.
---

Use the markstate CLI to work through a document workflow defined in `flow.yml`.
Markstate tracks document statuses in YAML front matter and evaluates phase gates
and transitions based on those statuses and checkbox task completion.

**Commands**

- `markstate focus [QUERY]` — set or show the current working directory.
  If QUERY does not resolve to an existing path, searches `docs_root` recursively
  for a directory whose name contains it as a substring. Errors if ambiguous.
- `markstate status [DIR]` — show current phase, document statuses, and task
  counts. Add `--json` for machine-readable output.
- `markstate next [DIR]` — list applicable moves on existing documents and
  documents that still need to be created.
- `markstate next-task [DIR]` — show the first unchecked `- [ ]` task. When
  all tasks are done, reports the current phase and auto-creates any `auto: true`
  documents for the entered phase.
- `markstate do MOVE FILE` — apply a named move to a document. Reports the
  status change and any phase transition.
- `markstate check TEXT [DIR]` — check off the first unchecked task whose text
  contains TEXT (case-insensitive). Reports `(N/M)` progress and fires a phase
  transition if it was the last task.
- `markstate set STATUS FILE...` — set status directly without a defined move.
  Works without `flow.yml`.
- `markstate new FILE [DIR]` — create a document from its template defined in
  `flow.yml`.
- `markstate check-gate PHASE [DIR]` — verify a phase's gate conditions.
  Exits 0 if satisfied, 1 otherwise.
- `markstate moves` — list all defined moves.

**Typical flow**

1. Set focus: `markstate focus PROJ-123`
2. Check status: `markstate status`
3. See what's next: `markstate next`
4. Apply a move: `markstate do approve spec.md`
5. For task-driven phases, repeat:
   - `markstate next-task` — get the next task
   - Implement it
   - `markstate check "<task text>"` — mark done; fires transition when last

If the AI edits task files directly without running `check`, call `next-task`
afterward — it detects completion and fires any pending transition.

**Phase transitions**

When a move or task completion causes a phase change, markstate prints:

```
→ entering phase: <name>
  advance when:
    - <condition>
```

Or `(complete)` when all phases are done. Auto-produced documents are created
at this point without further action.

**Guardrails**

- Do NOT modify `flow.yml` unless explicitly asked
- Do NOT use `markstate set` to bypass a gate condition
- Always check `markstate status` before acting if the current phase is unknown
- No emojis in output or files
