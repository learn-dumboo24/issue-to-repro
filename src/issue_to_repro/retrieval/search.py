"""Semantic code search for agents: hybrid (BM25 + embeddings) over a checkout's chunks.

The index for a checkout is built on first use and kept for the process, keyed by the checkout
path and a hash of its chunk texts, so a checkout whose code changes is re-indexed. Embeddings
are cached on disk (CachedEmbedder), so re-indexing only embeds changed chunks.
"""

import hashlib
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..tools.workspace import resolve_checkout
from .benchmark import fuse
from .bm25 import BM25Index
from .chunking import chunk_checkout
from .embedding import CachedEmbedder, Embedder, GeminiEmbedder
from .index import CodeIndex

DEFAULT_K = 8
_INDEXES: dict[tuple[str, str], tuple[CodeIndex, BM25Index]] = {}


def default_embedder() -> Embedder:
    s = get_settings()
    inner = GeminiEmbedder(
        s.embedding_model, s.embedding_dims, requests_per_minute=s.embedding_requests_per_minute
    )
    return CachedEmbedder(inner, s.embedding_cache_dir)


def semantic_search(
    repo_dir: str, query: str, k: int = DEFAULT_K, embedder: Embedder | None = None
) -> list[dict[str, Any]]:
    """Top-k chunks for `query` by reciprocal rank fusion of BM25 and embedding search."""
    if not query.strip():
        raise ValueError("query must not be empty")
    root = resolve_checkout(repo_dir)
    chunks = chunk_checkout(root)
    digest = hashlib.sha256("\0".join(c.text for c in chunks).encode()).hexdigest()
    key = (str(root), digest)
    if key not in _INDEXES:
        embedder = embedder or default_embedder()
        vectors = embedder.embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT") if chunks else []
        _INDEXES[key] = (CodeIndex(chunks, vectors, embedder), BM25Index(chunks))
    semantic, keyword = _INDEXES[key]
    depth = max(k * 5, 50)
    hits = fuse(keyword.search(query, depth), semantic.search(query, depth))[:k]
    return [
        {
            "path": h.chunk.path,
            "lines": f"{h.chunk.start_line}-{h.chunk.end_line}",
            "name": h.chunk.name,
            "score": round(h.score, 4),
        }
        for h in hits
    ]


def clear_cache() -> None:
    _INDEXES.clear()


def indexed_checkouts() -> list[Path]:
    return [Path(root) for root, _ in _INDEXES]
