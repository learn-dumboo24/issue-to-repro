"""Read a public GitHub issue through the REST API."""

import json
import re
import urllib.request
from typing import Any

from ..config import get_settings

REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_BODY_CHARS = 20_000


def fetch_issue(repo: str, number: int) -> dict[str, Any]:
    """Return the issue's title, body, labels and state. `repo` is "owner/name"."""
    if not REPO_PATTERN.match(repo):
        raise ValueError(f"repo must look like 'owner/name', got {repo!r}")
    if number < 1:
        raise ValueError("issue number must be positive")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{number}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "issue-to-repro"},
    )
    token = get_settings().github_token
    if token:
        request.add_header("Authorization", f"Bearer {token.get_secret_value()}")
    with urllib.request.urlopen(request, timeout=20) as response:  # raises on HTTP errors
        data: dict[str, Any] = json.load(response)
    return parse_issue(data)


def parse_issue(data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("body") or ""
    return {
        "url": data["html_url"],
        "title": data["title"],
        "body": body[:MAX_BODY_CHARS],
        "body_truncated": len(body) > MAX_BODY_CHARS,
        "labels": [label["name"] for label in data.get("labels", [])],
        "state": data["state"],
        "is_pull_request": "pull_request" in data,
    }
