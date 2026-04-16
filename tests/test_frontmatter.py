"""Tests for frontmatter parsing and checkbox utilities."""


from markstate.frontmatter import (
    _parse,
    _serialize,
    check_task,
    count_tasks,
    load,
    next_unchecked_task,
)

# --- parsing / serializing ---


def test_parse_no_frontmatter():
    fm, body = _parse("# Hello\n\nContent")
    assert fm == {}
    assert body == "# Hello\n\nContent"


def test_parse_with_frontmatter():
    fm, body = _parse("---\nstatus: draft\n---\n# Hello\n")
    assert fm == {"status": "draft"}
    assert body == "# Hello\n"


def test_parse_multiple_fields():
    fm, _ = _parse("---\nstatus: draft\ntitle: My Doc\n---\n")
    assert fm == {"status": "draft", "title": "My Doc"}


def test_serialize_round_trip():
    fm = {"status": "draft", "title": "Test"}
    body = "# Hello\n"
    text = _serialize(fm, body)
    fm2, body2 = _parse(text)
    assert fm2 == fm
    assert body2 == body


def test_serialize_empty_frontmatter():
    assert _serialize({}, "# Hello\n") == "# Hello\n"


def test_document_get_set_save(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("---\nstatus: draft\n---\n# Body\n")
    doc = load(p)
    assert doc.get("status") == "draft"
    assert doc.get("missing") is None
    doc.set("status", "approved")
    doc.save()
    assert load(p).get("status") == "approved"


def test_document_no_frontmatter(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("# Just a body\n")
    doc = load(p)
    assert doc.get("status") is None


# --- count_tasks ---


def test_count_tasks_empty():
    assert count_tasks("# No tasks here\n") == (0, 0)


def test_count_tasks_all_undone():
    assert count_tasks("- [ ] A\n- [ ] B\n") == (0, 2)


def test_count_tasks_mixed():
    assert count_tasks("- [x] Done\n- [ ] Todo\n- [x] Also done\n") == (2, 3)


def test_count_tasks_all_done():
    assert count_tasks("- [x] A\n- [x] B\n") == (2, 2)


def test_count_tasks_uppercase_x():
    assert count_tasks("- [X] Done\n") == (1, 1)


# --- next_unchecked_task ---


def test_next_unchecked_task_none():
    assert next_unchecked_task("- [x] Done\n") is None


def test_next_unchecked_task_empty():
    assert next_unchecked_task("# No tasks\n") is None


def test_next_unchecked_task_returns_first():
    text = "- [x] Done\n- [ ] Second\n- [ ] Third\n"
    assert next_unchecked_task(text) == "Second"


# --- check_task ---


def test_check_task_match():
    text = "- [x] Done\n- [ ] Implement auth\n- [ ] Write tests\n"
    result = check_task(text, "auth")
    assert result is not None
    new_text, task = result
    assert task == "Implement auth"
    assert "- [x] Implement auth" in new_text
    assert "- [ ] Write tests" in new_text


def test_check_task_case_insensitive():
    result = check_task("- [ ] Implement Auth\n", "AUTH")
    assert result is not None
    assert result[1] == "Implement Auth"


def test_check_task_no_match():
    assert check_task("- [ ] Something else\n", "nonexistent") is None


def test_check_task_skips_already_checked():
    # "done" matches "Already done" but it's [x] — should not match
    text = "- [x] Already done\n- [ ] Still todo\n"
    result = check_task(text, "done")
    assert result is None


def test_check_task_first_match_only():
    text = "- [ ] Task alpha\n- [ ] Task beta\n"
    result = check_task(text, "Task")
    assert result is not None
    _, task = result
    assert task == "Task alpha"


# --- HTML comment stripping ---

COMMENT_BODY = (
    "<!-- Example:\n"
    "- [ ] ignored 1\n"
    "- [ ] ignored 2\n"
    "- [ ] ignored 3\n"
    "-->\n"
    "\n"
    "- [x] real task\n"
)


def test_count_tasks_ignores_html_comments():
    assert count_tasks(COMMENT_BODY) == (1, 1)


def test_next_unchecked_task_ignores_html_comments():
    assert next_unchecked_task(COMMENT_BODY) is None


def test_check_task_ignores_html_comments():
    assert check_task(COMMENT_BODY, "ignored") is None
