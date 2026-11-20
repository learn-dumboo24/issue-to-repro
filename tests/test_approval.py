import pytest

from issue_to_repro.service.approval import handle_approval, render_comment
from issue_to_repro.service.drafts import Draft, FileDraftStore, mark_posted
from issue_to_repro.service.events import Approve

TEST_CODE = "def test_bug():\n    assert add(2, 2) == 4\n"


def draft(**overrides) -> Draft:
    values = {
        "repo": "o/r",
        "issue_number": 7,
        "status": "pending",
        "verdict": "reproduced",
        "test_path": "tests/test_issue_repro_7.py",
        "test_code": TEST_CODE,
        "report": "Fails because add subtracts.",
    }
    values.update(overrides)
    return Draft(**values)


class FakeGitHub:
    def __init__(self, level: str = "write") -> None:
        self.level = level
        self.posted: list[tuple[str, int, str]] = []

    def permission(self, repo, user, installation_id):
        return self.level

    def post_comment(self, repo, issue_number, body, installation_id):
        self.posted.append((repo, issue_number, body))
        return f"https://github.com/{repo}/issues/{issue_number}#issuecomment-1"


APPROVE = Approve("o/r", 7, "maintainer", 99)


def test_store_round_trip_and_missing(tmp_path):
    store = FileDraftStore(tmp_path / "drafts")
    assert store.get("o/r", 7) is None
    store.save(draft())
    assert store.get("o/r", 7) == draft()
    store.save(mark_posted(draft(), "u", "m"))
    assert store.get("o/r", 7).status == "posted"
    assert [p.name for p in (tmp_path / "drafts").iterdir()] == [
        "o_r__7.json"
    ]  # no temp files left


def test_posts_once_for_a_maintainer(tmp_path):
    store, github = FileDraftStore(tmp_path), FakeGitHub("maintain")
    store.save(draft())
    outcome = handle_approval(APPROVE, store, github)
    assert outcome.posted and outcome.url.endswith("issuecomment-1")
    assert (
        store.get("o/r", 7).status == "posted" and store.get("o/r", 7).approved_by == "maintainer"
    )
    again = handle_approval(APPROVE, store, github)
    assert (again.posted, again.reason) == (False, "already posted")
    assert len(github.posted) == 1


@pytest.mark.parametrize("level", ["read", "triage", "none"])
def test_refuses_users_without_write_access(tmp_path, level):
    store, github = FileDraftStore(tmp_path), FakeGitHub(level)
    store.save(draft())
    outcome = handle_approval(APPROVE, store, github)
    assert not outcome.posted and "write access is required" in outcome.reason
    assert github.posted == [] and store.get("o/r", 7).status == "pending"


@pytest.mark.parametrize(
    "overrides",
    [{"status": "not_reproduced"}, {"verdict": "flaky"}, {"test_code": None}, {"test_code": ""}],
)
def test_never_posts_unverified_drafts(tmp_path, overrides):
    store, github = FileDraftStore(tmp_path), FakeGitHub()
    store.save(draft(**overrides))
    outcome = handle_approval(APPROVE, store, github)
    assert not outcome.posted and outcome.reason.startswith("nothing verified to post")
    assert github.posted == []


def test_no_draft(tmp_path):
    assert (
        handle_approval(APPROVE, FileDraftStore(tmp_path), FakeGitHub()).reason
        == "no draft for this issue"
    )


def test_comment_contents_and_fences():
    body = render_comment(draft(), "maintainer")
    assert "approved for posting by @maintainer" in body
    assert "```python\n" + TEST_CODE in body and "`tests/test_issue_repro_7.py`" in body
    assert "<details><summary>Agent report</summary>" in body
    tricky = render_comment(draft(test_code='s = """```"""\n'), "m")
    assert "````python" in tricky  # a longer fence when the code contains ```
