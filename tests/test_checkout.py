import os
import sys
from pathlib import Path

import pytest
from conftest import git

from issue_to_repro.backtest.checkout import (
    checkout_dir,
    checkout_python,
    prepare_checkout,
    requirements_for_tests,
    run_checked,
)
from issue_to_repro.backtest.dataset import Case
from issue_to_repro.tools.sandbox import run_reproduction


def make_case(base: str, fix: str) -> Case:
    return Case(
        repo="o/proj",
        issue_number=12,
        issue_title="t",
        issue_body="b",
        issue_labels=(),
        issue_url="u",
        issue_created_at="",
        fix_commit=fix,
        base_commit=base,
        committed_at="",
        fix_subject="Fix rounding",
        source_files=("pkg/core.py",),
        test_files=("tests/test_core.py",),
    )


def test_prepare_checkout_creates_worktree_at_base_and_installs_env(history, tmp_path):
    repo, base, fix = history
    commands: list[list[str]] = []

    def fake_uv(command: list[str]) -> None:
        commands.append(command)
        if command[0] == "git":
            run_checked(command)  # real worktree; only the uv installs are faked

    target = prepare_checkout(repo, make_case(base, fix), tmp_path / "ws", run=fake_uv)
    assert target == (tmp_path / "ws" / "proj-12").resolve()
    assert git(target, "rev-parse", "HEAD") == base
    assert (target / "pkg" / "core.py").read_text() == "x = 1\n"
    uv_venv, uv_install = commands[-2:]
    assert uv_venv[:2] == ["uv", "venv"]
    assert uv_install[-1] == "pytest" and "-e" in uv_install

    # Preparing again replaces the old worktree instead of failing.
    (target / "scratch.txt").write_text("leftover")
    prepare_checkout(repo, make_case(base, fix), tmp_path / "ws", run=fake_uv)
    assert not (target / "scratch.txt").exists()


def test_test_requirements(tmp_path):
    assert requirements_for_tests(tmp_path) == ["pytest"]
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "tests.txt").write_text("hypothesis\n")
    assert requirements_for_tests(tmp_path) == [
        "-r",
        str(tmp_path / "requirements/tests.txt"),
        "pytest",
    ]
    (tmp_path / "pyproject.toml").write_text(
        '[dependency-groups]\ntests = ["pytest>=8", "freezegun", {include-group = "x"}]\n'
    )
    assert requirements_for_tests(tmp_path) == ["freezegun", "pytest", "pytest>=8"]


def test_checkout_dir_and_python(tmp_path):
    case = make_case("a", "b")
    assert checkout_dir(case, tmp_path) == tmp_path / "proj-12"
    assert checkout_python(tmp_path) is None
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    os.symlink(sys.executable, venv_bin / "python")
    assert checkout_python(tmp_path) == venv_bin / "python"


def test_sandbox_uses_the_checkouts_own_python(workspace):
    marker = workspace / "used_python.txt"
    venv_bin = workspace / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    wrapper = venv_bin / "python"
    wrapper.write_text(f'#!/bin/sh\necho venv > "{marker}"\nexec "{sys.executable}" "$@"\n')
    wrapper.chmod(0o755)
    code = "from demo import add\n\ndef test_add():\n    assert add(2, 2) == 4\n"
    assert (
        run_reproduction(str(workspace), "test_issue_repro_9.py", code)["verdict"] == "reproduced"
    )
    assert Path(marker).read_text().strip() == "venv"


def test_docker_sandbox_builds_venvs_on_the_standalone_python(history, tmp_path, monkeypatch):
    from issue_to_repro.backtest import checkout as checkout_module

    repo, base, fix = history
    monkeypatch.setenv("SANDBOX", "docker")
    monkeypatch.setattr(checkout_module, "standalone_python", lambda: "/opt/uv-python/py3.12")
    commands: list[list[str]] = []

    def record(command: list[str]) -> None:
        commands.append(command)
        if command[0] == "git":
            run_checked(command)

    prepare_checkout(repo, make_case(base, fix), tmp_path / "ws", run=record)
    uv_venv = next(c for c in commands if c[:2] == ["uv", "venv"])
    assert uv_venv[uv_venv.index("--python") + 1] == "/opt/uv-python/py3.12"


def test_standalone_python_installs_into_the_configured_dir(monkeypatch):
    from issue_to_repro.backtest import checkout as checkout_module

    seen = []
    found = {"path": "/opt/x/cpython-3.12/bin/python3.12"}

    class Done:
        @property
        def stdout(self):
            return found["path"] + "\n"

    def fake_run(cmd, **kwargs):
        env = kwargs["env"]
        seen.append((cmd, env["UV_PYTHON_INSTALL_DIR"], "VIRTUAL_ENV" in env))
        return Done()

    monkeypatch.setenv("VIRTUAL_ENV", "/some/project/.venv")
    monkeypatch.setattr(checkout_module.subprocess, "run", fake_run)
    assert checkout_module.standalone_python("3.12", "/opt/x") == found["path"]
    assert seen[0] == (["uv", "python", "install", "--no-bin", "3.12"], "/opt/x", False)
    assert seen[1][0] == ["uv", "python", "find", "--no-project", "--managed-python", "3.12"]

    # An interpreter outside the install dir (e.g. an active project venv) is an error.
    found["path"] = "/some/project/.venv/bin/python3"
    with pytest.raises(RuntimeError, match="not a standalone Python"):
        checkout_module.standalone_python("3.12", "/opt/x")
