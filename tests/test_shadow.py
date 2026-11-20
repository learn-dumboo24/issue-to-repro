import io
import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from conftest import commit, git

import issue_to_repro
from issue_to_repro.backtest.runner import AgentRun
from issue_to_repro.config import Settings
from issue_to_repro.shadow.run import (
    classification,
    done_issues,
    fence,
    load_results,
    render_markdown,
    run_candidate,
    run_shadow,
)
from issue_to_repro.shadow.select import (
    Candidate,
    ShadowConfig,
    load_config,
    select_issues,
    skip_reason,
)
from issue_to_repro.tools import github
from issue_to_repro.tools.github import fetch_issue, list_open_issues
from issue_to_repro.tools.sandbox import run_reproduction

NOW = datetime(2026, 11, 20, tzinfo=UTC)
FAILING = "from demo import add\n\ndef test_add():\n    assert add(2, 2) == 4\n"
BODY = (
    "add() returns the wrong result for small numbers. Calling it like this:\n\n"
    "```python\nfrom demo import add\nadd(2, 2)  # returns 0, expected 4\n```\n"
)
CONFIG = ShadowConfig(repos=("o/r",), per_repo=2, max_age_days=90)


def issue(number=1, created="2026-11-01T00:00:00Z", body=BODY, labels=(), **extra):
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": body,
        "body_truncated": False,
        "labels": list(labels),
        "url": f"https://github.com/o/r/issues/{number}",
        "created_at": created,
        "is_pull_request": False,
        **extra,
    }


# --- selection -------------------------------------------------------------------------------


def test_load_config_reads_limits_and_validates(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"repos": ["o/r"], "per_repo": 3, "skip_labels": ["nope"]}))
    config = load_config(path)
    assert (config.repos, config.per_repo, config.max_age_days) == (("o/r",), 3, 90)
    assert config.skip_labels == ("nope",)
    for bad, message in [
        ({"repos": []}, "no repos"),
        ({"repos": ["not a repo"]}, "not a repository"),
        ({"repos": ["o/r"], "per_repo": 0}, "positive"),
    ]:
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match=message):
            load_config(path)


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (issue(), None),
        (issue(body="Traceback (most recent call last):\n" + "x" * 100), None),
        (issue(is_pull_request=True), "pull request"),
        (issue(created="2026-01-01T00:00:00Z"), "too old"),
        (issue(labels=["type: Feature request"]), "label 'type: Feature request'"),
        (issue(labels=["bug"]), None),
        (issue(body_truncated=True), "body too long"),
        (issue(body="```x```"), "body too short"),
        (issue(body="It is broken. " * 20), "no code in the report"),
    ],
)
def test_skip_reason(item, reason):
    assert skip_reason(item, NOW, CONFIG) == reason


def test_select_takes_the_newest_candidates_not_already_done():
    issues = [
        issue(1, "2026-10-01T00:00:00Z"),
        issue(2, "2026-11-10T00:00:00Z"),
        issue(3, "2026-11-05T00:00:00Z", labels=["question"]),
        issue(4, "2026-11-08T00:00:00Z"),
        issue(5, "2026-11-12T00:00:00Z"),
    ]
    picked = select_issues("o/r", issues, CONFIG, done={("o/r", 5)}, now=NOW)
    assert [c.number for c in picked] == [2, 4]
    assert picked[0] == Candidate(
        "o/r", 2, "Issue 2", BODY, "https://github.com/o/r/issues/2", "2026-11-10T00:00:00Z", ()
    )
    assert select_issues("o/r", [issue()], CONFIG, set())  # defaults to the real clock


# --- GitHub listing ----------------------------------------------------------------------------


def fake_api(monkeypatch, payload, seen=None):
    def urlopen(request, timeout):
        if seen is not None:
            seen.append(request)
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)


def test_list_open_issues_skips_pull_requests_and_adds_numbers(monkeypatch):
    item = {"html_url": "u", "title": "t", "body": "b", "state": "open", "number": 7}
    seen: list = []
    fake_api(
        monkeypatch, [{**item, "comments": 2}, {**item, "number": 8, "pull_request": {}}], seen
    )
    [only] = list_open_issues("o/r", per_page=50)
    assert (only["number"], only["comments"], only["title"]) == (7, 2, "t")
    assert seen[0].full_url.endswith(
        "/repos/o/r/issues?state=open&sort=created&direction=desc&per_page=50"
    )


def test_list_open_issues_validates_input_and_response(monkeypatch):
    with pytest.raises(ValueError, match="owner/name"):
        list_open_issues("bad")
    with pytest.raises(ValueError, match="per_page"):
        list_open_issues("o/r", per_page=101)
    fake_api(monkeypatch, {"message": "not a list"})
    with pytest.raises(TypeError, match="listing issues"):
        list_open_issues("o/r")
    fake_api(monkeypatch, [])
    with pytest.raises(TypeError, match="unexpected response for o/r#1"):
        fetch_issue("o/r", 1)


