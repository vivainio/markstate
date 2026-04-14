"""Tests for the state engine."""

import pytest
from pathlib import Path

from markstate.config import (
    Condition,
    FlowConfig,
    Transition,
    Phase,
    ProducedDir,
    ProducedDoc,
)
from markstate import engine


def make_config(tmp_path, phases, transitions=None, docs_root=None):
    return FlowConfig(
        root=tmp_path,
        docs_root=docs_root or tmp_path,
        status_field="status",
        phases=phases,
        transitions=transitions or [],
    )


def write_md(path: Path, status: str = "", body: str = "") -> None:
    if status:
        path.write_text(f"---\nstatus: {status}\n---\n{body}")
    else:
        path.write_text(body)


# --- current_phase ---


def test_current_phase_initial(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("drafting", advance_when=[Condition(file="spec.md", status="approved")]),
        Phase("done", gates=[Condition(file="spec.md", status="approved")]),
    ])
    assert engine.current_phase(cfg, tmp_path).name == "drafting"


def test_current_phase_after_condition_met(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("drafting", advance_when=[Condition(file="spec.md", status="approved")]),
        Phase("done", gates=[Condition(file="spec.md", status="approved")]),
    ])
    write_md(tmp_path / "spec.md", status="approved")
    # Terminal phase has no advance_when → _all_pass([]) = True → complete → None
    assert engine.current_phase(cfg, tmp_path) is None


def test_current_phase_gate_blocks_entry(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("drafting", advance_when=[Condition(file="spec.md", status="approved")]),
        Phase("review", gates=[Condition(file="spec.md", status="approved")]),
    ])
    # No spec.md — gate blocks review, advance_when not met — stays in drafting
    assert engine.current_phase(cfg, tmp_path).name == "drafting"


def test_current_phase_none_when_complete(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("done", gates=[Condition(file="spec.md", status="approved")], advance_when=[]),
    ])
    write_md(tmp_path / "spec.md", status="approved")
    # Only phase: gates pass, advance_when empty (always passes) → complete
    assert engine.current_phase(cfg, tmp_path) is None


# --- current_phase with scope ---


def test_current_phase_scope_filters_phases(tmp_path):
    """A directory under plans/ should only see phases scoped to plans/ (and unscoped)."""
    cfg = make_config(tmp_path, [
        Phase("drafting", scope="changes/",
              advance_when=[Condition(file="proposal.md", status="accepted")]),
        Phase("planning", scope="plans/",
              advance_when=[Condition(file="plan.md", status="accepted")]),
        Phase("done"),
    ])
    plans_dir = tmp_path / "plans" / "migrate-db"
    plans_dir.mkdir(parents=True)
    # plans/migrate-db should be in "planning" phase, not "drafting"
    assert engine.current_phase(cfg, plans_dir).name == "planning"


def test_current_phase_scope_changes_path(tmp_path):
    """A directory under changes/ should only see changes-scoped phases."""
    cfg = make_config(tmp_path, [
        Phase("drafting", scope="changes/",
              advance_when=[Condition(file="proposal.md", status="accepted")]),
        Phase("planning", scope="plans/",
              advance_when=[Condition(file="plan.md", status="accepted")]),
        Phase("done"),
    ])
    changes_dir = tmp_path / "changes" / "auth" / "add-oauth"
    changes_dir.mkdir(parents=True)
    assert engine.current_phase(cfg, changes_dir).name == "drafting"


def test_status_only_shows_scoped_phases(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("drafting", scope="changes/",
              advance_when=[Condition(file="proposal.md", status="accepted")]),
        Phase("planning", scope="plans/",
              advance_when=[Condition(file="plan.md", status="accepted")]),
        Phase("done"),
    ])
    plans_dir = tmp_path / "plans" / "migrate-db"
    plans_dir.mkdir(parents=True)
    s = engine.status(cfg, plans_dir)
    phase_names = [p["name"] for p in s["phases"]]
    assert phase_names == ["planning", "done"]


# --- check_gate ---


def test_check_gate_all_met(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("review", gates=[Condition(file="spec.md", status="approved")]),
    ])
    write_md(tmp_path / "spec.md", status="approved")
    assert engine.check_gate(cfg.phases[0], cfg, tmp_path) == []


