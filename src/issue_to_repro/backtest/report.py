"""Summarise backtest results (JSONL from runner.run_backtest) into metrics and Markdown."""

import json
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Summary:
    cases: int
    verified: int  # reproduced, and the test passes once the real fix is applied
    reproduced: int  # sandbox verdict "reproduced" (verified or not)
    verdicts: dict[str, int]
    total_tokens: int
    tokens_per_case: float
    latency_p50_s: float
    latency_p95_s: float

    @property
    def verified_rate(self) -> float:
        return self.verified / self.cases if self.cases else 0.0

    @property
    def precision(self) -> float:
        """Of the reproductions claimed by the sandbox, the share the real fix confirms."""
        return self.verified / self.reproduced if self.reproduced else 0.0


def load_results(path: str | Path) -> list[dict[str, Any]]:
    """Read results, keeping the latest row per case (resumed runs append retried cases)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line]
    return list({row["case_id"]: row for row in rows}.values())


def summarize(results: list[dict[str, Any]]) -> Summary:
    tokens = [r["prompt_tokens"] + r["output_tokens"] for r in results]
    latencies = sorted(r["latency_s"] for r in results)
    return Summary(
        cases=len(results),
        verified=sum(1 for r in results if r["fail_to_pass"] is True),
        reproduced=sum(1 for r in results if r["verdict"] == "reproduced"),
        verdicts=dict(Counter(r["verdict"] for r in results).most_common()),
        total_tokens=sum(tokens),
        tokens_per_case=statistics.fmean(tokens) if tokens else 0.0,
        latency_p50_s=_percentile(latencies, 50),
        latency_p95_s=_percentile(latencies, 95),
    )


def render_markdown(results: list[dict[str, Any]], title: str) -> str:
    s = summarize(results)
    lines = [
        f"# {title}",
        "",
        (
            f"**Verified reproductions: {s.verified}/{s.cases} ({s.verified_rate:.0%})**: the"
            " agents' test fails on the buggy commit and passes once the real fix is applied."
        ),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases | {s.cases} |",
        f'| Sandbox said "reproduced" | {s.reproduced} |',
        f"| ...confirmed by the real fix (precision) | {s.verified} ({s.precision:.0%}) |",
        f"| Outcomes | {', '.join(f'{k}: {v}' for k, v in s.verdicts.items())} |",
        f"| Tokens, total / per case | {s.total_tokens:,} / {s.tokens_per_case:,.0f} |",
        f"| Latency per case, p50 / p95 | {s.latency_p50_s:.0f}s / {s.latency_p95_s:.0f}s |",
        "",
        "## Cases",
        "",
        "| Case | Verdict | Fail→pass | Attempts | LLM calls | Tokens | Time | Stopped |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        f2p = {True: "✅", False: "❌", None: "–"}[r["fail_to_pass"]]
        lines.append(
            f"| {r['case_id']} | {r['verdict']} | {f2p} | {r['attempts']} | {r['llm_calls']} "
            f"| {r['prompt_tokens'] + r['output_tokens']:,} | {r['latency_s']:.0f}s "
            f"| {r['stopped'] or r.get('error') or ''} |"
        )
    return "\n".join(lines) + "\n"


def _percentile(sorted_values: list[float], pct: int) -> float:
    if not sorted_values:
        return 0.0
    index = round((len(sorted_values) - 1) * pct / 100)
    return float(sorted_values[index])
