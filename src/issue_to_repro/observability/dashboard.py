"""A self-contained HTML dashboard from backtest results, retrieval rows and an optional trace.

No external scripts, fonts or styles: the page works opened from disk or served by GitHub Pages.
"""

import html
from dataclasses import dataclass
from typing import Any

from ..backtest.report import summarize
from ..retrieval.benchmark import summarize as summarize_retrieval
from .analyze import agent_breakdown

CSS = """
:root { --bg:#fbfbfa; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dd; --card:#ffffff;
  --accent:#2f6fde; --good:#2e7d4f; --bad:#b3412f; --none:#9a9a94; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#161615; --fg:#ecebe7; --muted:#a3a29c; --line:#34332f; --card:#1f1f1d;
  --accent:#7aa7ff; --good:#6cc08f; --bad:#ef8a78; --none:#77766f; } }
:root[data-theme="dark"] { --bg:#161615; --fg:#ecebe7; --muted:#a3a29c; --line:#34332f;
  --card:#1f1f1d; --accent:#7aa7ff; --good:#6cc08f; --bad:#ef8a78; --none:#77766f; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1040px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:1.6rem; margin:0 0 4px; } h2 { font-size:1.15rem; margin:36px 0 10px; }
p.lead { color:var(--muted); margin:0 0 8px; }
.wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card); }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { padding:8px 12px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
th { font-weight:600; color:var(--muted); font-size:.85rem; }
tr:last-child td { border-bottom:0; }
.good { color:var(--good); font-weight:600; } .bad { color:var(--bad); } .none { color:var(--none); }
.bar { display:flex; align-items:center; gap:10px; margin:6px 0; }
.bar .label { width:220px; flex:none; font-size:.9rem; }
.bar .track { flex:1; height:14px; background:var(--line); border-radius:7px; overflow:hidden; }
.bar .fill { height:100%; background:var(--accent); }
.bar .value { width:64px; text-align:right; font-variant-numeric:tabular-nums; }
.note { color:var(--muted); font-size:.85rem; margin-top:8px; }
@media (max-width: 600px) { .bar .label { width:120px; } }
"""


@dataclass(frozen=True)
class Run:
    label: str
    rows: list[dict[str, Any]]


def _e(value: Any) -> str:
    return html.escape(str(value))


def _cost(rows: list[dict[str, Any]]) -> float | None:
    costs = [r.get("cost_usd") for r in rows]
    return None if any(c is None for c in costs) else sum(c or 0.0 for c in costs)


def run_summary(run: Run) -> dict[str, Any]:
    s = summarize(run.rows)
    cost = _cost(run.rows)
    return {
        "label": run.label,
        "cases": s.cases,
        "verified": s.verified,
        "precision": s.precision,
        "precision_interval": s.precision_interval,
        "tokens": s.tokens_per_case,
        "p50": s.latency_p50_s,
        "p95": s.latency_p95_s,
        "cost": cost,
        "cost_per_fix": (cost / s.verified) if cost is not None and s.verified else None,
    }


def _runs_table(summaries: list[dict[str, Any]]) -> str:
    head = (
        "<tr><th>Run</th><th>Verified</th><th>Precision (95% CI)</th><th>Tokens / case</th>"
        "<th>p50 / p95</th><th>Cost</th><th>Cost / verified fix</th></tr>"
    )
    body = []
    for s in summaries:
        cost = "free tier / not priced" if s["cost"] is None else f"≤ ${s['cost']:.2f}"
        per_fix = "–" if s["cost_per_fix"] is None else f"≤ ${s['cost_per_fix']:.3f}"
        low, high = s["precision_interval"]
        body.append(
            f"<tr><td>{_e(s['label'])}</td><td>{s['verified']} / {s['cases']}</td>"
            f"<td>{s['precision']:.0%} <small>({low:.0%}–{high:.0%})</small></td>"
            f"<td>{s['tokens']:,.0f}</td>"
            f"<td>{s['p50']:.0f}s / {s['p95']:.0f}s</td><td>{cost}</td><td>{per_fix}</td></tr>"
        )
    return f'<div class="wrap"><table>{head}{"".join(body)}</table></div>'


