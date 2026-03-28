"""Read and write YAML front matter in markdown files."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


DELIMITER = "---"


@dataclass
class Document:
    path: Path
    front_matter: dict[str, object] = field(default_factory=dict)
    body: str = ""

    def get(self, key: str) -> object | None:
        return self.front_matter.get(key)

    def set(self, key: str, value: object) -> None:
        self.front_matter[key] = value

    def save(self) -> None:
        self.path.write_text(_serialize(self.front_matter, self.body))


def load(path: Path) -> Document:
    text = path.read_text()
    front_matter, body = _parse(text)
    return Document(path=path, front_matter=front_matter, body=body)


def _parse(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith(DELIMITER + "\n"):
        return {}, text

    end = text.index("\n" + DELIMITER, len(DELIMITER))
    raw = text[len(DELIMITER) + 1 : end]
    body = text[end + len(DELIMITER) + 2 :]  # skip closing --- and newline
    return yaml.safe_load(raw) or {}, body


def _serialize(front_matter: dict[str, object], body: str) -> str:
    if not front_matter:
        return body
    raw = yaml.dump(front_matter, default_flow_style=False, allow_unicode=True)
    return f"{DELIMITER}\n{raw}{DELIMITER}\n{body}"
