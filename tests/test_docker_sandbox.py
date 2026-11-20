"""Integration tests: real containers. Run with `uv run pytest -m docker` (needs Docker and network
access to download uv's standalone Python and the base image). CI runs them in their own job."""

import os
import subprocess

import pytest

from issue_to_repro.backtest.checkout import standalone_python
from issue_to_repro.tools.sandbox import run_reproduction

pytestmark = pytest.mark.docker


def _docker_ready() -> bool:
    try:
        done = subprocess.run(["docker", "info"], check=False, capture_output=True, timeout=30)
        return done.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="module")
def python_dir(tmp_path_factory):
    if not _docker_ready():
        pytest.skip("Docker is not available")
    directory = tmp_path_factory.mktemp("uv-python")
    python = standalone_python("3.12", str(directory))
    return directory, python


def _readable_by_everyone(path) -> None:
    """The container runs as nobody; pytest's temp dirs are private by default."""
    for root, dirs, files in os.walk(path):
        os.chmod(root, 0o755)
        for name in files:
            os.chmod(
                os.path.join(root, name),
                0o644 if not os.access(os.path.join(root, name), os.X_OK) else 0o755,
            )


@pytest.fixture
def docker_workspace(workspace, python_dir, monkeypatch):
    directory, python = python_dir
    subprocess.run(["uv", "venv", "-q", "--python", python, str(workspace / ".venv")], check=True)
    subprocess.run(
        ["uv", "pip", "install", "-q", "--python", str(workspace / ".venv/bin/python"), "pytest"],
        check=True,
    )
    _readable_by_everyone(directory)
    _readable_by_everyone(workspace)
    monkeypatch.setenv("SANDBOX", "docker")
    monkeypatch.setenv("PYTHON_INSTALL_DIR", str(directory))
    return workspace


def test_reproduces_a_real_bug_in_the_container(docker_workspace):
    code = "from demo import add\n\ndef test_add():\n    assert add(2, 2) == 4\n"
    result = run_reproduction(str(docker_workspace), "test_issue_repro_1.py", code)
    assert result["verdict"] == "reproduced", result["last_output_tail"]


def test_container_has_no_network(docker_workspace):
    code = (
        "import socket\n\ndef test_net():\n    with socket.socket() as s:\n"
        "        s.settimeout(5)\n        s.connect(('8.8.8.8', 53))\n"
    )
    result = run_reproduction(str(docker_workspace), "test_issue_repro_2.py", code)
    assert "Network is unreachable" in result["last_output_tail"], result["last_output_tail"]


def test_checkout_is_read_only_in_the_container(docker_workspace):
    code = "def test_write():\n    open('pwned.txt', 'w').write('x')\n"
    result = run_reproduction(str(docker_workspace), "test_issue_repro_3.py", code)
    assert "Read-only file system" in result["last_output_tail"], result["last_output_tail"]
    assert not (docker_workspace / "pwned.txt").exists()
