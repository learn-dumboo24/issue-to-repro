"""Post a stored reproduction only after a maintainer with write access approves it."""

from dataclasses import dataclass
from typing import Protocol

from .drafts import Draft, DraftStore, mark_posted
from .events import Approve

WRITE_LEVELS = frozenset({"admin", "maintain", "write"})
MAX_TEST_CHARS = 20_000


class GitHub(Protocol):
    def permission(self, repo: str, user: str, installation_id: int | None) -> str: ...

    def post_comment(
        self, repo: str, issue_number: int, body: str, installation_id: int | None
    ) -> str: ...


@dataclass(frozen=True)
class Outcome:
    posted: bool
    reason: str
    url: str | None = None


def render_comment(draft: Draft, approved_by: str) -> str:
    code = (draft.test_code or "")[:MAX_TEST_CHARS]
    fence = "````" if "```" in code else "```"
    return "\n".join(
        [
            "### Reproduction test",
            "",
            (
                "This test fails on the current code because of the bug reported here. It was "
                "written by [issue-to-repro](https://github.com/learn-dumboo24/issue-to-repro), "
                f"run three times in an isolated sandbox, and approved for posting by @{approved_by}."
            ),
            "",
            f"`{draft.test_path}`",
            "",
            f"{fence}python",
            code,
            fence,
            "",
            "<details><summary>Agent report</summary>",
            "",
            draft.report.strip(),
            "",
            "</details>",
        ]
    )


def handle_approval(action: Approve, store: DraftStore, github: GitHub) -> Outcome:
    draft = store.get(action.repo, action.issue_number)
    if draft is None:
        return Outcome(False, "no draft for this issue")
    if draft.status == "posted":
        return Outcome(False, "already posted", draft.comment_url)
    if draft.status != "pending" or draft.verdict != "reproduced" or not draft.test_code:
        return Outcome(False, f"nothing verified to post (status {draft.status})")
    level = github.permission(action.repo, action.actor, action.installation_id)
    if level not in WRITE_LEVELS:
        return Outcome(False, f"@{action.actor} has {level!r} access; write access is required")
    body = render_comment(draft, action.actor)
    url = github.post_comment(action.repo, action.issue_number, body, action.installation_id)
    store.save(mark_posted(draft, url, action.actor))
    return Outcome(True, "posted", url)
