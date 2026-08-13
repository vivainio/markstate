# Skill-provided flow

An agent skill can ship its canonical `flow.yml`, templates, and
`flow_hooks.py` together under its `resources/` directory. A project then keeps
only a small importing flow:

```yaml
use: ~/.claude/skills/my-workflow/resources/flow.yml
docs_root: project-docs
```

`~` is expanded to the current user's home directory. Markstate loads phases,
transitions, templates, and fallback hooks from the installed skill. Values in
the project file override the imported flow.

This arrangement keeps workflow policy beside the agent instructions that use
it and lets a skill upgrade update both together. It does mean every machine
running Markstate must install the skill at the same path.

