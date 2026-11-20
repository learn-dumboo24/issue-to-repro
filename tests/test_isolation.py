import subprocess
import sys
from pathlib import Path

import pytest

from issue_to_repro.config import Settings
from issue_to_repro.tools import isolation, sandbox
from issue_to_repro.tools.isolation import docker_command, pytest_command, venv_home
from issue_to_repro.tools.sandbox import RunOutcome


def fake_venv(root: Path, home: str) -> None:
    (root / ".venv").mkdir(parents=True, exist_ok=True)
    (root / ".venv" / "pyvenv.cfg").write_text(f"home = {home}\nversion_info = 3.12.13\n")


@pytest.fixture
def standalone(tmp_path):
    python_dir = tmp_path / "uv-python"
    (python_dir / "cpython-3.12" / "bin").mkdir(parents=True)
    root = tmp_path / "ws" / "proj-1"
    root.mkdir(parents=True)
    fake_venv(root, str(python_dir / "cpython-3.12" / "bin"))
    return root, Settings(python_install_dir=str(python_dir), sandbox="docker")


def test_docker_command_locks_the_container_down(standalone):
    root, settings = standalone
    target = root / "test_issue_repro_1.py"
    cmd = docker_command(root, target, settings, "c1", 120)
    joined = " ".join(cmd)
    for flag in (
        "--network none",
        "--user 65534:65534",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--read-only",
        "--memory 1g",
        "--cpus 1",
        "--pids-limit 256",
        "--name c1",
    ):
        assert flag in joined, flag
    python_dir = settings.python_install_dir
    assert f"{python_dir}:{python_dir}:ro" in cmd
    assert f"{root}:{root}:ro" in cmd
    # The test runs under an in-container timeout, with the checkout's own interpreter.
    image = cmd.index(settings.sandbox_image)
    assert cmd[image + 1 : image + 4] == ["timeout", "--kill-after=5", "120"]
    assert cmd[image + 4 :] == pytest_command(str(root / ".venv/bin/python"), target)


def test_docker_command_requires_a_standalone_python_venv(standalone, tmp_path):
    root, settings = standalone
    fake_venv(root, "/usr/bin")
    with pytest.raises(ValueError, match="standalone Python"):
        docker_command(root, root / "t.py", settings, "c", 10)
    with pytest.raises(ValueError, match="standalone Python"):
        docker_command(tmp_path, root / "t.py", settings, "c", 10)  # no .venv at all


def test_venv_home(tmp_path):
    assert venv_home(tmp_path) is None
    fake_venv(tmp_path, "/opt/x/bin")
    assert venv_home(tmp_path) == "/opt/x/bin"
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("version = 3.12\n")
    assert venv_home(tmp_path) is None


def test_container_names_are_unique():
    assert isolation.container_name() != isolation.container_name()


class Done:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def docker_mode(standalone, monkeypatch):
    root, settings = standalone
    monkeypatch.setenv("SANDBOX", "docker")
    monkeypatch.setenv("PYTHON_INSTALL_DIR", settings.python_install_dir)
    monkeypatch.setenv("TEST_TIMEOUT_S", "7")
    return root


def test_in_container_timeout_is_a_timeout(docker_mode, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs["timeout"]))
        return Done(124, "partial output")

    monkeypatch.setattr(subprocess, "run", fake_run)
    outcome, output = sandbox._run_once(docker_mode, docker_mode / "test_issue_repro_1.py", 7)
    assert outcome is RunOutcome.TIMEOUT
    assert "timed out after 7s in the sandbox" in output
    [(cmd, host_timeout)] = calls
    assert cmd[:2] == ["docker", "run"] and host_timeout == 7 + isolation.HOST_TIMEOUT_GRACE_S


def test_host_timeout_removes_the_container(docker_mode, monkeypatch):
    removed = []

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], output=b"slow")
        removed.append(cmd)
        return Done(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    outcome, output = sandbox._run_once(docker_mode, docker_mode / "test_issue_repro_1.py", 7)
    assert outcome is RunOutcome.TIMEOUT
    assert removed[0][:3] == ["docker", "rm", "-f"]
    assert "removed]" in output and output.startswith("slow")


def test_failed_container_removal_is_reported(docker_mode, monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return Done(1, stderr="daemon gone")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _, output = sandbox._run_once(docker_mode, docker_mode / "test_issue_repro_1.py", 7)
    assert "could not remove: daemon gone" in output


def test_docker_errors_are_errors_not_reproductions(docker_mode, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: Done(125, stderr="no such image"))
    outcome, output = sandbox._run_once(docker_mode, docker_mode / "test_issue_repro_1.py", 7)
    assert outcome is RunOutcome.ERROR and "no such image" in output


def test_local_mode_uses_the_checkout_python(tmp_path):
    assert isolation.checkout_python(tmp_path) == sys.executable
