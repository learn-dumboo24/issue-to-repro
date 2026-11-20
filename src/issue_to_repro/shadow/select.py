"""Which open issues are worth a shadow run: recent bug reports with concrete code in them."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..tools.github import REPO_PATTERN

# Issues labelled like this are not bug reports, so there is nothing to reproduce.
DEFAULT_SKIP_LABELS = (
    "feature",
    "enhancement",
    "question",
    "docs",
    "documentation",
    "discussion",
    "duplicate",
    "invalid",
    "wontfix",
)
CODE_MARKERS = ("```", ">>> ", "Traceback (most recent call last)")
MIN_BODY_CHARS = 100


@dataclass(frozen=True)
class ShadowConfig:
    repos: tuple[str, ...]
    per_repo: int = 2
    max_age_days: int = 90
    skip_labels: tuple[str, ...] = DEFAULT_SKIP_LABELS


@dataclass(frozen=True)
class Candidate:
    repo: str
    number: int
    title: str
    body: str
    url: str
    created_at: str
    labels: tuple[str, ...] = field(default_factory=tuple)


def load_config(path: str | Path) -> ShadowConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    repos = tuple(data["repos"])
    if not repos:
        raise ValueError("no repos to run on")
    for repo in repos:
        if not REPO_PATTERN.match(repo):
            raise ValueError(f"not a repository name: {repo!r}")
    config = ShadowConfig(
        repos=repos,
        per_repo=int(data.get("per_repo", 2)),
        max_age_days=int(data.get("max_age_days", 90)),
        skip_labels=tuple(data.get("skip_labels", DEFAULT_SKIP_LABELS)),
    )
    if config.per_repo < 1 or config.max_age_days < 1:
        raise ValueError("per_repo and max_age_days must be positive")
    return config


def skip_reason(issue: dict[str, Any], now: datetime, config: ShadowConfig) -> str | None:
    """Why an issue is not a candidate, or None if it is."""
    if issue.get("is_pull_request"):
        return "pull request"
    created = datetime.fromisoformat(issue["created_at"])
    if now - created > timedelta(days=config.max_age_days):
        return "too old"
    skip = [s.lower() for s in config.skip_labels]
    for label in issue.get("labels", []):
        if any(word in label.lower() for word in skip):
            return f"label {label!r}"
    body = issue.get("body") or ""
    if issue.get("body_truncated"):
        return "body too long"
    if len(body) < MIN_BODY_CHARS:
        return "body too short"
    if not any(marker in body for marker in CODE_MARKERS):
        return "no code in the report"
    return None


def select_issues(
    repo: str,
    issues: list[dict[str, Any]],
    config: ShadowConfig,
    done: set[tuple[str, int]],
    now: datetime | None = None,
) -> list[Candidate]:
    """Up to `config.per_repo` of the newest candidate issues not already in `done`."""
    now = now or datetime.now(UTC)
    chosen: list[Candidate] = []
    newest_first = sorted(issues, key=lambda i: i["created_at"], reverse=True)
    for issue in newest_first:
        if len(chosen) == config.per_repo:
            break
        if (repo, issue["number"]) in done or skip_reason(issue, now, config):
            continue
        chosen.append(
            Candidate(
                repo=repo,
                number=issue["number"],
                title=issue["title"],
                body=issue["body"],
                url=issue["url"],
                created_at=issue["created_at"],
                labels=tuple(issue.get("labels", [])),
            )
        )
    return chosen
