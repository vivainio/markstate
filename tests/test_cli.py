"""CLI integration tests."""

import json
import subprocess
import sys
from pathlib import Path


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "markstate", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


SIMPLE_FLOW = """\
phases:
  - name: drafting
    produces:
      - file: spec.md
        template: |
          ---
          status: draft
          ---

          # Spec
    advance_when:
      - file: spec.md
        status: approved

  - name: done
    gates:
      - file: spec.md
        status: approved

transitions:
  - name: approve
    from: draft
    to: approved
"""

TASKS_FLOW = """\
phases:
  - name: coding
    produces:
      - file: tasks.md
        template: |
          ---
          status: draft
          ---

          - [ ] Task one
          - [ ] Task two
    advance_when:
      - file: tasks.md
        tasks: all_done

  - name: done
    gates:
      - file: tasks.md
        tasks: all_done
    produces:
      - file: summary.md
        template: "# Summary\\n"
        auto: true

transitions: []
"""


def setup_flow(tmp_path: Path, content: str = SIMPLE_FLOW) -> None:
    (tmp_path / "flow.yml").write_text(content)


# --- status ---


def test_status_no_config(tmp_path):
    result = run(["status"], tmp_path)
    assert result.returncode == 0


def test_status_shows_files(tmp_path):
    setup_flow(tmp_path)
    (tmp_path / "spec.md").write_text("---\nstatus: draft\n---\n# Spec\n")
    result = run(["status"], tmp_path)
    assert result.returncode == 0
    assert "spec.md" in result.stdout
    assert "draft" in result.stdout


def test_status_json(tmp_path):
    setup_flow(tmp_path)
    (tmp_path / "spec.md").write_text("---\nstatus: draft\n---\n# Spec\n")
    result = run(["status", "--json"], tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "files" in data
    assert "spec.md" in data["files"]


def test_status_shows_task_counts(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text(
        "---\nstatus: draft\n---\n- [x] Done\n- [ ] Todo\n"
    )
    result = run(["status"], tmp_path)
    assert "1/2" in result.stdout


def test_status_shows_docs_root_when_redirect(tmp_path):
    docs_repo = tmp_path / "docs-repo"
    source_repo = tmp_path / "source-repo"
    docs_repo.mkdir()
    source_repo.mkdir()

    (docs_repo / "flow.yml").write_text(SIMPLE_FLOW)
    (source_repo / "flow.yml").write_text(f"redirect: ../docs-repo/flow.yml\n")

    result = run(["status"], source_repo)
    assert result.returncode == 0
    assert str(docs_repo) in result.stdout


def test_status_no_docs_root_header_when_local(tmp_path):
    setup_flow(tmp_path)
    result = run(["status"], tmp_path)
    assert "docs_root:" not in result.stdout


# --- do ---


def test_do_applies_move(tmp_path):
    setup_flow(tmp_path)
    (tmp_path / "spec.md").write_text("---\nstatus: draft\n---\n# Spec\n")
    result = run(["do", "approve", "spec.md"], tmp_path)
    assert result.returncode == 0
    assert "draft" in result.stdout
    assert "approved" in result.stdout


def test_do_reports_phase_transition(tmp_path):
    setup_flow(tmp_path)
    (tmp_path / "spec.md").write_text("---\nstatus: draft\n---\n# Spec\n")
    result = run(["do", "approve", "spec.md"], tmp_path)
    assert "(complete)" in result.stdout


def test_do_wrong_state(tmp_path):
    setup_flow(tmp_path)
    (tmp_path / "spec.md").write_text("---\nstatus: approved\n---\n# Spec\n")
    result = run(["do", "approve", "spec.md"], tmp_path)
    assert result.returncode == 1
    assert "error" in result.stderr


# --- next-task ---


def test_next_task_found(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [x] Done\n- [ ] Write tests\n")
    result = run(["next-task"], tmp_path)
    assert result.returncode == 0
    assert "Write tests" in result.stdout


def test_next_task_all_done_reports(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [x] Task one\n- [x] Task two\n")
    result = run(["next-task"], tmp_path)
    assert result.returncode == 0
    assert "all tasks done" in result.stdout


def test_next_task_reports_complete(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [x] Task one\n- [x] Task two\n")
    result = run(["next-task"], tmp_path)
    assert "all tasks done" in result.stdout
    assert "(complete)" in result.stdout


def test_next_task_auto_creates_doc(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [x] Task one\n- [x] Task two\n")
    run(["next-task"], tmp_path)
    assert (tmp_path / "summary.md").exists(), "auto doc should be created for terminal phase"


# --- check ---


def test_check_marks_task_done(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [ ] Task one\n- [ ] Task two\n")
    result = run(["check", "Task one"], tmp_path)
    assert result.returncode == 0
    assert "[x]" in result.stdout
    assert "Task one" in result.stdout
    assert "- [x] Task one" in (tmp_path / "tasks.md").read_text()


def test_check_reports_progress(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [ ] Task one\n- [ ] Task two\n")
    result = run(["check", "Task one"], tmp_path)
    assert "1/2" in result.stdout


def test_check_triggers_phase_transition(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [x] Task one\n- [ ] Task two\n")
    result = run(["check", "Task two"], tmp_path)
    assert "(complete)" in result.stdout


def test_check_not_found(tmp_path):
    setup_flow(tmp_path, TASKS_FLOW)
    (tmp_path / "tasks.md").write_text("- [ ] Task one\n")
    result = run(["check", "nonexistent"], tmp_path)
    assert result.returncode == 1
    assert "error" in result.stderr


# --- focus fuzzy search ---


def test_focus_exact_dir(tmp_path):
    setup_flow(tmp_path)
    task_dir = tmp_path / "tasks" / "PROJ-123.add-auth"
    task_dir.mkdir(parents=True)
    result = run(["focus", str(task_dir)], tmp_path)
    assert result.returncode == 0
    assert "PROJ-123" in result.stdout


def test_focus_fuzzy_match(tmp_path):
    setup_flow(tmp_path)
    task_dir = tmp_path / "tasks" / "PROJ-123.add-auth"
    task_dir.mkdir(parents=True)
    result = run(["focus", "PROJ-123"], tmp_path)
    assert result.returncode == 0
    assert "PROJ-123" in result.stdout


def test_focus_fuzzy_ambiguous(tmp_path):
    setup_flow(tmp_path)
    (tmp_path / "tasks" / "PROJ-123.add-auth").mkdir(parents=True)
    (tmp_path / "tasks" / "PROJ-123.add-login").mkdir(parents=True)
    result = run(["focus", "PROJ-123"], tmp_path)
    assert result.returncode == 1
    assert "ambiguous" in result.stderr


def test_focus_fuzzy_no_match(tmp_path):
    setup_flow(tmp_path)
    result = run(["focus", "PROJ-999"], tmp_path)
    assert result.returncode == 1
    assert "error" in result.stderr
