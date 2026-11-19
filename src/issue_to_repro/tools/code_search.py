"""Keyword search over a checkout: the baseline the vector index (RAG) will be measured against."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .workspace import resolve_checkout

SEARCHED_SUFFIXES = {".py", ".pyi", ".md", ".rst", ".txt", ".toml", ".cfg", ".ini"}
SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "build", "dist"}


def search_code(repo_dir: str, query: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Case-insensitive substring search. Returns [{"path", "line", "text"}], repo-relative."""
    if not query.strip():
        raise ValueError("query must not be empty")
    root = resolve_checkout(repo_dir)
    needle = query.lower()
    hits: list[dict[str, Any]] = []
    for path in sorted(_iter_files(root)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable file: not searchable text
        for number, text in enumerate(lines, start=1):
            if needle in text.lower():
                hits.append(
                    {"path": str(path.relative_to(root)), "line": number, "text": text.strip()}
                )
                if len(hits) >= max_results:
                    return hits
    return hits


def _iter_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if (
            path.is_file()
            and path.suffix in SEARCHED_SUFFIXES
            and not SKIPPED_DIRS.intersection(path.relative_to(root).parts)
        ):
            yield path
