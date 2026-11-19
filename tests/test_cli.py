import sys

import pytest

import issue_to_repro


def run_cli(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["issue-to-repro", *args])
    issue_to_repro.main()


def test_dry_run_builds_agents_without_calling_gemini(monkeypatch, capsys):
    run_cli(monkeypatch, "owner/name#12", "--checkout", "workspace/name", "--dry-run")
    assert "Coordinator 'coordinator'" in capsys.readouterr().out


@pytest.mark.parametrize("ref", ["owner/name", "owner/name#abc", "name#12"])
def test_rejects_malformed_issue_refs(monkeypatch, ref):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, ref, "--checkout", "workspace/name", "--dry-run")
    assert exc.value.code == 2


def test_adk_entry_point_exposes_root_agent():
    from issue_to_repro.agent import root_agent

    assert root_agent.name == "coordinator"
