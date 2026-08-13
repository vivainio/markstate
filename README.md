# markstate

Track Markdown documents through defined workflows: phases, gate conditions,
produced files, and named transitions stored in `flow.yml`.

Markstate works for spec reviews, ADRs, runbooks, content pipelines, and
spec-driven development. Humans and AI agents get the same precise view of
what exists, what is blocked, and what can happen next.

## Install

```bash
uv tool install markstate
```

## Quick start

```bash
markstate init
markstate new spec.md
markstate next
markstate do approve spec.md
markstate status
```

For a ready-made spec-driven development flow:

```bash
uvx skillset add vivainio/markstate -s sdd
markstate init \
  https://raw.githubusercontent.com/vivainio/markstate/main/examples/sdd/flow.yml \
  --hidden
markstate new changes/add-login
```

## Documentation

Full guides, command reference, configuration reference, and the versioned
`flow.yml` JSON Schema are available at
[vivainio.github.io/markstate](https://vivainio.github.io/markstate/).

Ready-made workflows live under [`examples/`](examples/), with matching agent
skills under [`skills/`](skills/).

## Use without a flow

Markstate can also track arbitrary front matter state without `flow.yml`:

```bash
markstate set in-progress notes.md
markstate query status=in-progress
markstate status
```

## License

MIT
