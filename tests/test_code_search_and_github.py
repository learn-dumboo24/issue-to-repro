import io
import json
import urllib.error
import urllib.request

import pytest

from issue_to_repro.tools import fetch_issue_tool, read_file_tool, search_code_tool
from issue_to_repro.tools.code_search import read_file, search_code
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


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


ISSUE_JSON = {
    "html_url": "https://github.com/o/r/issues/7",
    "title": "Crash on empty input",
    "body": None,
    "labels": [],
    "state": "closed",
}


def test_fetch_issue_calls_the_rest_api(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        seen["auth"] = request.get_header("Authorization")
        return FakeResponse(json.dumps(ISSUE_JSON).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    issue = fetch_issue("o/r", 7)
    assert seen == {"url": "https://api.github.com/repos/o/r/issues/7", "timeout": 20, "auth": None}
    assert issue["title"] == "Crash on empty input"
    assert issue["body"] == "" and not issue["is_pull_request"]


def test_fetch_issue_sends_token_when_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["auth"] = request.get_header("Authorization")
        return FakeResponse(json.dumps(ISSUE_JSON).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fetch_issue("o/r", 7)
    assert seen["auth"] == "Bearer t0ken"


def test_tool_wrappers_return_errors(workspace, monkeypatch):
    def offline(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    assert fetch_issue_tool("o/r", 1)["status"] == "error"
    assert search_code_tool(str(workspace), "")["status"] == "error"
    assert search_code_tool(str(workspace), "def add")["status"] == "ok"


def test_search_skips_files_that_are_not_utf8(workspace):
    (workspace / "latin1.txt").write_bytes("caf\xe9 def add".encode("latin-1"))
    assert [h["path"] for h in search_code(str(workspace), "def add")] == ["demo/__init__.py"]


def test_search_stops_at_max_results(workspace):
    (workspace / "many.py").write_text("x = 1\n" * 50)
    assert len(search_code(str(workspace), "x = 1", max_results=5)) == 5


def test_checkout_must_be_a_directory(workspace):
    with pytest.raises(ValueError, match="not a directory"):
        search_code(str(workspace / "README.md"), "add")


def test_read_file_returns_numbered_lines(workspace):
    assert read_file(str(workspace), "demo/__init__.py") == (
        "    1  def add(a, b):\n    2      return a - b  # bug"
    )
    assert read_file(str(workspace), "demo/__init__.py", 2, 2) == "    2      return a - b  # bug"


def test_read_file_caps_lines_and_says_where_to_continue(workspace):
    (workspace / "big.py").write_text("".join(f"line{n}\n" for n in range(1, 501)))
    text = read_file(str(workspace), "big.py", 10)
    assert text.splitlines()[0] == "   10  line10"
    assert text.splitlines()[-1] == "... (500 lines in total; read on from 210)"


@pytest.mark.parametrize("path", ["../outside.py", "demo", "missing.py"])
def test_read_file_rejects_paths_outside_or_missing(workspace, path):
    with pytest.raises(ValueError):
        read_file(str(workspace), path)


def test_read_file_tool_wraps_errors(workspace):
    assert read_file_tool(str(workspace), "demo/__init__.py")["status"] == "ok"
    assert read_file_tool(str(workspace), "x.py", start_line=0)["status"] == "error"
    assert read_file_tool(str(workspace), "demo/__init__.py", start_line=0)["status"] == "error"
