import json
import sys
from pathlib import Path

import pytest
from conftest import commit, git

import issue_to_repro
from issue_to_repro.backtest import demo
from issue_to_repro.backtest.demo import (
    DemoIssue,
    check_against_fix,
    fix_files,
    load_results,
    parse_issues,
    render_markdown,
    run_demo,
    run_issue,
)
from issue_to_repro.backtest.runner import AgentRun
from issue_to_repro.config import Settings
from issue_to_repro.tools.sandbox import run_reproduction

ROOT = Path(__file__).resolve().parents[1]
BUGGY = "def add(a, b):\n    return a - b  # bug\n"
FIXED = "def add(a, b):\n    return a + b\n"
FAILING = "from demo import add\n\ndef test_add():\n    assert add(2, 2) == 4\n"
ISSUES_MD = """# Demo issues

Intro text.

## Issue 1

**Title:** add() subtracts

**Body:**

`add(2, 2)` returns 0.

---

## Issue 2

**Title:** Feature: multiply

**Body:**

Please add multiply().
"""


@pytest.fixture
def checkout(workspace):
    """The workspace's buggy repo as a git checkout, like a real clone."""
    git(workspace, "init", "-q")
    commit(workspace, "buggy", {})
    return workspace


@pytest.fixture
def fix_dir(tmp_path):
    fix = tmp_path / "fix"
    (fix / "demo").mkdir(parents=True)
    (fix / "demo" / "__init__.py").write_text(FIXED)
    return fix


def fake_run(code=FAILING, calls=None):
    def run(prompt, settings):
        if calls is not None:
            calls.append(prompt)
        agent_run = AgentRun(llm_calls=3, prompt_tokens=100, output_tokens=20, final_text="done")
        if code is not None:
            root = prompt.split("checked out at ", 1)[1].split(".\n", 1)[0]
            result = run_reproduction(root, "test_issue_repro_1.py", code)
            agent_run.repro_results.append({"status": "ok", "result": result})
        return agent_run

    return run


def test_parse_issues_reads_title_and_body_up_to_the_rule():
    issues = parse_issues(ISSUES_MD)
    assert issues == [
        DemoIssue(1, "add() subtracts", "`add(2, 2)` returns 0."),
        DemoIssue(2, "Feature: multiply", "Please add multiply()."),
    ]


@pytest.mark.parametrize(
    ("markdown", "message"),
    [
        ("# nothing here\n", "no '## Issue N'"),
        ("## Issue 1\n\n**Body:**\n\ntext\n", "Title"),
        ("## Issue 1\n\n**Title:** t\n\n**Body:**\n\n---\n", "empty body"),
        ("## Issue 1\n**Title:** a\n**Body:** x\n## Issue 1\n**Title:** b\n**Body:** y\n", "dup"),
    ],
)
def test_parse_issues_rejects_malformed_files(markdown, message):
    with pytest.raises(ValueError, match=message):
        parse_issues(markdown)


def test_the_committed_demo_issues_and_fix_are_well_formed():
    issues = parse_issues((ROOT / "demo" / "issues.md").read_text(encoding="utf-8"))
    assert [i.number for i in issues] == [1, 2, 3, 4, 5]
    assert all(i.title and i.body for i in issues)
    assert [str(p) for p in fix_files(ROOT / "demo" / "fix")] == [
        "src/splitbill/money.py",
        "src/splitbill/settle.py",
        "src/splitbill/split.py",
    ]


def test_fix_files_ignores_caches_and_fails_when_empty(tmp_path, fix_dir):
    (fix_dir / "demo" / "__pycache__").mkdir()
    (fix_dir / "demo" / "__pycache__" / "x.pyc").write_bytes(b"")
    assert fix_files(fix_dir) == [Path("demo/__init__.py")]
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError, match="no fix files"):
        fix_files(tmp_path / "empty")


def test_reproduced_issue_is_verified_against_the_fix_and_the_checkout_restored(checkout, fix_dir):
    issue = DemoIssue(1, "add() subtracts", "add(2, 2) returns 0")
    calls: list[str] = []
    result = run_issue(
        "o/r", issue, fix_dir, lambda repo, n: checkout, fake_run(calls=calls), Settings()
    )
    assert (result.verdict, result.fail_to_pass) == ("reproduced", True)
    assert result.fix_runs == ["passed", "passed"]
    assert (result.test_code, result.tokens, result.report) == (FAILING, 120, "done")
    assert "o/r#1" in calls[0] and "<issue_title>add() subtracts</issue_title>" in calls[0]
    assert (checkout / "demo" / "__init__.py").read_text() == BUGGY


def test_a_fix_that_does_not_make_the_test_pass_is_not_verified(checkout, tmp_path):
    wrong = tmp_path / "wrong"
    (wrong / "demo").mkdir(parents=True)
    (wrong / "demo" / "__init__.py").write_text("def add(a, b):\n    return a * b + 1\n")
    issue = DemoIssue(1, "t", "b")
    result = run_issue("o/r", issue, wrong, lambda repo, n: checkout, fake_run(), Settings())
    assert (result.verdict, result.fail_to_pass) == ("reproduced", False)
    assert "reproduced, but the fixed run" in demo.outcome(json.loads(json.dumps(vars(result))))


