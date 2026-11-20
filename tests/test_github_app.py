import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from issue_to_repro.service.github_app import GitHubApp

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
NOW = 1_800_000_000.0


class FakeGitHubAPI:
    def __init__(self, permission_status: int = 200, level: str = "write") -> None:
        self.calls: list[httpx.Request] = []
        self.permission_status, self.level = permission_status, level

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/access_tokens"):
            return httpx.Response(
                201, json={"token": f"inst-{len(self.calls)}", "expires_at": "2027-01-15T09:00:00Z"}
            )
        if "/collaborators/" in path:
            if self.permission_status != 200:
                return httpx.Response(self.permission_status, json={"message": "nope"})
            return httpx.Response(200, json={"permission": self.level})
        if path.endswith("/comments"):
            return httpx.Response(
                201, json={"html_url": "https://github.com/o/r/issues/7#issuecomment-5"}
            )
        return httpx.Response(404)


def app(api: FakeGitHubAPI, now: float = NOW) -> GitHubApp:
    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(api))
    return GitHubApp("12345", PEM, client=client, clock=lambda: now)


def test_app_jwt_is_rs256_with_short_lifetime():
    token = app(FakeGitHubAPI()).app_jwt()
    # The fixed test clock is in the future, so time checks are off; only the claims matter here.
    no_time_checks = {"verify_exp": False, "verify_iat": False}
    claims = jwt.decode(token, KEY.public_key(), algorithms=["RS256"], options=no_time_checks)
    assert claims == {"iat": int(NOW) - 60, "exp": int(NOW) + 540, "iss": "12345"}


def test_installation_token_is_cached_until_near_expiry():
    api = FakeGitHubAPI()
    gh = app(api)
    assert gh.installation_token(99) == gh.installation_token(99) == "inst-1"
    assert len(api.calls) == 1
    assert api.calls[0].url.path == "/app/installations/99/access_tokens"
    assert api.calls[0].headers["Authorization"].startswith("Bearer ey")  # the app JWT
    expired = app(api, now=1_900_000_000.0)  # past expires_at
    expired._tokens = dict(gh._tokens)
    assert expired.installation_token(99) == "inst-2"


def test_permission_and_comment_use_the_installation_token():
    api = FakeGitHubAPI(level="maintain")
    gh = app(api)
    assert gh.permission("o/r", "alice", 99) == "maintain"
    url = gh.post_comment("o/r", 7, "hello", 99)
    assert url.endswith("issuecomment-5")
    comment = api.calls[-1]
    assert comment.url.path == "/repos/o/r/issues/7/comments"
    assert json.loads(comment.content) == {"body": "hello"}
    assert comment.headers["Authorization"] == "Bearer inst-1"


def test_non_collaborators_have_no_access_but_other_errors_raise():
    assert app(FakeGitHubAPI(permission_status=404)).permission("o/r", "bob", 99) == "none"
    with pytest.raises(httpx.HTTPStatusError):
        app(FakeGitHubAPI(permission_status=500)).permission("o/r", "bob", 99)


@pytest.mark.parametrize(
    ("repo", "user"), [("o/r/../x", "a"), ("o", "a"), ("o/r", "a/b"), ("o/r", "../x")]
)
def test_rejects_names_that_could_change_the_api_path(repo, user):
    with pytest.raises(ValueError):
        app(FakeGitHubAPI()).permission(repo, user, 99)


def test_bots_are_valid_users_and_missing_installation_is_an_error():
    assert app(FakeGitHubAPI(level="read")).permission("o/r", "dependabot[bot]", 99) == "read"
    with pytest.raises(ValueError, match="installation"):
        app(FakeGitHubAPI()).installation_token(None)
    with pytest.raises(ValueError):
        app(FakeGitHubAPI()).post_comment("bad name", 7, "x", 99)
