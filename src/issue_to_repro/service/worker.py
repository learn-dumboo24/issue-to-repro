"""Do the work behind each webhook action: reproduce an issue into a draft, or post an approved one.

A live issue comes from someone else's repository, so the worker refuses to run unless the docker
sandbox is configured: its tests must never execute directly on the host.
"""

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..backtest.runner import AgentRun, issue_prompt
from ..config import Settings, get_settings
from .approval import GitHub, Outcome, handle_approval
from .drafts import Draft, DraftStore
from .events import Action, Approve, Reproduce

log = logging.getLogger(__name__)

Fetch = Callable[[str, int], dict[str, Any]]
PrepareLive = Callable[[str, int], Path]
RunPrompt = Callable[[str, Settings], AgentRun]


@dataclass
class Deps:
    store: DraftStore
    github: GitHub
    fetch: Fetch
    prepare: PrepareLive
    run: RunPrompt
    settings: Settings = field(default_factory=get_settings)


def reproduce_issue(action: Reproduce, deps: Deps) -> Draft:
    if deps.settings.sandbox != "docker":
        raise RuntimeError("live issues run untrusted code: set SANDBOX=docker for the service")
    issue = deps.fetch(action.repo, action.issue_number)
    checkout = deps.prepare(action.repo, action.issue_number)
    ref = f"{action.repo}#{action.issue_number}"
    run = deps.run(issue_prompt(ref, issue["title"], issue["body"], checkout), deps.settings)
    attempts = [r["result"] for r in run.repro_results if r.get("status") == "ok"]
    last = attempts[-1] if attempts else None
    reproduced = last is not None and last["verdict"] == "reproduced"
    draft = Draft(
        repo=action.repo,
        issue_number=action.issue_number,
        status="pending" if reproduced else "not_reproduced",
        verdict=last["verdict"] if last else "no_attempt",
        test_path=last["test_path"] if last else None,
        test_code=(checkout / last["test_path"]).read_text(encoding="utf-8") if last else None,
        report=run.final_text,
    )
    deps.store.save(draft)
    return draft


def handle(action: Action, deps: Deps) -> Draft | Outcome | None:
    if isinstance(action, Reproduce):
        return reproduce_issue(action, deps)
    if isinstance(action, Approve):
        return handle_approval(action, deps.store, deps.github)
    return None


class WorkerQueue:
    """One background thread working through actions in order. Failures are logged with the
    action that caused them and the worker carries on; nothing is dropped silently."""

    def __init__(self, handler: Callable[[Action], object]) -> None:
        self._handler = handler
        self._queue: queue.Queue[Action | None] = queue.Queue()
        self.failures: list[tuple[Action, str]] = []
        self._thread = threading.Thread(
            target=self._loop, name="issue-to-repro-worker", daemon=True
        )
        self._thread.start()

    def put(self, action: Action) -> None:
        self._queue.put(action)

    def join(self) -> None:
        self._queue.join()

    def stop(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=10)

    def _loop(self) -> None:
        while True:
            action = self._queue.get()
            if action is None:  # stop signal
                self._queue.task_done()
                return
            try:
                self._handler(action)
            except Exception as exc:
                log.exception("job failed: %r", action)
                self.failures.append((action, f"{type(exc).__name__}: {exc}"))
            finally:
                self._queue.task_done()
