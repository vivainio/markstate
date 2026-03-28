"""CLI entry point for doc-flow."""

import json
import sys
from pathlib import Path

import click

from doc_flow import engine
from doc_flow.config import FlowConfig, find_and_load
from doc_flow.engine import MoveError


def _load_config() -> FlowConfig:
    try:
        return find_and_load()
    except FileNotFoundError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


@click.group()
def main() -> None:
    """Generic document flow processor."""


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.argument("directory", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
def status(as_json: bool, directory: Path) -> None:
    """Show current phase and phase completion status."""
    config = _load_config()
    result = engine.status(config, directory.resolve())
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        phase = result["current_phase"]
        click.echo(f"current phase: {phase or '(complete)'}")
        click.echo()
        for p in result["phases"]:
            gate = "ok" if p["gates_pass"] else "blocked"
            done = "complete" if p["complete"] else "in progress"
            click.echo(f"  {p['name']:20s}  gates={gate}  {done}")


@main.command("check-gate")
@click.argument("phase_name")
@click.argument("directory", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
def check_gate(phase_name: str, directory: Path) -> None:
    """Check if all gate conditions for a phase are met."""
    config = _load_config()
    phase = config.phase(phase_name)
    if phase is None:
        click.echo(f"error: unknown phase '{phase_name}'", err=True)
        sys.exit(1)

    unmet = engine.check_gate(phase, config, directory.resolve())
    if unmet:
        click.echo("gate not satisfied:")
        for condition in unmet:
            click.echo(f"  - {condition}")
        sys.exit(1)
    else:
        click.echo("gate satisfied")


class MoveName(click.ParamType):
    """Dynamic choice type that loads move names from flow.yml."""

    name = "move"

    def convert(self, value: str, param: click.Parameter | None, ctx: click.Context | None) -> str:
        try:
            config = find_and_load()
            names = config.move_names()
            if value not in names:
                self.fail(f"'{value}' is not a valid move. Choose from: {', '.join(names)}", param, ctx)
        except FileNotFoundError:
            pass  # let the command handle the missing config
        return value

    def shell_complete(self, ctx: click.Context, param: click.Parameter, incomplete: str):
        from click.shell_completion import CompletionItem

        try:
            config = find_and_load()
            return [CompletionItem(name) for name in config.move_names() if name.startswith(incomplete)]
        except FileNotFoundError:
            return []


@main.command("do")
@click.argument("move_name", type=MoveName())
@click.argument("target", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def do_move(move_name: str, target: Path) -> None:
    """Apply a named move to a document."""
    config = _load_config()
    try:
        old, new = engine.do_move(move_name, target.resolve(), config)
        click.echo(f"{target}: {old} → {new}")
    except MoveError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


@main.command("moves")
def list_moves() -> None:
    """List all available moves."""
    config = _load_config()
    for move in config.moves:
        click.echo(f"  {move.name:20s}  {move.from_state} → {move.to_state}")
