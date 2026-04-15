# markstate

Track the status of any markdown documents through a defined workflow — phases, gate conditions, and transitions stored in a `flow.yml` beside your docs.

Works for any document-centric process: spec reviews, ADRs, runbooks, content pipelines. A particularly good fit is **spec-driven development**, where proposals, specs, and task lists move through stages like draft → approved → in-progress → done, and an AI agent or human needs to know exactly where everything stands before proceeding.

## Examples

Ready-made flows and agent skills are in [`examples/`](examples/) and [`skills/`](skills/):

| Example | Description |
|---|---|
| [`examples/sdd/`](examples/sdd/) | Spec-driven development: proposal → spec → tasks → done |
| [`examples/openspec/`](examples/openspec/) | [OpenSpec](https://github.com/Fission-AI/OpenSpec)-style: proposal + design agreed upfront, then tasks |
| [`examples/shared-flow/`](examples/shared-flow/) | Multi-repo setup: canonical `flow.yml` in a docs repo, redirect stub in source repos |
| [`examples/scoped-tracks/`](examples/scoped-tracks/) | Two tracks in one flow: full spec-driven `changes/` and lightweight `plans/` |

Each example includes a `flow.yml` to place at the root of your change collection (e.g. `specs/flow.yml`) and a matching skill in `skills/` to guide an AI agent through the workflow.

## Install

```bash
uv tool install markstate
```

## Quick start

```bash
# Install the CLI
uv tool install markstate

# Install the sdd skill into Claude Code
uvx skillset add vivainio/markstate -s sdd

# Bootstrap a hidden SDD workflow — nothing visible in the repo until you're ready
markstate init https://raw.githubusercontent.com/vivainio/markstate/main/examples/sdd/flow.yml --hidden
# → creates .markstate/flow.yml and adds .markstate/ to .gitignore

# Start the workflow
markstate new proposal.md
markstate next
markstate do accept proposal.md
markstate status
```

## Commands

### `init`

Create a `flow.yml` in the current directory:

```
markstate init                                    # write built-in template
markstate init examples/sdd/flow.yml              # copy from an existing flow.yml
markstate init examples/sdd/flow.yml --hidden     # copy into .markstate/ (see below)
markstate init --force                            # overwrite existing
```

### `new`

Create a document from its template defined in `flow.yml`. Available files are shown in the help when a `flow.yml` is present:

```
markstate new spec.md
markstate new spec.md tasks/task-1/     # create in a specific directory
markstate new specs/03-password-reset   # create a directory from a dir template
```

When inside a directory matching a dir template (e.g. `specs/*`), shows only the files missing from that directory.

`new` figures out where to create files by trying bases in this order: your current directory (if inside `docs_root`), then `docs_root`, then the focus directory. The first match against a `produces` pattern wins.

```bash
# Full paths resolve against docs_root — no matter where you are or what's focused:
markstate new changes/auth/add-oauth          # → docs_root/changes/auth/add-oauth/

# Short paths resolve against focus — handy for adding stories to the current change:
markstate focus add-oauth
markstate new specs/01-login                  # → docs_root/changes/auth/add-oauth/specs/01-login/

# If you cd into docs_root, cwd takes priority:
cd docs_root/changes/auth/add-oauth
markstate new specs/02-logout                 # → cwd/specs/02-logout/
```

### `set`

Set the status of one or more documents directly, without a defined move. Works without `flow.yml`:

```
markstate set draft spec.md
markstate set done docs/*.md
```

### `do`

Apply a named transition to a document. Validates the current status before applying:

```
$ markstate do approve spec.md
spec.md: draft → approved
→ entering phase: review
  advance when:
    - all files matching 'specs/*/tasks.md' must have status 'done'
```

When a transition causes a phase change, the new phase and its completion conditions are printed. Files marked `auto: true` in the new phase's `produces` are created automatically.

### `--set key=value` and `--unset key`

`new`, `set`, `do`, and `check` all accept one or more `--set key=value` flags to write additional frontmatter fields alongside the main operation, and `--unset key` flags to remove fields:

```
markstate do accept proposal.md --set reviewer=me --set reviewed_at=now
markstate set approved spec.md --set approved_by=me
markstate new proposal.md --set author=me --set created_at=now
markstate do unblock spec.md --unset blocked-reason
```

`--unset KEY` pops the field if present and is a silent no-op otherwise.

Magic values are expanded automatically:

| Value | Expands to |
|---|---|
| `me` | Git user name (`git config user.name`) |
| `now` | UTC timestamp in ISO 8601 format (`2026-03-28T12:00:00Z`) |
| `today` | UTC date (`2026-03-28`) |

Prefix a key with `once-` to write only when the target field is currently absent. The prefix is stripped from the written key, so `--set once-first-accepted-at=now` writes `first-accepted-at` on the first application and is a no-op afterwards.

### Flow-level annotations: `set:` and `unset:` in `flow.yml`

Transitions and produced documents can declare a `set:` block whose key/value pairs are written whenever the transition fires or the document is materialized. Values use the same magic vocabulary as `--set` (`me`, `now`, `today`) and the same `once-` prefix. They can also declare an `unset:` list of field names to remove — useful for transient fields like `blocked-at` that should not outlive their status:

```yaml
phases:
  - name: drafting
    produces:
      - file: proposal.md
        template: |
          ---
          status: draft
          ---
        set:
          created-at: now
          author: me

transitions:
  - name: accept
    from: draft
    to: accepted
    set:
      accepted-at: now
      accepted-by: me
      once-first-accepted-at: now   # keeps the original timestamp across re-accepts
  - name: reopen
    from: accepted
    to: draft
    set:
      reopened-at: now
  - name: block
    from: draft
    to: blocked
    set:
      blocked-at: now
  - name: unblock
    from: blocked
    to: draft
    set:
      unblocked-at: now
    unset:
      - blocked-at
      - blocked-reason
```

A transition's edits are applied together with the status change, in order: `unset:` first, then `set:`. If the same key appears in both, `set:` wins. CLI `--set`/`--unset` are applied after the flow-level edits (same unset-then-set order), so the user's explicit intent always takes precedence.

**Tip:** if you repeat the same `set:` / `unset:` blocks across many entries, YAML anchors keep the flow file terse. Define them once under a scratch top-level key like `_anchors:` (markstate ignores unknown top-level keys) and reference them with `*name`:

```yaml
_anchors:
  creation: &creation
    once-created-at: now
    once-created-by: me
  acceptance: &acceptance
    accepted-at: now
    accepted-by: me
    once-first-accepted-at: now

phases:
  - name: drafting
    produces:
      - file: proposal.md
        template: "..."
        set: *creation

transitions:
  - name: accept
    from: draft
    to: accepted
    set: *acceptance
```

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

Show what can be done next — applicable transitions on existing documents, and files that still need to be created:

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

### `transitions`

List all defined transitions:

```
$ markstate transitions
  approve               draft → approved
  start-review          draft → in-review
  mark-reviewed         in-review → reviewed
```

### `query`

Find documents by front matter fields. Predicates are ANDed:

```
markstate query status=draft
markstate query status=draft "created-at>2024-06-01"
markstate query title~=api status!=done
markstate query status=done "closed-at<30d"       # closed more than 30 days ago
markstate query accepted-by=me "accepted-at>7d"   # things I accepted this week
markstate query status=draft --json
markstate query status=draft --dir path/to/docs
```

Supported operators:

| Operator | Meaning |
|---|---|
| `=` | exact match |
| `!=` | not equal |
| `~=` | substring match (case-insensitive) |
| `>` `<` `>=` `<=` | ordered comparison (numeric or string; ISO dates compare correctly) |

The right-hand side of a predicate expands the same magic values as `--set`, plus a few relative forms useful for time queries:

| RHS value | Expands to |
|---|---|
| `now` | current UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) |
| `today` | current UTC date (`YYYY-MM-DD`) |
| `me` | git user name |
| `Nd` / `Nw` / `Nm` / `Ny` | N days / weeks / months / years ago, as a date (months are 30d, years 365d — rough but good for audit queries) |

