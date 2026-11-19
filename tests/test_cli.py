import io
import json
import sys
import urllib.request

import pytest

import issue_to_repro


def run_cli(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["issue-to-repro", *args])
    issue_to_repro.main()


def test_dry_run_builds_agents_without_calling_gemini(monkeypatch, capsys):
    run_cli(monkeypatch, "reproduce", "owner/name#12", "--checkout", "workspace/name", "--dry-run")
    assert "Coordinator 'coordinator'" in capsys.readouterr().out


@pytest.mark.parametrize("ref", ["owner/name", "owner/name#abc", "name#12"])
def test_rejects_malformed_issue_refs(monkeypatch, ref):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, "reproduce", ref, "--checkout", "workspace/name", "--dry-run")
    assert exc.value.code == 2


def test_adk_entry_point_exposes_root_agent():
    from issue_to_repro.agent import root_agent

    assert root_agent.name == "coordinator"


def test_requires_a_subcommand(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch)
    assert exc.value.code == 2


def test_dataset_build_writes_jsonl(monkeypatch, capsys, history, tmp_path):
    repo, _, _ = history
    issue = {"html_url": "u", "title": "t", "body": "b", "labels": [], "state": "closed"}
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout: io.BytesIO(json.dumps(issue).encode())
    )
    out = tmp_path / "d.jsonl"
    run_cli(
        monkeypatch, "dataset", "build", "--repo", "o/r", "--checkout", str(repo), "--out", str(out)
    )
    assert "wrote 1 cases" in capsys.readouterr().out
    assert len(out.read_text().splitlines()) == 1


def test_backtest_report_writes_markdown(monkeypatch, tmp_path, capsys):
    results = tmp_path / "r.jsonl"
    row = {
        "case_id": "o/r#1",
        "verdict": "reproduced",
        "fail_to_pass": True,
        "attempts": 1,
        "llm_calls": 4,
        "prompt_tokens": 10,
        "output_tokens": 5,
        "latency_s": 3.0,
        "stopped": None,
    }
    results.write_text(json.dumps(row) + "\n")
    run_cli(monkeypatch, "backtest", "report", "--results", str(results), "--title", "T")
    assert "**Verified reproductions: 1/1 (100%)**" in capsys.readouterr().out
    out = tmp_path / "r.md"
    run_cli(monkeypatch, "backtest", "report", "--results", str(results), "--out", str(out))
    assert out.read_text().startswith("# Backtest results")


def test_backtest_run_filters_cases(monkeypatch, history, tmp_path):
    from issue_to_repro.backtest.dataset import build_dataset, write_jsonl

    repo, _, _ = history
    issue = {
        "url": "u",
        "title": "t",
        "body": "b",
        "labels": [],
        "state": "closed",
        "created_at": "",
        "is_pull_request": False,
    }
    cases, _ = build_dataset("o/r", repo, since="2020-01-01", fetch=lambda r, n: issue)
    dataset = tmp_path / "d.jsonl"
    write_jsonl(cases, dataset)
    seen = {}

    def fake_run_backtest(cases, out, prepare):
        seen["issues"] = [c.issue_number for c in cases]

    monkeypatch.setattr("issue_to_repro.backtest.runner.run_backtest", fake_run_backtest)
    args = ["backtest", "run", "--dataset", str(dataset), "--source", str(repo), "--out", "x"]
    run_cli(monkeypatch, *args, "--issues", "12")
    assert seen["issues"] == [12]
    run_cli(monkeypatch, *args, "--issues", "99")
    assert seen["issues"] == []
    run_cli(monkeypatch, *args, "--limit", "0")
    assert seen["issues"] == [12]
