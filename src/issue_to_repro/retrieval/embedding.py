"""Embedders: Gemini via google-genai, wrapped in an on-disk cache keyed by content hash."""

import hashlib
import math
import sqlite3
import time
from array import array
from collections import deque
from collections.abc import Callable, Sequence
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


class RateLimiter:
    """Keeps at most `per_minute` units (embedded texts) in any 60-second window.

    The Gemini free tier counts every text in a batch as one request (100/minute for
    gemini-embedding-2), so pacing on our side beats relying on 429 retries.
    """

    WINDOW_S = 60.0

    def __init__(
        self,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if per_minute < 1:
            raise ValueError("per_minute must be at least 1")
        self.per_minute, self._clock, self._sleep = per_minute, clock, sleep
        self._spent: deque[tuple[float, int]] = deque()

    def acquire(self, units: int) -> None:
        if units > self.per_minute:
            raise ValueError(f"cannot take {units} units at once; the limit is {self.per_minute}")
        while True:
            now = self._clock()
            while self._spent and self._spent[0][0] <= now - self.WINDOW_S:
                self._spent.popleft()
            used = sum(n for _, n in self._spent)
            if used + units <= self.per_minute:
                self._spent.append((now, units))
                return
            self._sleep(self._spent[0][0] + self.WINDOW_S - now)


class GeminiEmbedder:
    """Gemini embeddings (`gemini-embedding-2` by default), batched, unit-normalised."""

    def __init__(
        self, model: str, dims: int, requests_per_minute: int = 90, retry_attempts: int = 6
    ) -> None:
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
        self._limiter = RateLimiter(requests_per_minute)
        self._batch = min(BATCH_SIZE, requests_per_minute)

    def embed(self, texts: Sequence[str], task: Task) -> list[list[float]]:  # pragma: no cover
        vectors: list[list[float]] = []
        config = self._types.EmbedContentConfig(task_type=task, output_dimensionality=self._dims)
        for start in range(0, len(texts), self._batch):
            batch = list(texts[start : start + self._batch])
            self._limiter.acquire(len(batch))
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
