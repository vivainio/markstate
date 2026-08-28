# Variables and selection

Variables let one `flow.yml` select configuration at runtime. Declare variables
under `$variables`, then use `$select` wherever a YAML value is accepted.

```yaml
$variables:
  track:
    values: [standard, quick]
    default: standard
  platform:
    values: [cloud, local]
    required: true
```

Supply values through the CLI or environment:

```bash
markstate -D track=quick -D platform=cloud status
MARKSTATE_VARIABLES="track=quick,platform=cloud" markstate status
```

CLI values override `MARKSTATE_VARIABLES`, which overrides declared defaults.
Unknown variables and values outside `values` are errors.

## Persist a variable per project

`-D`/`MARKSTATE_VARIABLES` are one-off, per-invocation overrides. To make a
choice stick across invocations in one checkout, persist it instead:

```bash
markstate vars skill=myflow    # persist
markstate vars                  # show what's persisted
markstate vars --unset skill    # remove one
markstate vars --clear          # remove all
```

This writes to `.markstate-variables` at the project root (alongside
`.markstate-focus`). Like `-D`/`MARKSTATE_VARIABLES`, an unknown variable name
or a value outside its declared `values` is rejected rather than persisted.
Full precedence, lowest to highest: declared `default` <
`.markstate-variables` < `MARKSTATE_VARIABLES` env < `-D`/`--variable`.

## Select a base flow

```yaml
use:
  $select: track
  cases:
    standard: flows/standard.yml
    quick: flows/quick.yml

docs_root: project-docs
```

The local `docs_root` overrides the selected base flow.

## Redirect to a complete flow

```yaml
redirect:
  $select: platform
  cases:
    cloud: ../cloud/flow.yml
    local: ../local/flow.yml
```

Unlike `use`, `redirect` transfers control completely; sibling configuration
fields are ignored.

## Select arbitrary values

```yaml
docs_root:
  $select: track
  cases:
    standard: docs
    quick: notes
```

Selections can return scalars, mappings, or lists. Markstate does not perform
`${variable}` string interpolation.

