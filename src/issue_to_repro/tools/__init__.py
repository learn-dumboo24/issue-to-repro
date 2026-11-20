"""Agent tools. Each wrapper turns bad input into an explicit error result the model can act on,
instead of crashing the run; nothing is swallowed silently."""

from collections.abc import Callable
from typing import Any

from .code_search import read_file, search_code
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


def read_file_tool(
    repo_dir: str, path: str, start_line: int = 1, end_line: int = 0
) -> dict[str, Any]:
    """Read numbered lines of a file in the checkout (at most 200 per call). `path` is relative to
    the checkout root; end_line 0 means "as far as the limit allows"."""
    return _guard(read_file, repo_dir, path, start_line, end_line or None)


def semantic_search_tool(repo_dir: str, query: str) -> dict[str, Any]:
    """Search a checkout by meaning: describe the behaviour or concept (e.g. "wraps help text at
    hyphens"). Returns the best-matching functions and classes with file and line ranges. If it
    reports an error, use search_code_tool instead."""
    from google.genai import errors

    from ..retrieval.search import semantic_search

    try:
        return _guard(semantic_search, repo_dir, query)
    except errors.APIError as exc:  # quota or overload: report it, let the agent fall back
        return {"status": "error", "error": f"embedding API {exc.code}: {exc.status}"}


def run_reproduction_tool(repo_dir: str, test_relpath: str, test_code: str) -> dict[str, Any]:
    """Write a pytest file named test_issue_repro*.py into the checkout and run it several
    times. The verdict is "reproduced" only if it fails, for a real reason, on every run."""
    return _guard(run_reproduction, repo_dir, test_relpath, test_code)
