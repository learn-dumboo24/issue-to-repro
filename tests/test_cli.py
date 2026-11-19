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
