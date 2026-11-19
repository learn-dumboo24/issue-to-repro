import io
import urllib.error

import pytest

from issue_to_repro.backtest.dataset import build_dataset, read_jsonl, write_jsonl


def issue(number: int, *, pull_request: bool = False) -> dict:
    return {
        "url": f"https://github.com/o/r/issues/{number}",
        "title": f"Bug {number}",
        "body": "Steps to reproduce...",
        "labels": ["bug"],
        "state": "closed",
        "created_at": "2020-05-01T00:00:00Z",
        "is_pull_request": pull_request,
    }


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api", code, "x", {}, io.BytesIO())  # type: ignore[arg-type]


def test_builds_cases_with_issue_text(history):
    repo, base, fix = history
    cases, skipped = build_dataset("o/r", repo, since="2020-01-01", fetch=lambda r, n: issue(n))
    assert skipped == []
    [case] = cases
    assert case.case_id == "o/r#12"
    assert (case.base_commit, case.fix_commit) == (base, fix)
    assert case.issue_title == "Bug 12" and case.issue_labels == ("bug",)
    assert case.test_files == ("tests/test_core.py",)


def test_skips_pull_requests_and_deleted_issues_with_reasons(history):
    repo, _, _ = history
    _, skipped = build_dataset(
        "o/r", repo, since="2020-01-01", fetch=lambda r, n: issue(n, pull_request=True)
    )
    assert [s.reason for s in skipped] == ["reference is a pull request, not an issue"]

    def gone(r, n):
        raise http_error(404)

    _, skipped = build_dataset("o/r", repo, since="2020-01-01", fetch=gone)
    assert skipped[0].reason == "issue unavailable (HTTP 404)"


def test_other_http_errors_propagate(history):
    repo, _, _ = history

    def rate_limited(r, n):
        raise http_error(403)

    with pytest.raises(urllib.error.HTTPError):
        build_dataset("o/r", repo, since="2020-01-01", fetch=rate_limited)


def test_jsonl_round_trip(history, tmp_path):
    repo, _, _ = history
    cases, _ = build_dataset("o/r", repo, since="2020-01-01", fetch=lambda r, n: issue(n))
    path = tmp_path / "cases.jsonl"
    assert write_jsonl(cases, path) == 1
    assert read_jsonl(path) == cases


def test_read_jsonl_reports_bad_lines(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"repo": "o/r"}\n')
    with pytest.raises(ValueError, match="bad.jsonl:1"):
        read_jsonl(path)