def test_check_gate_unmet(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("review", gates=[Condition(file="spec.md", status="approved")]),
    ])
    write_md(tmp_path / "spec.md", status="draft")
    unmet = engine.check_gate(cfg.phases[0], cfg, tmp_path)
    assert len(unmet) == 1
    assert "spec.md" in unmet[0]


# --- do_move ---


def test_do_move_success(tmp_path):
    cfg = make_config(tmp_path, [], transitions=[Transition("approve", "draft", "approved")])
    write_md(tmp_path / "spec.md", status="draft")
    old, new = engine.do_transition("approve", tmp_path / "spec.md", cfg)
    assert old == "draft"
    assert new == "approved"
    from markstate import frontmatter
    assert frontmatter.load(tmp_path / "spec.md").get("status") == "approved"


def test_do_move_wrong_state(tmp_path):
    cfg = make_config(tmp_path, [], transitions=[Transition("approve", "draft", "approved")])
    write_md(tmp_path / "spec.md", status="approved")
    with pytest.raises(engine.TransitionError, match="expected status 'draft'"):
        engine.do_transition("approve", tmp_path / "spec.md", cfg)


def test_do_move_unknown(tmp_path):
    cfg = make_config(tmp_path, [], transitions=[Transition("approve", "draft", "approved")])
    write_md(tmp_path / "spec.md", status="draft")
    with pytest.raises(engine.TransitionError, match="unknown transition"):
        engine.do_transition("nonexistent", tmp_path / "spec.md", cfg)


# --- _evaluate: glob + all_status ---


def test_evaluate_glob_all_status(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("review", advance_when=[Condition(glob="docs/*.md", all_status="reviewed")]),
        Phase("done", gates=[Condition(glob="docs/*.md", all_status="reviewed")]),
    ])
    docs = tmp_path / "docs"
    docs.mkdir()
    write_md(docs / "a.md", status="reviewed")
    write_md(docs / "b.md", status="draft")
    assert engine.current_phase(cfg, tmp_path).name == "review"

    write_md(docs / "b.md", status="reviewed")
    assert engine.current_phase(cfg, tmp_path) is None


def test_evaluate_glob_empty_no_match(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("review", advance_when=[Condition(glob="docs/*.md", all_status="reviewed")]),
    ])
    # No files matching glob — condition fails
    assert engine.current_phase(cfg, tmp_path).name == "review"


# --- _evaluate: tasks conditions ---


def test_evaluate_file_tasks_all_done(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("coding", advance_when=[Condition(file="tasks.md", tasks="all_done")]),
        Phase("done", gates=[Condition(file="tasks.md", tasks="all_done")]),
    ])
    (tmp_path / "tasks.md").write_text("- [x] A\n- [ ] B\n")
    assert engine.current_phase(cfg, tmp_path).name == "coding"

    (tmp_path / "tasks.md").write_text("- [x] A\n- [x] B\n")
    assert engine.current_phase(cfg, tmp_path) is None


def test_evaluate_file_tasks_missing_file(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("coding", advance_when=[Condition(file="tasks.md", tasks="all_done")]),
    ])
    assert engine.current_phase(cfg, tmp_path).name == "coding"


def test_evaluate_file_tasks_empty_file(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("coding", advance_when=[Condition(file="tasks.md", tasks="all_done")]),
    ])
    (tmp_path / "tasks.md").write_text("# No checkboxes\n")
    # total == 0 → condition fails
    assert engine.current_phase(cfg, tmp_path).name == "coding"


def test_evaluate_glob_tasks_all_done(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("coding", advance_when=[Condition(glob="*/tasks.md", tasks="all_done")]),
        Phase("done", gates=[Condition(glob="*/tasks.md", tasks="all_done")]),
    ])
    (tmp_path / "s1").mkdir()
    (tmp_path / "s2").mkdir()
    (tmp_path / "s1" / "tasks.md").write_text("- [x] Done\n")
    (tmp_path / "s2" / "tasks.md").write_text("- [ ] Not done\n")
    assert engine.current_phase(cfg, tmp_path).name == "coding"

    (tmp_path / "s2" / "tasks.md").write_text("- [x] Done\n")
    assert engine.current_phase(cfg, tmp_path) is None


