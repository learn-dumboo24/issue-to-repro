"""Agent tools. Each wrapper turns bad input into an explicit error result the model can act on,
instead of crashing the run; nothing is swallowed silently."""

from collections.abc import Callable
from typing import Any

from .code_search import search_code
from .github import fetch_issue
from .sandbox import run_reproduction


def _guard(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return {"status": "ok", "result": fn(*args, **kwargs)}
    except (ValueError, OSError) as exc:  # bad input, missing checkout, network error
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def fetch_issue_tool(repo: str, number: int) -> dict[str, Any]:
    """Fetch a GitHub issue. Args: repo as "owner/name", number as the issue number."""
    return _guard(fetch_issue, repo, number)


def search_code_tool(repo_dir: str, query: str) -> dict[str, Any]:
    """Search a checked-out repository for a keyword; returns matching file/line/text hits."""
    return _guard(search_code, repo_dir, query)


def run_reproduction_tool(repo_dir: str, test_relpath: str, test_code: str) -> dict[str, Any]:
    """Write a pytest file named test_issue_repro*.py into the checkout and run it several
    times. The verdict is "reproduced" only if it fails, for a real reason, on every run."""
    return _guard(run_reproduction, repo_dir, test_relpath, test_code)
