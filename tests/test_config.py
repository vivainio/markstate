"""Tests for flow.yml loading and parsing."""

import pytest
from pathlib import Path

import markstate.config as config_module
from markstate.config import find_and_load


def write_flow(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "flow.yml"
    p.write_text(content)
    return p


def test_load_minimal(tmp_path):
    write_flow(tmp_path, "phases: []\nmoves: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.status_field == "status"
    assert cfg.root == tmp_path
    assert cfg.docs_root == tmp_path
    assert cfg.phases == []
    assert cfg.moves == []


def test_docs_root_defaults_to_config_dir(tmp_path):
    write_flow(tmp_path, "phases: []\nmoves: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.docs_root == tmp_path


def test_docs_root_relative(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    write_flow(tmp_path, "docs_root: docs\nphases: []\nmoves: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.docs_root == docs


def test_docs_root_absolute(tmp_path):
    docs = tmp_path / "elsewhere"
    docs.mkdir()
    write_flow(tmp_path, f"docs_root: {docs}\nphases: []\nmoves: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.docs_root == docs


def test_find_walks_up(tmp_path):
    write_flow(tmp_path, "phases: []\nmoves: []\n")
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    cfg = find_and_load(subdir)
    assert cfg.root == tmp_path


def test_find_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_and_load(tmp_path)


def test_status_field_custom(tmp_path):
    write_flow(tmp_path, "status_field: state\nphases: []\nmoves: []\n")
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
moves: []
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
moves: []
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
moves: []
""")
    cfg = find_and_load(tmp_path)
    cond = cfg.phases[0].advance_when[0]
    assert cond.file == "tasks.md"
    assert cond.tasks == "all_done"


def test_parse_moves(tmp_path):
    write_flow(tmp_path, """
phases: []
moves:
  - name: approve
    from: draft
    to: approved
  - name: reject
    from: draft
    to: rejected
""")
    cfg = find_and_load(tmp_path)
    assert cfg.move_names() == ["approve", "reject"]
    approve = cfg.move("approve")
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
moves: []
""")
    cfg = find_and_load(tmp_path)
    doc = cfg.phases[0].produces[0]
    assert doc.file == "spec.md"
    assert doc.auto is True
    assert "status: draft" in doc.template


def test_parse_produced_dir(tmp_path):
    write_flow(tmp_path, """
phases:
  - name: review
    produces:
      - dir: specs/*
        files:
          - file: functional-spec.md
          - file: technical-spec.md
moves: []
""")
    from markstate.config import ProducedDir
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert isinstance(entry, ProducedDir)
    assert entry.dir == "specs/*"
    assert [f.file for f in entry.files] == ["functional-spec.md", "technical-spec.md"]
