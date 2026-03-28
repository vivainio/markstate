# markstate

Generic document flow processor for state tracking in markdown front matter.

Define a workflow in `flow.yml` — phases, gate conditions, and moves — then use `markstate` to track and advance documents through the flow.

## Install

```bash
pip install markstate
```

## Quick start

```
markstate init          # create a template flow.yml
markstate new spec.md   # create a document from its template
markstate next          # see what you can do
markstate do approve spec.md
markstate status
```

## Commands

### `init`

Create a template `flow.yml` in the current directory:

```
markstate init
markstate init --force   # overwrite existing
```

### `new`

Create a document from its template defined in `flow.yml`. Available files are shown in the help when a `flow.yml` is present:

```
markstate new spec.md
markstate new spec.md tasks/task-1/     # create in a specific directory
markstate new specs/03-password-reset   # create a directory from a dir template
```

When inside a directory matching a dir template (e.g. `specs/*`), shows only the files missing from that directory.

### `set`

Set the status of one or more documents directly, without a defined move. Works without `flow.yml`:

```
markstate set draft spec.md
markstate set done docs/*.md
```

### `do`

Apply a named move to a document. Validates the current status before applying:

```
$ markstate do approve spec.md
spec.md: draft → approved
→ entering phase: review
  advance when:
    - all files matching 'specs/*/tasks.md' must have status 'done'
```

When a move causes a phase transition, the new phase and its completion conditions are printed. Files marked `auto: true` in the new phase's `produces` are created automatically.

### `status`

Show file statuses and phase progress:

```
$ markstate status
current phase: drafting

  spec.md                         draft
  design.md                       draft

  drafting              in progress
  review                pending
  done                  pending
```

Takes an optional directory argument. Add `--json` for machine-readable output.

### `next`

Show what can be done next — applicable moves on existing documents, and files that still need to be created:

```
$ markstate next
  spec.md                         draft           → approve (→ approved), start-review (→ in-review)
  design.md                       (not created)   → markstate new design.md
```

### `focus`

Set or show the current task directory. Once set, `status`, `next`, and `check-gate` use it as the default directory:

```
markstate focus tasks/PROJ-123.add-auth   # set focus
markstate focus                           # show current focus
markstate next                            # operates on the focused directory
```

Focus is stored in `.markstate-focus` at the project root. Add it to `.gitignore` as it is personal state.

### `moves`

List all defined moves:

```
$ markstate moves
  approve               draft → approved
  start-review          draft → in-review
  mark-reviewed         in-review → reviewed
```

### `check-gate`

Check if gate conditions for a phase are met. Exits 0 if satisfied, 1 otherwise:

```
$ markstate check-gate review
gate not satisfied:
  - spec.md must have status 'approved'
```

## Configuration reference

`flow.yml` is discovered by walking up from the current directory.

| Field | Description |
|---|---|
| `status_field` | Front matter key to track state (default: `status`) |
| `docs_root` | Directory where documents live, relative to `flow.yml` or absolute (default: same directory as `flow.yml`) |
| `phases` | Ordered list of phases |
| `moves` | Named transitions between states |

`docs_root` allows `flow.yml` to live in a separate location — even a different repository — from the documents it manages:

```yaml
# flow.yml in a tooling repo, docs_root pointing to a sibling docs repo
docs_root: ../my-docs-repo
```

**Phase fields:**

| Field | Description |
|---|---|
| `name` | Phase name |
| `produces` | Documents this phase produces (files or directory templates) |
| `gates` | Conditions that must pass to enter this phase |
| `advance_when` | Conditions that must pass to leave this phase |

**Produces — file:**

```yaml
produces:
  - file: spec.md
    template: |
      ---
      status: draft
      ---

      # Spec
    auto: true   # create automatically when phase is entered
```

**Produces — directory template:**

```yaml
produces:
  - dir: specs/*
    files:
      - file: functional-spec.md
        template: |
          ---
          status: draft
          ---

          # Functional Spec
      - file: tasks.md
        template: |
          ---
          status: todo
          ---

          # Tasks
```

`markstate new specs/03-password-reset` creates the directory with all files. When inside a matching directory, `markstate new` shows only the missing files.

**Condition fields** (use one pair):

| Fields | Description |
|---|---|
| `file` + `status` | A specific file must have the given status |
| `glob` + `all_status` | All files matching the glob must have the given status |

**Move fields:**

| Field | Description |
|---|---|
| `name` | Move name (used with `markstate do`) |
| `from` | Required current status |
| `to` | New status after applying the move |

## Minimal flow without config

`markstate` can be used without a `flow.yml` for lightweight, free-form status tracking. No phases, no moves, no gates — just statuses in front matter.

Add a status to any markdown file:

```markdown
---
status: todo
---

# My note
```

Then use `set` to update it:

```
$ markstate set done notes.md
notes.md: todo → done

$ markstate set in-progress docs/*.md
docs/api.md: todo → in-progress
docs/guide.md: todo → in-progress
```

And `status` to see everything in a directory:

```
$ markstate status
  notes.md                        done
  docs/api.md                     in-progress
  docs/guide.md                   in-progress
```

Status values are arbitrary strings — use whatever fits your workflow.

## License

MIT
