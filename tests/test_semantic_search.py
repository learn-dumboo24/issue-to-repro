import pytest
from test_retrieval import SOURCE, WordEmbedder

from issue_to_repro.agents import build_agents
from issue_to_repro.config import Settings
from issue_to_repro.retrieval import search
from issue_to_repro.tools import semantic_search_tool


@pytest.fixture(autouse=True)
def fresh_index_cache():
    search.clear_cache()
    yield
    search.clear_cache()


@pytest.fixture
def checkout(workspace):
    (workspace / "demo" / "fmt.py").write_text(SOURCE)
    return workspace


def test_returns_ranked_chunks_with_locations(checkout):
    hits = search.semantic_search(
        str(checkout), "write usage formatter prog", embedder=WordEmbedder()
    )
    assert hits[0] == {
        "path": "demo/fmt.py",
        "lines": "12-13",
        "name": "Formatter.write_usage",
        "score": hits[0]["score"],
    }
    assert len(hits) <= search.DEFAULT_K


def test_index_is_built_once_and_rebuilt_when_code_changes(checkout):
    embedder = WordEmbedder()
    search.semantic_search(str(checkout), "add numbers", embedder=embedder)
    search.semantic_search(str(checkout), "write usage", embedder=embedder)
    document_calls = [c for c in embedder.calls if c[1] == "RETRIEVAL_DOCUMENT"]
    assert len(document_calls) == 1
    (checkout / "demo" / "extra.py").write_text("def extra():\n    pass\n")
    search.semantic_search(str(checkout), "extra", embedder=embedder)
    assert len([c for c in embedder.calls if c[1] == "RETRIEVAL_DOCUMENT"]) == 2
    assert search.indexed_checkouts() == [checkout.resolve(), checkout.resolve()]


def test_rejects_empty_queries_and_outside_paths(checkout, tmp_path_factory):
    with pytest.raises(ValueError):
        search.semantic_search(str(checkout), "  ", embedder=WordEmbedder())
    with pytest.raises(ValueError, match="outside the workspace"):
        search.semantic_search(str(tmp_path_factory.mktemp("x")), "q", embedder=WordEmbedder())


def test_tool_uses_the_default_embedder_and_wraps_errors(checkout, monkeypatch):
    monkeypatch.setattr(search, "default_embedder", WordEmbedder)
    ok = semantic_search_tool(str(checkout), "write usage")
    assert ok["status"] == "ok" and ok["result"][0]["name"] == "Formatter.write_usage"
    assert semantic_search_tool(str(checkout), "")["status"] == "error"


def test_embedding_api_failures_become_error_results(checkout, monkeypatch):
    from google.genai import errors

    class Overloaded:
        name = "x"

        def embed(self, texts, task):
            raise errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})

    monkeypatch.setattr(search, "default_embedder", Overloaded)
    result = semantic_search_tool(str(checkout), "write usage")
    assert result == {"status": "error", "error": "embedding API 503: UNAVAILABLE"}


def test_default_embedder_is_cached_gemini(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GOOGLE_API_KEY", "placeholder")
    embedder = search.default_embedder()
    assert type(embedder).__name__ == "CachedEmbedder"
    assert embedder.name == "gemini-embedding-2@768"


def test_retriever_gets_semantic_search_only_when_enabled():
    def names(settings):
        return [t.__name__ for t in build_agents(settings, offline=True).sub_agents[0].tools]

    assert names(Settings()) == ["search_code_tool", "read_file_tool"]
    assert names(Settings(retrieval="semantic")) == [
        "semantic_search_tool",
        "search_code_tool",
        "read_file_tool",
    ]
