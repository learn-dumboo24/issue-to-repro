import sys

import pytest
from test_approval import FakeGitHub

from issue_to_repro.backtest.checkout import prepare_live_checkout
from issue_to_repro.backtest.runner import AgentRun
from issue_to_repro.config import Settings
from issue_to_repro.service.drafts import FileDraftStore
from issue_to_repro.service.events import Approve, Ignore, Reproduce
from issue_to_repro.service.worker import Deps, WorkerQueue, handle, reproduce_issue
from issue_to_repro.tools.sandbox import run_reproduction

FAILING = "from demo import add\n\ndef test_add():\n    assert add(2, 2) == 4\n"
ISSUE = {"title": "add() subtracts", "body": "add(2, 2) returns 0"}


def make_deps(tmp_path, workspace, code=FAILING, sandbox="docker", prompts=None):
    def run(prompt, settings):
        if prompts is not None:
            prompts.append(prompt)
        agent_run = AgentRun(final_text="Reproduced: add subtracts.")
        if code is not None:
            result = run_reproduction(str(workspace), "test_issue_repro_7.py", code)
            agent_run.repro_results.append({"status": "ok", "result": result})
        return agent_run

    return Deps(
        store=FileDraftStore(tmp_path / "drafts"),
        github=FakeGitHub(),
        fetch=lambda repo, n: ISSUE,
        prepare=lambda repo, n: workspace,
        run=run,
        settings=Settings(sandbox=sandbox),
    )


def test_reproduced_issue_becomes_a_pending_draft(tmp_path, workspace):
    prompts: list[str] = []
    deps = make_deps(tmp_path, workspace, prompts=prompts)
    draft = reproduce_issue(Reproduce("o/r", 7, 99), deps)
    assert (draft.status, draft.verdict, draft.test_code) == ("pending", "reproduced", FAILING)
    assert draft.report == "Reproduced: add subtracts."
    assert deps.store.get("o/r", 7) == draft
    assert "o/r#7" in prompts[0] and "<issue_title>add() subtracts</issue_title>" in prompts[0]


def test_no_reproduction_is_stored_but_never_postable(tmp_path, workspace):
    deps = make_deps(tmp_path, workspace, code=None)
    draft = reproduce_issue(Reproduce("o/r", 7, 99), deps)
    assert (draft.status, draft.verdict, draft.test_code) == ("not_reproduced", "no_attempt", None)


def test_refuses_to_run_live_issues_outside_the_docker_sandbox(tmp_path, workspace):
    with pytest.raises(RuntimeError, match="SANDBOX=docker"):
        reproduce_issue(Reproduce("o/r", 7, 99), make_deps(tmp_path, workspace, sandbox="local"))


def test_handle_routes_actions(tmp_path, workspace):
    deps = make_deps(tmp_path, workspace)
    handle(Reproduce("o/r", 7, 99), deps)
    outcome = handle(Approve("o/r", 7, "maintainer", 99), deps)
    assert outcome.posted and deps.github.posted[0][:2] == ("o/r", 7)
    assert handle(Ignore("x"), deps) is None


def test_worker_queue_runs_in_order_and_survives_failures():
    seen = []

    def handler(action):
        if action.issue_number == 2:
            raise RuntimeError("boom")
        seen.append(action.issue_number)

    worker = WorkerQueue(handler)
    for n in (1, 2, 3):
        worker.put(Reproduce("o/r", n, None))
    worker.join()
    worker.stop()
    assert seen == [1, 3]
    assert worker.failures == [(Reproduce("o/r", 2, None), "RuntimeError: boom")]


def test_prepare_live_checkout_clones_and_installs(tmp_path):
    commands: list[list[str]] = []
    stale = tmp_path / "live" / "o__r-7"
    stale.mkdir(parents=True)
    (stale / "old.txt").write_text("x")
    target = prepare_live_checkout("o/r", 7, tmp_path, python="3.12", run=commands.append)
    assert target == stale.resolve() and not (stale / "old.txt").exists()
    clone, venv, install = commands
    assert clone[:5] == ["git", "clone", "--quiet", "--depth", "1"]
    assert clone[5] == "https://github.com/o/r.git"
    assert venv[:2] == ["uv", "venv"] and install[:3] == ["uv", "pip", "install"]
    with pytest.raises(ValueError):
        prepare_live_checkout("o/r; rm -rf /", 7, tmp_path, python="3.12", run=commands.append)


def test_serve_needs_app_credentials_and_wires_the_app(monkeypatch):
    import issue_to_repro

    monkeypatch.setattr(sys, "argv", ["issue-to-repro", "serve"])
    with pytest.raises(SystemExit, match="GITHUB_APP_ID"):
        issue_to_repro.main()

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s")
    served = {}
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: served.update(app=app, port=port))
    monkeypatch.setattr(sys, "argv", ["issue-to-repro", "serve", "--port", "9000"])
    issue_to_repro.main()
    from fastapi.testclient import TestClient

    assert served["port"] == 9000
    assert TestClient(served["app"]).get("/healthz").json() == {"status": "ok"}
