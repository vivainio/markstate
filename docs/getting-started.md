# Getting started

## Install

```bash
uv tool install markstate
```

## Start with the built-in flow

```bash
mkdir my-workflow
cd my-workflow
markstate init
markstate new spec.md
markstate next
markstate status
```

`markstate init` writes `flow.yml`. Markstate discovers that file by walking up
from the current directory, checking `flow.yml` and `.markstate/flow.yml` at
each level.

## Start a spec-driven workflow

```bash
uvx skillset add vivainio/markstate -s sdd
markstate init \
  https://raw.githubusercontent.com/vivainio/markstate/main/examples/sdd/flow.yml \
  --hidden
markstate new changes/add-login
markstate focus add-login
markstate next
```

`--hidden` creates `.markstate/flow.yml`, which is useful while evaluating
Markstate without adding visible workflow files throughout a repository.

## Use Markstate without configuration

Add arbitrary state to Markdown front matter:

```markdown
---
status: todo
---

# My note
```

Then query and update it directly:

```bash
markstate status
markstate set in-progress notes.md
markstate set done notes.md
```

