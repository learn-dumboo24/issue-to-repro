import pytest

from issue_to_repro.tools.code_search import search_code
from issue_to_repro.tools.github import fetch_issue, parse_issue


def test_search_finds_definition(workspace):
    hits = search_code(str(workspace), "def ADD")
    assert hits == [{"path": "demo/__init__.py", "line": 1, "text": "def add(a, b):"}]


def test_search_skips_virtualenvs(workspace):
    venv = workspace / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "x.py").write_text("def add(): pass\n")
    assert all(".venv" not in h["path"] for h in search_code(str(workspace), "def add"))


def test_search_rejects_empty_query(workspace):
    with pytest.raises(ValueError):
        search_code(str(workspace), "  ")


def test_parse_issue_truncates_and_flags_pull_requests():
    data = {
        "html_url": "https://github.com/o/r/issues/1",
        "title": "add() subtracts",
        "body": "x" * 25_000,
        "labels": [{"name": "bug"}],
        "state": "open",
        "pull_request": {},
    }
    issue = parse_issue(data)
    assert issue["labels"] == ["bug"]
    assert issue["body_truncated"] and len(issue["body"]) == 20_000
    assert issue["is_pull_request"]


@pytest.mark.parametrize(("repo", "number"), [("not a repo", 1), ("o/r; rm -rf", 1), ("o/r", 0)])
def test_fetch_issue_validates_before_any_network_call(repo, number):
    with pytest.raises(ValueError):
        fetch_issue(repo, number)
