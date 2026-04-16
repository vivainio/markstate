"""Read and write YAML front matter in markdown files."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_TASK_RE = re.compile(r'^(\s*-\s+\[)([ xX])(\]\s+)(.*)', re.MULTILINE)
_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)


def _strip_comments(text: str) -> str:
    return _COMMENT_RE.sub('', text)


DELIMITER = "---"


@dataclass
class Document:
    path: Path
    front_matter: dict[str, object] = field(default_factory=dict)
    body: str = ""
    first_keys: tuple[str, ...] = ("status",)

    def get(self, key: str) -> object | None:
        return self.front_matter.get(key)

    def set(self, key: str, value: object) -> None:
        self.front_matter[key] = value

    def unset(self, key: str) -> None:
        self.front_matter.pop(key, None)

    def save(self) -> None:
        self.path.write_text(
            _serialize(self.front_matter, self.body, first_keys=self.first_keys),
            encoding="utf-8",
        )


def count_tasks(text: str) -> tuple[int, int]:
    """Return (done, total) checkbox task counts."""
    matches = _TASK_RE.findall(_strip_comments(text))
    total = len(matches)
    done = sum(1 for _, mark, _, _ in matches if mark.lower() == "x")
    return done, total


def next_unchecked_task(text: str) -> str | None:
    """Return the text of the first unchecked task, or None."""
    for m in _TASK_RE.finditer(_strip_comments(text)):
        if m.group(2) == " ":
            return m.group(4)
    return None


def check_task(text: str, substring: str) -> tuple[str, str] | None:
    """Check off the first unchecked task whose text contains substring.

    Returns (updated_text, task_text) or None if no match.
    """
    for m in _TASK_RE.finditer(text):
        if m.group(2) == " " and substring.lower() in m.group(4).lower():
            # Verify this match is not inside a comment
            before = text[: m.start()]
            open_comments = before.count("<!--")
            close_comments = before.count("-->")
            if open_comments > close_comments:
                continue
            task_text = m.group(4)
            new_text = text[: m.start(2)] + "x" + text[m.end(2) :]
            return new_text, task_text
    return None


def load(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    front_matter, body = _parse(text)
    return Document(path=path, front_matter=front_matter, body=body)


def _parse(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith(DELIMITER + "\n"):
        return {}, text

    end = text.index("\n" + DELIMITER, len(DELIMITER))
    raw = text[len(DELIMITER) + 1 : end]
    body = text[end + len(DELIMITER) + 2 :]  # skip closing --- and newline
    return yaml.safe_load(raw) or {}, body


def _reorder(front_matter: dict[str, object], first_keys: tuple[str, ...]) -> dict[str, object]:
    """Return a new dict with first_keys at the top, rest in original order."""
    ordered: dict[str, object] = {}
    for k in first_keys:
        if k in front_matter:
            ordered[k] = front_matter[k]
    for k, v in front_matter.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def _serialize(
    front_matter: dict[str, object],
    body: str,
    first_keys: tuple[str, ...] = (),
) -> str:
    if not front_matter:
        return body
    ordered = _reorder(front_matter, first_keys) if first_keys else front_matter
    raw = yaml.dump(ordered, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"{DELIMITER}\n{raw}{DELIMITER}\n{body}"