def _bars(summaries: list[dict[str, Any]]) -> str:
    out = []
    for s in summaries:
        share = s["verified"] / s["cases"] if s["cases"] else 0.0
        out.append(
            f'<div class="bar"><span class="label">{_e(s["label"])}</span>'
            f'<span class="track" role="img" aria-label="{share:.0%} verified">'
            f'<span class="fill" style="display:block;width:{share * 100:.1f}%"></span></span>'
            f'<span class="value">{s["verified"]}/{s["cases"]}</span></div>'
        )
    return "".join(out)


def _case_grid(runs: list[Run]) -> str:
    cases = sorted({r["case_id"] for run in runs for r in run.rows})
    head = "<tr><th>Case</th>" + "".join(f"<th>{_e(run.label)}</th>" for run in runs) + "</tr>"
    body = []
    for case in cases:
        cells = []
        for run in runs:
            row = next((r for r in run.rows if r["case_id"] == case), None)
            if row is None:
                cells.append('<td class="none">not run</td>')
            elif row["fail_to_pass"] is True:
                cells.append('<td class="good">✓ verified</td>')
            elif row["verdict"] == "reproduced":
                cells.append('<td class="bad">✗ rejected by fix</td>')
            else:
                cells.append(f'<td class="none">{_e(row["verdict"].replace("_", " "))}</td>')
        body.append(f"<tr><td>{_e(case)}</td>{''.join(cells)}</tr>")
    return f'<div class="wrap"><table>{head}{"".join(body)}</table></div>'


def _retrieval_table(rows: list[dict[str, Any]]) -> str:
    s = summarize_retrieval(rows)
    head = "<tr><th>Method</th><th>Right file first</th><th>In top 3</th><th>In top 5</th><th>MRR</th></tr>"
    body = "".join(
        f"<tr><td>{_e(m)}</td><td>{v['hit@1']:.0%}</td><td>{v['hit@3']:.0%}</td>"
        f"<td>{v['hit@5']:.0%}</td><td>{v['mrr']:.2f}</td></tr>"
        for m, v in s.items()
    )
    note = f'<p class="note">{len(rows)} issues; relevant = files the real fix changed.</p>'
    return f'<div class="wrap"><table>{head}{body}</table></div>{note}'


def _agent_table(spans: list[dict[str, Any]]) -> str:
    head = (
        "<tr><th>Agent</th><th>Model calls</th><th>Input tokens</th><th>Output tokens</th>"
        "<th>Model time</th><th>Tool calls</th><th>Tool time</th></tr>"
    )
    body = "".join(
        f"<tr><td>{_e(a['agent'])}</td><td>{a['model_calls']}</td><td>{a['input_tokens']:,}</td>"
        f"<td>{a['output_tokens']:,}</td><td>{a['model_ms'] / 1000:.1f}s</td>"
        f"<td>{a['tool_calls']}</td><td>{a['tool_ms'] / 1000:.1f}s</td></tr>"
        for a in agent_breakdown(spans)
    )
    return f'<div class="wrap"><table>{head}{body}</table></div>'


def _trace_label(spans: list[dict[str, Any]]) -> str:
    cases = [s["attributes"] for s in spans if s["name"] == "backtest.case"]
    if not cases:
        return "traced run"
    ids = ", ".join(sorted({str(c.get("case.id", "?")) for c in cases}))
    models = ", ".join(sorted({str(c.get("case.models", "?")) for c in cases}))
    return f"{ids} on {models}"


def render(
    runs: list[Run],
    retrieval_rows: list[dict[str, Any]] | None = None,
    spans: list[dict[str, Any]] | None = None,
    title: str = "issue-to-repro: backtest dashboard",
) -> str:
    summaries = [run_summary(run) for run in runs]
    sections = [
        f"<h1>{_e(title)}</h1>",
        (
            '<p class="lead">Each case is a real, already-fixed bug. A reproduction is '
            "<b>verified</b> only if the agents' test fails on the buggy commit and passes once "
            "the real fix is applied. Costs are upper-bound estimates.</p>"
        ),
        "<h2>Runs</h2>",
        _runs_table(summaries),
        "<h2>Verified reproductions</h2>",
        _bars(summaries),
        "<h2>Per case</h2>",
        _case_grid(runs),
    ]
    if retrieval_rows:
        sections += ["<h2>Retrieval</h2>", _retrieval_table(retrieval_rows)]
    if spans:
        sections += [
            f"<h2>Where the time and tokens go: {_e(_trace_label(spans))}</h2>",
            _agent_table(spans),
        ]
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Backtest dashboard</title><style>{CSS}</style></head>"
        f"<body><main>{''.join(sections)}</main></body></html>\n"
    )
