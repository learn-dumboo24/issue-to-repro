"""Find past bug fixes in a repository's git history.

A usable case is a non-merge commit whose message closes exactly one issue ("Fixes #123") and
that changes both source and test files. Its parent is the buggy base; the commit itself is the
fix, and the tests it adds are the ground truth for whether a reproduction is genuine.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ISSUE_REF = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+#(\d+)", re.IGNORECASE)
TEST_PREFIXES = ("tests/", "test/")
NON_SOURCE_PREFIXES = ("docs/", ".github/", "CHANGES", "CHANGELOG", "README")
RECORD_SEP, FIELD_SEP = "\x1e", "\x00"
LOG_FORMAT = "%H%x00%P%x00%cI%x00%s%x00%b%x1e"  # git expands %x00 / %x1e to the separators


@dataclass(frozen=True)
class FixCommit:
    issue_number: int
    fix_commit: str
    base_commit: str
    committed_at: str
    subject: str
    source_files: tuple[str, ...]
    test_files: tuple[str, ...]


def find_fix_commits(repo_dir: str | Path, since: str = "2019-01-01") -> list[FixCommit]:
    """Return one fix commit per issue (the earliest), oldest first."""
    log = _git(
        repo_dir,
        "log",
        "--no-merges",
        "--reverse",
        f"--since={since}",
        f"--format={LOG_FORMAT}",
    )
    found: dict[int, FixCommit] = {}
    for record in log.split(RECORD_SEP):
        if not record.strip():
            continue
        sha, parents, committed_at, subject, body = record.strip("\n").split(FIELD_SEP)
        issues = {int(n) for n in ISSUE_REF.findall(f"{subject}\n{body}")}
        if len(issues) != 1 or len(parents.split()) != 1:
            continue  # ambiguous (several issues) or a merge: no single buggy base
        issue = issues.pop()
        if issue in found:
            continue  # cherry-picks and follow-ups: keep the first fix
        source, tests = split_changed_files(_changed_files(repo_dir, sha))
        if source and tests:
            found[issue] = FixCommit(issue, sha, parents, committed_at, subject, source, tests)
    return list(found.values())


def split_changed_files(paths: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split paths into (source .py files, test files); docs and changelogs are dropped."""
    tests = tuple(p for p in paths if p.startswith(TEST_PREFIXES))
    source = tuple(
        p
        for p in paths
        if p.endswith(".py") and not p.startswith(TEST_PREFIXES + NON_SOURCE_PREFIXES)
    )
    return source, tests


def _changed_files(repo_dir: str | Path, sha: str) -> list[str]:
    out = _git(repo_dir, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha)
    return [p for p in out.split("\0") if p]


def _git(repo_dir: str | Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True
    )
    return done.stdout
