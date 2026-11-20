"""Embedders: Gemini via google-genai, wrapped in an on-disk cache keyed by content hash."""

import hashlib
import math
import sqlite3
from array import array
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

Task = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
BATCH_SIZE = 100


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str], task: Task) -> list[list[float]]: ...


def normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        raise ValueError("cannot normalise a zero vector")
    return [v / norm for v in vector]


class GeminiEmbedder:
    """Gemini embeddings (`gemini-embedding-2` by default), batched, unit-normalised."""

    def __init__(self, model: str, dims: int, retry_attempts: int = 6) -> None:
        from google import genai
        from google.genai import types

        self.name = f"{model}@{dims}"
        self._model, self._dims, self._types = model, dims, types
        retry = types.HttpRetryOptions(
            attempts=retry_attempts,
            initial_delay=2.0,
            max_delay=60.0,
            http_status_codes=[429, 500, 503, 504],
        )
        self._client = genai.Client(http_options=types.HttpOptions(retry_options=retry))

    def embed(self, texts: Sequence[str], task: Task) -> list[list[float]]:  # pragma: no cover
        vectors: list[list[float]] = []
        config = self._types.EmbedContentConfig(task_type=task, output_dimensionality=self._dims)
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            # One Content per text: gemini-embedding-2 merges a plain list[str] into a single
            # embedding, while separate Content items get one embedding each (on all models).
            contents = [self._types.Content(parts=[self._types.Part(text=t)]) for t in batch]
            response = self._client.models.embed_content(
                model=self._model, contents=contents, config=config
            )
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch):
                raise RuntimeError(f"asked for {len(batch)} embeddings, got {len(embeddings)}")
            vectors.extend(normalize(e.values or []) for e in embeddings)
        return vectors


class CachedEmbedder:
    """Caches another embedder's vectors in SQLite, keyed by (embedder, task, text) hash, so
    re-indexing a checkout only embeds chunks whose text changed."""

    def __init__(self, inner: Embedder, cache_dir: str | Path) -> None:
        self.inner = inner
        self.name = inner.name
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(Path(cache_dir) / "embeddings.sqlite")
        self._db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vec BLOB)")
        self.hits = self.misses = 0

    def embed(self, texts: Sequence[str], task: Task) -> list[list[float]]:
        keys = [self._key(text, task) for text in texts]
        found = dict(self._lookup(set(keys)))
        missing = [i for i, key in enumerate(keys) if key not in found]
        self.hits += len(keys) - len(missing)
        self.misses += len(missing)
        if missing:
            fresh = self.inner.embed([texts[i] for i in missing], task)
            rows = [
                (keys[i], array("f", vec).tobytes()) for i, vec in zip(missing, fresh, strict=True)
            ]
            with self._db:
                self._db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)", rows)
            found.update((key, list(vec)) for (key, _), vec in zip(rows, fresh, strict=True))
        return [found[key] for key in keys]

    def _key(self, text: str, task: Task) -> str:
        return hashlib.sha256(f"{self.name}\0{task}\0{text}".encode()).hexdigest()

    def _lookup(self, keys: set[str]) -> list[tuple[str, list[float]]]:
        found = []
        key_list = list(keys)
        for start in range(0, len(key_list), 500):  # stay under SQLite's variable limit
            part = key_list[start : start + 500]
            marks = ",".join("?" * len(part))
            for key, blob in self._db.execute(
                f"SELECT key, vec FROM vectors WHERE key IN ({marks})", part
            ):
                vec = array("f")
                vec.frombytes(blob)
                found.append((key, list(vec)))
        return found
