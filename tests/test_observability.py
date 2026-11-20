import json
import sys

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from test_runner import FIXED_BEHAVIOUR, agent_writing

from issue_to_repro.backtest.runner import run_backtest
from issue_to_repro.observability import analyze, tracing
from issue_to_repro.observability.tracing import JsonlSpanExporter, clean_attributes, load_spans


def test_clean_attributes_drops_secrets_and_truncates():
    cleaned = clean_attributes(
        {
            "http.authorization": "Bearer x",
            "x-goog-api-key": "k",
            "client.secret": "s",
            "gen_ai.usage.input_tokens": 12,
            "long": "y" * 5000,
            "list": ("a", "b" * 5000),
        }
    )
    assert set(cleaned) == {"gen_ai.usage.input_tokens", "long", "list"}
    assert cleaned["gen_ai.usage.input_tokens"] == 12
    assert cleaned["long"].endswith("... [5000 chars]") and len(cleaned["long"]) < 2100
    assert len(cleaned["list"][1]) == tracing.MAX_VALUE_CHARS


@pytest.fixture
def traced(tmp_path, monkeypatch):
    """A private tracer provider writing to a temp file (the global one can only be set once)."""
    path = tmp_path / "spans.jsonl"
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(path)))
    monkeypatch.setattr("issue_to_repro.backtest.runner.TRACER", provider.get_tracer("test"))
    yield path
    provider.shutdown()


def test_backtest_case_spans_nest_stages(backtest_setup, traced):
    case, prepare, out = backtest_setup
    run_backtest([case], out, prepare, agent_writing(FIXED_BEHAVIOUR), log=lambda m: None)
    spans = load_spans(traced)
    by_name = {s["name"]: s for s in spans}
    assert set(by_name) == {
        "backtest.case",
        "backtest.prepare",
        "backtest.agents",
        "backtest.fix_check",
    }
    root = by_name["backtest.case"]
    assert root["parent_id"] is None and root["attributes"]["case.id"] == "o/proj#12"
    assert root["attributes"]["case.verdict"] == "reproduced"
    assert root["attributes"]["case.fail_to_pass"] == "True"
    for stage in ("backtest.prepare", "backtest.agents", "backtest.fix_check"):
        assert by_name[stage]["parent_id"] == root["span_id"]
        assert by_name[stage]["trace_id"] == root["trace_id"]


def span(name, span_id, parent=None, ms=1.0, **attrs):
    return {
        "name": name,
        "span_id": span_id,
        "parent_id": parent,
        "duration_ms": ms,
        "trace_id": "t",
        "status": "OK",
        "attributes": attrs,
    }


SPANS = [
    span("backtest.case", "c1", ms=10_000, **{"case.id": "o/r#1", "case.verdict": "reproduced"}),
    span("backtest.prepare", "p1", "c1", ms=1_000),
    span("backtest.agents", "a1", "c1", ms=8_000),
    span("backtest.fix_check", "f1", "c1", ms=500),
    span(
        "invoke_agent coordinator",
        "w1",
        "a1",
        ms=8_000,
        **{"gen_ai.agent.name": "coordinator", "gen_ai.operation.name": "invoke_agent"},
    ),
    span(
        "generate_content m",
        "g1",
        "w1",
        ms=3_000,
        **{
            "gen_ai.agent.name": "retriever",
            "gen_ai.operation.name": "generate_content",
            "gen_ai.request.model": "m",
            "gen_ai.usage.input_tokens": "100",
            "gen_ai.usage.output_tokens": "10",
        },
    ),
    span(
        "generate_content m",
        "g2",
        "w1",
        ms=500,
        **{
            "gen_ai.agent.name": "retriever",
            "gen_ai.operation.name": "generate_content",
            "gen_ai.request.model": "m",
            "gen_ai.usage.input_tokens": "200",
            "gen_ai.usage.output_tokens": "x",
        },
    ),
    span(
        "execute_tool t",
        "t1",
        "w1",
        ms=20,
        **{"gen_ai.agent.name": "retriever", "gen_ai.operation.name": "execute_tool"},
    ),
    span(
        "generate_content m",
        "g3",
        "w1",
        ms=1_000,
        **{
            "gen_ai.agent.name": "reproducer",
            "gen_ai.operation.name": "generate_content",
            "gen_ai.request.model": "m",
            "gen_ai.usage.input_tokens": "50",
        },
    ),
    span(
        "generate_content m",
        "g4",
        "w1",
        ms=10,
        **{"gen_ai.agent.name": "custom", "gen_ai.operation.name": "generate_content"},
    ),
]


def test_agent_breakdown_sums_per_agent_and_skips_workflows():
    rows = {r["agent"]: r for r in analyze.agent_breakdown(SPANS)}
    assert list(rows) == ["retriever", "reproducer", "custom"]
    assert rows["retriever"] == {
        "agent": "retriever",
        "model_calls": 2,
        "input_tokens": 300,
        "output_tokens": 10,
        "model_ms": 3_500,
        "tool_calls": 1,
        "tool_ms": 20,
    }


def test_stage_breakdown_and_slowest_calls():
    [case] = analyze.stage_breakdown(SPANS)
    assert case == {
        "case": "o/r#1",
        "verdict": "reproduced",
        "total_ms": 10_000,
        "prepare": 1_000,
        "agents": 8_000,
        "fix_check": 500,
    }
    slow = analyze.slowest_model_calls(SPANS, n=2)
    assert [s["duration_ms"] for s in slow] == [3_000, 1_000]
    assert slow[0] == {
        "agent": "retriever",
        "model": "m",
        "duration_ms": 3_000,
        "input_tokens": 100,
    }


def test_markdown_and_cli(tmp_path, monkeypatch, capsys):
    md = analyze.render_markdown(SPANS, "T")
    assert "| retriever | 2 | 300 | 10 | 3.5s | 1 | 0.0s |" in md
    assert "| o/r#1 | reproduced | 10.0s | 1.0s | 8.0s | 0.5s |" in md
    path = tmp_path / "spans.jsonl"
    path.write_text("".join(json.dumps(s) + "\n" for s in SPANS))
    import issue_to_repro

    monkeypatch.setattr(sys, "argv", ["issue-to-repro", "trace", "report", "--trace", str(path)])
    issue_to_repro.main()
    assert "## Per agent" in capsys.readouterr().out
    out = tmp_path / "r.md"
    monkeypatch.setattr(
        sys, "argv", ["issue-to-repro", "trace", "report", "--trace", str(path), "--out", str(out)]
    )
    issue_to_repro.main()
    assert out.read_text().startswith("# Trace report")
