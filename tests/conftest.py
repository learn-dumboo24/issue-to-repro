import os
import subprocess
from pathlib import Path

import pytest

from issue_to_repro.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep tests independent of the machine: no stray env vars, no local .env file."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A workspace root containing one tiny 'repository' with a known bug in add()."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("REPRO_RUNS", "2")
    repo = tmp_path / "demo"
    (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "__init__.py").write_text("def add(a, b):\n    return a - b  # bug\n")
    (repo / "README.md").write_text("Demo package. add() should add numbers.\n")
    return repo


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
