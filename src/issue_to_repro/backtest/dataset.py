"""Build a frozen backtest dataset: mined fix commits joined with their issue text.

Only the issue's title and body are stored, never its comments: comments written after the
fix often reveal it, which would leak the answer to the agents.
"""

import json
import urllib.error
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..tools.github import fetch_issue
from .mining import find_fix_commits

GONE_STATUSES = {404, 410}  # deleted or transferred issues


@dataclass(frozen=True)
class Case:
    repo: str
    issue_number: int
    issue_title: str
    issue_body: str
    issue_labels: tuple[str, ...]
    issue_url: str
    issue_created_at: str
    fix_commit: str
    base_commit: str
    committed_at: str
    fix_subject: str
    source_files: tuple[str, ...]
    test_files: tuple[str, ...]

    @property
    def case_id(self) -> str:
        return f"{self.repo}#{self.issue_number}"


@dataclass(frozen=True)
class Skipped:
    issue_number: int
    reason: str


def build_dataset(
    repo: str,
    checkout: str | Path,
    since: str = "2019-01-01",
    fetch: Callable[[str, int], dict[str, Any]] = fetch_issue,
) -> tuple[list[Case], list[Skipped]]:
    """Mine `checkout` (a clone of `repo`) and attach issue text. Unknown errors propagate."""
    cases: list[Case] = []
    skipped: list[Skipped] = []
    for fix in find_fix_commits(checkout, since=since):
        try:
            issue = fetch(repo, fix.issue_number)
        except urllib.error.HTTPError as exc:
            if exc.code not in GONE_STATUSES:
                raise
            skipped.append(Skipped(fix.issue_number, f"issue unavailable (HTTP {exc.code})"))
            continue
        if issue["is_pull_request"]:
            skipped.append(Skipped(fix.issue_number, "reference is a pull request, not an issue"))
            continue
        cases.append(
            Case(
                repo=repo,
                issue_number=fix.issue_number,
                issue_title=issue["title"],
                issue_body=issue["body"],
                issue_labels=tuple(issue["labels"]),
                issue_url=issue["url"],
                issue_created_at=issue["created_at"],
                fix_commit=fix.fix_commit,
                base_commit=fix.base_commit,
                committed_at=fix.committed_at,
                fix_subject=fix.subject,
                source_files=fix.source_files,
                test_files=fix.test_files,
            )
        )
    return cases, skipped


def write_jsonl(cases: Iterable[Case], path: str | Path) -> int:
    """Write one JSON object per line; returns the number written."""
    count = 0
    with Path(path).open("w", encoding="utf-8") as out:
        for case in cases:
            out.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl(path: str | Path) -> list[Case]:
    cases = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            for key in ("issue_labels", "source_files", "test_files"):
                data[key] = tuple(data[key])
            cases.append(Case(**data))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}:{line_no}: not a valid case: {exc}") from exc
    return cases
