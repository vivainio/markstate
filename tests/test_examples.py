"""Integration tests that walk through each example flow end-to-end."""

import shutil
import subprocess
import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "markstate", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# sdd example
# ---------------------------------------------------------------------------


def test_sdd_full_workflow(tmp_path):
    shutil.copy(EXAMPLES_DIR / "sdd" / "flow.yml", tmp_path / "flow.yml")

    # create the change directory — proposal.md is auto-populated
    result = run(["new", "changes/PROJ-1.add-feature"], tmp_path)
    assert result.returncode == 0
    change = tmp_path / "changes" / "PROJ-1.add-feature"
    assert (change / "proposal.md").exists()

    # --- drafting phase ---
    result = run(["status"], change)
    assert result.returncode == 0
    assert "drafting" in result.stdout

    # accepting proposal advances to speccing and auto-creates spec.md
    result = run(["do", "accept", "proposal.md"], change)
    assert result.returncode == 0
    assert "accepted" in result.stdout
    assert (change / "spec.md").exists(), "spec.md should be auto-created on entering speccing"

    # --- speccing phase ---
    result = run(["status"], change)
    assert "speccing" in result.stdout

    # gate: trying to skip ahead should still be in speccing
    result = run(["check-gate", "implementing"], change)
    assert result.returncode == 1

    # accepting spec advances to implementing and auto-creates tasks.md
    result = run(["do", "accept", "spec.md"], change)
    assert result.returncode == 0
    assert "accepted" in result.stdout
    assert (change / "tasks.md").exists(), "tasks.md should be auto-created on entering implementing"

    # --- implementing phase ---
    result = run(["status"], change)
    assert "implementing" in result.stdout

    # replace placeholder with real tasks
    (change / "tasks.md").write_text("- [ ] Implement feature\n- [ ] Write tests\n")

    result = run(["check", "Implement feature"], change)
    assert result.returncode == 0
    assert "1/2" in result.stdout

    result = run(["check", "Write tests"], change)
    assert result.returncode == 0
    assert "2/2" in result.stdout
    assert "(complete)" in result.stdout

    # --- done phase ---
    result = run(["status"], change)
    assert "done" in result.stdout


def test_sdd_hook_stamps_and_aborts(tmp_path):
    """flow_hooks.py beside flow.yml runs on transitions."""
    shutil.copy(EXAMPLES_DIR / "sdd" / "flow.yml", tmp_path / "flow.yml")
    shutil.copy(EXAMPLES_DIR / "sdd" / "flow_hooks.py", tmp_path / "flow_hooks.py")

    run(["new", "changes/PROJ-1.add-feature"], tmp_path)
    change = tmp_path / "changes" / "PROJ-1.add-feature"
    proposal = change / "proposal.md"

    # Stamp path: hook adds accepted-via-hook on accept
    result = run(["do", "accept", "proposal.md"], change)
    assert result.returncode == 0
    assert "accepted-via-hook: true" in proposal.read_text()

    # Reopen, then add the veto flag and try to accept again
    run(["do", "reopen", "proposal.md"], change)
    text = proposal.read_text()
    proposal.write_text(text.replace("status: draft", "status: draft\nblock-accept: true"))

    result = run(["do", "accept", "proposal.md"], change)
    assert result.returncode == 1
    assert "block-accept" in result.stderr
    # File must remain at draft — hook aborted before save
    assert "status: draft" in proposal.read_text()


def test_sdd_reopen_blocks_advance(tmp_path):
    """Reopening an accepted proposal should block phase advancement."""
    shutil.copy(EXAMPLES_DIR / "sdd" / "flow.yml", tmp_path / "flow.yml")

    run(["new", "changes/PROJ-1.add-feature"], tmp_path)
    change = tmp_path / "changes" / "PROJ-1.add-feature"
    run(["do", "accept", "proposal.md"], change)

    # reopen drops proposal back to draft
    result = run(["do", "reopen", "proposal.md"], change)
    assert result.returncode == 0
    assert "draft" in result.stdout

    # now gate for speccing should fail
    result = run(["check-gate", "speccing"], change)
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# openspec example
# ---------------------------------------------------------------------------


def test_openspec_full_workflow(tmp_path):
    shutil.copy(EXAMPLES_DIR / "openspec" / "flow.yml", tmp_path / "flow.yml")
    change = tmp_path / "changes" / "add-dark-mode"
    change.mkdir(parents=True)

    # --- speccing phase: create proposal, design, and one delta spec ---
    result = run(["new", "proposal.md"], change)
    assert result.returncode == 0
    assert (change / "proposal.md").exists()

    result = run(["new", "design.md"], change)
    assert result.returncode == 0
    assert (change / "design.md").exists()

    # create a delta spec directory
    result = run(["new", "specs/ui"], change)
    assert result.returncode == 0
    assert (change / "specs" / "ui" / "spec.md").exists()

    result = run(["status"], change)
    assert result.returncode == 0
    assert "speccing" in result.stdout

    # gate for implementing should not be satisfied yet
    result = run(["check-gate", "implementing"], change)
    assert result.returncode == 1

    # accept all three artifacts
    run(["do", "accept", "proposal.md"], change)
    run(["do", "accept", "design.md"], change)
    run(["do", "accept", "specs/ui/spec.md"], change)

    # implementing gate should now pass
    result = run(["check-gate", "implementing"], change)
    assert result.returncode == 0

    # tasks.md should have been auto-created when gate became satisfied
    assert (change / "tasks.md").exists(), "tasks.md should be auto-created on entering implementing"

    # --- implementing phase ---
    result = run(["status"], change)
    assert "implementing" in result.stdout

    (change / "tasks.md").write_text("- [ ] Add dark mode toggle\n- [ ] Update theme tokens\n")

    run(["check", "dark mode toggle"], change)
    result = run(["check", "theme tokens"], change)
    assert result.returncode == 0
    assert "(complete)" in result.stdout

    # --- done phase ---
    result = run(["status"], change)
    assert "done" in result.stdout


