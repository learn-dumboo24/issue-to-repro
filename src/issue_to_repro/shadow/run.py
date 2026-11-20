"""Run the agents on selected open issues and record what the sandbox found.

There is no fix to check against yet, so "reproduced" here means the sandbox saw the test fail on
the repository's current default branch in every run. A person reviews each test against the
issue before anything is shared with maintainers.
"""

import json
import re
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..backtest.runner import MAX_REPORT_CHARS, MAX_TRACE_STEPS, AgentRun, issue_prompt
from ..config import Settings
from .select import Candidate

PrepareLive = Callable[[str, int], Path]
RunPrompt = Callable[[str, Settings], AgentRun]


@dataclass
class ShadowResult:
    repo: str
    issue: int
    title: str
    url: str
    created_at: str
    commit: str | None  # the default-branch commit the agents worked on
    classification: str  # the classifier's first word, e.g. "bug" or "feature_request"
    verdict: str  # sandbox verdict of the last attempt, or no_attempt / setup_error
    attempts: int
    test_path: str | None
    test_code: str | None
    output_tail: str | None  # the end of the last test run's output
    llm_calls: int
    tokens: int
    latency_s: float
    stopped: str | None
    models: str
    report: str
    error: str | None = None
    trace: list[str] = field(default_factory=list)


def classification(trace: list[str]) -> str:
    for line in trace:
        if line.startswith("[classifier] "):
            words = re.findall(r"[a-z_]+", line.removeprefix("[classifier] ").lower())
            return words[0] if words else "unknown"
    return "unknown"


def run_candidate(
    candidate: Candidate, prepare: PrepareLive, run_prompt: RunPrompt, settings: Settings
) -> ShadowResult:
    started = time.monotonic()
    common: dict[str, Any] = {
        "repo": candidate.repo,
        "issue": candidate.number,
        "title": candidate.title,
        "url": candidate.url,
        "created_at": candidate.created_at,
        "models": f"{settings.coordinator_model}/{settings.worker_model}",
    }
    try:
        checkout = prepare(candidate.repo, candidate.number)
        commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        return ShadowResult(
            **common,
            commit=None,
            classification="unknown",
            verdict="setup_error",
            attempts=0,
            test_path=None,
            test_code=None,
            output_tail=None,
            llm_calls=0,
            tokens=0,
            latency_s=round(time.monotonic() - started, 1),
            stopped=None,
            report="",
            error=f"{type(exc).__name__}: {detail}"[:2_000],
        )
    ref = f"{candidate.repo}#{candidate.number}"
    run = run_prompt(issue_prompt(ref, candidate.title, candidate.body, checkout), settings)
    attempts = [r["result"] for r in run.repro_results if r.get("status") == "ok"]
    last = attempts[-1] if attempts else None
    return ShadowResult(
        **common,
        commit=commit,
        classification=classification(run.trace),
        verdict=last["verdict"] if last else "no_attempt",
        attempts=len(attempts),
        test_path=last["test_path"] if last else None,
        test_code=(checkout / last["test_path"]).read_text(encoding="utf-8") if last else None,
        output_tail=last.get("last_output_tail") if last else None,
        llm_calls=run.llm_calls,
        tokens=run.prompt_tokens + run.output_tokens,
        latency_s=round(time.monotonic() - started, 1),
        stopped=run.stopped,
        report=run.final_text[:MAX_REPORT_CHARS],
        trace=run.trace[:MAX_TRACE_STEPS],
    )


def run_shadow(
    candidates: list[Candidate],
    out: Path,
    prepare: PrepareLive,
    run_prompt: RunPrompt,
    settings: Settings,
) -> list[ShadowResult]:
    """Run each candidate, appending one JSON line per issue. Live issues run someone else's
    code, so this refuses to start outside the docker sandbox."""
    if settings.sandbox != "docker":
        raise RuntimeError("shadow runs execute untrusted code: set SANDBOX=docker")
    results = []
    for candidate in candidates:
        result = run_candidate(candidate, prepare, run_prompt, settings)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(result)) + "\n")
        results.append(result)
    return results


def load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def done_issues(rows: list[dict[str, Any]]) -> set[tuple[str, int]]:
    return {(row["repo"], row["issue"]) for row in rows}


def cell(text: str, limit: int = 80) -> str:
    """Issue text is untrusted: keep it to plain text that cannot break the table or add HTML."""
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("`", "'")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fence(code: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def render_markdown(rows: list[dict[str, Any]], title: str) -> str:
    reproduced = [r for r in rows if r["verdict"] == "reproduced"]
    kinds = Counter(r["classification"] for r in rows)
    tokens = sum(r["tokens"] for r in rows)
    lines = [
        f"# {title}",
        "",
        f"{len(reproduced)} of {len(rows)} issues reproduced · {tokens:,} tokens · "
        "classified as: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())),
        "",
        (
            '**Unreviewed.** "Reproduced" means the agents\' test failed on the default branch in '
            "every sandbox run. A person must check each test matches the issue before it is shared."
        ),
        "",
        "| Issue | Title | Classified | Verdict | Model calls | Tokens |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda row: (row["repo"], row["issue"])):
        link = f"[{r['repo']}#{r['issue']}]({r['url']})"
        verdict = r["verdict"] + (f" ({cell(r['error'], 60)})" if r.get("error") else "")
        if r.get("stopped"):
            verdict += f", stopped: {cell(r['stopped'], 40)}"
        cells = [link, cell(r["title"]), r["classification"], verdict]
        lines.append("| " + " | ".join([*cells, str(r["llm_calls"]), f"{r['tokens']:,}"]) + " |")
    if reproduced:
        lines += ["", "## Reproductions to review"]
    for r in reproduced:
        code = r["test_code"] or ""
        marker = fence(code)
        lines += [
            "",
            f"### [{r['repo']}#{r['issue']}]({r['url']}): {cell(r['title'])}",
            "",
            f"`{r['test_path']}`, failing at {r['commit'][:12] if r['commit'] else 'unknown'}:",
            "",
            f"{marker}python",
            code.rstrip("\n"),
            marker,
        ]
    return "\n".join(lines) + "\n"
