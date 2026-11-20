"""Re-prove benchmark tasks without any model: each test must fail at the buggy commit and pass
once the maintainers' fix is applied. Verdicts come from the sandbox (`tools/sandbox.py`)."""

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..tools.sandbox import rerun_test, run_reproduction
from .tasks import BenchTask

PrepareTask = Callable[[BenchTask], Path]


@dataclass
class TaskCheck:
    instance_id: str
    ok: bool
    before: str  # sandbox verdict at base_commit; must be "reproduced"
    before_runs: list[str]
    after_runs: list[str] | None  # runs with gold_patch applied; must all pass
    error: str | None
    latency_s: float


def _git(checkout: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args], input=stdin, check=True, capture_output=True, text=True
    ).stdout


def verify_task(task: BenchTask, prepare: PrepareTask) -> TaskCheck:
    started = time.monotonic()
    before: dict[str, Any] = {"verdict": "not_run", "runs": []}
    after: list[str] | None = None

    def result(error: str | None) -> TaskCheck:
        return TaskCheck(
            instance_id=task.instance_id,
            ok=error is None,
            before=str(before["verdict"]),
            before_runs=[str(r) for r in before["runs"]],
            after_runs=after,
            error=error,
            latency_s=round(time.monotonic() - started, 1),
        )

    checkout = prepare(task)
    head = _git(checkout, "rev-parse", "HEAD").strip()
    if head != task.base_commit:
        return result(f"checkout is at {head}, expected {task.base_commit}")
    before = run_reproduction(str(checkout), task.test_path, task.test_code)
    if before["verdict"] != "reproduced":
        return result(f"test does not fail at base: {before['verdict']}")
    try:
        _git(checkout, "apply", "--check", "-", stdin=task.gold_patch)
    except subprocess.CalledProcessError as exc:
        return result(f"gold patch does not apply: {exc.stderr.strip()}")
    _git(checkout, "apply", "-", stdin=task.gold_patch)
    try:
        after = list(rerun_test(str(checkout), task.test_path)["runs"])
    finally:
        _git(checkout, "apply", "-R", "-", stdin=task.gold_patch)
    if not all(run == "passed" for run in after):
        return result("test does not pass with the fix")
    return result(None)


def verify_tasks(tasks: list[BenchTask], prepare: PrepareTask) -> list[TaskCheck]:
    return [verify_task(task, prepare) for task in tasks]
