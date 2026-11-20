"""Prepare a checkout of one backtest case: a git worktree at the buggy commit with its own
virtualenv, so the target's tests run against the target's code and dependencies."""

import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

from ..config import get_settings
from .dataset import Case

PYTHON_VERSION = "3.12"
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

TEST_GROUPS = ("tests", "test", "testing")
REQUIREMENTS_FILES = ("requirements/tests.txt", "requirements/test.txt", "requirements-test.txt")
Runner = Callable[[list[str]], None]


def run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def checkout_dir(case: Case, workspace_root: str | Path) -> Path:
    return Path(workspace_root) / f"{case.repo.split('/')[1]}-{case.issue_number}"


def standalone_python(version: str = PYTHON_VERSION, install_dir: str | None = None) -> str:
    """Install (if needed) and return uv's standalone CPython in `install_dir`.

    The docker sandbox mounts this directory into the container, so checkouts built on it need
    nothing installed inside the container.
    """
    install_dir = install_dir or get_settings().python_install_dir
    # Without VIRTUAL_ENV and with --no-project: inside `uv run`, uv would otherwise return the
    # active project venv's interpreter instead of the standalone one.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["UV_PYTHON_INSTALL_DIR"] = install_dir
    subprocess.run(
        ["uv", "python", "install", "--no-bin", version],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    found = subprocess.run(
        ["uv", "python", "find", "--no-project", "--managed-python", version],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    python = found.stdout.strip()
    root = Path(install_dir).resolve()
    if root not in Path(python).resolve().parents:
        raise RuntimeError(f"uv returned {python!r}, which is not a standalone Python in {root}")
    return python


def prepare_checkout(
    source: str | Path,
    case: Case,
    workspace_root: str | Path,
    python: str | None = None,
    run: Runner = run_checked,
) -> Path:
    """Create (or recreate) the case's worktree at `base_commit` and install its environment.

    With SANDBOX=docker the virtualenv is built on uv's standalone Python; otherwise on any
    Python `PYTHON_VERSION` uv can find.
    """
    if python is None:
        docker = get_settings().sandbox == "docker"
        python = standalone_python() if docker else PYTHON_VERSION
    target = checkout_dir(case, workspace_root).resolve()
    git = ["git", "-C", str(source)]
    if target.exists():
        run([*git, "worktree", "remove", "--force", str(target)])
    run([*git, "worktree", "add", "--detach", "--force", str(target), case.base_commit])
    install_env(target, python, run)
    return target


def prepare_live_checkout(
    repo: str,
    issue_number: int,
    workspace_root: str | Path,
    python: str | None = None,
    run: Runner = run_checked,
) -> Path:
    """Shallow-clone `repo`'s default branch for one live issue and install its environment."""
    if not REPO_NAME.match(repo):
        raise ValueError(f"not a repository name: {repo!r}")
    if python is None:
        docker = get_settings().sandbox == "docker"
        python = standalone_python() if docker else PYTHON_VERSION
    target = (Path(workspace_root) / "live" / f"{repo.replace('/', '__')}-{issue_number}").resolve()
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--quiet", "--depth", "1", f"https://github.com/{repo}.git", str(target)])
    install_env(target, python, run)
    return target


def install_env(target: Path, python: str, run: Runner = run_checked) -> None:
    """A .venv in `target` with the project (editable) and its test dependencies."""
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
