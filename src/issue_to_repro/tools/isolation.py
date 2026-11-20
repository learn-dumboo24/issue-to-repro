"""Build the command that runs a reproduction test, locally or in a locked-down container.

The docker sandbox runs the target repository's tests with:
  --network none, a non-root user (nobody), all capabilities dropped, no-new-privileges,
  a read-only root filesystem and read-only mounts, a small /tmp, memory/CPU/process limits,
  and an in-container timeout.
Nothing is installed in the container: the checkout's virtualenv is built beforehand on uv's
standalone Python (in `python_install_dir`), and both are mounted read-only at the same paths.
"""

import os
import sys
import uuid
from pathlib import Path

from ..config import Settings

NOBODY = "65534:65534"
TIMEOUT_EXIT_CODES = {124, 137}  # coreutils `timeout`: timed out / killed after --kill-after
HOST_TIMEOUT_GRACE_S = 30  # covers container start-up and image checks


def pytest_command(python: str, target: Path) -> list[str]:
    return [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(target)]


def checkout_python(root: Path) -> str:
    """The checkout's own interpreter if it has a .venv, else this interpreter."""
    venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def container_name() -> str:
    return f"issue-to-repro-{uuid.uuid4().hex[:12]}"


def docker_command(
    root: Path, target: Path, settings: Settings, name: str, timeout_s: int
) -> list[str]:
    """`docker run` for one test run; `root` must have a .venv built on the standalone Python."""
    python_dir = str(Path(settings.python_install_dir).resolve())
    home = venv_home(root)
    if home is None or not (home == python_dir or home.startswith(python_dir + os.sep)):
        raise ValueError(
            f"{root} has no virtualenv built on the standalone Python in {python_dir}; "
            "prepare the checkout with SANDBOX=docker"
        )
    inner = pytest_command(str(root / ".venv" / "bin" / "python"), target)
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--user",
        NOBODY,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:size=64m",
        "--memory",
        settings.sandbox_memory,
        "--cpus",
        settings.sandbox_cpus,
        "--pids-limit",
        str(settings.sandbox_pids),
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-v",
        f"{python_dir}:{python_dir}:ro",
        "-v",
        f"{root}:{root}:ro",
        "-w",
        str(root),
        settings.sandbox_image,
        "timeout",
        "--kill-after=5",
        str(timeout_s),
        *inner,
    ]


def venv_home(root: Path) -> str | None:
    """The `home` directory recorded in the checkout's pyvenv.cfg, resolved."""
    cfg = root / ".venv" / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            return str(Path(value.strip()).resolve())
    return None
