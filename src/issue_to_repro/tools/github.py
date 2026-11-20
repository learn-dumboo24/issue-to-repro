"""Read public GitHub issues through the REST API."""

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
    data = _get_json(f"https://api.github.com/repos/{repo}/issues/{number}")
    if not isinstance(data, dict):
        raise TypeError(f"unexpected response for {repo}#{number}")
    return parse_issue(data)


def list_open_issues(repo: str, per_page: int = 100) -> list[dict[str, Any]]:
    """The newest open issues of `repo` (pull requests left out), each as `parse_issue` returns
    it plus its number and comment count."""
    if not REPO_PATTERN.match(repo):
        raise ValueError(f"repo must look like 'owner/name', got {repo!r}")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100")
    url = (
        f"https://api.github.com/repos/{repo}/issues"
        f"?state=open&sort=created&direction=desc&per_page={per_page}"
    )
    data = _get_json(url)
    if not isinstance(data, list):
        raise TypeError(f"unexpected response listing issues of {repo}")
    issues = []
    for item in data:
        if "pull_request" in item:
            continue
        issue = parse_issue(item)
        issue["number"] = item["number"]
        issue["comments"] = item.get("comments", 0)
        issues.append(issue)
    return issues


def _get_json(url: str) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "issue-to-repro"}
    )
    token = get_settings().github_token
    if token:
        request.add_header("Authorization", f"Bearer {token.get_secret_value()}")
    with urllib.request.urlopen(request, timeout=20) as response:  # raises on HTTP errors
        return json.load(response)


def parse_issue(data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("body") or ""
    return {
        "url": data["html_url"],
        "title": data["title"],
        "body": body[:MAX_BODY_CHARS],
        "body_truncated": len(body) > MAX_BODY_CHARS,
        "labels": [label["name"] for label in data.get("labels", [])],
        "state": data["state"],
        "created_at": data.get("created_at", ""),
        "is_pull_request": "pull_request" in data,
    }
