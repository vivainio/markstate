# Versioning flows

A flow evolves. You add `analysis.md` to the change template, or require a new
review step. Without help, every existing item then fails the new requirement
and falls back to an earlier phase, because phases are re-evaluated from the
files on disk each time.

Versioning lets a requirement apply only to items created after it was
introduced.

## Declare a version

Put `version` and `version_file` on the item type, which is a `dir:` entry, and
mark newer files with `since`:

```yaml
phases:
  - name: drafting
    produces:
      - dir: changes/<change>
        version: 2
        version_file: proposal.md
        files:
          - file: proposal.md
            template: |
              ---
              status: draft
              ---
              # Proposal
          - file: analysis.md        # added in version 2
            since: 2
            template: |
              ---
              status: draft
              ---
              # Analysis
    advance_when:
      - file: proposal.md
        status: accepted
      - file: analysis.md            # skipped for items below version 2
        status: accepted
```

| Key | Where | Meaning |
|---|---|---|
| `version` | `dir:` entry | Current version, stamped into new items |
| `version_file` | `dir:` entry | Produced file whose front matter carries the item's version |
| `since` | produced file | Only expected for items at this version or later |

## Where the version lives

The version is stored in the front matter of the `version_file`, in a field
called `flow-version`:

```markdown
---
status: draft
flow-version: 2
---

# Proposal
```

`markstate new` writes it when it creates the file. You do not put it in the
template. It is written once and never overwritten.

Every `dir:` pattern names its own `version_file` and has its own counter, so a
`changes/` item can be at version 3 while a `plans/` item is at version 1.

## How an item's version is read

| Item state | Version |
|---|---|
| `version_file` has `flow-version: N` | N |
| `version_file` exists with no `flow-version` | 0 |
| `version_file` missing, but the directory has other `.md` files | 0 |
| Directory has no `.md` files yet | the current `version` |

Items that exist before you introduce versioning therefore need no changes:
adding `version` and `version_file` to the flow leaves them at version 0.

Only the `version_file` matters. Other documents never need the field.

## What `since` does

For an item whose version is lower than a file's `since`, that file is treated
as not part of the item:

- it is not listed as missing by `markstate next`;
- it is not offered by `markstate new`, and `markstate new <file>` refuses it;
- it is not created by `auto: true`;
- a `file:` condition that names it counts as satisfied, in `gates`,
  `advance_when` and transition `gates`.

You declare `since` once, on the produced file. Conditions that reference the
file need no extra annotation.

Items at or above the file's `since` are held to the full rule.

## Adding a new requirement

1. Bump `version` on the `dir:` entry.
2. Add the file with `since:` set to the new version.
3. Add the condition that references it, if any.

New items are created at the new version. Existing items are unaffected and keep
their phase.

To bring an old item under the new rules, set `flow-version` to the new value in
its `version_file`. Setting it by hand is the only way for now.

## Limits

- `since` is evaluated per produced file, and only for `file:` conditions.
  `glob:` conditions and whole phases cannot be skipped yet.
- Conditions are only skipped when evaluated in an item directory that matches a
  versioned `dir:` entry. At a parent directory, they behave as before.

## Validation

The flow fails to load when:

- `version` and `version_file` are not given together;
- `version_file` is not one of the dir's `files`, or has a `since`;
- `since` is not an integer between 0 and the dir's `version`;
- `since` is used on a file that is not in a versioned dir;
- two entries with the same `dir:` disagree on `version` or `version_file`.
