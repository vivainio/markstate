# markstate

Generic document flow processor for state tracking in markdown front matter.

Define a workflow in `flow.yml` — phases, gate conditions, and moves — then use `markstate` to track and advance documents through the flow.

## Install

```bash
pip install markstate
```

## Quick start

Create `flow.yml` in your project root:

```yaml
status_field: status

phases:
  - name: drafting
    advance_when:
      - file: spec.md
        status: approved

  - name: review
    gates:
      - file: spec.md
        status: approved
    advance_when:
      - glob: "docs/*.md"
        all_status: reviewed

moves:
  - name: approve-spec
    from: draft
    to: approved

  - name: mark-reviewed
    from: in-review
    to: reviewed
```

Documents are markdown files with YAML front matter:

```markdown
---
status: draft
---

# My document
```

## Commands

```
markstate status [DIRECTORY]        Show current phase and completion status
markstate do MOVE TARGET            Apply a named move to a document
markstate moves                     List all available moves
markstate check-gate PHASE [DIR]    Check if gate conditions for a phase are met
```

### `status`

```
$ markstate status
current phase: drafting

  drafting              gates=ok  in progress
  review                gates=blocked  in progress
```

Add `--json` for machine-readable output.

### `do`

Apply a move to advance a document's status:

```
$ markstate do approve-spec spec.md
spec.md: draft → approved
```

Moves are validated against the current status — applying a move to a document in the wrong state is an error.

### `moves`

```
$ markstate moves
  approve-spec          draft → approved
  mark-reviewed         in-review → reviewed
```

### `check-gate`

Exits 0 if all gate conditions pass, 1 otherwise:

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
| `phases` | Ordered list of phases |
| `moves` | Named transitions between states |

**Phase fields:**

| Field | Description |
|---|---|
| `name` | Phase name |
| `gates` | Conditions that must pass to enter this phase |
| `advance_when` | Conditions that must pass to leave this phase |

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

## License

MIT
