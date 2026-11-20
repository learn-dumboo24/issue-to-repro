"""Retrieval benchmark: does a search method surface the files the real fix changed?

For each dataset case the code is snapshotted at the buggy commit, chunked once, and searched
with the issue's title and body. Ground truth is the case's `source_files` that exist at the
buggy commit (files the fix created cannot be retrieved and are excluded).
"""

import io
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..backtest.dataset import Case
from .bm25 import BM25Index
from .chunking import chunk_checkout
from .embedding import Embedder
from .index import CodeIndex, Hit

KS = (1, 3, 5, 10)
SEARCH_DEPTH = 100  # chunks retrieved before collapsing to files
RRF_K = 60
MAX_QUERY_CHARS = 8_000
Search = Callable[[str, int], list[Hit]]


@dataclass(frozen=True)
class MethodResult:
    ranked_files: list[str]
    first_relevant_rank: int | None  # 1-based, among files

    def hit_at(self, k: int, relevant: set[str]) -> bool:
        return bool(relevant.intersection(self.ranked_files[:k]))

    def recall_at(self, k: int, relevant: set[str]) -> float:
        return len(relevant.intersection(self.ranked_files[:k])) / len(relevant)


def snapshot(source: str | Path, commit: str, dest_root: str | Path) -> Path:
    """Extract the tree at `commit` into dest_root/<commit> (once; reused afterwards)."""
    dest = Path(dest_root) / commit
    if not dest.exists():
        archive = subprocess.run(
            ["git", "-C", str(source), "archive", "--format=tar", commit],
            check=True,
            capture_output=True,
        ).stdout
        partial = dest.with_name(dest.name + ".partial")
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(partial, filter="data")
        partial.rename(dest)
    return dest


def ranked_files(hits: list[Hit]) -> list[str]:
    seen: dict[str, None] = {}
    for hit in hits:
        seen.setdefault(hit.chunk.path, None)
    return list(seen)


def fuse(*rankings: list[Hit]) -> list[Hit]:
    """Reciprocal rank fusion of chunk rankings."""
    scores: dict[tuple[str, int], float] = {}
    chunks: dict[tuple[str, int], Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            key = (hit.chunk.path, hit.chunk.start_line)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            chunks.setdefault(key, hit)
    order = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [Hit(chunks[key].chunk, scores[key]) for key in order]


def evaluate(hits: list[Hit], relevant: set[str]) -> MethodResult:
    files = ranked_files(hits)
    first = next((i for i, f in enumerate(files, start=1) if f in relevant), None)
    return MethodResult(files, first)


def evaluate_case(case: Case, root: Path, embedder: Embedder) -> dict[str, Any] | None:
    """Score keyword, semantic and hybrid search for one case; None if nothing is retrievable."""
    relevant = {f for f in case.source_files if (root / f).is_file()}
    if not relevant:
        return None
    chunks = chunk_checkout(root)
    semantic = CodeIndex(
        chunks, embedder.embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT"), embedder
    )
    keyword = BM25Index(chunks)
    query = f"{case.issue_title}\n\n{case.issue_body}"[:MAX_QUERY_CHARS]
    sem_hits = semantic.search(query, SEARCH_DEPTH)
    kw_hits = keyword.search(query, SEARCH_DEPTH)
    methods = {"keyword": kw_hits, "semantic": sem_hits, "hybrid": fuse(kw_hits, sem_hits)}
    row: dict[str, Any] = {
        "case_id": case.case_id,
        "relevant": sorted(relevant),
        "chunks": len(chunks),
    }
    for name, hits in methods.items():
        result = evaluate(hits, relevant)
        row[name] = {
            "first_relevant_rank": result.first_relevant_rank,
            "top_files": result.ranked_files[:5],
            **{f"hit@{k}": result.hit_at(k, relevant) for k in KS},
            **{f"recall@{k}": result.recall_at(k, relevant) for k in KS},
        }
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Mean hit@k, recall@k and MRR per method."""
    summary: dict[str, dict[str, float]] = {}
    for method in ("keyword", "semantic", "hybrid"):
        values = [row[method] for row in rows]
        metrics = {
            key: sum(float(v[key]) for v in values) / len(values)
            for key in values[0]
            if key.startswith(("hit@", "recall@"))
        }
        metrics["mrr"] = sum(
            1.0 / v["first_relevant_rank"] if v["first_relevant_rank"] else 0.0 for v in values
        ) / len(values)
        summary[method] = metrics
    return summary


def render_markdown(rows: list[dict[str, Any]], title: str, embedder_name: str) -> str:
    s = summarize(rows)
    lines = [
        f"# {title}",
        "",
        (
            f"{len(rows)} cases. Query: the issue's title and body. Relevant: the source files the real"
            f" fix changed. Semantic search: `{embedder_name}`; keyword search: BM25 over the same"
            " chunks; hybrid: reciprocal rank fusion of both."
        ),
        "",
        "| Method | hit@1 | hit@3 | hit@5 | hit@10 | recall@5 | MRR |",
        "|---|---|---|---|---|---|---|",
    ]
    for method, m in s.items():
        lines.append(
            f"| {method} | {m['hit@1']:.0%} | {m['hit@3']:.0%} | {m['hit@5']:.0%} "
            f"| {m['hit@10']:.0%} | {m['recall@5']:.0%} | {m['mrr']:.2f} |"
        )
    lines += [
        "",
        (
            "hit@k: a changed file is among the top k files. recall@5: share of changed files in the"
            " top 5. MRR: mean of 1/rank of the first changed file."
        ),
        "",
        "## Cases",
        "",
        "| Case | Changed files | keyword rank | semantic rank | hybrid rank |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        ranks = [row[m]["first_relevant_rank"] or "–" for m in ("keyword", "semantic", "hybrid")]
        lines.append(
            f"| {row['case_id']} | {', '.join(row['relevant'])} | {ranks[0]} | {ranks[1]} | {ranks[2]} |"
        )
    return "\n".join(lines) + "\n"
