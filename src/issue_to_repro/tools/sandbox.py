"""Run a candidate reproduction test in a checkout and decide whether it really reproduces.

SECURITY: this executes the target repository's code on this machine. Until the Docker /
Cloud Run job sandbox lands, only point it at repositories you trust.
"""

import os
import re
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..config import get_settings
from .workspace import resolve_checkout

TEST_NAME = re.compile(r"^test_issue_repro[A-Za-z0-9_]*\.py$")
# A run that fails for one of these reasons is a broken test, not a reproduced bug.
WRONG_REASON = re.compile(
    r"fixture '[^']+' not found|^E\s+(ModuleNotFoundError|ImportError|SyntaxError|IndentationError)\b",
    re.MULTILINE,
)
OUTPUT_TAIL_CHARS = 4_000


class RunOutcome(StrEnum):
    FAILED = "failed"  # test ran and failed: candidate reproduction
    PASSED = "passed"  # bug not reproduced
    INVALID = "invalid"  # failed for the wrong reason (collection, import, fixture)
    TIMEOUT = "timeout"
    ERROR = "error"  # pytest internal or usage error


class Verdict(StrEnum):
    REPRODUCED = "reproduced"  # failed, for the right reason, on every run
    NOT_REPRODUCED = "not_reproduced"
    FLAKY = "flaky"
    INVALID = "invalid"
    ERROR = "error"


def classify_run(returncode: int, output: str) -> RunOutcome:
    """Map one pytest exit code + output to an outcome (exit codes per pytest docs)."""
    if returncode == 0:
        return RunOutcome.PASSED
    if returncode == 1:
        return RunOutcome.INVALID if WRONG_REASON.search(output) else RunOutcome.FAILED
    if returncode in (2, 5):  # collection errors / interrupted, or no tests collected
        return RunOutcome.INVALID
    return RunOutcome.ERROR


def combine(outcomes: list[RunOutcome]) -> Verdict:
    """Fold per-run outcomes into one verdict."""
    if not outcomes:
        raise ValueError("no runs to combine")
    kinds = set(outcomes)
    if RunOutcome.INVALID in kinds:
        return Verdict.INVALID
    if kinds & {RunOutcome.TIMEOUT, RunOutcome.ERROR}:
        return Verdict.ERROR
    if kinds == {RunOutcome.FAILED}:
        return Verdict.REPRODUCED
    if kinds == {RunOutcome.PASSED}:
        return Verdict.NOT_REPRODUCED
    return Verdict.FLAKY


def run_reproduction(repo_dir: str, test_relpath: str, test_code: str) -> dict[str, Any]:
    """Write `test_code` to `test_relpath` in the checkout, run it N times, return the verdict.

    `test_relpath` must be a repo-relative file named test_issue_repro*.py.
    """
    root = resolve_checkout(repo_dir)
    target = (root / test_relpath).resolve()
    if root not in target.parents or not TEST_NAME.match(target.name):
        raise ValueError(
            "test_relpath must be a file named test_issue_repro*.py inside the checkout"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(test_code, encoding="utf-8")
    return _run_repeatedly(root, target)


def rerun_test(repo_dir: str, test_relpath: str) -> dict[str, Any]:
    """Run an existing reproduction test again (e.g. after applying the real fix)."""
    root = resolve_checkout(repo_dir)
    target = (root / test_relpath).resolve()
    if root not in target.parents or not TEST_NAME.match(target.name) or not target.is_file():
        raise ValueError(
            f"{test_relpath!r} is not an existing test_issue_repro*.py in the checkout"
        )
    return _run_repeatedly(root, target)


def _run_repeatedly(root: Path, target: Path) -> dict[str, Any]:
    settings = get_settings()
    outcomes: list[RunOutcome] = []
    output = ""
    for _ in range(settings.repro_runs):
        outcome, output = _run_once(root, target, settings.test_timeout_s)
        outcomes.append(outcome)
        if outcome in (RunOutcome.INVALID, RunOutcome.ERROR, RunOutcome.TIMEOUT):
            break  # later runs cannot change the verdict
    return {
        "verdict": str(combine(outcomes)),
        "runs": [str(o) for o in outcomes],
        "test_path": str(target.relative_to(root)),
        "last_output_tail": output[-OUTPUT_TAIL_CHARS:],
    }


def _python_for(root: Path) -> str:
    """Prefer the checkout's own virtualenv (see backtest.checkout); else this interpreter."""
    venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def _run_once(root: Path, target: Path, timeout_s: int) -> tuple[RunOutcome, str]:
    command = [_python_for(root), "-m", "pytest", "-q", "-p", "no:cacheprovider", str(target)]
    try:
        # check=False: a failing test is an expected outcome, classified below.
        done = subprocess.run(
            command,
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            # No bytecode cache: after the fix is applied, a same-size source file edited within
            # the same second would otherwise run from stale .pyc files.
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        return RunOutcome.TIMEOUT, partial + f"\n[timed out after {timeout_s}s]"
    output = done.stdout + done.stderr
    return classify_run(done.returncode, output), output
