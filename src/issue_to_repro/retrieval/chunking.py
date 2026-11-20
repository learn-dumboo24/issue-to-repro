"""Split Python source into retrievable chunks: one per function, method and class header."""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..tools.code_search import SKIPPED_DIRS

WINDOW_LINES = 60  # fallback chunk size for files that do not parse
MAX_CHUNK_CHARS = 6_000  # embedding input limit per chunk; longer bodies are truncated


@dataclass(frozen=True)
class Chunk:
    path: str  # repo-relative
    start_line: int
    end_line: int
    name: str  # e.g. "HelpFormatter.write_usage", "<lines 1-60>"
    text: str

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


def chunk_source(path: str, source: str) -> list[Chunk]:
    """Chunks for one file. Unparseable files fall back to fixed line windows."""
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _windows(path, lines)
    chunks = list(_walk(path, lines, tree.body, prefix=""))
    return chunks or _windows(path, lines)


def chunk_checkout(root: str | Path, include_tests: bool = False) -> list[Chunk]:
    """Chunks for every .py file under `root`, skipping virtualenvs and (by default) tests."""
    base = Path(root)
    chunks: list[Chunk] = []
    for file in sorted(base.rglob("*.py")):
        rel = file.relative_to(base)
        if SKIPPED_DIRS.intersection(rel.parts) or rel.name.startswith("test_issue_repro"):
            continue
        if not include_tests and (
            rel.parts[0] in {"tests", "test"} or rel.name.startswith("test_")
        ):
            continue
        chunks.extend(chunk_source(str(rel), file.read_text(encoding="utf-8", errors="replace")))
    return chunks


def _walk(path: str, lines: list[str], body: list[ast.stmt], prefix: str) -> Iterator[Chunk]:
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield _chunk(path, lines, node.lineno, _end(node), prefix + node.name)
        elif isinstance(node, ast.ClassDef):
            methods = [
                n for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            header_end = (methods[0].lineno - 1) if methods else _end(node)
            yield _chunk(path, lines, node.lineno, header_end, prefix + node.name)
            yield from _walk(path, lines, node.body, prefix=f"{prefix}{node.name}.")


def _chunk(path: str, lines: list[str], start: int, end: int, name: str) -> Chunk:
    text = "\n".join(lines[start - 1 : end])[:MAX_CHUNK_CHARS]
    return Chunk(path, start, end, name, f"# {path} :: {name}\n{text}")


def _end(node: ast.stmt) -> int:
    return node.end_lineno or node.lineno


def _windows(path: str, lines: list[str]) -> list[Chunk]:
    return [
        _chunk(path, lines, start, min(start + WINDOW_LINES - 1, len(lines)), f"<lines {start}->")
        for start in range(1, len(lines) + 1, WINDOW_LINES)
    ]
