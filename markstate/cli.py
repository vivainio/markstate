"""CLI entry point for markstate."""

import argparse
import json
import sys
from importlib.metadata import version
from pathlib import Path

from markstate import engine, frontmatter
from markstate.config import FlowConfig, ProducedDir, ProducedDoc, find_and_load
from markstate.engine import MoveError


FOCUS_FILE = ".markstate-focus"


def _try_load_config() -> FlowConfig | None:
    try:
        return find_and_load()
    except FileNotFoundError:
        return None


def _read_focus(config: FlowConfig) -> Path | None:
    focus_file = config.root / FOCUS_FILE
    if focus_file.exists():
        rel = focus_file.read_text().strip()
        return (config.docs_root / rel).resolve()
    return None


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

moves:
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
    target = Path("flow.yml")
    if target.exists() and not args.force:
        print("error: flow.yml already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    target.write_text(TEMPLATE_FLOW)
    print(f"created {target}")


def _cmd_new(args: argparse.Namespace) -> None:
    config = _load_config()
    cwd = Path.cwd()

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
    else:
        # Top-level: find a matching ProducedDoc or ProducedDir
        file_path = Path(args.file)
        for phase in config.phases:
            for entry in phase.produces:
                if isinstance(entry, ProducedDoc) and entry.file == args.file:
                    target = Path(args.directory).resolve() / args.file
                    _write_doc(entry, target, args.force)
                    return
                if isinstance(entry, ProducedDir) and file_path.match(entry.dir):
                    _write_dir(entry, Path(args.directory).resolve() / args.file, args.force)
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


def _cmd_set(args: argparse.Namespace) -> None:
    config = _try_load_config()
    status_field = config.status_field if config else "status"
    for t in args.targets:
        target = Path(t).resolve()
        if not target.exists():
            print(f"error: '{t}' does not exist", file=sys.stderr)
            sys.exit(1)
        doc = frontmatter.load(target)
        old = str(doc.get(status_field) or "")
        doc.set(status_field, args.status)
        doc.save()
        print(f"{t}: {old or '(none)'} → {args.status}")


def _cmd_do(args: argparse.Namespace) -> None:
    config = _load_config()
    target = Path(args.target).resolve()
    directory = target.parent

    phase_before = engine.current_phase(config, directory)

    try:
        old, new = engine.do_move(args.move_name, target, config)
        print(f"{args.target}: {old} → {new}")
    except MoveError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    phase_after = engine.current_phase(config, directory)

    if phase_after != phase_before:
        print(f"→ entering phase: {phase_after.name if phase_after else '(complete)'}")
        if phase_after and phase_after.advance_when:
            print("  advance when:")
            for cond in phase_after.advance_when:
                print(f"    - {engine.describe_condition(cond)}")

    if phase_after is None:
        return
    for doc in phase_after.produces:
        if not isinstance(doc, ProducedDoc) or not doc.auto or doc.template is None:
            continue
        dest = directory / doc.file
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(doc.template)
            print(f"created {dest.relative_to(Path.cwd())}")


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
        if s:
            files[str(path.relative_to(directory))] = s

    if args.as_json:
        result = engine.status(config, directory) if config else {}
        print(json.dumps({**result, "files": files}, indent=2))
        return

    if config:
        result = engine.status(config, directory)
        phase = result["current_phase"]
        print(f"current phase: {phase or '(complete)'}")
        print()

    for rel, s in files.items():
        print(f"  {rel:30s}  {s}")

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


def _cmd_moves(args: argparse.Namespace) -> None:
    config = _load_config()
    for move in config.moves:
        print(f"  {move.name:20s}  {move.from_state} → {move.to_state}")


def _cmd_next(args: argparse.Namespace) -> None:
    config = _load_config()
    results = engine.next_moves(config, _resolve_directory(args, config))
    if args.as_json:
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("nothing to do")
            return
        move_map = {m.name: m.to_state for m in config.moves}
        for item in results:
            if item["missing"]:
                print(f"  {item['file']:30s}  (not created)    → markstate new {item['file']}")
            else:
                moves = ", ".join(
                    f"{m} (→ {move_map[m]})" for m in item["moves"]
                )
                print(f"  {item['file']:30s}  {item['status']:15s}  → {moves}")


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
    move_names = config.move_names() if config else []

    parser = argparse.ArgumentParser(
        prog="markstate",
        description="Generic document flow processor.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('markstate')}"
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # init
    p = sub.add_parser("init", help="Create a template flow.yml in the current directory.")
    p.add_argument("--force", action="store_true", help="Overwrite existing flow.yml")

    # new
    p = sub.add_parser("new", help="Create a document from its template defined in flow.yml.")
    p.add_argument("file", metavar=_new_metavar(config))
    p.add_argument("directory", nargs="?", default=None)
    p.add_argument("--force", action="store_true", help="Overwrite existing file")

    # set
    p = sub.add_parser("set", help="Set the status of one or more documents directly.")
    p.add_argument("status", metavar="STATUS")
    p.add_argument("targets", metavar="FILE", nargs="+")

    # do
    move_metavar = "[" + "|".join(move_names) + "]" if move_names else "MOVE"
    p = sub.add_parser("do", help="Apply a named move to a document.")
    p.add_argument("move_name", metavar=move_metavar)
    p.add_argument("target", metavar="FILE")

    # status
    # focus
    p = sub.add_parser("focus", help="Set or show the current task directory.")
    p.add_argument("directory", nargs="?", default=None)

    p = sub.add_parser("status", help="Show current phase and phase completion status.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.add_argument("directory", nargs="?", default=None)

    # check-gate
    p = sub.add_parser("check-gate", help="Check if gate conditions for a phase are met.")
    p.add_argument("phase_name", metavar="PHASE")
    p.add_argument("directory", nargs="?", default=None)

    # moves
    sub.add_parser("moves", help="List all available moves.")

    # next
    p = sub.add_parser("next", help="Show which moves can be applied to documents.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.add_argument("directory", nargs="?", default=None)

    return parser


def main() -> None:
    config = _try_load_config()
    parser = _build_parser(config)
    args = parser.parse_args()

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
        "moves": _cmd_moves,
        "next": _cmd_next,
    }
    dispatch[args.command](args)
