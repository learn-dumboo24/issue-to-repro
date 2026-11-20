"""An in-memory cosine-similarity index over code chunks.

Kept deliberately small: a few hundred to a few thousand chunks per repository, unit vectors,
dot-product scoring. The `search` interface is what a managed store (Vertex AI Vector Search)
would implement for larger corpora.
"""

from dataclasses import dataclass
from pathlib import Path

from .chunking import Chunk, chunk_checkout
from .embedding import Embedder


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class CodeIndex:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]], embedder: Embedder):
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self.chunks, self.vectors, self.embedder = chunks, vectors, embedder

    @classmethod
    def build(
        cls, root: str | Path, embedder: Embedder, include_tests: bool = False
    ) -> "CodeIndex":
        chunks = chunk_checkout(root, include_tests=include_tests)
        vectors = embedder.embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT") if chunks else []
        return cls(chunks, vectors, embedder)

    def search(self, query: str, k: int = 10) -> list[Hit]:
        if not self.chunks:
            return []
        [q] = self.embedder.embed([query], "RETRIEVAL_QUERY")
        scored = [
            Hit(chunk, sum(a * b for a, b in zip(q, vec, strict=True)))
            for chunk, vec in zip(self.chunks, self.vectors, strict=True)
        ]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]
