import json

import pytest
from fastapi.testclient import TestClient

from issue_to_repro.config import Settings
from issue_to_repro.service.app import create_app
from issue_to_repro.service.events import Approve, Ignore, Reproduce, route
from issue_to_repro.service.signature import sign, verify_signature

SECRET = "s3cret"
LABEL = "issue-to-repro:approved"


def issue_payload(action="opened", private=False, pr=False, label=None, sender="maintainer"):
    issue = {"number": 7, "title": "t"}
    if pr:
        issue["pull_request"] = {}
    payload = {
        "action": action,
        "issue": issue,
        "repository": {"full_name": "o/r", "private": private},
        "installation": {"id": 99},
        "sender": {"login": sender},
    }
    if label:
        payload["label"] = {"name": label}
    return payload


def test_signature():
    body = b'{"a":1}'
    good = sign(SECRET.encode(), body)
    assert good.startswith("sha256=") and verify_signature(SECRET.encode(), body, good)
    assert not verify_signature(SECRET.encode(), body + b" ", good)
    assert not verify_signature(b"other", body, good)
    assert not verify_signature(SECRET.encode(), body, None)
    assert not verify_signature(SECRET.encode(), body, good.removeprefix("sha256="))
    assert not verify_signature(b"", body, sign(b"", body))


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [
        ("issues", issue_payload(), Reproduce("o/r", 7, 99)),
        ("issues", issue_payload("labeled", label=LABEL), Approve("o/r", 7, "maintainer", 99)),
        ("issues", issue_payload("labeled", label="bug"), Ignore("issues.labeled is not handled")),
        ("issues", issue_payload("closed"), Ignore("issues.closed is not handled")),
        ("issues", issue_payload(pr=True), Ignore("pull requests are not issues")),
        (
            "issues",
            issue_payload(private=True),
            Ignore("private repositories are out of scope (public data only)"),
        ),
        ("issues", {"action": "opened"}, Ignore("payload has no repository or issue number")),
        ("ping", {}, Ignore("ping")),
        ("push", {}, Ignore("event 'push' is not handled")),
    ],
)
def test_route(event, payload, expected):
    assert route(event, payload, LABEL) == expected


def test_route_label_without_sender_is_ignored():
    payload = issue_payload("labeled", label=LABEL)
    del payload["sender"]
    assert route("issues", payload, LABEL) == Ignore("label event has no sender")


def test_private_flag_missing_counts_as_private():
    payload = issue_payload()
    del payload["repository"]["private"]
    assert isinstance(route("issues", payload, LABEL), Ignore)


@pytest.fixture
def client():
    queued = []
    app = create_app(queued.append, Settings(github_webhook_secret=SECRET))
    return TestClient(app), queued


def post(client, event, payload, secret=SECRET, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"X-GitHub-Event": event, "X-Hub-Signature-256": sign(secret.encode(), body)}
    return client.post("/webhooks/github", content=body, headers=headers)


def test_app_refuses_to_start_without_a_secret():
    with pytest.raises(ValueError, match="GITHUB_WEBHOOK_SECRET"):
        create_app(lambda a: None, Settings())
    with pytest.raises(ValueError):
        create_app(lambda a: None, Settings(github_webhook_secret=""))


def test_rejects_bad_signatures_before_parsing(client):
    c, queued = client
    assert post(c, "issues", issue_payload(), secret="wrong").status_code == 401
    response = c.post("/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "issues"})
    assert response.status_code == 401
    assert queued == []


def test_rejects_signed_non_json(client):
    c, _ = client
    assert post(c, "issues", None, raw=b"not json").status_code == 400
    assert post(c, "issues", None, raw=b"[1, 2]").status_code == 400


def test_queues_reproduce_and_approve_and_ignores_the_rest(client):
    c, queued = client
    r = post(c, "issues", issue_payload())
    assert r.status_code == 202
    assert r.json() == {"status": "queued", "action": "reproduce", "issue": "o/r#7"}
    r = post(c, "issues", issue_payload("labeled", label=LABEL))
    assert r.json() == {"status": "queued", "action": "approve", "issue": "o/r#7"}
    r = post(c, "ping", {"zen": "hi"})
    assert r.json() == {"status": "ignored", "reason": "ping"}
    assert queued == [Reproduce("o/r", 7, 99), Approve("o/r", 7, "maintainer", 99)]


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}
