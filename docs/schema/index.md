# JSON Schema

Markstate publishes versioned JSON Schemas for `flow.yml` with this
documentation site. Choose the schema generation matching your flow format:

```text
https://vivainio.github.io/markstate/schema/v1/flow.schema.json
```

Associate it explicitly with a flow file to get completion, hover help, and
inline validation in editors using YAML Language Server:

```yaml
# yaml-language-server: $schema=https://vivainio.github.io/markstate/schema/v1/flow.schema.json
```

Or configure a workspace-wide association in VS Code:

```json
{
  "yaml.schemas": {
    "https://vivainio.github.io/markstate/schema/v1/flow.schema.json": [
      "flow.yml",
      ".markstate/flow.yml"
    ]
  }
}
```

The version identifies the flow-format generation. Backward-compatible fields
can be added to v1; an incompatible format will be published under
`schema/v2/`. To pin an exact schema revision, use the corresponding Markstate
release tag through GitHub's raw-content URL.

The schema validates structure and documents available fields. Cross-file
resolution (`use` and `redirect`) and relationships between `$variables` and
`$select` cases are validated by Markstate itself:

```bash
markstate doctor
```
