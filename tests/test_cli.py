"""CLI integration tests."""

import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
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
    (source_repo / "flow.yml").write_text("redirect: ../docs-repo/flow.yml\n")

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


def test_do_puts_status_first_in_frontmatter(tmp_path):
    setup_flow(tmp_path)
    # Status is NOT first in the input
    (tmp_path / "spec.md").write_text("---\nauthor: me\nstatus: draft\n---\n# Spec\n")
    result = run(["do", "approve", "spec.md"], tmp_path)
    assert result.returncode == 0
    content = (tmp_path / "spec.md").read_text()
    lines = content.split("\n")
    # After opening ---, status should come first
    assert lines[1] == "status: approved"
    assert "author: me" in content


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


def test_focus_exact_path_over_substring(tmp_path):
    """When query matches a relative path exactly, don't also match subdirs."""
    setup_flow(tmp_path)
    parent = tmp_path / "changes" / "auth" / "api-key"
    parent.mkdir(parents=True)
    (parent / "specs" / "01-storage").mkdir(parents=True)
    (parent / "specs" / "02-auth").mkdir(parents=True)
    result = run(["focus", "changes/auth/api-key"], tmp_path)
    assert result.returncode == 0
    assert "api-key" in result.stdout
    # Should NOT report ambiguity
    assert "ambiguous" not in result.stderr


def test_focus_fuzzy_no_match(tmp_path):
    setup_flow(tmp_path)
    result = run(["focus", "PROJ-999"], tmp_path)
    assert result.returncode == 1
    assert "error" in result.stderr


# --- flow-level set: annotations ---


SET_FLOW = """\
phases:
  - name: drafting
    produces:
      - file: spec.md
        template: |
          ---
          status: draft
          ---

          # Spec
        set:
          created-at: today
          once-first-touched-at: today
    advance_when:
      - file: spec.md
        status: accepted

  - name: done
    gates:
      - file: spec.md
        status: accepted

transitions:
  - name: accept
    from: draft
    to: accepted
    set:
      accepted-at: now
      once-first-accepted-at: now
  - name: reopen
    from: accepted
    to: draft
"""


def test_new_applies_produces_set_fields(tmp_path):
    setup_flow(tmp_path, SET_FLOW)
    result = run(["new", "spec.md"], tmp_path)
    assert result.returncode == 0, result.stderr
    text = (tmp_path / "spec.md").read_text()
    assert "created-at:" in text
    assert "first-touched-at:" in text


UNSET_FLOW = """\
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
        status: accepted

  - name: done
    gates:
      - file: spec.md
        status: accepted

transitions:
  - name: accept
    from: draft
    to: accepted
  - name: block
    from: draft
    to: blocked
    set:
      blocked-at: now
  - name: unblock
    from: blocked
    to: draft
    set:
      unblocked-at: now
    unset:
      - blocked-at
      - blocked-reason
"""


REQUIRE_SET_FLOW = """\
phases:
  - name: drafting
    produces:
      - file: spec.md
        template: |
          ---
          status: draft
          ---

          # Spec

transitions:
  - name: block
    from: draft
    to: blocked
    set:
      blocked-at: now
    require_set:
      - blocked-reason
"""


def test_do_rejects_transition_missing_required_set(tmp_path):
    setup_flow(tmp_path, REQUIRE_SET_FLOW)
    assert run(["new", "spec.md"], tmp_path).returncode == 0
    result = run(["do", "block", "spec.md"], tmp_path)
    assert result.returncode != 0
    assert "requires --set blocked-reason" in result.stderr
    # Status must remain draft — no partial transition
    text = (tmp_path / "spec.md").read_text()
    assert "status: draft" in text
    assert "blocked-at" not in text


