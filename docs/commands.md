# Command reference

Global options include `--focus DIR`, repeatable `-D NAME=VALUE` /
`--variable NAME=VALUE`, and `--version`.

## `init`

Install or upgrade a flow:

```bash
markstate init
markstate init examples/sdd/flow.yml
markstate init https://example.com/flow.yml
markstate init examples/sdd/flow.yml --hidden
```

If a reachable flow already exists, `init` replaces its final target. Otherwise
it creates `flow.yml` in the current directory. `--hidden` applies only to a
fresh install and writes `.markstate/flow.yml`.

## `new`

Create a document or directory from a phase template:

```bash
markstate new spec.md
markstate new spec.md tasks/task-1/
markstate new changes/add-login
```

Resolution tries the current directory when it is inside `docs_root`, then
`docs_root`, then the focused directory. The first matching `produces` pattern
wins.

## `set`

Set arbitrary document state, with or without a flow:

```bash
markstate set draft spec.md
markstate set done docs/*.md
```

## `update`

Edit arbitrary front matter without changing status:

```bash
markstate update spec.md --set reviewer=me --unset blocked-reason
```

## `do`

Apply a named transition after validating current state and transition gates:

```bash
markstate do approve spec.md
markstate do accept proposal.md --set reviewer=me
markstate do unblock spec.md --unset blocked-reason
```

`new`, `set`, `do`, and `check` accept repeatable `--set KEY=VALUE` and
`--unset KEY`. Values `me`, `now`, and `today` expand automatically. Prefix a
key with `once-` to write it only when the target field is absent.

## `status`

Show document states and phase progress:

```bash
markstate status
markstate status path/to/change
markstate status --json
```

## `viz`

Render phase and document progress with compact visual indicators:

```bash
markstate viz
markstate viz path/to/change
```

## `next`

Show applicable transitions and documents that can be created:

```bash
markstate next
```

## `focus`

Set or display the current task directory:

```bash
markstate focus changes/add-login
markstate focus
```

Focus is personal state stored in `.markstate-focus` at the project root.

## `which`

Print `docs_root` or resolve a focus-style query without changing focus:

```bash
markstate which
markstate which add-login
```

## `transitions`

List every transition defined by the active flow:

```bash
markstate transitions
```

## Task commands

Find or complete Markdown checklist items:

```bash
markstate next-task
markstate check "Add integration tests"
```

`check` accepts the same `--set` and `--unset` annotations as other
document-changing commands.

## `list`

List directories containing Markdown documents:

```bash
markstate list
```

## `audit`

Show the merged transition audit log across users:

```bash
markstate audit
markstate audit --days 7
markstate audit --days 0 --json
```

## `query`

Find documents by front matter fields. Predicates are ANDed:

```bash
markstate query status=draft
markstate query status=draft "created-at>2024-06-01"
markstate query title~=api status!=done
markstate query status=done "closed-at<30d" --json
```

| Operator | Meaning |
|---|---|
| `=` | Exact match |
| `!=` | Not equal |
| `~=` | Case-insensitive substring |
| `>` `<` `>=` `<=` | Numeric or string comparison |

Query values support `me`, `now`, `today`, and relative dates `Nd`, `Nw`,
`Nm`, and `Ny`.

## `check-gate`

Check whether a phase's gate conditions are met. Exit status is zero when
satisfied and one otherwise:

```bash
markstate check-gate review
```

## `doctor`

Validate the active flow chain and check for broken links under `docs_root`:

```bash
markstate doctor
markstate doctor --verbose
```

## `install-skills`

Install Markstate's bundled agent skill:

```bash
markstate install-skills
```
