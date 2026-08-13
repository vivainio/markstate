# Markstate

Markstate tracks Markdown documents through a workflow defined in `flow.yml`.
It gives humans and AI agents the same precise view of phases, gates, available
transitions, and remaining work.

It works for spec reviews, ADRs, runbooks, content pipelines, and especially
spec-driven development.

```bash
uv tool install markstate
markstate init
markstate new spec.md
markstate status
```

[Get started](getting-started.md){ .md-button .md-button--primary }
[Browse examples](examples.md){ .md-button }

## Why Markstate?

- **Workflow as data:** phases and transitions live in a readable YAML file.
- **Markdown-native:** state is stored in document front matter.
- **Agent-friendly:** commands expose exactly what exists and what can happen next.
- **Composable:** share flows, redirect between repositories, scope phases, and
  select configuration with runtime variables.
- **Optional:** use `markstate set` and `markstate status` without a flow file.

## Typical loop

```bash
markstate next
markstate new proposal.md
markstate do accept proposal.md
markstate check-gate review
markstate status
```

