"""Turn a span file (observability.tracing) into per-agent, per-stage and slowest-call views."""

from collections import defaultdict
from typing import Any

AGENT_ORDER = ["retriever", "classifier", "reproducer", "verifier", "reporter"]
STAGES = ["backtest.prepare", "backtest.agents", "backtest.fix_check"]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _op(span: dict[str, Any]) -> str:
    return str(span["attributes"].get("gen_ai.operation.name") or span["name"].split(" ")[0])


def agent_breakdown(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Model calls, tokens, model time, tool calls and tool time per agent."""
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model_ms": 0.0,
            "tool_calls": 0,
            "tool_ms": 0.0,
        }
    )
    for span in spans:
        agent = span["attributes"].get("gen_ai.agent.name")
        if not agent:
            continue
        op, row = _op(span), rows[agent]
        if op == "generate_content":
            row["model_calls"] += 1
            row["input_tokens"] += _int(span["attributes"].get("gen_ai.usage.input_tokens"))
            row["output_tokens"] += _int(span["attributes"].get("gen_ai.usage.output_tokens"))
            row["model_ms"] += span["duration_ms"]
        elif op == "execute_tool":
            row["tool_calls"] += 1
            row["tool_ms"] += span["duration_ms"]
    order = {name: i for i, name in enumerate(AGENT_ORDER)}
    active = {
        k: v for k, v in rows.items() if v["model_calls"] or v["tool_calls"]
    }  # skip workflows
    return [
        {"agent": name, **values}
        for name, values in sorted(active.items(), key=lambda kv: order.get(kv[0], len(order)))
    ]


def stage_breakdown(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per backtest case: total time and time in each stage."""
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for span in spans:
        if span.get("parent_id"):
            by_parent[span["parent_id"]].append(span)
    rows = []
    for case in (s for s in spans if s["name"] == "backtest.case"):
        stages = {c["name"]: c["duration_ms"] for c in by_parent[case["span_id"]]}
        rows.append(
            {
                "case": case["attributes"].get("case.id", "?"),
                "verdict": case["attributes"].get("case.verdict", "?"),
                "total_ms": case["duration_ms"],
                **{stage.removeprefix("backtest."): stages.get(stage, 0.0) for stage in STAGES},
            }
        )
    return rows


def slowest_model_calls(spans: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    calls = [s for s in spans if _op(s) == "generate_content"]
    calls.sort(key=lambda s: s["duration_ms"], reverse=True)
    return [
        {
            "agent": s["attributes"].get("gen_ai.agent.name", "?"),
            "model": s["attributes"].get("gen_ai.request.model", "?"),
            "duration_ms": s["duration_ms"],
            "input_tokens": _int(s["attributes"].get("gen_ai.usage.input_tokens")),
        }
        for s in calls[:n]
    ]


def render_markdown(spans: list[dict[str, Any]], title: str = "Trace report") -> str:
    agents = agent_breakdown(spans)
    lines = [
        f"# {title}",
        "",
        "## Per agent",
        "",
        "| Agent | Model calls | Input tokens | Output tokens | Model time | Tool calls | Tool time |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in agents:
        lines.append(
            f"| {a['agent']} | {a['model_calls']} | {a['input_tokens']:,} | {a['output_tokens']:,} "
            f"| {a['model_ms'] / 1000:.1f}s | {a['tool_calls']} | {a['tool_ms'] / 1000:.1f}s |"
        )
    lines += [
        "",
        "## Per case",
        "",
        "| Case | Verdict | Total | Prepare | Agents | Fix check |",
        "|---|---|---|---|---|---|",
    ]
    for c in stage_breakdown(spans):
        lines.append(
            f"| {c['case']} | {c['verdict']} | {c['total_ms'] / 1000:.1f}s | "
            f"{c['prepare'] / 1000:.1f}s | {c['agents'] / 1000:.1f}s | {c['fix_check'] / 1000:.1f}s |"
        )
    lines += [
        "",
        "## Slowest model calls",
        "",
        "| Agent | Model | Time | Input tokens |",
        "|---|---|---|---|",
    ]
    for c in slowest_model_calls(spans):
        lines.append(
            f"| {c['agent']} | {c['model']} | {c['duration_ms'] / 1000:.1f}s | {c['input_tokens']:,} |"
        )
    return "\n".join(lines) + "\n"
