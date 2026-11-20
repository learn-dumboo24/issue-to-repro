"""Reproduction drafts awaiting maintainer approval, and where they are stored.

A draft is never posted automatically. FileDraftStore keeps one JSON file per issue and writes
atomically (temp file + rename); a Firestore store can replace it on Cloud Run.
"""

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

Status = Literal["pending", "posted", "not_reproduced"]
SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass(frozen=True)
class Draft:
    repo: str
    issue_number: int
    status: Status
    verdict: str  # sandbox verdict of the agents' last attempt
    test_path: str | None
    test_code: str | None
    report: str  # the reporter agent's summary for the maintainer
    comment_url: str | None = None
    approved_by: str | None = None

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.issue_number}"


class DraftStore(Protocol):
    def save(self, draft: Draft) -> None: ...

    def get(self, repo: str, issue_number: int) -> Draft | None: ...


class FileDraftStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, repo: str, issue_number: int) -> Path:
        return self.directory / f"{SAFE.sub('_', repo)}__{issue_number}.json"

    def save(self, draft: Draft) -> None:
        target = self._path(draft.repo, draft.issue_number)
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(asdict(draft), out, ensure_ascii=False)
        os.replace(tmp, target)

    def get(self, repo: str, issue_number: int) -> Draft | None:
        path = self._path(repo, issue_number)
        if not path.exists():
            return None
        return Draft(**json.loads(path.read_text(encoding="utf-8")))


def mark_posted(draft: Draft, url: str, approved_by: str) -> Draft:
    return replace(draft, status="posted", comment_url=url, approved_by=approved_by)
