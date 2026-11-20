import hashlib
import re
from collections.abc import Sequence

import pytest

from issue_to_repro.retrieval.chunking import WINDOW_LINES, chunk_checkout, chunk_source
from issue_to_repro.retrieval.embedding import CachedEmbedder, Task, normalize
from issue_to_repro.retrieval.index import CodeIndex

SOURCE = '''"""Module docstring."""

def add(a, b):
    return a - b


class Formatter:
    """Formats help."""

    width = 80

    def write_usage(self, prog):
        return prog

    async def flush(self):
        pass
'''


class WordEmbedder:
    """Deterministic stand-in for Gemini: hashed bag of words, unit length."""

    name = "words@64"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def embed(self, texts: Sequence[str], task: Task) -> list[list[float]]:
        self.calls.append((list(texts), task))
        out = []
        for text in texts:
            vec = [0.0] * 64
            for word in re.findall(r"[a-z]+", text.lower()):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
            vec[0] += 1e-6  # never all-zero
            out.append(normalize(vec))
        return out


def test_chunks_functions_class_headers_and_methods():
    chunks = chunk_source("pkg/fmt.py", SOURCE)
    assert [(c.name, c.start_line, c.end_line) for c in chunks] == [
        ("add", 3, 4),
        ("Formatter", 7, 11),
        ("Formatter.write_usage", 12, 13),
        ("Formatter.flush", 15, 16),
    ]
    assert chunks[1].text.startswith("# pkg/fmt.py :: Formatter\nclass Formatter:")
    assert chunks[2].location == "pkg/fmt.py:12-13"


def test_unparseable_or_flat_files_fall_back_to_line_windows():
    broken = "def broken(:\n" + "x = 1\n" * (WINDOW_LINES + 5)
    chunks = chunk_source("bad.py", broken)
    assert [(c.start_line, c.end_line) for c in chunks] == [
        (1, WINDOW_LINES),
        (WINDOW_LINES + 1, WINDOW_LINES + 6),
    ]
    assert chunk_source("consts.py", "X = 1\nY = 2\n")[0].name == "<lines 1->"
    assert chunk_source("empty.py", "") == []


def test_chunk_checkout_skips_tests_venvs_and_repro_files(tmp_path):
    for rel, text in {
        "src/pkg/core.py": "def core():\n    pass\n",
        "tests/test_core.py": "def test_core():\n    pass\n",
        "test_issue_repro_1.py": "def test_x():\n    pass\n",
        ".venv/lib/site.py": "def site():\n    pass\n",
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    assert [c.path for c in chunk_checkout(tmp_path)] == ["src/pkg/core.py"]
    assert {c.path for c in chunk_checkout(tmp_path, include_tests=True)} == {
        "src/pkg/core.py",
        "tests/test_core.py",
    }


def test_normalize_rejects_zero_vectors():
    assert normalize([3.0, 4.0]) == [0.6, 0.8]
    with pytest.raises(ValueError):
        normalize([0.0, 0.0])


def test_cache_only_embeds_what_it_has_not_seen(tmp_path):
    inner = WordEmbedder()
    cache = CachedEmbedder(inner, tmp_path / "cache")
    first = cache.embed(["alpha beta", "gamma"], "RETRIEVAL_DOCUMENT")
    second = cache.embed(["gamma", "alpha beta", "delta"], "RETRIEVAL_DOCUMENT")
    assert second[0] == pytest.approx(first[1]) and second[1] == pytest.approx(first[0])
    assert [texts for texts, _ in inner.calls] == [["alpha beta", "gamma"], ["delta"]]
    assert (cache.hits, cache.misses) == (2, 3)

    # The task is part of the key: a query is embedded separately from a document.
    cache.embed(["gamma"], "RETRIEVAL_QUERY")
    assert inner.calls[-1] == (["gamma"], "RETRIEVAL_QUERY")

    # Vectors persist across instances (a new process reuses the same cache).
    fresh_inner = WordEmbedder()
    CachedEmbedder(fresh_inner, tmp_path / "cache").embed(["alpha beta"], "RETRIEVAL_DOCUMENT")
    assert fresh_inner.calls == []


def test_index_ranks_the_relevant_chunk_first(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "fmt.py").write_text(SOURCE)
    (tmp_path / "pkg" / "net.py").write_text("def download(url):\n    return fetch(url)\n")
    index = CodeIndex.build(tmp_path, WordEmbedder())
    hits = index.search("usage of prog in write usage formatter", k=2)
    assert hits[0].chunk.name == "Formatter.write_usage"
    assert len(hits) == 2 and hits[0].score >= hits[1].score


def test_index_edge_cases(tmp_path):
    assert CodeIndex.build(tmp_path, WordEmbedder()).search("anything") == []
    with pytest.raises(ValueError):
        CodeIndex([], [[1.0]], WordEmbedder())
