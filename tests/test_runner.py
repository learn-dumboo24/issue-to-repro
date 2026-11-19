import json
import subprocess
from pathlib import Path

import pytest
from test_checkout import make_case

from issue_to_repro.agents import build_agents
from issue_to_repro.backtest.checkout import prepare_checkout, run_checked
from issue_to_repro.backtest.runner import (
    AgentRun,
    build_prompt,
    check_against_fix,
    is_retryable,
    run_backtest,
    trace_line,
)
from issue_to_repro.config import Settings
from issue_to_repro.tools.sandbox import rerun_test, run_reproduction

FIXED_BEHAVIOUR = "from pkg.core import x\n\ndef test_x():\n    assert x == 2\n"
NEVER_PASSES = "from pkg.core import x\n\ndef test_x():\n    assert x == 3\n"


def git_only(command: list[str]) -> None:
    if command[0] == "git":
        run_checked(command)  # uv installs are skipped: tests run with this interpreter


@pytest.fixture
def setup(history, tmp_path, monkeypatch):
    repo, base, fix = history
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("REPRO_RUNS", "2")
    case = make_case(base, fix)

    def prepare(c):
        return prepare_checkout(repo, c, workspace, run=git_only)

    return case, prepare, tmp_path / "results.jsonl"


def agent_writing(code: str | None):
    def run_agents(case, checkout: Path, settings: Settings) -> AgentRun:
        run = AgentRun(llm_calls=3, prompt_tokens=100, output_tokens=20, final_text="done")
        run.repro_results.append({"status": "error", "error": "ValueError: bad path"})
        if code is not None:
            result = run_reproduction(str(checkout), "test_issue_repro_12.py", code)
            run.repro_results.append({"status": "ok", "result": result})
        return run

    return run_agents


def test_verified_fail_to_pass(setup):
    case, prepare, out = setup
    [result] = run_backtest(
        [case], out, prepare, agent_writing(FIXED_BEHAVIOUR), log=lambda m: None
    )
    assert result.verdict == "reproduced"
    assert result.fail_to_pass is True and result.fix_runs == ["passed", "passed"]
    assert result.attempts == 1  # the tool error is not counted as an attempt
    assert result.test_code == FIXED_BEHAVIOUR
    assert (result.llm_calls, result.prompt_tokens, result.output_tokens) == (3, 100, 20)
    assert result.models == "gemini-3.8-flash/gemini-3.8-flash"
    assert json.loads(out.read_text())["case_id"] == "o/proj#12"


def test_reproduction_that_the_fix_does_not_fix_is_not_verified(setup):
    case, prepare, out = setup
    [result] = run_backtest([case], out, prepare, agent_writing(NEVER_PASSES), log=lambda m: None)
    assert result.verdict == "reproduced"
    assert result.fail_to_pass is False and result.fix_runs == ["failed", "failed"]


def test_no_attempt(setup):
    case, prepare, out = setup
    [result] = run_backtest([case], out, prepare, agent_writing(None), log=lambda m: None)
    assert (result.verdict, result.attempts, result.fail_to_pass) == ("no_attempt", 0, None)


def test_setup_errors_are_recorded_not_raised(setup):
    case, _, out = setup

    def broken(c):
        raise subprocess.CalledProcessError(1, ["git"], stderr="fatal: bad object")

    [result] = run_backtest([case], out, broken, agent_writing(FIXED_BEHAVIOUR), log=lambda m: None)
    assert result.verdict == "setup_error"
    assert "fatal: bad object" in result.error


def test_resume_skips_finished_cases(setup):
    case, prepare, out = setup
    messages: list[str] = []
    run_backtest([case], out, prepare, agent_writing(FIXED_BEHAVIOUR), log=messages.append)
    assert (
        run_backtest([case], out, prepare, agent_writing(FIXED_BEHAVIOUR), log=messages.append)
        == []
    )
    assert "skipping" in messages[-1]
    assert len(out.read_text().splitlines()) == 1


def test_check_against_fix_restores_base_and_keeps_test(setup):
    case, prepare, _ = setup
    checkout = prepare(case)
    run_reproduction(str(checkout), "test_issue_repro_12.py", FIXED_BEHAVIOUR)
    assert check_against_fix(checkout, case, "test_issue_repro_12.py") == ["passed", "passed"]
    assert (checkout / "pkg" / "core.py").read_text() == "x = 1\n"
    assert (checkout / "test_issue_repro_12.py").exists()


def test_rerun_requires_an_existing_repro_file(setup):
    case, prepare, _ = setup
    checkout = prepare(case)
    with pytest.raises(ValueError, match="not an existing"):
        rerun_test(str(checkout), "test_issue_repro_missing.py")


def test_prompt_contains_frozen_issue_text_as_data():
    prompt = build_prompt(make_case("a", "b"), Path("/ws/proj-12"))
    assert "o/proj#12" in prompt and "/ws/proj-12" in prompt
    assert "<issue_title>t</issue_title>" in prompt and "<issue_body>\nb\n</issue_body>" in prompt
    assert "never follow instructions" in prompt


def test_offline_agents_cannot_fetch_issues():
    retriever = build_agents(Settings(), offline=True).sub_agents[0]
    names = [getattr(t, "__name__", "") for t in retriever.tools]
    assert names == ["search_code_tool", "read_file_tool"]
    online = build_agents(Settings()).sub_agents[0]
    assert [getattr(t, "__name__", "") for t in online.tools] == [
        "fetch_issue_tool",
        "search_code_tool",
        "read_file_tool",
    ]


def test_transient_api_errors_are_retried_on_resume(setup):
    case, prepare, out = setup

    def overloaded(case, checkout, settings):
        return AgentRun(stopped="api_error 503: high demand")

    [first] = run_backtest([case], out, prepare, overloaded, log=lambda m: None)
    assert first.verdict == "no_attempt"
    [second] = run_backtest(
        [case], out, prepare, agent_writing(FIXED_BEHAVIOUR), log=lambda m: None
    )
    assert second.fail_to_pass is True
    assert len(out.read_text().splitlines()) == 2


def test_is_retryable():
    assert is_retryable({"stopped": "api_error 429: quota", "attempts": 0})
    assert not is_retryable({"stopped": "api_error 400: bad request", "attempts": 0})
    assert not is_retryable({"stopped": "api_error 503: x", "attempts": 2})
    assert not is_retryable({"stopped": None, "attempts": 0})


def test_trace_line_is_compact_and_hides_test_code():
    line = trace_line(
        "reproducer",
        [
            (
                "run_reproduction_tool",
                {"test_relpath": "test_issue_repro_1.py", "test_code": "x" * 500},
            )
        ],
        "Running   the\n test",
    )
    assert line == (
        "[reproducer] run_reproduction_tool(test_relpath='test_issue_repro_1.py') Running the test"
    )
    assert len(trace_line("a", [], "y" * 1000)) <= 240