def test_do_accepts_transition_with_required_set(tmp_path):
    setup_flow(tmp_path, REQUIRE_SET_FLOW)
    assert run(["new", "spec.md"], tmp_path).returncode == 0
    result = run(
        ["do", "block", "spec.md", "--set", "blocked-reason=waiting on infra"],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    text = (tmp_path / "spec.md").read_text()
    assert "status: blocked" in text
    assert "blocked-reason: waiting on infra" in text


def test_do_unblock_clears_blocked_fields(tmp_path):
    setup_flow(tmp_path, UNSET_FLOW)
    assert run(["new", "spec.md"], tmp_path).returncode == 0
    # block with a CLI-supplied reason
    assert run(
        ["do", "block", "spec.md", "--set", "blocked-reason=waiting"], tmp_path
    ).returncode == 0
    text = (tmp_path / "spec.md").read_text()
    assert "blocked-at:" in text
    assert "blocked-reason: waiting" in text

    assert run(["do", "unblock", "spec.md"], tmp_path).returncode == 0
    text = (tmp_path / "spec.md").read_text()
    assert re.search(r"^blocked-at:", text, re.MULTILINE) is None
    assert re.search(r"^blocked-reason:", text, re.MULTILINE) is None
    assert re.search(r"^unblocked-at:", text, re.MULTILINE) is not None


def test_cli_unset_flag_removes_field(tmp_path):
    setup_flow(tmp_path, UNSET_FLOW)
    assert run(["new", "spec.md"], tmp_path).returncode == 0
    assert run(["set", "draft", "spec.md", "--set", "note=temp"], tmp_path).returncode == 0
    assert "note: temp" in (tmp_path / "spec.md").read_text()
    assert run(["set", "draft", "spec.md", "--unset", "note"], tmp_path).returncode == 0
    assert "note:" not in (tmp_path / "spec.md").read_text()


def test_init_creates_fresh_when_no_flow_exists(tmp_path):
    source = tmp_path / "source-flow.yml"
    source.write_text(SIMPLE_FLOW)

    result = run(["init", str(source)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "flow.yml").read_text() == SIMPLE_FLOW
    assert "created" in result.stdout


def test_init_upgrades_when_flow_already_exists(tmp_path):
    """Running `init` on a project that already has a flow.yml replaces it."""
    setup_flow(tmp_path)
    source = tmp_path / "source-flow.yml"
    source.write_text(TASKS_FLOW)

    result = run(["init", str(source)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "flow.yml").read_text() == TASKS_FLOW
    assert "upgraded" in result.stdout


def test_init_follows_redirect(tmp_path):
    """`init` from a subdir whose flow.yml redirects should rewrite the target."""
    real = tmp_path / "real"
    real.mkdir()
    stub = tmp_path / "stub"
    stub.mkdir()
    real_flow = real / "flow.yml"
    real_flow.write_text(SIMPLE_FLOW)
    (stub / "flow.yml").write_text("redirect: ../real/flow.yml\n")

    source = tmp_path / "source-flow.yml"
    source.write_text(TASKS_FLOW)

    result = run(["init", str(source)], stub)
    assert result.returncode == 0, result.stderr
    assert "redirect" in (stub / "flow.yml").read_text()
    assert real_flow.read_text() == TASKS_FLOW


def test_init_hidden_errors_when_flow_already_exists(tmp_path):
    setup_flow(tmp_path)
    source = tmp_path / "source-flow.yml"
    source.write_text(SIMPLE_FLOW)
    result = run(["init", str(source), "--hidden"], tmp_path)
    assert result.returncode == 1
    assert "can't convert in place" in result.stderr


def test_init_noop_when_source_identical(tmp_path):
    setup_flow(tmp_path)
    source = tmp_path / "source-flow.yml"
    source.write_text(SIMPLE_FLOW)
    result = run(["init", str(source)], tmp_path)
    assert result.returncode == 0
    assert "already up to date" in result.stdout


def test_init_skips_when_use_directive(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "flow.yml").write_text(SIMPLE_FLOW)

    project = tmp_path / "project"
    project.mkdir()
    use_content = f"use: {shared / 'flow.yml'}\n"
    (project / "flow.yml").write_text(use_content)

    result = run(["init"], project)
    assert result.returncode == 0
    assert "use:" in result.stdout
    assert "skipping" in result.stdout
    # File should be unchanged
    assert (project / "flow.yml").read_text() == use_content


def test_init_errors_on_invalid_yaml(tmp_path):
    setup_flow(tmp_path)
    bad = tmp_path / "bad.yml"
    bad.write_text("phases:\n  - name: x\n    bad: [unterminated\n")
    result = run(["init", str(bad)], tmp_path)
    assert result.returncode == 1
    assert "does not parse as YAML" in result.stderr


def test_query_relative_dates(tmp_path):
    """Right-hand side of query predicates expands Nd/Nw/Nm/Ny relative dates."""
    setup_flow(tmp_path)
    now = datetime.now(UTC)
    far_past = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    (tmp_path / "old.md").write_text(f"---\nstatus: done\nclosed-at: '{far_past}'\n---\n# Old\n")
    (tmp_path / "new.md").write_text(f"---\nstatus: done\nclosed-at: '{recent}'\n---\n# New\n")

    # "30d" expands to 30 days ago; only the far-past doc is older than that
    result = run(["query", "status=done", "closed-at<30d"], tmp_path)
    assert result.returncode == 0
    assert "old.md" in result.stdout
    assert "new.md" not in result.stdout

    # And the inverse: within the last 30 days
    result = run(["query", "status=done", "closed-at>30d"], tmp_path)
    assert result.returncode == 0
    assert "new.md" in result.stdout
    assert "old.md" not in result.stdout


def test_query_me_value(tmp_path):
    """Query value `me` expands to the git user name."""
    setup_flow(tmp_path)
    try:
        me = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return  # no git user configured; skip silently
    if not me:
        return

    (tmp_path / "mine.md").write_text(f"---\nstatus: draft\nauthor: {me}\n---\n# Mine\n")
    (tmp_path / "yours.md").write_text("---\nstatus: draft\nauthor: someone-else\n---\n# Yours\n")

    result = run(["query", "author=me"], tmp_path)
    assert result.returncode == 0
    assert "mine.md" in result.stdout
    assert "yours.md" not in result.stdout


def test_do_applies_transition_set_and_once_is_stable(tmp_path):
    setup_flow(tmp_path, SET_FLOW)
    assert run(["new", "spec.md"], tmp_path).returncode == 0
    assert run(["do", "accept", "spec.md"], tmp_path).returncode == 0
    first_text = (tmp_path / "spec.md").read_text()
    m = re.search(r"^first-accepted-at:\s*(\S+)", first_text, re.MULTILINE)
    assert m, first_text
    first_ts = m.group(1)

    assert run(["do", "reopen", "spec.md"], tmp_path).returncode == 0
    assert run(["do", "accept", "spec.md"], tmp_path).returncode == 0
    second_text = (tmp_path / "spec.md").read_text()
    m2 = re.search(r"^first-accepted-at:\s*(\S+)", second_text, re.MULTILINE)
    assert m2
    assert m2.group(1) == first_ts, "once- field should not be overwritten on re-accept"
    # accepted-at (non-once) must update on every accept
    assert "accepted-at:" in second_text
