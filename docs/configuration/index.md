# Flow configuration

A `flow.yml` defines the document root, ordered phases, produced documents,
gate conditions, and named transitions.

```yaml
docs_root: changes
status_field: status

phases:
  - name: drafting
    produces:
      - file: proposal.md
        template: |
          ---
          status: draft
          ---

          # Proposal
    advance_when:
      - file: proposal.md
        status: accepted

  - name: done
    gates:
      - file: proposal.md
        status: accepted

transitions:
  - name: accept
    from: draft
    to: accepted
```

## Top-level fields

| Field | Description |
|---|---|
| `status_field` | Front matter key used for state; defaults to `status` |
| `docs_root` | Document directory, relative to `flow.yml` or absolute |
| `exclude_dirs` | Additional directory names excluded from recursive searches |
| `phases` | Ordered workflow phases |
| `transitions` | Named state transitions |
| `use` | Base flow whose values are locally overridden |
| `redirect` | Transfer control to another complete flow |
| `$variables` | Runtime variable declarations |

## Phases

| Field | Description |
|---|---|
| `name` | Phase name |
| `description` | Human-readable purpose |
| `scope` | Optional path-prefix filter |
| `produces` | Files or directory templates produced by the phase |
| `gates` | Conditions required to enter the phase |
| `advance_when` | Conditions required to leave the phase |

Produced files accept `file`, `template`, `auto`, `set`, and `unset`. Directory
templates use `dir` and a `files` list:

```yaml
produces:
  - dir: specs/<area>
    files:
      - file: spec.md
        template: "# Specification"
      - file: tasks.md
        template: "# Tasks\n\n- [ ]"
```

### Versioning produced files

Adding a file to a directory template would otherwise make every existing item
look incomplete. Give the template a `version` and a `version_file`, and mark
newer files with `since`:

```yaml
produces:
  - dir: changes/<change>
    version: 2
    version_file: proposal.md
    files:
      - file: proposal.md
        template: "..."
      - file: analysis.md   # added in version 2
        since: 2
        template: "..."
```

- `markstate new` stamps `flow-version: <version>` into the `version_file`.
- An item's version is the `flow-version` in its `version_file`. A file without
  the field is version 0; a missing file means a new item at the current version.
- Files with `since` above the item's version are not listed as missing, not
  offered by `markstate new`, and not auto-created.
- To adopt the newer files, set `flow-version` in that file by hand.
- `version` and `version_file` go together, `version_file` must be one of the
  dir's files, and `since` cannot exceed `version`.

## Conditions

Conditions use one of these forms:

```yaml
- file: proposal.md
  status: accepted
- glob: "specs/*/spec.md"
  all_status: [accepted, done]
- file: tasks.md
  tasks: all_done
```

## Transitions and annotations

```yaml
transitions:
  - name: accept
    from: draft
    to: accepted
    require_set: [reviewer]
    gates:
      - file: checks.md
        status: passed
    set:
      accepted-at: now
      accepted-by: me
      once-first-accepted-at: now
    unset: [blocked-at, blocked-reason]
```

`me`, `now`, and `today` are expanded when fields are written. A key beginning
with `once-` is only written when the target field is absent; the prefix is
removed from the stored key.

