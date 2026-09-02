"""Tests for flow.yml loading and parsing."""

import subprocess
from pathlib import Path

import pytest

from markstate.config import (
    FlowConfigError,
    ProducedDir,
    ProducedDoc,
    find_and_load,
    find_flow_target,
)


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


def test_select_uses_declared_default_recursively(tmp_path):
    write_flow(
        tmp_path,
        """
$variables:
  track:
    values: [standard, quick]
    default: standard
docs_root:
  $select: track
  cases:
    standard: docs
    quick: notes
phases:
  - name:
      $select: track
      cases:
        standard: drafting
        quick: doing
transitions: []
""",
    )

    cfg = find_and_load(tmp_path)

    assert cfg.docs_root == tmp_path / "docs"
    assert cfg.phases[0].name == "drafting"


def test_variable_override_selects_values(tmp_path):
    write_flow(
        tmp_path,
        """
$variables:
  track:
    values: [standard, quick]
    default: standard
docs_root:
  $select: track
  cases:
    standard: docs
    quick: notes
phases: []
transitions: []
""",
    )

    cfg = find_and_load(tmp_path, variables={"track": "quick"})

    assert cfg.docs_root == tmp_path / "notes"


def test_select_can_choose_use_target(tmp_path):
    (tmp_path / "standard.yml").write_text(
        "status_field: standard_status\nphases: []\ntransitions: []\n"
    )
    (tmp_path / "quick.yml").write_text("status_field: quick_status\nphases: []\ntransitions: []\n")
    write_flow(
        tmp_path,
        """
$variables:
  track:
    values: [standard, quick]
    default: standard
use:
  $select: track
  cases:
    standard: standard.yml
    quick: quick.yml
""",
    )

    cfg = find_and_load(tmp_path, variables={"track": "quick"})

    assert cfg.status_field == "quick_status"


def test_select_can_choose_redirect_target(tmp_path):
    (tmp_path / "standard.yml").write_text("phases: []\ntransitions: []\n")
    (tmp_path / "quick.yml").write_text("phases: []\ntransitions: []\n")
    flow = write_flow(
        tmp_path,
        """
$variables:
  track:
    values: [standard, quick]
    default: standard
redirect:
  $select: track
  cases:
    standard: standard.yml
    quick: quick.yml
""",
    )

    target = find_flow_target(flow.parent, variables={"track": "quick"})

    assert target == tmp_path / "quick.yml"


def test_select_rejects_invalid_variable_value(tmp_path):
    write_flow(
        tmp_path,
        """
$variables:
  track:
    values: [standard, quick]
    default: standard
phases: []
transitions: []
""",
    )

    with pytest.raises(FlowConfigError, match="invalid value 'quik'"):
        find_and_load(tmp_path, variables={"track": "quik"})


def test_unknown_variable_lists_known_names_and_suggestion(tmp_path):
    write_flow(
        tmp_path,
        """
$variables:
  track:
    default: standard
  platform:
    default: cloud
phases: []
transitions: []
""",
    )

    with pytest.raises(FlowConfigError) as error:
        find_and_load(tmp_path, variables={"trak": "quick"})

    assert "unknown variable 'trak'" in str(error.value)
    assert "did you mean 'track'?" in str(error.value)
    assert "known variables: platform, track" in str(error.value)


def test_variable_declared_in_redirect_target_is_known(tmp_path):
    target = tmp_path / "target.yml"
    target.write_text("""
$variables:
  platform:
    values: [cloud, local]
    default: local
phases: []
transitions: []
""")
    write_flow(tmp_path, "redirect: target.yml\n")

    cfg = find_and_load(tmp_path, variables={"platform": "cloud"})

    assert cfg.phases == []


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


