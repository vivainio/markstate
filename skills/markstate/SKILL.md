---
name: markstate
description: Use the markstate CLI to navigate focus, check document status, apply transitions, and work through checkbox tasks in a flow.yml-defined workflow.
---

Use the markstate CLI to work through a document workflow defined in `flow.yml`.
Markstate tracks document statuses in YAML front matter and evaluates phase gates
and transitions based on those statuses and checkbox task completion.

**Commands**

- `markstate init [SOURCE] [--hidden]` — create a `flow.yml` in the current
  directory, from the built-in template or by copying SOURCE (file or URL).
  `--hidden` writes to `.markstate/flow.yml` instead.
- `markstate new FILE [DIR]` — create a document from its template defined in
  `flow.yml`.
- `markstate set STATUS FILE... [--set KEY=VALUE ...] [--unset KEY ...]` — set
  status directly without a defined transition. Works without `flow.yml`.
- `markstate update FILE... [--set KEY=VALUE ...] [--unset KEY ...]` — set or
  remove arbitrary frontmatter fields without touching status. Requires at
  least one `--set`/`--unset`.
- `markstate do TRANSITION FILE [--set KEY=VALUE ...]` — apply a named transition
  to a document. Reports the status change and any phase change.
- `markstate focus [QUERY]` — set or show the current working directory.
  If QUERY does not resolve to an existing path, searches `docs_root` recursively
  for a directory whose name contains it as a substring. Errors if ambiguous.
- `markstate which [QUERY]` — read-only counterpart to `focus`: resolves QUERY
  the same way (or prints `docs_root` with no QUERY) without changing focus.
- `markstate status [DIR] [--json]` — show current phase, document statuses, and
  task counts. Add `--json` for machine-readable output.
- `markstate viz [DIR]` — visualize status and progress with emoji and bars.
- `markstate check-gate PHASE [DIR]` — verify a phase's gate conditions.
  Exits 0 if satisfied, 1 otherwise.
- `markstate transitions` — list all defined transitions.
- `markstate next [DIR] [--json]` — list applicable transitions on existing
  documents and documents that still need to be created.
- `markstate next-task [DIR]` — show the first unchecked `- [ ]` task. When
  all tasks are done, reports the current phase and auto-creates any `auto: true`
  documents for the entered phase.
- `markstate check TEXT [DIR]` — check off the first unchecked task whose text
  contains TEXT (case-insensitive). Reports `(N/M)` progress and fires a phase
  transition if it was the last task.
- `markstate list` — list directories that contain markdown documents.
- `markstate audit [--json] [--days DAYS]` — show merged transition audit log
  across users (default: last 1 day, `--days 0` for all).
- `markstate doctor [--verbose]` — validate the `flow.yml` redirect chain and
  check for broken symlinks under `docs_root`.
- `markstate query PRED [PRED ...] [--json] [--dir DIR]` — find documents by
  front matter fields. Predicates are ANDed. Operators: `=` (exact), `!=`,
  `~=` (case-insensitive substring), `>`, `<`, `>=`, `<=` (numeric or string;
  ISO dates compare correctly). Searches from `docs_root` or cwd.
  Example: `markstate query status=draft "created-at>2024-06-01" title~=api`
- `markstate install-skills` — install this Claude skill to `~/.claude/skills/`.

`new`, `set`, `update`, `do`, and `check` all accept `--set KEY=VALUE` (repeatable)
to write extra frontmatter fields alongside the main operation. Magic values: `me`
expands to the git user name, `now` to a UTC ISO 8601 timestamp.

**Typical flow**

1. Set focus: `markstate focus PROJ-123`
2. Check status: `markstate status`
3. See what's next: `markstate next`
4. Apply a transition: `markstate do approve spec.md`
5. For task-driven phases, repeat:
   - `markstate next-task` — get the next task
   - Implement it
   - `markstate check "<task text>"` — mark done; fires transition when last

If the AI edits task files directly without running `check`, call `next-task`
afterward — it detects completion and fires any pending transition.

**Phase transitions**

When a transition or task completion causes a phase change, markstate prints:

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
