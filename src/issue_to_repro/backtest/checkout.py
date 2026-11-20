"""Prepare a checkout of one backtest case: a git worktree at the buggy commit with its own
virtualenv, so the target's tests run against the target's code and dependencies."""

import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

from .dataset import Case

TEST_GROUPS = ("tests", "test", "testing")
REQUIREMENTS_FILES = ("requirements/tests.txt", "requirements/test.txt", "requirements-test.txt")
Runner = Callable[[list[str]], None]


def run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def checkout_dir(case: Case, workspace_root: str | Path) -> Path:
    return Path(workspace_root) / f"{case.repo.split('/')[1]}-{case.issue_number}"


def prepare_checkout(
    source: str | Path,
    case: Case,
    workspace_root: str | Path,
    python: str = "3.12",
    run: Runner = run_checked,
) -> Path:
    """Create (or recreate) the case's worktree at `base_commit` and install its environment."""
    target = checkout_dir(case, workspace_root).resolve()
    git = ["git", "-C", str(source)]
    if target.exists():
        run([*git, "worktree", "remove", "--force", str(target)])
    run([*git, "worktree", "add", "--detach", "--force", str(target), case.base_commit])
    venv_python = target / ".venv" / "bin" / "python"
    run(["uv", "venv", "--quiet", "--python", python, str(target / ".venv")])
    run(
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "--python",
            str(venv_python),
            "-e",
            str(target),
            *requirements_for_tests(target),
        ]
    )
    return target


def requirements_for_tests(checkout: str | Path) -> list[str]:
    """`uv pip install` arguments for the project's test dependencies (always includes pytest)."""
    root = Path(checkout)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        groups = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("dependency-groups", {})
        for name in TEST_GROUPS:
            if name in groups:
                # Plain requirement strings only; {include-group = ...} tables are skipped.
                deps = [d for d in groups[name] if isinstance(d, str)]
                return sorted({*deps, "pytest"})
    for name in REQUIREMENTS_FILES:
        if (root / name).is_file():
            return ["-r", str(root / name), "pytest"]
    return ["pytest"]


def checkout_python(checkout: str | Path) -> Path | None:
    """The checkout's own interpreter, if `prepare_checkout` created one."""
    candidate = Path(checkout) / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None