def test_redirect_resolves_via_main_worktree_anchor(tmp_path):
    """In a linked git worktree, `../` in redirect/use must anchor at the
    main working tree, not the worktrees container."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": __import__("os").environ["PATH"],
        },
    )

    # Sibling of the main project (NOT sibling of the worktrees container)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "flow.yml").write_text("docs_root: changes\nphases: []\ntransitions: []\n")

    (project / "flow.yml").write_text("redirect: ../shared/flow.yml\n")
    project_use = tmp_path / "project_use"
    project_use.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(project_use)], check=True)
    subprocess.run(
        ["git", "-C", str(project_use), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": __import__("os").environ["PATH"],
        },
    )
    (project_use / "flow.yml").write_text("use: ../shared/flow.yml\n")

    # Create a linked worktree under project/.worktrees/feat
    wt = project / ".worktrees" / "feat"
    subprocess.run(
        ["git", "-C", str(project), "worktree", "add", "-q", str(wt), "-b", "feat"],
        check=True,
    )
    # The worktree has the same untracked flow.yml, copied onto disk.
    (wt / "flow.yml").write_text("redirect: ../shared/flow.yml\n")

    # Without the fix, this would resolve to tmp_path/project/.worktrees/shared/flow.yml
    cfg = find_and_load(wt)
    assert cfg.docs_root == (shared / "changes").resolve()
    target = find_flow_target(wt)
    assert target.resolve() == (shared / "flow.yml").resolve()


def test_redirect_prefers_naive_resolution_in_worktree(tmp_path):
    """If the naive ``../`` target exists relative to the worktree, use it --
    don't silently retarget to the main checkout."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": __import__("os").environ["PATH"],
    }
    subprocess.run(
        ["git", "-C", str(project), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        env=env,
    )

    # Sibling of the MAIN checkout (would be picked up by the git anchor)
    main_sibling = tmp_path / "shared"
    main_sibling.mkdir()
    (main_sibling / "flow.yml").write_text("docs_root: from_main\nphases: []\ntransitions: []\n")

    # Worktree at project/.worktrees/feat -- and a sibling of *that* called shared
    wt = project / ".worktrees" / "feat"
    subprocess.run(
        ["git", "-C", str(project), "worktree", "add", "-q", str(wt), "-b", "feat"],
        check=True,
    )
    wt_sibling = project / ".worktrees" / "shared"
    wt_sibling.mkdir()
    (wt_sibling / "flow.yml").write_text("docs_root: from_worktree\nphases: []\ntransitions: []\n")
    (wt / "flow.yml").write_text("redirect: ../shared/flow.yml\n")

    # Naive resolution finds wt_sibling first, so that wins.
    cfg = find_and_load(wt)
    assert cfg.docs_root == (wt_sibling / "from_worktree").resolve()


def test_redirect_loads_target(tmp_path):
    docs_repo = tmp_path / "docs-repo"
    source_repo = tmp_path / "source-repo"
    docs_repo.mkdir()
    source_repo.mkdir()

    (docs_repo / "flow.yml").write_text("docs_root: changes\nphases: []\ntransitions: []\n")
    (source_repo / "flow.yml").write_text("redirect: ../docs-repo/flow.yml\n")

    cfg = find_and_load(source_repo)
    assert cfg.docs_root == (docs_repo / "changes").resolve()
    assert cfg.phases == []


def test_redirect_glob_picks_newest_version(tmp_path):
    """redirect: with a wildcard picks the highest version-sorted match,
    same as use: (see test_use_glob_picks_newest_version)."""
    docs_repos = tmp_path / "docs-repos"
    for version in ("0.3.4", "0.10.0", "0.9.0"):
        target = docs_repos / version
        target.mkdir(parents=True)
        (target / "flow.yml").write_text(f"status_field: v{version}\nphases: []\ntransitions: []\n")

    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    (source_repo / "flow.yml").write_text("redirect: ../docs-repos/*/flow.yml\n")

    cfg = find_and_load(source_repo)
    assert cfg.status_field == "v0.10.0"


def test_status_field_custom(tmp_path):
    write_flow(tmp_path, "status_field: state\nphases: []\ntransitions: []\n")
    cfg = find_and_load(tmp_path)
    assert cfg.status_field == "state"


def test_parse_phase_with_gates_and_advance_when(tmp_path):
    write_flow(
        tmp_path,
        """
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
""",
    )
    cfg = find_and_load(tmp_path)
    drafting = cfg.phase("drafting")
    assert drafting is not None
    assert len(drafting.advance_when) == 1
    assert drafting.advance_when[0].file == "spec.md"
    assert drafting.advance_when[0].status == "approved"

    done = cfg.phase("done")
    assert done is not None
    assert len(done.gates) == 1


def test_parse_glob_condition(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: review
    advance_when:
      - glob: "docs/*.md"
        all_status: reviewed
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    cond = cfg.phases[0].advance_when[0]
    assert cond.glob == "docs/*.md"
    assert cond.all_status == "reviewed"


def test_parse_tasks_condition(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: coding
    advance_when:
      - file: tasks.md
        tasks: all_done
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    cond = cfg.phases[0].advance_when[0]
    assert cond.file == "tasks.md"
    assert cond.tasks == "all_done"


def test_parse_transitions(tmp_path):
    write_flow(
        tmp_path,
        """
phases: []
transitions:
  - name: approve
    from: draft
    to: approved
  - name: reject
    from: draft
    to: rejected
""",
    )
    cfg = find_and_load(tmp_path)
    assert cfg.transition_names() == ["approve", "reject"]
    approve = cfg.transition("approve")
    assert approve is not None
    assert approve.from_state == "draft"
    assert approve.to_state == "approved"


def test_parse_produced_doc_with_template(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: drafting
    produces:
      - file: spec.md
        template: "---\\nstatus: draft\\n---\\n"
        auto: true
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    doc = cfg.phases[0].produces[0]
    assert isinstance(doc, ProducedDoc)
    assert doc.file == "spec.md"
    assert doc.auto is True
    assert doc.template is not None
    assert "status: draft" in doc.template


def test_parse_scope(tmp_path):
    write_flow(
        tmp_path,
        """
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
""",
    )
    cfg = find_and_load(tmp_path)
    assert cfg.phases[0].scope == "changes/"
    assert cfg.phases[1].scope == "plans/"
    assert cfg.phases[2].scope is None


def test_phases_for_filters_by_scope(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: drafting
    scope: changes/
  - name: planning
    scope: plans/
  - name: done
transitions: []
""",
    )
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
    write_flow(
        tmp_path,
        """
phases:
  - name: drafting
  - name: done
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    subdir = tmp_path / "anything"
    subdir.mkdir()
    assert [p.name for p in cfg.phases_for(subdir)] == ["drafting", "done"]


def test_phases_for_outside_docs_root(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: drafting
    scope: changes/
  - name: done
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    # Outside docs_root → all phases returned (no filtering)
    assert [p.name for p in cfg.phases_for(tmp_path.parent)] == ["drafting", "done"]


def test_parse_transition_set_fields(tmp_path):
    write_flow(
        tmp_path,
        """
phases: []
transitions:
  - name: accept
    from: draft
    to: accepted
    set:
      accepted-at: now
      accepted-by: me
      once-first-accepted-at: now
""",
    )
    cfg = find_and_load(tmp_path)
    t = cfg.transition("accept")
    assert t is not None
    assert t.set_fields == {
        "accepted-at": "now",
        "accepted-by": "me",
        "once-first-accepted-at": "now",
    }


def test_parse_transition_unset_fields(tmp_path):
    write_flow(
        tmp_path,
        """
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
""",
    )
    cfg = find_and_load(tmp_path)
    t = cfg.transition("unblock")
    assert t is not None
    assert t.set_fields == {"unblocked-at": "now"}
    assert t.unset_fields == ["blocked-at", "blocked-reason"]


def test_parse_transition_require_set(tmp_path):
    write_flow(
        tmp_path,
        """
phases: []
transitions:
  - name: block
    from: draft
    to: blocked
    set:
      blocked-at: now
    require_set:
      - blocked-reason
""",
    )
    cfg = find_and_load(tmp_path)
    t = cfg.transition("block")
    assert t is not None
    assert t.require_set == ["blocked-reason"]


def test_parse_transition_require_set_defaults_empty(tmp_path):
    write_flow(
        tmp_path,
        """
phases: []
transitions:
  - name: accept
    from: draft
    to: accepted
""",
    )
    cfg = find_and_load(tmp_path)
    t = cfg.transition("accept")
    assert t is not None
    assert t.require_set == []


def test_parse_produced_doc_unset_fields(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: drafting
    produces:
      - file: proposal.md
        template: "---\\nstatus: draft\\nstale: yes\\n---\\n"
        unset:
          - stale
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert isinstance(entry, ProducedDoc)
    assert entry.unset_fields == ["stale"]


def test_parse_produced_doc_set_fields(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: drafting
    produces:
      - file: proposal.md
        template: "---\\nstatus: draft\\n---\\n"
        set:
          created-at: now
          author: me
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert isinstance(entry, ProducedDoc)
    assert entry.set_fields == {"created-at": "now", "author": "me"}


def test_parse_produced_dir_file_set_fields(tmp_path):
    write_flow(
        tmp_path,
        """
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
""",
    )
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert isinstance(entry, ProducedDir)
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
    (shared / "flow.yml").write_text("docs_root: shared-docs\nphases: []\ntransitions: []\n")

    project = tmp_path / "project"
    specs = project / "specs"
    specs.mkdir(parents=True)
    (project / "flow.yml").write_text(f"use: {shared / 'flow.yml'}\ndocs_root: specs\n")

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
    (skills / "flow.yml").write_text("status_field: state\nphases: []\ntransitions: []\n")
    monkeypatch.setenv("HOME", str(fake_home))

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text("use: ~/.claude/skills/flow.yml\n")

    cfg = find_and_load(project)
    assert cfg.status_field == "state"
    assert cfg.root == project


def test_use_glob_picks_newest_version(tmp_path):
    """use: with a wildcard picks the highest version-sorted match."""
    skills = tmp_path / "skills"
    for version in ("0.3.4", "0.10.0", "0.9.0"):
        resources = skills / version / "resources"
        resources.mkdir(parents=True)
        (resources / "flow.yml").write_text(
            f"status_field: v{version}\nphases: []\ntransitions: []\n"
        )

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text("use: ../skills/*/resources/flow.yml\n")

    cfg = find_and_load(project)
    # 0.10.0 must win over 0.9.0 (numeric, not lexical, comparison) and 0.3.4.
    assert cfg.status_field == "v0.10.0"


def test_use_glob_tilde_expansion(tmp_path, monkeypatch):
    """use: glob patterns expand ~ before matching, mirroring plugin cache
    layouts like ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/..."""
    fake_home = tmp_path / "home"
    base = fake_home / ".claude" / "plugins" / "cache" / "example-marketplace" / "example-plugin"
    for version in ("0.3.4", "0.4.0"):
        resources = base / version / "skills" / "example-skill" / "resources"
        resources.mkdir(parents=True)
        (resources / "flow.yml").write_text("phases: []\ntransitions: []\n")
    monkeypatch.setenv("HOME", str(fake_home))

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text(
        "use: ~/.claude/plugins/cache/example-marketplace/example-plugin/*/skills/"
        "example-skill/resources/flow.yml\n"
    )

    cfg = find_and_load(project)
    assert cfg.root == project


def test_use_glob_no_match_raises(tmp_path):
    """use: with a wildcard that matches nothing raises like a plain missing use target."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text("use: ../skills/*/resources/flow.yml\n")

    with pytest.raises(FlowConfigError, match="use target not found"):
        find_and_load(project)


def test_use_list_picks_first_existing_candidate(tmp_path):
    """use: as a list tries candidates in order and picks the first that exists."""
    second = tmp_path / "second-location"
    resources = second / "resources"
    resources.mkdir(parents=True)
    (resources / "flow.yml").write_text("status_field: from-second\nphases: []\ntransitions: []\n")

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text(
        "use:\n"
        "  - ../first-location/resources/flow.yml\n"
        "  - ../second-location/resources/flow.yml\n"
    )

    cfg = find_and_load(project)
    assert cfg.status_field == "from-second"


def test_use_list_first_candidate_wins_when_both_exist(tmp_path):
    """use: as a list prefers earlier entries over later ones."""
    for name, value in (("first-location", "from-first"), ("second-location", "from-second")):
        resources = tmp_path / name / "resources"
        resources.mkdir(parents=True)
        (resources / "flow.yml").write_text(f"status_field: {value}\nphases: []\ntransitions: []\n")

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text(
        "use:\n"
        "  - ../first-location/resources/flow.yml\n"
        "  - ../second-location/resources/flow.yml\n"
    )

    cfg = find_and_load(project)
    assert cfg.status_field == "from-first"


def test_use_list_no_candidate_exists_raises_with_all_tried(tmp_path):
    """use: as a list reports every candidate it tried when none exist."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text(
        "use:\n  - ../first-location/flow.yml\n  - ../second-location/flow.yml\n"
    )

    with pytest.raises(FlowConfigError, match="none of the use candidates were found"):
        find_and_load(project)


def test_redirect_list_picks_first_existing_candidate(tmp_path):
    """redirect: as a list behaves the same as use: (first existing wins)."""
    fallback = tmp_path / "fallback-repo"
    fallback.mkdir()
    (fallback / "flow.yml").write_text("status_field: from-fallback\nphases: []\ntransitions: []\n")

    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    (source_repo / "flow.yml").write_text(
        "redirect:\n  - ../primary-repo/flow.yml\n  - ../fallback-repo/flow.yml\n"
    )

    cfg = find_and_load(source_repo)
    assert cfg.status_field == "from-fallback"


def test_use_local_status_field_overrides(tmp_path):
    """Local status_field takes precedence over imported one."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "flow.yml").write_text("status_field: phase\nphases: []\ntransitions: []\n")

    project = tmp_path / "project"
    project.mkdir()
    (project / "flow.yml").write_text(f"use: {shared / 'flow.yml'}\nstatus_field: state\n")

    cfg = find_and_load(project)
    assert cfg.status_field == "state"


def test_parse_produced_dir(tmp_path):
    write_flow(
        tmp_path,
        """
phases:
  - name: review
    produces:
      - dir: specs/*
        files:
          - file: functional-spec.md
          - file: technical-spec.md
transitions: []
""",
    )
    cfg = find_and_load(tmp_path)
    entry = cfg.phases[0].produces[0]
    assert isinstance(entry, ProducedDir)
    assert entry.dir == "specs/*"
    assert [f.file for f in entry.files] == ["functional-spec.md", "technical-spec.md"]