Relative dates expand to `YYYY-MM-DD`, which compares lexicographically against stored full timestamps exactly as you'd expect — `closed-at<30d` captures everything strictly before midnight UTC on the threshold day.

Searches recursively from `docs_root` (or cwd if no `flow.yml`). Add `--json` for machine-readable output.

### `check-gate`

Check if gate conditions for a phase are met. Exits 0 if satisfied, 1 otherwise:

```
$ markstate check-gate review
gate not satisfied:
  - spec.md must have status 'approved'
```

## Trying it without visible marks

To experiment without touching the repo visibly, point `init` at an existing `flow.yml` (a sample, a colleague's, a cloned example) and pass `--hidden`:

```
markstate init path/to/flow.yml --hidden
echo '.markstate/' >> .gitignore
```

`init --hidden` copies the file to `.markstate/flow.yml`, creates the directory, and prints a reminder to update `.gitignore`. All documents and the focus file land under `.markstate/` — one gitignore entry covers everything.

If the experiment works and you want to share it, move `flow.yml` to the root and commit.

## Configuration reference

`flow.yml` is discovered by walking up from the current directory, checking `flow.yml` then `.markstate/flow.yml` at each level.

| Field | Description |
|---|---|
| `status_field` | Front matter key to track state (default: `status`) |
| `docs_root` | Directory where documents live, relative to `flow.yml` or absolute (default: same directory as `flow.yml`) |
| `phases` | Ordered list of phases |
| `transitions` | Named transitions between states |

`docs_root` allows `flow.yml` to live in a separate location — even a different repository — from the documents it manages:

```yaml
# flow.yml in a tooling repo, docs_root pointing to a sibling docs repo
docs_root: ../my-docs-repo
```

**Phase fields:**

| Field | Description |
|---|---|
| `name` | Phase name |
| `scope` | Path prefix filter — phase only applies to directories under this path (optional) |
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

**Transition fields:**

| Field | Description |
|---|---|
| `name` | Transition name (used with `markstate do`) |
| `from` | Required current status |
| `to` | New status after applying the transition |

## Scoped phases

When a single project has different kinds of work that follow different workflows, use `scope` to restrict phases to specific directory prefixes. Each directory only sees phases whose scope matches its path (plus any unscoped phases).

```yaml
phases:
  - name: drafting
    scope: changes/
    # ...
  - name: speccing
    scope: changes/
    # ...
  - name: implementing
    scope: changes/
    # ...
  - name: changes-done
    scope: changes/

  - name: planning
    scope: plans/
    # ...
  - name: plans-done
    scope: plans/
```

A directory under `changes/auth/add-oauth/` sees: drafting → speccing → implementing → changes-done. A directory under `plans/infra/migrate-db/` sees: planning → plans-done. Phases without a scope apply to all directories.

See [`examples/scoped-tracks/`](examples/scoped-tracks/) for a complete example.

## Sharing a flow across multiple repos

When several source repos follow the same workflow, keep one canonical `flow.yml` in a shared docs or tooling repo and put a one-line redirect stub in each source repo. A symlink to `flow.yml` would also work, but a redirect stub is more reliable — it survives clones, CI environments, and Windows checkouts where symlinks are often broken.

```yaml
# source-repo/flow.yml
redirect: ../docs-repo/flow.yml
```

The path is resolved relative to the stub's location. `docs_root` and all other settings come from the target file, so documents land in the docs repo's directory tree.

See [`examples/shared-flow/`](examples/shared-flow/) for a working layout.

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