def test_openspec_missing_delta_spec_blocks_advance(tmp_path):
    """Unaccepted delta spec keeps current phase as speccing, not implementing."""
    shutil.copy(EXAMPLES_DIR / "openspec" / "flow.yml", tmp_path / "flow.yml")
    change = tmp_path / "changes" / "add-dark-mode"
    change.mkdir(parents=True)

    run(["new", "proposal.md"], change)
    run(["new", "design.md"], change)
    run(["new", "specs/ui"], change)

    # accept proposal and design but NOT the delta spec
    run(["do", "accept", "proposal.md"], change)
    run(["do", "accept", "design.md"], change)

    # speccing advance_when requires all delta specs accepted — phase stays speccing
    result = run(["status"], change)
    assert result.returncode == 0
    assert "speccing" in result.stdout
    assert "implementing" not in result.stdout.split("current phase:")[0]


# ---------------------------------------------------------------------------
# scoped-tracks example
# ---------------------------------------------------------------------------


def test_scoped_tracks_changes_workflow(tmp_path):
    """Changes track follows the full drafting → speccing → implementing → done flow."""
    shutil.copy(EXAMPLES_DIR / "scoped-tracks" / "flow.yml", tmp_path / "flow.yml")

    result = run(["new", "changes/auth/add-oauth"], tmp_path)
    assert result.returncode == 0
    change = tmp_path / "changes" / "auth" / "add-oauth"
    assert (change / "proposal.md").exists()

    # --- drafting ---
    result = run(["status"], change)
    assert "drafting" in result.stdout
    # plans-only phases should not appear
    assert "planning" not in result.stdout

    result = run(["do", "accept", "proposal.md"], change)
    assert result.returncode == 0
    assert (change / "spec.md").exists()

    # --- speccing ---
    result = run(["status"], change)
    assert "speccing" in result.stdout

    result = run(["do", "accept", "spec.md"], change)
    assert result.returncode == 0
    assert (change / "tasks.md").exists()

    # --- implementing ---
    result = run(["status"], change)
    assert "implementing" in result.stdout

    (change / "tasks.md").write_text("- [ ] Do it\n")
    run(["check", "Do it"], change)

    # --- done ---
    result = run(["status"], change)
    assert "changes-done" in result.stdout


def test_scoped_tracks_plans_workflow(tmp_path):
    """Plans track follows the shorter planning → done flow."""
    shutil.copy(EXAMPLES_DIR / "scoped-tracks" / "flow.yml", tmp_path / "flow.yml")

    result = run(["new", "plans/infra/migrate-db"], tmp_path)
    assert result.returncode == 0
    plan = tmp_path / "plans" / "infra" / "migrate-db"
    assert (plan / "plan.md").exists()

    # --- planning ---
    result = run(["status"], plan)
    assert "planning" in result.stdout
    # changes-only phases should not appear
    assert "drafting" not in result.stdout
    assert "speccing" not in result.stdout
    assert "implementing" not in result.stdout

    result = run(["do", "accept", "plan.md"], plan)
    assert result.returncode == 0

    # --- done ---
    result = run(["status"], plan)
    assert "plans-done" in result.stdout


def test_scoped_tracks_independent(tmp_path):
    """Changes and plans don't interfere with each other."""
    shutil.copy(EXAMPLES_DIR / "scoped-tracks" / "flow.yml", tmp_path / "flow.yml")

    run(["new", "changes/auth/add-oauth"], tmp_path)
    run(["new", "plans/infra/migrate-db"], tmp_path)

    change = tmp_path / "changes" / "auth" / "add-oauth"
    plan = tmp_path / "plans" / "infra" / "migrate-db"

    # accepting the plan doesn't affect the change
    run(["do", "accept", "plan.md"], plan)
    result = run(["status"], change)
    assert "drafting" in result.stdout

    # change is still in drafting while plan is done
    result = run(["status"], plan)
    assert "plans-done" in result.stdout


# ---------------------------------------------------------------------------
# use-fallback example
# ---------------------------------------------------------------------------


def test_use_fallback_loads_hook_from_shared(tmp_path):
    """A project flow.yml with `use:` and no local hook picks up the shared one."""
    src = EXAMPLES_DIR / "use-fallback"
    shutil.copytree(src, tmp_path / "use-fallback")
    project = tmp_path / "use-fallback" / "project"

    result = run(["new", "proposal.md"], project)
    assert result.returncode == 0

    result = run(["do", "accept", "proposal.md"], project)
    assert result.returncode == 0
    assert "stamped-by: shared" in (project / "proposal.md").read_text()