def test_no_attempt_skips_the_fix_check(checkout, fix_dir):
    issue = DemoIssue(2, "Feature", "multiply")
    result = run_issue("o/r", issue, fix_dir, lambda r, n: checkout, fake_run(None), Settings())
    assert (result.verdict, result.fail_to_pass, result.fix_runs) == ("no_attempt", None, None)
    assert result.test_code is None


def test_fix_file_missing_from_the_checkout_is_an_error_and_changes_nothing(checkout, tmp_path):
    other = tmp_path / "other"
    (other / "elsewhere").mkdir(parents=True)
    (other / "elsewhere" / "x.py").write_text("x = 1\n")
    run_reproduction(str(checkout), "test_issue_repro_1.py", FAILING)
    with pytest.raises(FileNotFoundError, match="does not exist in the checkout"):
        check_against_fix(checkout, other, "test_issue_repro_1.py")
    assert not (checkout / "elsewhere").exists()


def test_run_demo_appends_results_and_resumes(checkout, fix_dir, tmp_path):
    issues = parse_issues(ISSUES_MD)
    out = tmp_path / "results.jsonl"
    calls: list[str] = []
    prepare = lambda repo, n: checkout
    run_demo("o/r", issues[:1], fix_dir, out, prepare, fake_run(calls=calls), Settings())
    run_demo("o/r", issues, fix_dir, out, prepare, fake_run(None, calls), Settings())
    rows = load_results(out)
    assert [(r["issue"], r["verdict"]) for r in rows] == [(1, "reproduced"), (2, "no_attempt")]
    assert len(calls) == 2  # issue 1 was not run again


def test_run_demo_fails_before_any_model_call_without_fix_files(tmp_path):
    (tmp_path / "empty").mkdir()
    calls: list[str] = []
    with pytest.raises(FileNotFoundError):
        run_demo(
            "o/r",
            [DemoIssue(1, "t", "b")],
            tmp_path / "empty",
            tmp_path / "out.jsonl",
            lambda repo, n: tmp_path,
            fake_run(calls=calls),
            Settings(),
        )
    assert calls == []


def row(issue, verdict, fail_to_pass, fix_runs=None):
    return {
        "issue": issue,
        "title": f"Issue {issue}",
        "verdict": verdict,
        "fail_to_pass": fail_to_pass,
        "fix_runs": fix_runs,
        "llm_calls": 7,
        "tokens": 1500,
        "latency_s": 12.4,
        "models": "m/m",
    }


def test_render_markdown_summarises_and_links_each_issue():
    rows = [
        row(2, "no_attempt", None),
        row(1, "reproduced", True, ["passed"]),
        row(3, "flaky", None),
    ]
    markdown = render_markdown(rows, "o/r", "Demo")
    assert markdown.startswith("# Demo\n\n1 of 3 issues verified · 4,500 tokens · models: m/m")
    lines = markdown.splitlines()
    assert lines[6].startswith("| [#1](https://github.com/o/r/issues/1) Issue 1 | verified")
    assert "| no test written | 7 | 1,500 | 12s |" in lines[7]
    assert "| flaky |" in lines[8]


def run_cli(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["issue-to-repro", *args])
    issue_to_repro.main()


def test_demo_cli_runs_and_reports(monkeypatch, checkout, fix_dir, tmp_path, capsys):
    from issue_to_repro.backtest import checkout as checkout_module
    from issue_to_repro.backtest import runner

    issues_file = tmp_path / "issues.md"
    issues_file.write_text(ISSUES_MD)
    out = tmp_path / "demo.jsonl"
    prepared: list[tuple[str, int]] = []

    def prepare(repo, number, workspace_root):
        prepared.append((repo, number))
        return checkout

    monkeypatch.setattr(checkout_module, "prepare_live_checkout", prepare)
    monkeypatch.setattr(runner, "run_prompt_adk", fake_run())
    args = ["--repo", "o/r", "--issues", str(issues_file), "--fix", str(fix_dir)]
    run_cli(monkeypatch, "demo", "run", *args, "--out", str(out), "--only", "1")
    assert prepared == [("o/r", 1)]
    assert "#1: reproduced fail_to_pass=True" in capsys.readouterr().out
    report = tmp_path / "demo.md"
    run_cli(monkeypatch, "demo", "report", "--repo", "o/r", "--results", str(out), "--title", "T")
    assert capsys.readouterr().out.startswith("# T\n\n1 of 1 issues verified")
    run_cli(
        monkeypatch, "demo", "report", "--repo", "o/r", "--results", str(out), "--out", str(report)
    )
    assert report.read_text().startswith("# Demo results\n")


def test_demo_cli_rejects_a_bad_repo_name(monkeypatch):
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "demo", "report", "--repo", "not a repo", "--results", "x.jsonl")
