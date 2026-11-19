import os
import subprocess
from pathlib import Path

import pytest

from issue_to_repro.backtest.mining import find_fix_commits, split_changed_files

COMMIT_DATE = "2020-06-01T12:00:00+00:00"


def git(repo: Path, *args: str) -> str:
    env_args = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    dates = {"GIT_AUTHOR_DATE": COMMIT_DATE, "GIT_COMMITTER_DATE": COMMIT_DATE}
    done = subprocess.run(
        ["git", "-C", str(repo), *env_args, *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **dates},
    )
    return done.stdout.strip()


def commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    base = commit(repo, "Initial", {"pkg/core.py": "x = 1\n", "tests/test_core.py": ""})
    fix = commit(
        repo, "Fix rounding\n\nFixes #12", {"pkg/core.py": "x = 2\n", "tests/test_core.py": "# t\n"}
    )
    commit(repo, "Docs only, closes #13", {"docs/a.md": "a", "tests/test_core.py": "# t2\n"})
    commit(repo, "No test, fixes #14", {"pkg/core.py": "x = 3\n"})
    commit(repo, "Two issues, fixes #15, fixes #16", {"pkg/core.py": "x = 4\n", "tests/t.py": "1"})
    commit(repo, "Backport: closes #12", {"pkg/core.py": "x = 5\n", "tests/test_core.py": "# t3\n"})
    commit(repo, "Refactor (#99), no fix keyword", {"pkg/core.py": "x = 6\n", "tests/t.py": "2"})
    return repo, base, fix


def test_finds_only_unambiguous_fixes_with_source_and_tests(history):
    repo, base, fix = history
    cases = find_fix_commits(repo, since="2020-01-01")
    assert [c.issue_number for c in cases] == [12]
    case = cases[0]
    assert (case.fix_commit, case.base_commit) == (fix, base)
    assert case.subject == "Fix rounding"
    assert case.source_files == ("pkg/core.py",)
    assert case.test_files == ("tests/test_core.py",)


def test_since_filters_old_history(history):
    repo, _, _ = history
    assert find_fix_commits(repo, since="2021-01-01") == []


def test_split_changed_files():
    source, tests = split_changed_files(
        ["src/a.py", "tests/test_a.py", "docs/x.py", "CHANGES.rst", "setup.cfg", "test/b.py"]
    )
    assert source == ("src/a.py",)
    assert tests == ("tests/test_a.py", "test/b.py")


def test_reports_git_errors(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        find_fix_commits(tmp_path)
