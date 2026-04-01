"""CLI entry point for markstate."""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from markstate import engine, frontmatter
from markstate.config import FlowConfig, Phase, ProducedDir, ProducedDoc, find_and_load
from markstate.engine import TaskNotFoundError, TransitionError


FOCUS_FILE = ".markstate-focus"
FOCUS_ENV_VAR = "MARKSTATE_FOCUS"

_PRED_RE = re.compile(r'^([a-zA-Z0-9_-]+)(>=|<=|!=|~=|>|<|=)(.+)$')

_focus_override: str | None = None


def _resolve_magic(value: str) -> str:
    if value == "me":
        try:
            return subprocess.run(
                ["git", "config", "user.name"], capture_output=True, text=True, check=True
            ).stdout.strip()
        except subprocess.CalledProcessError:
            return value
    if value == "now":
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def _parse_set_args(set_args: list[str]) -> dict[str, str]:
    result = {}
    for item in set_args:
        if "=" not in item:
            print(f"error: --set value must be key=value, got '{item}'", file=sys.stderr)
            sys.exit(1)
        key, _, value = item.partition("=")
        result[key] = _resolve_magic(value)
    return result


def _add_set_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--set", metavar="KEY=VALUE", action="append", default=[],
        help="Set extra frontmatter fields ('me' = git user, 'now' = UTC timestamp)",
    )


def _apply_extra_fields(path: Path, fields: dict[str, str]) -> None:
    if not fields:
        return
    doc = frontmatter.load(path)
    for key, value in fields.items():
        doc.set(key, value)
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
        rel = focus_file.read_text().strip()
        return (config.docs_root / rel).resolve()
    return None


