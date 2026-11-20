"""GitHub App client: app JWT -> installation token -> permission lookups and comments.

Names are validated before they are placed in API paths, HTTP errors raise (nothing is swallowed),
and installation tokens are cached until a minute before they expire.
"""

import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import jwt

API = "https://api.github.com"
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
USER = re.compile(r"^[A-Za-z0-9-]+(\[bot\])?$")
JWT_LIFETIME_S = 540  # GitHub allows at most 10 minutes
CLOCK_SKEW_S = 60


class GitHubApp:
    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app_id, self._key, self._clock = app_id, private_key_pem, clock
        self._http = client or httpx.Client(base_url=API, timeout=20.0)
        self._tokens: dict[int, tuple[str, float]] = {}

    def app_jwt(self) -> str:
        now = int(self._clock())
        claims = {"iat": now - CLOCK_SKEW_S, "exp": now + JWT_LIFETIME_S, "iss": self.app_id}
        return jwt.encode(claims, self._key, algorithm="RS256")

    def installation_token(self, installation_id: int | None) -> str:
        if installation_id is None:
            raise ValueError("the event has no installation id; is the GitHub App installed?")
        cached = self._tokens.get(installation_id)
        if cached and cached[1] - CLOCK_SKEW_S > self._clock():
            return cached[0]
        data = self._request(
            "POST", f"/app/installations/{int(installation_id)}/access_tokens", self.app_jwt()
        )
        expires = datetime.fromisoformat(data["expires_at"]).timestamp()
        self._tokens[installation_id] = (data["token"], expires)
        return str(data["token"])

    def permission(self, repo: str, user: str, installation_id: int | None) -> str:
        _check(repo, user)
        token = self.installation_token(installation_id)
        try:
            data = self._request("GET", f"/repos/{repo}/collaborators/{user}/permission", token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # not a collaborator
                return "none"
            raise
        return str(data.get("permission", "none"))

    def post_comment(
        self, repo: str, issue_number: int, body: str, installation_id: int | None
    ) -> str:
        _check(repo)
        token = self.installation_token(installation_id)
        data = self._request(
            "POST", f"/repos/{repo}/issues/{int(issue_number)}/comments", token, {"body": body}
        )
        return str(data["html_url"])

    def _request(
        self, method: str, path: str, token: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._http.request(
            method,
            path,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "issue-to-repro",
            },
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def _check(repo: str, user: str | None = None) -> None:
    if not REPO.match(repo):
        raise ValueError(f"not a repository name: {repo!r}")
    if user is not None and not USER.match(user):
        raise ValueError(f"not a GitHub user name: {user!r}")
