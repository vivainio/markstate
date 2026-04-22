"""CLI entry point for markstate."""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from importlib.resources import files as pkg_files
from pathlib import Path

import yaml

from markstate import engine, frontmatter
from markstate.config import (
    FlowConfig,
    Phase,
    ProducedDir,
    ProducedDoc,
    filtered_rglob,
    find_and_load,
    find_flow_target,
    has_use,
)
from markstate.engine import TaskNotFoundError, TransitionError

FOCUS_FILE = ".markstate-focus"
FOCUS_ENV_VAR = "MARKSTATE_FOCUS"

_PRED_RE = re.compile(r'^([a-zA-Z0-9_-]+)(>=|<=|!=|~=|>|<|=)(.+)$')
_REL_AGO_RE = re.compile(r'^(\d+)([dwmy])$')

_focus_override: str | None = None


def _parse_set_args(set_args: list[str]) -> dict[str, str]:
    result = {}
    for item in set_args:
        if "=" not in item:
            print(f"error: --set value must be key=value, got '{item}'", file=sys.stderr)
            sys.exit(1)
        key, _, value = item.partition("=")
        result[key] = value
    return result


def _add_set_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--set", metavar="KEY=VALUE", action="append", default=[],
        help="Set extra frontmatter fields ('me' = git user, 'now' = UTC timestamp, 'today' = UTC date). Prefix key with 'once-' to write only when absent.",
    )
    p.add_argument(
        "--unset", metavar="KEY", action="append", default=[],
        help="Remove a frontmatter field (repeatable). No-op if the field is absent.",
    )


def _apply_frontmatter_edits(
    path: Path,
    set_fields: dict[str, str],
    unset_fields: list[str] | tuple[str, ...] = (),
    status_field: str = "status",
) -> None:
    if not set_fields and not unset_fields:
        return
    doc = frontmatter.load(path)
    doc.first_keys = (status_field,)
    engine.unset_keys(doc, unset_fields)
    engine.apply_fields(doc, set_fields)
    doc.save()


def _try_load_config() -> FlowConfig | None:
    try:
        return find_and_load()
    except FileNotFoundError:
        return None


def _read_focus(config: FlowConfig) -> Path | None:
    if _focus_override is not None:
        p = Path(_focus_override)
        if not p.is_absolute():
            p = (config.docs_root / p).resolve()
        return p
    focus_file = config.root / FOCUS_FILE
    if focus_file.exists():
        rel = focus_file.read_text(encoding="utf-8").strip()
        return (config.docs_root / rel).resolve()
    return None


def _resolve_file(path_str: str, config: FlowConfig | None) -> Path:
    """Resolve a file path: absolute paths used as-is, relative paths resolved
    against doc base when config is available, otherwise against cwd.

    Resolution order: docs_root → doc_base (cwd or focus) → focus fallback.
    This prevents path doubling when focus is a subdirectory and the user
    passes a path relative to docs_root that already includes that subdirectory.
    """
    p = Path(path_str)
    if p.is_absolute():
        return p
    if config:
        # Try docs_root first — handles full relative paths like
        # "changes/area/name/proposal.md" regardless of focus.
        docs_root_resolved = (config.docs_root / path_str).resolve()
        if docs_root_resolved.exists():
            return docs_root_resolved

        # Try the doc base (cwd if inside docs_root, else focus).
        base = _resolve_doc_base(config)
        resolved = (base / path_str).resolve()
        if resolved.exists():
            return resolved

        # Fallback: try focus directly (when base != focus).
        focus = _read_focus(config)
        if focus and focus != base:
            focused = (focus / path_str).resolve()
            if focused.exists():
                return focused

        # Nothing found — return docs_root-based path for the error message.
        return docs_root_resolved
    return p.resolve()


