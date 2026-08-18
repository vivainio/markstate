# Command reference

Global options include `--focus DIR`, repeatable `-D NAME=VALUE` /
`--variable NAME=VALUE`, and `--version`. Variables can also be persisted
per-project with the [`vars`](#vars) command.

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

## `vars`

Set, unset, or show persisted flow variables:

```bash
markstate vars                  # show current persisted variables
markstate vars skill=basflow    # persist one or more NAME=VALUE
markstate vars --unset skill    # remove a persisted variable
markstate vars --clear          # remove all persisted variables
```

Persisted variables are personal state stored in `.markstate-variables` at the
project root (same directory as `.markstate-focus`), one `NAME=VALUE` per
line. Each name is checked against the `$variables` declared across the flow
chain (following `use`/`redirect`, resolved with whatever's already known),
and each value is checked against that variable's declared `values` list, if
it has one — both rejected up front (with a "did you mean" suggestion for an
unknown name close to a real one) rather than persisted, so a typo or bad
value doesn't sit quietly in the file only to break every later command with
an unrelated-looking error. Locating the `.markstate-variables` file itself
doesn't require resolving the flow's own `$variables`/`$select`, though — so
`vars` can still set a variable's value even before it's been set for the
first time, including one declared `required: true` with no default.

Precedence (lowest to highest): declared `default` < `.markstate-variables` <
`MARKSTATE_VARIABLES` env < `-D`/`--variable`. Use `vars` for a value that
should stick across invocations in this project (e.g. "this checkout always
uses the `basflow` skill"); use `-D`/`--variable` for a one-off override.

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

## `validate`

Validate a flow file against the current bundled schema. With no argument,
Markstate discovers the nearest `flow.yml` or `.markstate/flow.yml`:

```bash
markstate validate
markstate validate path/to/flow.yml
```

Validation uses the schema shipped with the installed Markstate version. The
validator is loaded only when this command runs, keeping normal command startup
fast. It follows `use` and `redirect`, validating every reachable flow file;
variable-selected references use the normal `-D` and `MARKSTATE_VARIABLES`
values. Use `markstate doctor` for additional document-tree diagnostics.

## `install-skills`

Install Markstate's bundled agent skill:

```bash
markstate install-skills
```
