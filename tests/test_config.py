"""Tests for flow.yml loading and parsing."""

from pathlib import Path

import pytest

from markstate.config import ProducedDir, find_and_load


def write_flow(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "flow.yml"
    p.write_text(content)
    return p


def test_load_minimal(tmp_path):
    write_flow(tmp_path, "phases: []\ntransitions: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.status_field == "status"
    assert cfg.root == tmp_path
    assert cfg.docs_root == tmp_path
    assert cfg.phases == []
    assert cfg.transitions == []


def test_docs_root_defaults_to_config_dir(tmp_path):
    write_flow(tmp_path, "phases: []\ntransitions: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.docs_root == tmp_path


def test_docs_root_relative(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    write_flow(tmp_path, "docs_root: docs\nphases: []\ntransitions: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.docs_root == docs


def test_docs_root_absolute(tmp_path):
    docs = tmp_path / "elsewhere"
    docs.mkdir()
    write_flow(tmp_path, f"docs_root: {docs}\nphases: []\ntransitions: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.docs_root == docs


def test_find_walks_up(tmp_path):
    write_flow(tmp_path, "phases: []\ntransitions: []\n")
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    cfg = find_and_load(subdir)
    assert cfg.root == tmp_path


def test_find_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_and_load(tmp_path)


def test_redirect_loads_target(tmp_path):
    docs_repo = tmp_path / "docs-repo"
    source_repo = tmp_path / "source-repo"
    docs_repo.mkdir()
    source_repo.mkdir()

    (docs_repo / "flow.yml").write_text(
        "docs_root: changes\nphases: []\ntransitions: []\n"
    )
    (source_repo / "flow.yml").write_text(
        "redirect: ../docs-repo/flow.yml\n"
    )

    cfg = find_and_load(source_repo)
    assert cfg.docs_root == (docs_repo / "changes").resolve()
    assert cfg.phases == []


def test_status_field_custom(tmp_path):
    write_flow(tmp_path, "status_field: state\nphases: []\ntransitions: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.status_field == "state"


def test_parse_phase_with_gates_and_advance_when(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    advance_when:
      - file: spec.md
        status: approved
  - name: done
    gates:
      - file: spec.md
        status: approved
transitions: []
""")
    cfg = find_and_load(tmp_path)
    drafting = cfg.phase("drafting")
    assert drafting is not None
    assert len(drafting.advance_when) == 1
    assert drafting.advance_when[0].file == "spec.md"
    assert drafting.advance_when[0].status == "approved"

    done = cfg.phase("done")
    assert len(done.gates) == 1


def test_parse_glob_condition(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: review
    advance_when:
      - glob: "docs/*.md"
        all_status: reviewed
transitions: []
""")
    cfg = find_and_load(tmp_path)
    cond = cfg.phases[0].advance_when[0]
    assert cond.glob == "docs/*.md"
    assert cond.all_status == "reviewed"


def test_parse_tasks_condition(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: coding
    advance_when:
      - file: tasks.md
        tasks: all_done
transitions: []
""")
    cfg = find_and_load(tmp_path)
    cond = cfg.phases[0].advance_when[0]
    assert cond.file == "tasks.md"
    assert cond.tasks == "all_done"


def test_parse_transitions(tmp_path):
    write_flow(tmp_path, """
phases: []
transitions:
  - name: approve
    from: draft
    to: approved
  - name: reject
    from: draft
    to: rejected
""")
    cfg = find_and_load(tmp_path)
    assert cfg.transition_names() == ["approve", "reject"]
    approve = cfg.transition("approve")
    assert approve.from_state == "draft"
    assert approve.to_state == "approved"


def test_parse_produced_doc_with_template(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    produces:
      - file: spec.md
        template: "---\\nstatus: draft\\n---\\n"
        auto: true
transitions: []
""")
    cfg = find_and_load(tmp_path)
    doc = cfg.phases[0].produces[0]
    assert doc.file == "spec.md"
    assert doc.auto is True
    assert "status: draft" in doc.template


def test_parse_scope(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    scope: changes/
    advance_when:
      - file: proposal.md
        status: accepted
  - name: planning
    scope: plans/
    advance_when:
      - file: plan.md
        status: accepted
  - name: done
transitions: []
""")
    cfg = find_and_load(tmp_path)
    assert cfg.phases[0].scope == "changes/"
    assert cfg.phases[1].scope == "plans/"
    assert cfg.phases[2].scope is None


def test_phases_for_filters_by_scope(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    scope: changes/
  - name: planning
    scope: plans/
  - name: done
transitions: []
""")
    cfg = find_and_load(tmp_path)

    changes_dir = tmp_path / "changes" / "auth" / "add-oauth"
    changes_dir.mkdir(parents=True)
    phases = cfg.phases_for(changes_dir)
    assert [p.name for p in phases] == ["drafting", "done"]

    plans_dir = tmp_path / "plans" / "migrate-db"
    plans_dir.mkdir(parents=True)
    phases = cfg.phases_for(plans_dir)
    assert [p.name for p in phases] == ["planning", "done"]


def test_phases_for_no_scope_matches_all(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
  - name: done
transitions: []
""")
    cfg = find_and_load(tmp_path)
    subdir = tmp_path / "anything"
    subdir.mkdir()
    assert [p.name for p in cfg.phases_for(subdir)] == ["drafting", "done"]


def test_phases_for_outside_docs_root(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    scope: changes/
  - name: done
transitions: []
""")
    cfg = find_and_load(tmp_path)
    # Outside docs_root → all phases returned (no filtering)
    assert [p.name for p in cfg.phases_for(tmp_path.parent)] == ["drafting", "done"]


def test_parse_transition_set_fields(tmp_path):
    write_flow(tmp_path, """
phases: []
transitions:
  - name: accept
    from: draft
    to: accepted
    set:
      accepted-at: now
      accepted-by: me
      once-first-accepted-at: now
""")
    cfg = find_and_load(tmp_path)
    t = cfg.transition("accept")
    assert t.set_fields == {
        "accepted-at": "now",
        "accepted-by": "me",
        "once-first-accepted-at": "now",
    }


def test_parse_transition_unset_fields(tmp_path):
    write_flow(tmp_path, """
phases: []
transitions:
  - name: unblock
    from: blocked
    to: draft
    set:
      unblocked-at: now
    unset:
      - blocked-at
      - blocked-reason
""")
    cfg = find_and_load(tmp_path)
    t = cfg.transition("unblock")
    assert t.set_fields == {"unblocked-at": "now"}
    assert t.unset_fields == ["blocked-at", "blocked-reason"]


def test_parse_transition_require_set(tmp_path):
    write_flow(tmp_path, """
phases: []
transitions:
  - name: block
    from: draft
    to: blocked
    set:
      blocked-at: now
    require_set:
      - blocked-reason
""")
    cfg = find_and_load(tmp_path)
    t = cfg.transition("block")
    assert t.require_set == ["blocked-reason"]


def test_parse_transition_require_set_defaults_empty(tmp_path):
    write_flow(tmp_path, """
phases: []
transitions:
  - name: accept
    from: draft
    to: accepted
""")
    cfg = find_and_load(tmp_path)
    t = cfg.transition("accept")
    assert t.require_set == []


def test_parse_produced_doc_unset_fields(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    produces:
      - file: proposal.md
        template: "---\\nstatus: draft\\nstale: yes\\n---\\n"
        unset:
          - stale
transitions: []
""")
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert entry.unset_fields == ["stale"]


def test_parse_produced_doc_set_fields(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    produces:
      - file: proposal.md
        template: "---\\nstatus: draft\\n---\\n"
        set:
          created-at: now
          author: me
transitions: []
""")
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert entry.set_fields == {"created-at": "now", "author": "me"}


def test_parse_produced_dir_file_set_fields(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: drafting
    produces:
      - dir: changes/<change>
        files:
          - file: proposal.md
            template: "---\\nstatus: draft\\n---\\n"
            set:
              created-at: today
transitions: []
""")
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert entry.files[0].set_fields == {"created-at": "today"}


def test_use_imports_flow_definition(tmp_path):
    """use: loads phases/transitions from another file but keeps local root."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "flow.yml").write_text(
        "phases:\n"
        "  - name: drafting\n"
        "    produces:\n"
        "      - file: spec.md\n"
        "transitions:\n"
        "  - name: approve\n"
        "    from: draft\n"
        "    to: approved\n"
    )

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text(f"use: {shared / 'flow.yml'}\n")

    cfg = find_and_load(project)
    assert cfg.root == project
    assert cfg.docs_root == project
    assert cfg.phase("drafting") is not None
    assert cfg.transition("approve") is not None


def test_use_local_docs_root_overrides(tmp_path):
    """Local docs_root overrides the imported one."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "flow.yml").write_text(
        "docs_root: shared-docs\nphases: []\ntransitions: []\n"
    )

    project = tmp_path / "project"
    specs = project / "specs"
    specs.mkdir(parents=True)
    (project / "flow.yml").write_text(
        f"use: {shared / 'flow.yml'}\ndocs_root: specs\n"
    )

    cfg = find_and_load(project)
    assert cfg.root == project
    assert cfg.docs_root == specs


def test_use_relative_path(tmp_path):
    """use: with a relative path resolves from the importing file's directory."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "flow.yml").write_text("phases: []\ntransitions: []\n")

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text("use: ../shared/flow.yml\n")

    cfg = find_and_load(project)
    assert cfg.root == project
    assert cfg.phases == []


def test_use_tilde_expansion(tmp_path, monkeypatch):
    """use: expands ~ in the path."""
    fake_home = tmp_path / "home"
    skills = fake_home / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "flow.yml").write_text(
        "status_field: state\nphases: []\ntransitions: []\n"
    )
    monkeypatch.setenv("HOME", str(fake_home))

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text("use: ~/.claude/skills/flow.yml\n")

    cfg = find_and_load(project)
    assert cfg.status_field == "state"
    assert cfg.root == project


def test_use_local_status_field_overrides(tmp_path):
    """Local status_field takes precedence over imported one."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "flow.yml").write_text(
        "status_field: phase\nphases: []\ntransitions: []\n"
    )

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text(
        f"use: {shared / 'flow.yml'}\nstatus_field: state\n"
    )

    cfg = find_and_load(project)
    assert cfg.status_field == "state"


def test_parse_produced_dir(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: review
    produces:
      - dir: specs/*
        files:
          - file: functional-spec.md
          - file: technical-spec.md
transitions: []
""")
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert isinstance(entry, ProducedDir)
    assert entry.dir == "specs/*"
    assert [f.file for f in entry.files] == ["functional-spec.md", "technical-spec.md"]