# --- running -----------------------------------------------------------------------------------


@pytest.fixture
def checkout(workspace):
    git(workspace, "init", "-q")
    commit(workspace, "buggy", {})
    return workspace


def fake_run(code=FAILING, classifier="[classifier] bug: add subtracts"):
    def run(prompt, settings):
        agent_run = AgentRun(llm_calls=4, prompt_tokens=90, output_tokens=10, final_text="report")
        agent_run.trace = ["[retriever] looked", classifier] if classifier else []
        if code is not None:
            root = prompt.split("checked out at ", 1)[1].split(".\n", 1)[0]
            result = run_reproduction(root, "test_issue_repro_1.py", code)
            agent_run.repro_results.append({"status": "ok", "result": result})
        return agent_run

    return run


def candidate(number=1):
    return Candidate("o/r", number, "add() subtracts", BODY, "https://x/1", "2026-11-01", ())


def test_run_candidate_records_the_sandbox_verdict_and_commit(checkout):
    result = run_candidate(candidate(), lambda r, n: checkout, fake_run(), Settings())
    assert (result.verdict, result.classification, result.attempts) == ("reproduced", "bug", 1)
    assert result.commit == git(checkout, "rev-parse", "HEAD")
    assert (result.test_code, result.tokens, result.report) == (FAILING, 100, "report")
    assert "assert" in result.output_tail and result.error is None


def test_run_candidate_without_an_attempt(checkout):
    run = fake_run(code=None, classifier="[classifier] Feature_request: wants more")
    result = run_candidate(candidate(), lambda r, n: checkout, run, Settings())
    assert (result.verdict, result.classification, result.test_code) == (
        "no_attempt",
        "feature_request",
        None,
    )


def test_a_failed_checkout_is_recorded_not_raised(tmp_path):
    def prepare(repo, number):
        raise subprocess.CalledProcessError(1, ["uv"], stderr="build failed")

    result = run_candidate(candidate(), prepare, fake_run(), Settings())
    assert (result.verdict, result.error) == ("setup_error", "CalledProcessError: build failed")
    assert result.llm_calls == 0


def test_classification_handles_missing_or_empty_lines():
    assert classification(["[reporter] x"]) == "unknown"
    assert classification(["[classifier] ???"]) == "unknown"


def test_run_shadow_refuses_outside_docker_and_appends_with_docker(checkout, tmp_path):
    out = tmp_path / "shadow.jsonl"
    with pytest.raises(RuntimeError, match="SANDBOX=docker"):
        run_shadow([candidate()], out, lambda r, n: checkout, fake_run(), Settings())
    # The settings object says docker; the tests' own sandbox still runs locally (env unset).
    docker = Settings(sandbox="docker")
    run_shadow([candidate(1), candidate(2)], out, lambda r, n: checkout, fake_run(), docker)
    rows = load_results(out)
    assert [(r["issue"], r["verdict"]) for r in rows] == [(1, "reproduced"), (2, "reproduced")]
    assert done_issues(rows) == {("o/r", 1), ("o/r", 2)}
    assert load_results(tmp_path / "missing.jsonl") == []


# --- report ------------------------------------------------------------------------------------


def row(number, verdict, **extra):
    base = {
        "repo": "o/r",
        "issue": number,
        "title": f"Issue {number}",
        "url": f"https://github.com/o/r/issues/{number}",
        "classification": "bug",
        "verdict": verdict,
        "llm_calls": 5,
        "tokens": 1000,
        "commit": "abcdef1234567890",
        "test_path": "test_issue_repro_1.py",
        "test_code": FAILING,
        "error": None,
        "stopped": None,
    }
    return {**base, **extra}


def test_render_markdown_summarises_and_lists_tests_to_review():
    rows = [
        row(2, "not_reproduced", classification="feature_request", test_code=None),
        row(1, "reproduced"),
        row(3, "setup_error", error="CalledProcessError: build failed", llm_calls=0),
        row(4, "no_attempt", stopped="llm_call_limit"),
    ]
    markdown = render_markdown(rows, "Shadow")
    assert markdown.startswith("# Shadow\n\n1 of 4 issues reproduced · 4,000 tokens")
    assert "classified as: bug 3, feature_request 1" in markdown
    assert "**Unreviewed.**" in markdown
    table = [line for line in markdown.splitlines() if line.startswith("| [o/r#")]
    assert [line.split("]")[0] for line in table] == [
        "| [o/r#1",
        "| [o/r#2",
        "| [o/r#3",
        "| [o/r#4",
    ]
    assert "setup_error (CalledProcessError: build failed)" in table[2]
    assert "no_attempt, stopped: llm_call_limit" in table[3]
    assert "### [o/r#1](https://github.com/o/r/issues/1): Issue 1" in markdown
    assert "failing at abcdef123456:" in markdown
    assert "```python\n" + FAILING.rstrip("\n") + "\n```" in markdown