def _resolve_file(path_str: str, config: FlowConfig | None) -> Path:
    """Resolve a file path: absolute paths used as-is, relative paths resolved
    against doc base (focus > cwd-if-inside-docs_root) when config is available,
    otherwise against cwd."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    if config:
        base = _resolve_doc_base(config)
        return (base / path_str).resolve()
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
    return Path.cwd()


def _load_config() -> FlowConfig:
    config = _try_load_config()
    if config is None:
        print("error: flow.yml not found", file=sys.stderr)
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
      - dir: specs/*
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


def _cmd_init(args: argparse.Namespace) -> None:
    target = Path(".markstate/flow.yml") if args.hidden else Path("flow.yml")
    if target.exists() and not args.force:
        print(f"error: '{target}' already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.source:
        if args.source.startswith(("http://", "https://")):
            try:
                with urllib.request.urlopen(args.source) as resp:
                    content = resp.read().decode()
            except Exception as e:
                print(f"error: could not fetch '{args.source}': {e}", file=sys.stderr)
                sys.exit(1)
        else:
            source = Path(args.source)
            if not source.exists():
                print(f"error: '{args.source}' not found", file=sys.stderr)
                sys.exit(1)
            content = source.read_text()
        target.write_text(content)
    else:
        target.write_text(TEMPLATE_FLOW)
    print(f"created {target}")
    if args.hidden:
        gitignore = Path(".gitignore")
        entry = ".markstate/\n"
        if gitignore.exists():
            existing = gitignore.read_text()
            if ".markstate/" not in existing:
                gitignore.write_text(existing.rstrip("\n") + "\n" + entry)
                print("updated .gitignore")
        else:
            gitignore.write_text(entry)
            print("created .gitignore")


def _cmd_new(args: argparse.Namespace) -> None:
    config = _load_config()
    cwd = Path.cwd()
    extra = _parse_set_args(args.set)

    _, dir_entry = engine.find_dir_template(config, cwd)

    if dir_entry:
        # Inside a dir template: create a single file within cwd
        produced = next((f for f in dir_entry.files if f.file == args.file), None)
        if produced is None:
            available = [f.file for f in dir_entry.files]
            print(f"error: '{args.file}' is not in this dir template. "
                  f"Available: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        target = cwd / args.file
        _write_doc(produced, target, args.force)
        _apply_extra_fields(target, extra)
    else:
        # Top-level: resolve base from cwd (if inside docs_root) or focus.
        # Both ProducedDoc and ProducedDir use the same base so that instance-level
        # dirs (e.g. specs/* inside a change dir) resolve relative to the active change,
        # while top-level dirs (e.g. changes/* at docs_root) work when cwd == docs_root.
        explicit_base = Path(args.directory).resolve() if args.directory else None
        base = explicit_base or _resolve_doc_base(config)
        file_path = Path(args.file)
        for phase in config.phases:
            for entry in phase.produces:
                if isinstance(entry, ProducedDoc) and entry.file == args.file:
                    target = base / args.file
                    _write_doc(entry, target, args.force)
                    _apply_extra_fields(target, extra)
                    return
                if isinstance(entry, ProducedDir) and file_path.match(entry.dir):
                    dir_target = base / args.file
                    _write_dir(entry, dir_target, args.force)
                    for f in entry.files:
                        _apply_extra_fields(dir_target / f.file, extra)
                    return
        print(f"error: '{args.file}' does not match any produces entry", file=sys.stderr)
        sys.exit(1)


def _write_doc(doc: ProducedDoc, target: Path, force: bool) -> None:
    if doc.template is None:
        print(f"error: '{target.name}' has no template defined", file=sys.stderr)
        sys.exit(1)
    if target.exists() and not force:
        print(f"error: '{target}' already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc.template)
    print(f"created {target.name}")


def _write_dir(entry: ProducedDir, target: Path, force: bool) -> None:
    if target.exists() and not force:
        print(f"error: '{target}' already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    target.mkdir(parents=True, exist_ok=True)
    for f in entry.files:
        _write_doc(f, target / f.file, force)


def _create_auto_docs(phase: Phase, directory: Path) -> None:
    for doc in phase.produces:
        if not isinstance(doc, ProducedDoc) or not doc.auto or doc.template is None:
            continue
        dest = directory / doc.file
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(doc.template)
            print(f"created {dest.relative_to(Path.cwd())}")


def _report_transition(
    phase_before: Phase | None, phase_after: Phase | None, config: FlowConfig, directory: Path
) -> None:
    if phase_after == phase_before:
        return
    print(f"→ entering phase: {phase_after.name if phase_after else '(complete)'}")
    if phase_after and phase_after.advance_when:
        print("  advance when:")
        for cond in phase_after.advance_when:
            print(f"    - {engine.describe_condition(cond)}")

    docs_phase = phase_after or (
        engine.find_entered_phase(config, directory) if phase_before is not None else None
    )
    if docs_phase:
        _create_auto_docs(docs_phase, directory)


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
        old = str(doc.get(status_field) or "")
        doc.set(status_field, args.status)
        for key, value in extra.items():
            doc.set(key, value)
        doc.save()
        print(f"{t}: {old or '(none)'} → {args.status}")


def _cmd_do(args: argparse.Namespace) -> None:
    config = _load_config()
    directory = _resolve_doc_base(config)
    target = _resolve_file(args.target, config)

    phase_before = engine.current_phase(config, directory)

    try:
        old, new = engine.do_transition(args.transition_name, target, config)
        print(f"{args.target}: {old} → {new}")
    except TransitionError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    _apply_extra_fields(target, _parse_set_args(args.set))

    phase_after = engine.current_phase(config, directory)
    _report_transition(phase_before, phase_after, config, directory)


def _find_focus_dir(query: str, docs_root: Path) -> Path:
    """Find a unique directory under docs_root whose name contains query as a substring."""
    matches = [d for d in docs_root.rglob("*") if d.is_dir() and query in d.name]
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
    (config.root / FOCUS_FILE).write_text(str(rel) + "\n")
    print(f"focus: {rel}")


def _cmd_status(args: argparse.Namespace) -> None:
    config = _try_load_config()
    directory = _resolve_directory(args, config)
    status_field = config.status_field if config else "status"

    files = {}
    for path in sorted(directory.rglob("*.md")):
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
        print(f"current phase: {phase or '(complete)'}")
        print()

    for rel, entry in files.items():
        s = entry.get("status", "")
        task_info = f"  {entry['tasks_done']}/{entry['tasks_total']} tasks" if "tasks_total" in entry else ""
        print(f"  {rel:30s}  {s:15s}{task_info}")

    if config:
        print()
        for p in result["phases"]:
            if p["complete"]:
                state = "complete"
            elif p["gates_pass"]:
                state = "in progress"
            else:
                state = "pending"
            print(f"  {p['name']:20s}  {state}")


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
    for t in config.transitions:
        print(f"  {t.name:20s}  {t.from_state} → {t.to_state}")


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
        for item in results:
            if item["missing"]:
                print(f"  {item['file']:30s}  (not created)    → markstate new {item['file']}")
            else:
                transitions = ", ".join(
                    f"{t} (→ {transition_map[t]})" for t in item["transitions"]
                )
                print(f"  {item['file']:30s}  {item['status']:15s}  → {transitions}")


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
        _create_auto_docs(entered, directory)


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
        predicates.append((m.group(1), m.group(2), m.group(3)))

    results: list[tuple[Path, frontmatter.Document]] = []
    for path in sorted(root.rglob("*.md")):
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
    _apply_extra_fields(directory / result["file"], _parse_set_args(args.set))

    phase_after = engine.current_phase(config, directory)
    _report_transition(phase_before, phase_after, config, directory)


def _new_metavar(config: FlowConfig | None) -> str:
    if not config:
        return "FILE"
    cwd = Path.cwd()
    _, dir_entry = engine.find_dir_template(config, cwd)
    if dir_entry:
        missing = [f.file for f in dir_entry.files if not (cwd / f.file).exists()]
        return "[" + "|".join(missing) + "]" if missing else "FILE"
    items = []
    for phase in config.phases:
        for entry in phase.produces:
            if isinstance(entry, ProducedDoc):
                items.append(entry.file)
            elif isinstance(entry, ProducedDir):
                items.append(entry.dir.replace("*", "<name>"))
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
                   help="Copy from an existing flow.yml instead of writing the built-in template.")
    p.add_argument("--hidden", action="store_true",
                   help="Write to .markstate/flow.yml instead of flow.yml.")
    p.add_argument("--force", action="store_true", help="Overwrite existing file")

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
    import os
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
        "check-gate": _cmd_check_gate,
        "transitions": _cmd_transitions,
        "next": _cmd_next,
        "next-task": _cmd_next_task,
        "check": _cmd_check,
        "query": _cmd_query,
    }
    dispatch[args.command](args)
