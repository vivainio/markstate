# AI-native SDLC

An example flow modeled on Anthropic's [The AI-Native SDLC Playbook](https://claude.com/blog/the-ai-native-sdlc-playbook),
which describes six stages — Plan, Design, Build, Test, Deploy, Maintain —
each committing a version-controlled artifact that the next stage reads.
That's markstate's phase/gate/produces model already, so the mapping is
direct: one phase per stage, one tracked document per artifact, gated on the
previous artifact's approval.

## Stage → phase mapping

| Playbook stage | markstate phase | Artifact     | Gate                          |
|-----------------|-----------------|--------------|--------------------------------|
| Plan             | `plan`          | `intent.md`  | —                               |
| Design           | `design`        | `spec.md`    | `intent.md` approved            |
| Build            | `build`         | `plan.md`    | `spec.md` approved              |
| Test             | `test`          | `evals.md`   | `plan.md` approved + all tasks done |
| Deploy           | `deploy`        | `review.md`  | `evals.md` approved             |
| Maintain         | `maintain`      | —            | `review.md` approved            |

`spec.md`, `plan.md`, `evals.md`, and `review.md` are all `auto: true`: they
appear the moment their gate is satisfied, mirroring the playbook's "each
stage commits an artifact the next stage reads" — nobody has to remember to
scaffold the next document by hand. `build`'s `advance_when` requires both
`plan.md: approved` *and* `tasks: all_done`, matching the playbook's
distinction between an approved plan and the diff that actually implements
it.

`maintain` is a terminal phase with no `produces`: closing the loop back to
`plan` isn't another phase transition within one change, it's a *new* change.
See below.

## Try it

```bash
markstate init https://raw.githubusercontent.com/vivainio/markstate/main/examples/ai-native-sdlc/flow.yml
markstate new changes/add-oauth-login
markstate focus add-oauth-login
markstate status
```

## Worked demo

```
$ markstate new changes/add-oauth-login
created changes/add-oauth-login/intent.md
$ markstate focus add-oauth-login
focus: changes/add-oauth-login

$ markstate status
current phase: plan — Capture intent as a version-controlled artifact
    intent.md  draft
  plan      in progress
  design    pending
  ...

$ markstate do approve intent.md
intent.md: draft → approved
→ entering phase: design — Collapse requirements and technical design into one artifact
  advance when:
    - spec.md must have status 'approved'
created changes/add-oauth-login/spec.md

$ markstate do approve spec.md
spec.md: draft → approved
→ entering phase: build — Plan mode, then implementation against the approved plan
  advance when:
    - plan.md must have status 'approved'
    - all tasks in plan.md must be done
created changes/add-oauth-login/plan.md

$ markstate do approve plan.md
plan.md: draft → approved
$ markstate check "OAuth callback route"
$ markstate check "refresh tokens"
$ markstate check "login UI"
  plan.md  [x] Update login UI  (3/3)
→ entering phase: test — Feedback loops and eval sign-off before human review
  advance when:
    - evals.md must have status 'approved'
created changes/add-oauth-login/evals.md

$ markstate do approve evals.md
evals.md: draft → approved
→ entering phase: deploy — PR review and release approval gate
  advance when:
    - review.md must have status 'approved'
created changes/add-oauth-login/review.md

$ markstate do approve review.md
review.md: draft → approved
→ entering phase: (complete)

$ markstate viz
  ✓ plan  →  ✓ design  →  ✓ build  →  ✓ test  →  ✓ deploy  →  ✓ maintain
    ✅ evals.md   approved
    ✅ intent.md  approved
    ✅ review.md  approved
    ✅ spec.md    approved
    ✅ plan.md    approved  [██████████]  3/3 tasks
```

## Closing the loop from `maintain`

The playbook's Maintain stage watches control bands (test failure rate,
post-deploy errors, cycle time) and, on a breach, has Claude write a fresh
`intent.md` that re-enters the pipeline at Plan. In markstate terms that's
just another `markstate new`, run by whatever monitors the control bands
rather than by a person opening an editor:

```
$ markstate new changes/fix-oauth-token-leak
created changes/fix-oauth-token-leak/intent.md
```

A real setup would fire that command from the monitoring job itself once a
band is breached, and could set `--set source=incident-<id>` (or similar) on
the new `intent.md` so the audit trail shows it was machine-filed rather than
human-originated — `markstate query source~=incident` then finds every
change that started life as an incident response.

## What this leaves out

The playbook also covers things markstate doesn't model directly and that a
real adoption would layer on top:

- **Separation of duties** ("the agent cannot approve its own code"): a
  `flow_hooks.py` `on_transition` hook can compare a document's
  `created-by` against `approved-by` on the `deploy` phase's `approve`
  transition and veto a match — see `examples/sdd/flow_hooks.py` for the
  hook mechanics (stamping fields, raising `HookAbort`). Left out here to
  keep the flow itself the focus.
- **CI/CD tiering by environment** (dev free, staging supervised, prod
  gated) and **regulated-enterprise sandboxing** (deny-listed paths,
  OS-level network/file limits) are deployment infrastructure concerns,
  outside what a `flow.yml` describes.
- **Skills and `CLAUDE.md`** (Build stage) encode institutional knowledge for
  the agent doing the work; they sit alongside a change's documents rather
  than being tracked as phase artifacts themselves.