def test_render_markdown_neutralises_untrusted_issue_text():
    title = "Bad | title <img src=x onerror=alert(1)> `code`\nnext line " + "x" * 100
    code = 'def test_x():\n    s = """\n```\n"""\n'
    markdown = render_markdown([row(1, "reproduced", title=title, test_code=code)], "T")
    assert "<img" not in markdown and "&lt;img" in markdown
    assert "Bad \\| title" in markdown and "\nnext line" not in markdown
    assert "…" in markdown  # long titles are cut
    assert fence(code) == "````" and "````python\n" in markdown


def test_render_markdown_without_a_commit():
    assert "failing at unknown:" in render_markdown([row(1, "reproduced", commit=None)], "T")


# --- CLI ---------------------------------------------------------------------------------------


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["issue-to-repro", *args])
    issue_to_repro.main()


def test_shadow_cli_runs_selected_issues_and_reports(monkeypatch, checkout, tmp_path, capsys):
    from issue_to_repro.backtest import checkout as checkout_module
    from issue_to_repro.backtest import runner

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"repos": ["o/r", "o/other"], "per_repo": 5}))
    listed: list[str] = []

    def list_issues(repo):
        listed.append(repo)
        return [issue(1, datetime.now(UTC).isoformat())]

    def canned_run(prompt, settings):  # no sandbox here: SANDBOX=docker is set for the CLI
        (checkout / "test_issue_repro_1.py").write_text(FAILING)
        result = {"verdict": "reproduced", "test_path": "test_issue_repro_1.py", "runs": []}
        agent_run = AgentRun(llm_calls=3, trace=["[classifier] bug: yes"])
        agent_run.repro_results.append({"status": "ok", "result": result})
        return agent_run

    monkeypatch.setattr(github, "list_open_issues", list_issues)
    monkeypatch.setattr(checkout_module, "prepare_live_checkout", lambda r, n, root: checkout)
    monkeypatch.setattr(runner, "run_prompt_adk", canned_run)
    monkeypatch.setenv("SANDBOX", "docker")
    out = tmp_path / "results" / "shadow.jsonl"
    args = ["shadow", "run", "--config", str(config), "--out", str(out)]
    run_cli(monkeypatch, *args, "--repos", "o/r", "--per-repo", "1")
    printed = capsys.readouterr().out
    assert listed == ["o/r"] and "o/r: [1]" in printed
    assert "o/r#1: bug reproduced calls=3" in printed
    run_cli(monkeypatch, *args, "--repos", "o/r")  # resumes: issue 1 is not run again
    assert "o/r: []" in capsys.readouterr().out
    assert len(load_results(out)) == 1

    report = tmp_path / "shadow.md"
    run_cli(monkeypatch, "shadow", "report", "--results", str(out), "--out", str(report))
    assert report.read_text().startswith("# Shadow run\n\n1 of 1 issues reproduced")
    capsys.readouterr()  # drop the "wrote ..." line
    run_cli(monkeypatch, "shadow", "report", "--results", str(out), "--title", "T")
    assert capsys.readouterr().out.startswith("# T\n")

    with pytest.raises(SystemExit, match="not in the config"):
        run_cli(monkeypatch, *args, "--repos", "x/y")

    # Issues in earlier runs' results are skipped when --skip-tried points at them.
    earlier = tmp_path / "earlier"
    earlier.mkdir()
    (earlier / "run-1.jsonl").write_text(json.dumps({"repo": "o/r", "issue": 1}) + "\n")
    fresh = tmp_path / "fresh.jsonl"
    fresh_args = ["shadow", "run", "--config", str(config), "--out", str(fresh)]
    run_cli(monkeypatch, *fresh_args, "--repos", "o/r", "--skip-tried", str(earlier))
    printed = capsys.readouterr().out
    assert "skipping 1 issues tried before" in printed and "o/r: []" in printed
    with pytest.raises(SystemExit, match="no such folder"):
        run_cli(monkeypatch, *fresh_args, "--skip-tried", str(tmp_path / "missing"))


def test_shadow_cli_refuses_without_docker_and_empty_reports(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="SANDBOX=docker"):
        run_cli(monkeypatch, "shadow", "run", "--config", "c.json", "--out", "o.jsonl")
    with pytest.raises(SystemExit, match="no results"):
        run_cli(monkeypatch, "shadow", "report", "--results", str(tmp_path / "none.jsonl"))