# --- find_dir_template ---


def test_find_dir_template_match(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("review", produces=[
            ProducedDir("specs/*", files=[ProducedDoc("spec.md")])
        ]),
    ])
    spec_dir = tmp_path / "specs" / "01-auth"
    spec_dir.mkdir(parents=True)
    task_dir, entry = engine.find_dir_template(cfg, spec_dir)
    # task_dir is the directory from which `markstate new specs/01-auth` would be run
    assert task_dir == tmp_path
    assert entry.dir == "specs/*"


def test_find_dir_template_outside_docs_root(tmp_path):
    cfg = make_config(tmp_path, [])
    assert engine.find_dir_template(cfg, tmp_path.parent) == (None, None)


def test_find_dir_template_no_match(tmp_path):
    cfg = make_config(tmp_path, [
        Phase("review", produces=[ProducedDir("specs/*", files=[])]),
    ])
    other_dir = tmp_path / "other" / "thing"
    other_dir.mkdir(parents=True)
    assert engine.find_dir_template(cfg, other_dir) == (None, None)


# --- next_task ---


def test_next_task_found(tmp_path):
    cfg = make_config(tmp_path, [])
    (tmp_path / "tasks.md").write_text("- [x] Done\n- [ ] Todo item\n")
    result = engine.next_task(cfg, tmp_path)
    assert result is not None
    assert result["task"] == "Todo item"
    assert "tasks.md" in result["file"]


def test_next_task_none_when_all_done(tmp_path):
    cfg = make_config(tmp_path, [])
    (tmp_path / "tasks.md").write_text("- [x] All done\n")
    assert engine.next_task(cfg, tmp_path) is None


def test_next_task_none_when_no_tasks(tmp_path):
    cfg = make_config(tmp_path, [])
    (tmp_path / "doc.md").write_text("# No checkboxes\n")
    assert engine.next_task(cfg, tmp_path) is None


def test_next_task_searches_subdirs(tmp_path):
    cfg = make_config(tmp_path, [])
    sub = tmp_path / "specs" / "01"
    sub.mkdir(parents=True)
    (sub / "tasks.md").write_text("- [ ] Nested task\n")
    result = engine.next_task(cfg, tmp_path)
    assert result["task"] == "Nested task"


# --- check_task ---


def test_check_task_success(tmp_path):
    cfg = make_config(tmp_path, [])
    (tmp_path / "tasks.md").write_text("- [ ] Implement auth\n- [ ] Write tests\n")
    result = engine.check_task("auth", cfg, tmp_path)
    assert result["task"] == "Implement auth"
    assert result["done"] == 1
    assert result["total"] == 2
    assert "tasks.md" in result["file"]


def test_check_task_writes_file(tmp_path):
    cfg = make_config(tmp_path, [])
    f = tmp_path / "tasks.md"
    f.write_text("- [ ] Do the thing\n")
    engine.check_task("thing", cfg, tmp_path)
    assert "- [x] Do the thing" in f.read_text()


def test_check_task_not_found(tmp_path):
    cfg = make_config(tmp_path, [])
    (tmp_path / "tasks.md").write_text("- [ ] Something\n")
    with pytest.raises(engine.TaskNotFoundError):
        engine.check_task("nonexistent", cfg, tmp_path)


# --- describe_condition ---


def test_describe_condition_file_status():
    c = Condition(file="spec.md", status="approved")
    assert "spec.md" in engine.describe_condition(c)
    assert "approved" in engine.describe_condition(c)


def test_describe_condition_glob_all_status():
    c = Condition(glob="docs/*.md", all_status="reviewed")
    assert "docs/*.md" in engine.describe_condition(c)
    assert "reviewed" in engine.describe_condition(c)


def test_describe_condition_file_tasks():
    c = Condition(file="tasks.md", tasks="all_done")
    assert "tasks.md" in engine.describe_condition(c)
    assert "done" in engine.describe_condition(c)


def test_describe_condition_glob_tasks():
    c = Condition(glob="*/tasks.md", tasks="all_done")
    assert "*/tasks.md" in engine.describe_condition(c)
