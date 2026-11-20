import json
import sys

import pytest
from conftest import git
from test_checkout import make_case
from test_retrieval import WordEmbedder

from issue_to_repro.retrieval import benchmark
from issue_to_repro.retrieval.bm25 import BM25Index, tokenize
from issue_to_repro.retrieval.chunking import Chunk
from issue_to_repro.retrieval.index import Hit


def chunk(path: str, line: int, text: str) -> Chunk:
    return Chunk(path, line, line + 1, f"f{line}", text)


def test_tokenize_splits_identifiers():
    assert tokenize("HelpFormatter.write_usage(HTTPError, x2)") == [
        "help",
        "formatter",
        "write",
        "usage",
        "http",
        "error",
        "x",
        "2",
    ]


def test_bm25_prefers_rarer_matching_terms():
    chunks = [
        chunk("a.py", 1, "def wrap_text(text): return text"),
        chunk("b.py", 1, "def write_usage(prog): return prog"),
        chunk("c.py", 1, "def write_text(text): return text"),
    ]
    index = BM25Index(chunks)
    assert [h.chunk.path for h in index.search("usage line breaks", 3)] == ["b.py"]
    assert index.search("nothing matches", 3) == []
    assert BM25Index([]).search("x") == []


def test_fuse_rewards_agreement():
    a, b, c = chunk("a.py", 1, "a"), chunk("b.py", 1, "b"), chunk("c.py", 1, "c")
    first = [Hit(a, 3), Hit(b, 2), Hit(c, 1)]
    second = [Hit(b, 3), Hit(c, 2), Hit(a, 1)]
    assert benchmark.fuse(first, second)[0].chunk.path == "b.py"


def test_evaluate_collapses_chunks_to_files():
    hits = [
        Hit(chunk("x.py", 1, ""), 1),
        Hit(chunk("x.py", 9, ""), 1),
        Hit(chunk("fix.py", 1, ""), 1),
    ]
    result = benchmark.evaluate(hits, {"fix.py", "other.py"})
    assert result.ranked_files == ["x.py", "fix.py"]
    assert result.first_relevant_rank == 2
    assert not result.hit_at(1, {"fix.py"}) and result.hit_at(2, {"fix.py"})
    assert result.recall_at(5, {"fix.py", "other.py"}) == 0.5
    assert benchmark.evaluate([], {"fix.py"}).first_relevant_rank is None


def test_snapshot_extracts_the_commit_once(history, tmp_path):
    repo, base, _ = history
    root = benchmark.snapshot(repo, base, tmp_path / "snaps")
    assert (root / "pkg" / "core.py").read_text() == "x = 1\n"
    (root / "marker").write_text("kept")
    assert benchmark.snapshot(repo, base, tmp_path / "snaps") == root
    assert (root / "marker").exists()


def test_evaluate_case_and_report(history, tmp_path):
    repo, base, fix = history
    (tmp_path / "extra").mkdir()
    git(repo, "checkout", "-q", base)
    (repo / "pkg" / "util.py").write_text("def unrelated_network_call():\n    pass\n")
    (repo / "pkg" / "core.py").write_text("def rounding(x):\n    return round(x)\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "more code")
    new_base = git(repo, "rev-parse", "HEAD")
    case = make_case(new_base, fix)
    case = case.__class__(
        **{**case.__dict__, "issue_title": "rounding is wrong", "issue_body": "round x"}
    )
    root = benchmark.snapshot(repo, new_base, tmp_path / "snaps")
    row = benchmark.evaluate_case(case, root, WordEmbedder())
    assert row["relevant"] == ["pkg/core.py"] and row["chunks"] == 2
    for method in ("keyword", "semantic", "hybrid"):
        assert row[method]["first_relevant_rank"] == 1 and row[method]["hit@1"] is True

    summary = benchmark.summarize([row])
    assert summary["keyword"]["mrr"] == 1.0 and summary["semantic"]["recall@5"] == 1.0
    md = benchmark.render_markdown([row], "T", "words@64")
    assert "| keyword | 100% |" in md and "| o/proj#12 | pkg/core.py | 1 | 1 | 1 |" in md

    gone = case.__class__(**{**case.__dict__, "source_files": ("pkg/new_file.py",)})
    assert benchmark.evaluate_case(gone, root, WordEmbedder()) is None


def test_cli_retrieval_benchmark(monkeypatch, history, tmp_path, capsys):
    import issue_to_repro
    from issue_to_repro.backtest.dataset import build_dataset, write_jsonl
    from issue_to_repro.retrieval import embedding

    repo, _, _ = history
    issue = {
        "url": "u",
        "title": "x value",
        "body": "x",
        "labels": [],
        "state": "closed",
        "created_at": "",
        "is_pull_request": False,
    }
    cases, _ = build_dataset("o/r", repo, since="2020-01-01", fetch=lambda r, n: issue)
    dataset = tmp_path / "d.jsonl"
    write_jsonl(cases, dataset)
    monkeypatch.setattr(embedding, "GeminiEmbedder", lambda *a, **k: WordEmbedder())
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", str(tmp_path / "cache"))
    out, report = tmp_path / "rows.jsonl", tmp_path / "r.md"
    args = [
        "issue-to-repro",
        "retrieval",
        "benchmark",
        "--dataset",
        str(dataset),
        "--source",
        str(repo),
        "--out",
        str(out),
        "--report",
        str(report),
    ]
    monkeypatch.setattr(sys, "argv", args)
    issue_to_repro.main()
    assert json.loads(out.read_text())["case_id"] == "o/r#12"
    assert report.read_text().startswith("# Retrieval benchmark: d")
    issue_to_repro.main()  # resumes: nothing new to do
    assert len(out.read_text().splitlines()) == 1
    monkeypatch.setattr(sys, "argv", [*args, "--since", "2999"])
    issue_to_repro.main()
    assert "o/r#12: first relevant file rank" in capsys.readouterr().out


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
