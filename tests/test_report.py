import json

from issue_to_repro.backtest.report import load_results, render_markdown, summarize


def result(case: str, verdict: str, f2p, tokens: int, latency: float, **extra) -> dict:
    return {
        "case_id": case,
        "verdict": verdict,
        "fail_to_pass": f2p,
        "attempts": 1,
        "llm_calls": 5,
        "prompt_tokens": tokens,
        "output_tokens": 0,
        "latency_s": latency,
        "stopped": None,
        **extra,
    }


RESULTS = [
    result("o/r#1", "reproduced", True, 1000, 10),
    result("o/r#2", "reproduced", False, 3000, 30),
    result("o/r#3", "no_attempt", None, 500, 5, stopped="llm_call_limit"),
    result("o/r#4", "setup_error", None, 0, 1, error="boom"),
]


def test_summarize():
    s = summarize(RESULTS)
    assert (s.cases, s.verified, s.reproduced) == (4, 1, 2)
    assert s.verified_rate == 0.25 and s.precision == 0.5
    assert s.verdicts == {"reproduced": 2, "no_attempt": 1, "setup_error": 1}
    assert (s.total_tokens, s.tokens_per_case) == (4500, 1125)
    assert (s.latency_p50_s, s.latency_p95_s) == (10, 30)


def test_empty_summary():
    s = summarize([])
    assert (s.cases, s.verified_rate, s.precision, s.latency_p95_s) == (0, 0.0, 0.0, 0.0)


def test_markdown(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in RESULTS))
    md = render_markdown(load_results(path), "Click")
    assert md.startswith("# Click")
    assert "**Verified reproductions: 1/4 (25%)**" in md
    assert "| o/r#1 | reproduced | ✅ |" in md and "| o/r#2 | reproduced | ❌ |" in md
    assert "llm_call_limit" in md and "boom" in md


def test_load_results_keeps_latest_row_per_case(tmp_path):
    path = tmp_path / "r.jsonl"
    retry = result("o/r#3", "reproduced", True, 10, 1)
    path.write_text("".join(json.dumps(r) + "\n" for r in [*RESULTS, retry]))
    loaded = load_results(path)
    assert len(loaded) == 4
    assert next(r for r in loaded if r["case_id"] == "o/r#3")["verdict"] == "reproduced"
