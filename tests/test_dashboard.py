import json
import sys

import pytest
from test_observability import SPANS

from issue_to_repro.observability.dashboard import Run, render, run_summary


def row(case, verdict, f2p, cost=0.01, **extra):
    return {
        "case_id": case,
        "verdict": verdict,
        "fail_to_pass": f2p,
        "attempts": 1,
        "llm_calls": 5,
        "prompt_tokens": 1000,
        "output_tokens": 0,
        "latency_s": 10.0,
        "stopped": None,
        "cost_usd": cost,
        **extra,
    }


PRICED = Run(
    "Haiku <b>",
    [
        row("o/r#1", "reproduced", True),
        row("o/r#2", "reproduced", False),
        row("o/r#3", "no_attempt", None),
    ],
)
FREE = Run("Flash-Lite", [row("o/r#1", "reproduced", True, cost=None)])


def test_run_summary_costs():
    s = run_summary(PRICED)
    assert (s["verified"], s["cases"]) == (1, 3)
    assert s["cost"] == pytest.approx(0.03) and s["cost_per_fix"] == pytest.approx(0.03)
    free = run_summary(FREE)
    assert free["cost"] is None and free["cost_per_fix"] is None
    nothing_verified = run_summary(Run("x", [row("o/r#1", "no_attempt", None)]))
    assert nothing_verified["cost_per_fix"] is None


def test_render_shows_states_escapes_labels_and_optional_sections():
    page = render([PRICED, FREE])
    assert page.startswith("<!doctype html>") and "<title>Backtest dashboard</title>" in page
    assert "Haiku &lt;b&gt;" in page and "Haiku <b>" not in page
    assert "✓ verified" in page and "✗ rejected by fix" in page and "no attempt" in page
    assert "not run" in page  # o/r#2 and o/r#3 are missing from FREE
    assert "free tier / not priced" in page and "≤ $0.03" in page
    assert "<h2>Retrieval</h2>" not in page and "Where the time" not in page
    rows = [
        {
            "case_id": "o/r#1",
            "relevant": ["a.py"],
            "chunks": 3,
            **{
                m: {
                    "first_relevant_rank": 1,
                    "hit@1": True,
                    "hit@3": True,
                    "hit@5": True,
                    "hit@10": True,
                    "recall@1": 1.0,
                    "recall@3": 1.0,
                    "recall@5": 1.0,
                    "recall@10": 1.0,
                }
                for m in ("keyword", "semantic", "hybrid")
            },
        }
    ]
    full = render([PRICED], retrieval_rows=rows, spans=SPANS)
    assert "<h2>Retrieval</h2>" in full and "1 issues" in full
    assert "Where the time and tokens go: o/r#1 on ?" in full
    assert "<td>retriever</td><td>2</td><td>300</td>" in full


def test_trace_without_case_spans_gets_a_generic_label():
    spans = [s for s in SPANS if s["name"] != "backtest.case"]
    assert "Where the time and tokens go: traced run" in render([FREE], spans=spans)


def test_cli_dashboard(tmp_path, monkeypatch):
    import issue_to_repro

    results = tmp_path / "r.jsonl"
    results.write_text("".join(json.dumps(r) + "\n" for r in PRICED.rows))
    retrieval = tmp_path / "ret.jsonl"
    retrieval.write_text("")
    trace = tmp_path / "t.jsonl"
    trace.write_text("".join(json.dumps(s) + "\n" for s in SPANS))
    out = tmp_path / "site" / "index.html"
    args = [
        "issue-to-repro",
        "dashboard",
        "--run",
        f"Haiku={results}",
        "--retrieval",
        str(retrieval),
        "--trace",
        str(trace),
        "--out",
        str(out),
    ]
    monkeypatch.setattr(sys, "argv", args)
    issue_to_repro.main()
    assert "Haiku" in out.read_text()
    monkeypatch.setattr(
        sys, "argv", ["issue-to-repro", "dashboard", "--run", "no-equals", "--out", str(out)]
    )
    with pytest.raises(SystemExit, match="LABEL=results.jsonl"):
        issue_to_repro.main()
