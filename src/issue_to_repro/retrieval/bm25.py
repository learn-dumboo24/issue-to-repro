"""Okapi BM25 over the same chunks as the semantic index: the keyword baseline."""

import math
import re
from collections import Counter

from .chunking import Chunk
from .index import Hit

# Acronyms first ("HTTPError" -> HTTP, Error), then words ("writeUsage" -> write, Usage), digits.
WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def tokenize(text: str) -> list[str]:
    """Split identifiers too: `write_usage` -> write, usage; `HelpFormatter` -> help, formatter."""
    return [w.lower() for w in WORD.findall(text)]


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks, self.k1, self.b = chunks, k1, b
        self._terms = [Counter(tokenize(c.text)) for c in chunks]
        self._lengths = [sum(t.values()) for t in self._terms]
        self._avg = (sum(self._lengths) / len(chunks)) if chunks else 0.0
        df: Counter[str] = Counter()
        for terms in self._terms:
            df.update(terms.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 10) -> list[Hit]:
        words = [w for w in set(tokenize(query)) if w in self._idf]
        scored = []
        for chunk, terms, length in zip(self.chunks, self._terms, self._lengths, strict=True):
            score = 0.0
            for word in words:
                tf = terms.get(word, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * length / self._avg)
                    score += self._idf[word] * tf * (self.k1 + 1) / norm
            if score > 0:
                scored.append(Hit(chunk, score))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]