def _resolve_doc_base(config: FlowConfig) -> Path:
    """Resolve the base directory for document operations (new, do).

    Priority: cwd if inside docs_root → focus → error.
    """
    cwd = Path.cwd()
    if config.docs_root in cwd.parents or cwd == config.docs_root:
        return cwd
    focus = _read_focus(config)
    if focus:
        return focus
    print(
        "error: not inside docs_root and no focus set — "
        "run 'markstate focus <dir>' or cd into the target directory",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_directory(args: argparse.Namespace, config: FlowConfig | None) -> Path:
    if args.directory:
        return Path(args.directory).resolve()
    if config:
        focus = _read_focus(config)
        if focus:
            return focus
        # If cwd is outside docs_root (e.g. redirect from another repo), use docs_root
        cwd = Path.cwd()
        if not cwd.is_relative_to(config.docs_root):
            return config.docs_root
    return Path.cwd()


def _load_config() -> FlowConfig:
    config = _try_load_config()
    if config is None:
        print(
            f"error: flow.yml not found (searched from {Path.cwd()} upward)",
            file=sys.stderr,
        )
        sys.exit(1)
    return config


TEMPLATE_FLOW = """\
# flow.yml — markstate workflow definition
# Run `markstate status` to see current phase and progress.

status_field: status

phases:
  - name: drafting
    produces:
      - file: spec.md
        template: |
          ---
          status: draft
          ---

          # Spec

          ## Overview

          ## Requirements
      - file: design.md
        template: |
          ---
          status: draft
          ---

          # Design

          ## Approach
    advance_when:
      - file: spec.md
        status: approved

  - name: review
    produces:
      - dir: specs/<name>
        files:
          - file: functional-spec.md
            template: |
              ---
              status: draft
              ---

              # Functional Spec
          - file: technical-spec.md
            template: |
              ---
              status: draft
              ---

              # Technical Spec
    gates:
      - file: spec.md
        status: approved
    advance_when:
      - glob: "docs/*.md"
        all_status: reviewed

  - name: done
    gates:
      - glob: "docs/*.md"
        all_status: reviewed

transitions:
  - name: approve
    from: draft
    to: approved

  - name: start-review
    from: draft
    to: in-review

  - name: mark-reviewed
    from: in-review
    to: reviewed
"""


def _load_source_content(source_arg: str | None) -> str:
    """Resolve a source argument (file path, URL, or None) to flow.yml content."""
    if source_arg is None:
        return TEMPLATE_FLOW
    if source_arg.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(source_arg) as resp:
                return resp.read().decode()
        except Exception as e:
            print(f"error: could not fetch '{source_arg}': {e}", file=sys.stderr)
            sys.exit(1)
    source = Path(source_arg).expanduser()
    if not source.is_file():
        print(f"error: '{source_arg}' not found", file=sys.stderr)
        sys.exit(1)
    return source.read_text(encoding="utf-8")


def _diff_counts(old: str, new: str) -> tuple[int, int]:
    """Return (added, removed) line counts between two strings."""
    added = removed = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _cmd_init(args: argparse.Namespace) -> None:
    # If a flow.yml is already reachable from cwd, replace it (idempotent upgrade).
    try:
        existing = find_flow_target()
    except (FileNotFoundError, ValueError):
        existing = None

    content = _load_source_content(args.source)
    if args.source is not None:
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"error: source does not parse as YAML: {e}", file=sys.stderr)
            sys.exit(1)

    if existing is not None:
        if has_use(existing):
            print(f"{existing} uses 'use:' directive, skipping update")
            return
        if args.hidden:
            print(
                f"error: flow.yml already exists at {existing}; --hidden can't convert in place",
                file=sys.stderr,
            )
            sys.exit(1)
        old_content = existing.read_text(encoding="utf-8")
        if old_content == content:
            print(f"{existing} is already up to date")
            return
        added, removed = _diff_counts(old_content, content)
        existing.write_text(content, encoding="utf-8")
        print(f"upgraded {existing}  (+{added} -{removed})")
        return

    target = Path(".markstate/flow.yml") if args.hidden else Path("flow.yml")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"created {target}")
    if args.hidden:
        gitignore = Path(".gitignore")
        entry = ".markstate/\n"
        if gitignore.exists():
            existing_gi = gitignore.read_text(encoding="utf-8")
            if ".markstate/" not in existing_gi:
                gitignore.write_text(existing_gi.rstrip("\n") + "\n" + entry, encoding="utf-8")
                print("updated .gitignore")
        else:
            gitignore.write_text(entry, encoding="utf-8")
            print("created .gitignore")


