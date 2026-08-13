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

