"""Turn a GitHub webhook delivery into the one action the service should take."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reproduce:
    repo: str
    issue_number: int
    installation_id: int | None


@dataclass(frozen=True)
class Approve:
    repo: str
    issue_number: int
    actor: str
    installation_id: int | None


@dataclass(frozen=True)
class Ignore:
    reason: str


Action = Reproduce | Approve | Ignore


def route(event: str, payload: dict[str, Any], approve_label: str) -> Action:
    """Decide what to do with one delivery. Anything unexpected is ignored, never guessed."""
    if event == "ping":
        return Ignore("ping")
    if event != "issues":
        return Ignore(f"event {event!r} is not handled")
    repo = payload.get("repository") or {}
    issue = payload.get("issue") or {}
    name, number = repo.get("full_name"), issue.get("number")
    if not isinstance(name, str) or not isinstance(number, int):
        return Ignore("payload has no repository or issue number")
    if repo.get("private", True):
        return Ignore("private repositories are out of scope (public data only)")
    if "pull_request" in issue:
        return Ignore("pull requests are not issues")
    installation = (payload.get("installation") or {}).get("id")
    action = payload.get("action")
    if action == "opened":
        return Reproduce(name, number, installation)
    if action == "labeled" and (payload.get("label") or {}).get("name") == approve_label:
        actor = (payload.get("sender") or {}).get("login")
        if not isinstance(actor, str):
            return Ignore("label event has no sender")
        return Approve(name, number, actor, installation)
    return Ignore(f"issues.{action} is not handled")