def _cmd_new(args: argparse.Namespace) -> None:
    config = _load_config()
    cwd = Path.cwd()
    extra = _parse_set_args(args.set)
    extra_unset = list(args.unset)

    # Resolve the target path relative to docs_root.
    # If inside a dir template (cd'd into a change dir), a bare filename
    # resolves via cwd. Otherwise, resolve via explicit --dir, focus, or cwd.
    file_path = Path(args.file)
    _, dir_entry = engine.find_dir_template(config, cwd)

    if dir_entry and "/" not in args.file:
        # Bare filename inside a dir template: create file in cwd
        all_files = {f.file: f for f in engine.collect_dir_files(config, dir_entry.dir)}
        produced = all_files.get(args.file)
        if produced is None:
            available = list(all_files.keys())
            print(f"error: '{args.file}' is not in this dir template. "
                  f"Available: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        target = cwd / args.file
        _write_doc(produced, target, args.force, config.status_field)
        _apply_frontmatter_edits(target, extra, extra_unset, config.status_field)
        return

    # Build candidate base directories to try, in priority order.
    # Try focus/cwd first (so relative paths like specs/foo work),
    # then docs_root (so full paths like changes/area/name work).
    explicit_base = Path(args.directory).resolve() if args.directory else None
    if explicit_base is not None:
        candidates = [explicit_base]
    else:
        candidates = []
        if config.docs_root in cwd.parents or cwd == config.docs_root:
            candidates.append(cwd)
        # Try docs_root before focus: a path like "changes/area/name"
        # should resolve against docs_root, not nest under focus.
        # Focus is only useful for relative sub-paths like "specs/foo".
        if config.docs_root not in candidates:
            candidates.append(config.docs_root)
        focus = _read_focus(config)
        if focus and focus not in candidates:
            candidates.append(focus)

    # Try each candidate base: resolve the path, check it's inside docs_root,
    # and see if it matches a produces pattern.
    for base in candidates:
        resolved = (base / args.file).resolve()
        if not resolved.is_relative_to(config.docs_root):
            continue
        rel = resolved.relative_to(config.docs_root)
        for phase in config.phases:
            for entry in phase.produces:
                if isinstance(entry, ProducedDoc) and entry.file == args.file:
                    _write_doc(entry, resolved, args.force, config.status_field)
                    _apply_frontmatter_edits(resolved, extra, extra_unset, config.status_field)
                    return
                if isinstance(entry, ProducedDir) and rel.match(entry.glob_pattern):
                    _write_dir_files(entry.files, resolved, args.force)
                    for f in entry.files:
                        _apply_frontmatter_edits(resolved / f.file, extra, extra_unset, config.status_field)
                    return
    # Collect all producible patterns for the hint
    hints = []
    for phase in config.phases:
        for entry in phase.produces:
            if isinstance(entry, ProducedDoc):
                hints.append(entry.file)
            elif isinstance(entry, ProducedDir):
                hints.append(entry.dir)
    print(f"error: '{args.file}' does not match any produces entry", file=sys.stderr)
    if hints:
        seen = set()
        unique = [h for h in hints if h not in seen and not seen.add(h)]
        print(f"hint: expected one of: {', '.join(unique)}", file=sys.stderr)
    sys.exit(1)


def _write_doc(doc: ProducedDoc, target: Path, force: bool, status_field: str = "status") -> None:
    if doc.template is None:
        print(f"error: '{target.name}' has no template defined", file=sys.stderr)
        sys.exit(1)
    if target.exists() and not force:
        print(f"error: '{target}' already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc.template, encoding="utf-8")
    _apply_frontmatter_edits(target, doc.set_fields, doc.unset_fields, status_field)
    print(f"created {target}")


def _write_dir_files(files: list[ProducedDoc], target: Path, force: bool) -> None:
    if target.exists() and not force:
        print(f"error: '{target}' already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        _write_doc(f, target / f.file, force)


def _create_auto_docs(phase: Phase, config: FlowConfig, directory: Path) -> None:
    for entry in phase.produces:
        if isinstance(entry, ProducedDoc):
            if not entry.auto or entry.template is None:
                continue
            dest = directory / entry.file
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(entry.template, encoding="utf-8")
                _apply_frontmatter_edits(dest, entry.set_fields, entry.unset_fields, config.status_field)
                print(f"created {dest.relative_to(Path.cwd())}")
        elif isinstance(entry, ProducedDir):
            # Auto-create files inside existing directories matching the pattern.
            # Glob from docs_root, but only in dirs under the current directory.
            for existing_dir in sorted(config.docs_root.glob(entry.glob_pattern)):
                if not existing_dir.is_dir():
                    continue
                if not existing_dir.is_relative_to(directory):
                    continue
                for f in entry.files:
                    if not f.auto or f.template is None:
                        continue
                    dest = existing_dir / f.file
                    if not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(f.template, encoding="utf-8")
                        _apply_frontmatter_edits(dest, f.set_fields, f.unset_fields, config.status_field)
                        print(f"created {dest.relative_to(Path.cwd())}")


_USER_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _audit_user(config: FlowConfig) -> tuple[str, str]:
    """Return (identity, filename_slug) for the current git user."""
    try:
        result = subprocess.run(
            ["git", "-C", str(config.root), "config", "user.email"],
            capture_output=True, text=True, check=False, timeout=2,
        )
        email = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        email = ""
    identity = email or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    slug = _USER_SLUG_RE.sub("_", identity).strip("_") or "unknown"
    return identity, slug


def _append_audit_log(
    config: FlowConfig,
    target: Path,
    transition_name: str,
    old: str,
    new: str,
    set_fields: dict[str, str] | None = None,
) -> None:
    identity, slug = _audit_user(config)
    try:
        doc_rel = str(target.resolve().relative_to(config.root.resolve()))
    except ValueError:
        doc_rel = str(target)
    entry = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": identity,
        "transition": transition_name,
        "doc": doc_rel,
        "from": old,
        "to": new,
    }
    if set_fields:
        resolved = {k: engine.resolve_magic(str(v)) for k, v in set_fields.items()}
        entry["set"] = {k: v if isinstance(v, str) else str(v) for k, v in resolved.items()}
    log_dir = config.root / ".markstate"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"audit-{slug}.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _report_transition(
    phase_before: Phase | None, phase_after: Phase | None, config: FlowConfig, directory: Path
) -> None:
    if phase_after == phase_before:
        return
    if phase_after and phase_after.description:
        print(f"→ entering phase: {phase_after.name} — {phase_after.description}")
    else:
        print(f"→ entering phase: {phase_after.name if phase_after else '(complete)'}")
    if phase_after and phase_after.advance_when:
        print("  advance when:")
        for cond in phase_after.advance_when:
            print(f"    - {engine.describe_condition(cond)}")

    docs_phase = phase_after or (
        engine.find_entered_phase(config, directory) if phase_before is not None else None
    )
    if docs_phase:
        _create_auto_docs(docs_phase, config, directory)


def _cmd_set(args: argparse.Namespace) -> None:
    config = _try_load_config()
    status_field = config.status_field if config else "status"
    extra = _parse_set_args(args.set)
    for t in args.targets:
        target = _resolve_file(t, config)
        if not target.exists():
            print(f"error: '{t}' does not exist", file=sys.stderr)
            sys.exit(1)
        doc = frontmatter.load(target)
        doc.first_keys = (status_field,)
        old = str(doc.get(status_field) or "")
        doc.set(status_field, args.status)
        engine.unset_keys(doc, args.unset)
        engine.apply_fields(doc, extra)
        doc.save()
        print(f"{t}: {old or '(none)'} → {args.status}")


def _cmd_do(args: argparse.Namespace) -> None:
    config = _load_config()
    directory = _resolve_doc_base(config)
    target = _resolve_file(args.target, config)
    if not target.exists():
        print(f"error: '{args.target}' not found (resolved to {target})", file=sys.stderr)
        sys.exit(1)
    # Evaluate phase relative to the document's parent directory context.
    # For files inside a focused change dir, use focus; otherwise use directory.
    phase_dir = _read_focus(config) or directory

    phase_before = engine.current_phase(config, phase_dir)

    cli_set = _parse_set_args(args.set)
    try:
        old, new = engine.do_transition(
            args.transition_name, target, config, provided_keys=set(cli_set.keys())
        )
        print(f"{args.target}: {old} → {new}")
        t_def = next((t for t in config.transitions if t.name == args.transition_name), None)
        merged_set = {**(t_def.set_fields if t_def else {}), **cli_set}
        _append_audit_log(config, target, args.transition_name, old, new, merged_set)
    except TransitionError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    _apply_frontmatter_edits(target, cli_set, list(args.unset), config.status_field)

    phase_after = engine.current_phase(config, phase_dir)
    _report_transition(phase_before, phase_after, config, phase_dir)


def _find_focus_dir(query: str, docs_root: Path) -> Path:
    """Find a unique directory under docs_root whose name contains query as a substring."""
    matches = [
        d for d in filtered_rglob(docs_root, "*")
        if d.is_dir() and (query in d.name or query in str(d.relative_to(docs_root)))
    ]
    # If query matches a relative path exactly, prefer that over substring matches
    query_normalized = query.replace("\\", "/")
    exact = [d for d in matches if d.relative_to(docs_root).as_posix() == query_normalized]
    if exact:
        matches = exact
    if not matches:
        print(f"error: no directory matching '{query}' found under {docs_root}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"error: '{query}' is ambiguous, matches:", file=sys.stderr)
        for m in sorted(matches):
            print(f"  {m.relative_to(docs_root)}", file=sys.stderr)
        sys.exit(1)
    return matches[0]


def _cmd_focus(args: argparse.Namespace) -> None:
    config = _load_config()
    if args.directory is None:
        focus = _read_focus(config)
        print(focus or "(none)")
        return
    target = Path(args.directory).resolve()
    if not target.is_dir():
        target = _find_focus_dir(args.directory, config.docs_root)
    rel = target.relative_to(config.docs_root)
    (config.root / FOCUS_FILE).write_text(str(rel) + "\n", encoding="utf-8")
    print(f"focus: {rel}")


def _cmd_status(args: argparse.Namespace) -> None:
    config = _try_load_config()
    directory = _resolve_directory(args, config)
    status_field = config.status_field if config else "status"

    files = {}
    exclude = config.exclude_dirs if config else None
    for path in filtered_rglob(directory, "*.md", exclude):
        doc = frontmatter.load(path)
        s = doc.get(status_field)
        done, total = frontmatter.count_tasks(doc.body)
        if s or total > 0:
            entry: dict = {}
            if s:
                entry["status"] = s
            if total > 0:
                entry["tasks_done"] = done
                entry["tasks_total"] = total
            files[str(path.relative_to(directory))] = entry

    if args.as_json:
        result = engine.status(config, directory) if config else {}
        print(json.dumps({**result, "files": files}, indent=2))
        return

    if config:
        result = engine.status(config, directory)
        phase = result["current_phase"]
        if not config.docs_root.is_relative_to(Path.cwd()):
            print(f"docs_root: {config.docs_root}")
        try:
            display_dir = directory.relative_to(config.docs_root)
        except ValueError:
            display_dir = directory
        print(f"directory: {display_dir}")
        phase_obj = config.phase(phase) if phase else None
        if phase_obj and phase_obj.description:
            print(f"current phase: {phase} — {phase_obj.description}")
        else:
            print(f"current phase: {phase or '(complete)'}")
        print()

    # Factor out the longest common directory prefix
    rel_paths = list(files.keys())
    if rel_paths:
        parts_list = [Path(r).parts for r in rel_paths]
        common_parts: list[str] = []
        for pieces in zip(*parts_list):
            if len(set(pieces)) == 1:
                common_parts.append(pieces[0])
            else:
                break
        # Only use common prefix if it's a directory (not the filename itself)
        # and it actually saves something
        common = Path(*common_parts) if common_parts else None
        if common and all(str(r) != str(common) for r in rel_paths):
            print(f"  {directory / common}/")
            strip = len(common_parts)
        else:
            common = None
            strip = 0

        short_names = {
            rel: str(Path(*Path(rel).parts[strip:])) if strip else rel
            for rel in files
        }
        name_width = max(len(s) for s in short_names.values())
        status_width = max(
            (len(str(e.get("status", ""))) for e in files.values()), default=0
        )
        for rel, entry in files.items():
            s = entry.get("status", "")
            task_info = f"  {entry['tasks_done']}/{entry['tasks_total']} tasks" if "tasks_total" in entry else ""
            short = short_names[rel]
            print(f"    {short:{name_width}s}  {s:>{status_width}s}{task_info}")

    if config and result["phases"]:
        print()
        phase_width = max(len(p["name"]) for p in result["phases"])
        for p in result["phases"]:
            if p["complete"]:
                state = "complete"
            elif p["gates_pass"]:
                state = "in progress"
            else:
                state = "pending"
            print(f"  {p['name']:{phase_width}s}  {state}")


_STATUS_ORDER = {
    "draft": 0,
    "proposed": 1,
    "in-progress": 2,
    "wip": 2,
    "blocked": 2,
    "in-review": 3,
    "reviewed": 4,
    "approved": 5,
    "accepted": 5,
    "done": 6,
    "complete": 6,
    "archived": 7,
    "rejected": 7,
}


_STATUS_EMOJI = {
    "draft": "📝",
    "proposed": "💭",
    "approved": "✅",
    "accepted": "✅",
    "in-progress": "🚧",
    "in-review": "👀",
    "reviewed": "✔️ ",
    "blocked": "🚫",
    "done": "🎉",
    "complete": "🎉",
    "archived": "📦",
    "rejected": "❌",
    "wip": "🚧",
}


def _progress_bar(frac: float, width: int = 10) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def _cmd_viz(args: argparse.Namespace) -> None:
    config = _try_load_config()
    directory = _resolve_directory(args, config)
    status_field = config.status_field if config else "status"

    exclude = config.exclude_dirs if config else None
    groups: dict[str, list[tuple[Path, str | None, int, int]]] = {}
    for path in filtered_rglob(directory, "*.md", exclude):
        doc = frontmatter.load(path)
        s = doc.get(status_field)
        done, total = frontmatter.count_tasks(doc.body)
        if not s and total == 0:
            continue
        rel = path.relative_to(directory)
        parent = str(rel.parent) if str(rel.parent) != "." else ""
        groups.setdefault(parent, []).append((rel, str(s) if s else None, done, total))

    if not groups:
        print("no files with status or tasks")
        return

    if config:
        phase = engine.current_phase(config, directory)
        phase_names = [p.name for p in config.phases_for(directory)]
        if phase_names:
            cur = phase.name if phase else None
            marks = []
            passed = True
            for n in phase_names:
                if n == cur:
                    marks.append(f"▶ {n}")
                    passed = False
                elif passed:
                    marks.append(f"✓ {n}")
                else:
                    marks.append(f"  {n}")
            if cur is None:
                marks = [f"✓ {n}" for n in phase_names]
            print("  " + "  →  ".join(marks))
            print()

    for parent in sorted(groups):
        if parent:
            print(f"  {parent}/")
        rows = sorted(groups[parent], key=lambda r: (r[3] > 0, r[0].name))
        name_w = max(len(p.name) for p, _, _, _ in rows)
        status_w = max((len(s or "") for _, s, _, _ in rows), default=0)
        for rel, s, done, total in rows:
            emoji = _STATUS_EMOJI.get(s, "• ") if s else "  "
            status_str = s or ""
            if total > 0:
                tail = f"  {_progress_bar(done / total)}  {done}/{total} tasks"
            else:
                tail = ""
            print(f"    {emoji} {rel.name:{name_w}s}  {status_str:{status_w}s}{tail}")
        print()


def _cmd_check_gate(args: argparse.Namespace) -> None:
    config = _load_config()
    phase = config.phase(args.phase_name)
    if phase is None:
        print(f"error: unknown phase '{args.phase_name}'", file=sys.stderr)
        sys.exit(1)
    unmet = engine.check_gate(phase, config, _resolve_directory(args, config))
    if unmet:
        print("gate not satisfied:")
        for condition in unmet:
            print(f"  - {condition}")
        sys.exit(1)
    else:
        print("gate satisfied")


def _cmd_transitions(args: argparse.Namespace) -> None:
    config = _load_config()
    name_width = max(len(t.name) for t in config.transitions)
    from_width = max(len(t.from_state) for t in config.transitions)
    for t in config.transitions:
        print(f"  {t.name:{name_width}s}  {t.from_state:{from_width}s} → {t.to_state}")


def _cmd_next(args: argparse.Namespace) -> None:
    config = _load_config()
    results = engine.next_transitions(config, _resolve_directory(args, config))
    if args.as_json:
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("nothing to do")
            return
        transition_map = {t.name: t.to_state for t in config.transitions}
        file_width = max(len(item["file"]) for item in results)
        for item in results:
            if item["missing"]:
                hint = item.get("hint", f"markstate new {item['file']}")
                print(f"  {item['file']:{file_width}s}  (not created)  → {hint}")
            else:
                transitions = ", ".join(
                    f"{t} (→ {transition_map[t]})" for t in item["transitions"]
                )
                print(f"  {item['file']:{file_width}s}  {item['status']:15s}  → {transitions}")


def _cmd_next_task(args: argparse.Namespace) -> None:
    config = _load_config()
    directory = _resolve_directory(args, config)
    result = engine.next_task(config, directory)
    if result is not None:
        print(f"  {result['file']:30s}  {result['task']}")
        return

    print("all tasks done")
    phase = engine.current_phase(config, directory)
    print(f"→ phase: {phase.name if phase else '(complete)'}")
    entered = engine.find_entered_phase(config, directory)
    if entered:
        _create_auto_docs(entered, config, directory)


def _resolve_query_value(value: str) -> str:
    """Expand right-hand-side magic values in `query` predicates.

    `now`    → current UTC timestamp in ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`)
    `today`  → current UTC date (`YYYY-MM-DD`)
    `me`     → git user name
    `Nd` / `Nw` / `Nm` / `Ny` → N days/weeks/months/years ago, as a date
                                (`YYYY-MM-DD`). Months are 30d, years 365d
                                — rough but good enough for audit queries.

    Date strings compare correctly (lexicographically) against stored
    full timestamps, so `completed-at<30d` captures everything before
    midnight UTC on the threshold day.
    """
    if value == "now":
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if value == "today":
        return datetime.now(UTC).strftime("%Y-%m-%d")
    if value == "me":
        return engine.resolve_magic("me")
    m = _REL_AGO_RE.match(value)
    if m:
        n = int(m.group(1))
        days = {"d": n, "w": 7 * n, "m": 30 * n, "y": 365 * n}[m.group(2)]
        return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    return value


def _eval_predicate(actual: object, op: str, value: str) -> bool:
    actual_str = str(actual)
    if op == "=":
        return actual_str == value
    if op == "!=":
        return actual_str != value
    if op == "~=":
        return value.lower() in actual_str.lower()
    # Ordered comparison: try numeric, fall back to string (handles ISO dates)
    try:
        a: float | str = float(actual_str)
        v: float | str = float(value)
    except ValueError:
        a, v = actual_str, value
    if op == ">":
        return a > v
    if op == "<":
        return a < v
    if op == ">=":
        return a >= v
    if op == "<=":
        return a <= v
    return False


def _cmd_query(args: argparse.Namespace) -> None:
    config = _try_load_config()

    if args.directory:
        root = Path(args.directory).resolve()
    elif config:
        root = config.docs_root
    else:
        root = Path.cwd()

    predicates: list[tuple[str, str, str]] = []
    for pred in args.predicates:
        m = _PRED_RE.match(pred)
        if not m:
            print(
                f"error: invalid predicate '{pred}' — expected field=value, field>value, etc.",
                file=sys.stderr,
            )
            sys.exit(1)
        predicates.append((m.group(1), m.group(2), _resolve_query_value(m.group(3))))

    results: list[tuple[Path, frontmatter.Document]] = []
    exclude = config.exclude_dirs if config else None
    for path in filtered_rglob(root, "*.md", exclude):
        doc = frontmatter.load(path)
        if all(
            doc.front_matter.get(field) is not None
            and _eval_predicate(doc.front_matter[field], op, value)
            for field, op, value in predicates
        ):
            results.append((path, doc))

    if args.as_json:
        output = []
        for path, doc in results:
            entry: dict = {"file": str(path.relative_to(root))}
            entry.update({k: v for k, v in doc.front_matter.items()})
            output.append(entry)
        print(json.dumps(output, indent=2, default=str))
        return

    for path, doc in results:
        rel = str(path.relative_to(root))
        fm_parts = "  ".join(f"{k}={v}" for k, v in doc.front_matter.items())
        print(f"  {rel:40s}  {fm_parts}")


def _cmd_list(args: argparse.Namespace) -> None:
    config = _load_config()
    root = config.docs_root
    status_field = config.status_field
    info: dict[tuple[str, ...], tuple[int, str, str]] = {}
    for md in filtered_rglob(root, "*.md", config.exclude_dirs):
        if not md.is_file():
            continue
        d = md.parent
        key = tuple(d.relative_to(root).parts)
        if key in info:
            continue
        docs = [p for p in d.iterdir() if p.is_file() and p.suffix == ".md"]
        statuses: list[str] = []
        for p in docs:
            try:
                s = frontmatter.load(p).get(status_field)
            except Exception:
                s = None
            if s:
                statuses.append(str(s))
        least = min(statuses, key=lambda s: _STATUS_ORDER.get(s, -1)) if statuses else ""
        icon = _STATUS_EMOJI.get(least, "📄") if least else "📄"
        phase = engine.current_phase(config, d)
        info[key] = (len(docs), icon, phase.name if phase else "")
    if not info:
        print("(no directories with documents)")
        return

    all_keys: set[tuple[str, ...]] = set()
    for key in info:
        for i in range(1, len(key) + 1):
            all_keys.add(key[:i])

    max_label = max(len(k[-1]) + 2 * (len(k) - 1) for k in all_keys) if all_keys else 0

    for key in sorted(all_keys):
        depth = len(key) - 1
        name = key[-1]
        indent = "  " * depth
        label = f"{indent}{name}"
        if key in info:
            count, icon, phase = info[key]
            pad = " " * max(1, max_label - len(label) + 2)
            suffix = f"  [{phase}]" if phase else ""
            print(f"{icon} {label}{pad}{count} doc{'s' if count != 1 else ''}{suffix}")
        else:
            print(f"📁 {label}")


def _cmd_audit(args: argparse.Namespace) -> None:
    config = _load_config()
    log_dir = config.root / ".markstate"
    entries: list[dict] = []
    if log_dir.is_dir():
        for log_path in sorted(log_dir.glob("audit-*.log")):
            for line in log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    entries.sort(key=lambda e: e.get("ts", ""))
    if args.days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=args.days)
        def _parse_ts(s: str) -> datetime | None:
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None
        entries = [e for e in entries
                   if (ts := _parse_ts(e.get("ts", ""))) is not None and ts >= cutoff]

    if args.as_json:
        print(json.dumps(entries, indent=2, default=str))
        return

    if not entries:
        print("(no audit entries)")
        return

    user_w = max(len(e.get("user", "")) for e in entries)
    doc_w = max(len(e.get("doc", "")) for e in entries)
    for e in entries:
        ts = e.get("ts", "").replace("T", " ").rstrip("Z")
        arrow = f"{e.get('from', '')} → {e.get('to', '')}"
        line = (
            f"{ts}  {e.get('user', ''):{user_w}s}  "
            f"{e.get('doc', ''):{doc_w}s}  "
            f"{arrow}  ({e.get('transition', '')})"
        )
        set_fields = e.get("set") or {}
        if set_fields:
            extras = " ".join(f"{k}={v}" for k, v in set_fields.items())
            line += f"  [{extras}]"
        print(line)


def _cmd_install_skills(args: argparse.Namespace) -> None:
    target_root = Path.home() / ".claude" / "skills"
    source_root = pkg_files("markstate").joinpath("skills")
    for skill_dir in source_root.iterdir():
        if not skill_dir.is_dir():
            continue
        dest = target_root / skill_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for item in skill_dir.iterdir():
            if item.is_file():
                (dest / item.name).write_text(
                    item.read_text(encoding="utf-8"), encoding="utf-8"
                )
                print(f"installed {dest / item.name}")


def _cmd_check(args: argparse.Namespace) -> None:
    config = _load_config()
    directory = _resolve_directory(args, config)
    phase_before = engine.current_phase(config, directory)

    try:
        result = engine.check_task(args.substring, config, directory)
    except TaskNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  {result['file']}  [x] {result['task']}  ({result['done']}/{result['total']})")
    _apply_frontmatter_edits(directory / result["file"], _parse_set_args(args.set), list(args.unset), config.status_field)

    phase_after = engine.current_phase(config, directory)
    _report_transition(phase_before, phase_after, config, directory)


def _new_metavar(config: FlowConfig | None) -> str:
    if not config:
        return "FILE"
    cwd = Path.cwd()
    _, dir_entry = engine.find_dir_template(config, cwd)
    if dir_entry:
        all_files = engine.collect_dir_files(config, dir_entry.dir)
        missing = [f.file for f in all_files if not (cwd / f.file).exists()]
        return "[" + "|".join(missing) + "]" if missing else "FILE"
    items = []
    for phase in config.phases:
        for entry in phase.produces:
            if isinstance(entry, ProducedDoc):
                items.append(entry.file)
            elif isinstance(entry, ProducedDir):
                items.append(entry.dir)
    return "[" + "|".join(items) + "]" if items else "FILE"


def _build_parser(config: FlowConfig | None) -> argparse.ArgumentParser:
    transition_names = config.transition_names() if config else []

    parser = argparse.ArgumentParser(
        prog="markstate",
        description="Generic document flow processor.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('markstate')}"
    )
    parser.add_argument(
        "--focus", metavar="DIR",
        help="Override the active focus directory (also: MARKSTATE_FOCUS env var).",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # init
    p = sub.add_parser("init", help="Create a flow.yml in the current directory.")
    p.add_argument("source", nargs="?", default=None, metavar="SOURCE",
                   help="Copy from an existing flow.yml (file or URL) instead of writing the built-in template.")
    p.add_argument("--hidden", action="store_true",
                   help="Write to .markstate/flow.yml instead of flow.yml. Only applies when no flow.yml exists upward from cwd.")

    # new
    p = sub.add_parser("new", help="Create a document from its template defined in flow.yml.")
    p.add_argument("file", metavar=_new_metavar(config))
    p.add_argument("directory", nargs="?", default=None)
    p.add_argument("--force", action="store_true", help="Overwrite existing file")
    _add_set_arg(p)

    # set
    p = sub.add_parser("set", help="Set the status of one or more documents directly.")
    p.add_argument("status", metavar="STATUS")
    p.add_argument("targets", metavar="FILE", nargs="+")
    _add_set_arg(p)

    # do
    transition_metavar = "[" + "|".join(transition_names) + "]" if transition_names else "TRANSITION"
    p = sub.add_parser("do", help="Apply a named transition to a document.")
    p.add_argument("transition_name", metavar=transition_metavar)
    p.add_argument("target", metavar="FILE")
    _add_set_arg(p)

    # focus
    p = sub.add_parser("focus", help="Set or show the current task directory.")
    p.add_argument("directory", nargs="?", default=None)

    # status
    p = sub.add_parser("status", help="Show current phase and phase completion status.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.add_argument("directory", nargs="?", default=None)

    # viz
    p = sub.add_parser("viz", help="Visualize status and progress with emoji and bars.")
    p.add_argument("directory", nargs="?", default=None)

    # check-gate
    p = sub.add_parser("check-gate", help="Check if gate conditions for a phase are met.")
    p.add_argument("phase_name", metavar="PHASE")
    p.add_argument("directory", nargs="?", default=None)

    # transitions
    sub.add_parser("transitions", help="List all available transitions.")

    # next
    p = sub.add_parser("next", help="Show which transitions can be applied to documents.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.add_argument("directory", nargs="?", default=None)

    # next-task
    p = sub.add_parser("next-task", help="Show the first unchecked task in the current directory.")
    p.add_argument("directory", nargs="?", default=None)

    # check
    p = sub.add_parser("check", help="Check off a task by substring match.")
    p.add_argument("substring", metavar="TEXT")
    p.add_argument("directory", nargs="?", default=None)
    _add_set_arg(p)

    # list
    sub.add_parser("list", help="List directories that contain markdown documents.")

    # audit
    p = sub.add_parser("audit", help="Show merged transition audit log across users.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.add_argument("--days", type=float, default=1.0,
                   help="Show entries from the last N days (default: 1, 0 for all)")

    # install-skills
    sub.add_parser("install-skills", help="Install markstate Claude skill to ~/.claude/skills/.")

    # query
    p = sub.add_parser(
        "query",
        help="Query documents by front matter fields (e.g. status=draft created-at>2024-01-01).",
    )
    p.add_argument(
        "predicates",
        metavar="FIELD=VALUE",
        nargs="+",
        help="One or more predicates: field=value, field!=value, field>value, field<value, field>=value, field<=value",
    )
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.add_argument("--dir", dest="directory", default=None, metavar="DIR",
                   help="Root directory to search (default: docs_root or cwd)")

    return parser


def main() -> None:
    global _focus_override
    config = _try_load_config()
    parser = _build_parser(config)
    args = parser.parse_args()

    if args.focus:
        _focus_override = args.focus
    elif os.environ.get(FOCUS_ENV_VAR):
        _focus_override = os.environ[FOCUS_ENV_VAR]

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "init": _cmd_init,
        "focus": _cmd_focus,
        "set": _cmd_set,
        "new": _cmd_new,
        "do": _cmd_do,
        "status": _cmd_status,
        "viz": _cmd_viz,
        "check-gate": _cmd_check_gate,
        "transitions": _cmd_transitions,
        "next": _cmd_next,
        "next-task": _cmd_next_task,
        "check": _cmd_check,
        "query": _cmd_query,
        "list": _cmd_list,
        "audit": _cmd_audit,
        "install-skills": _cmd_install_skills,
    }
    dispatch[args.command](args)
