"""End-to-end demo: run the agents on a set of filed issues and check each test against a fix.

The backtest needs a fix commit per issue; a demo repository has planted bugs instead, so the
reference fixes live in a folder that mirrors the checkout. Each issue's title and body are frozen
in a Markdown file and go into the prompt, so reruns see the same text. The verdict comes from the
sandbox; a reproduced test counts as fail-to-pass only if it passes once the fix files are copied
in, and the checkout is restored afterwards.
"""

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import Settings
from ..tools.sandbox import rerun_test
from .runner import MAX_REPORT_CHARS, MAX_TRACE_STEPS, AgentRun, issue_prompt

ISSUE_HEADING = re.compile(r"^## Issue (\d+)\s*$", re.MULTILINE)
TITLE = re.compile(r"^\*\*Title:\*\* (.+)$", re.MULTILINE)
BODY_MARKER = "**Body:**"

PrepareIssue = Callable[[str, int], Path]
RunPrompt = Callable[[str, Settings], AgentRun]


@dataclass(frozen=True)
class DemoIssue:
    number: int
    title: str
    body: str


@dataclass
class DemoResult:
    issue: int
    title: str
    verdict: str  # sandbox verdict of the last attempt, or no_attempt
    attempts: int
    fail_to_pass: bool | None  # None when there was no reproduction to check
    fix_runs: list[str] | None
    test_path: str | None
    test_code: str | None
    llm_calls: int
    tokens: int
    latency_s: float
    stopped: str | None
    models: str
    report: str
    trace: list[str] = field(default_factory=list)


def parse_issues(markdown: str) -> list[DemoIssue]:
    """Issues from `## Issue N` sections, each with a `**Title:**` line and a `**Body:**` part
    that runs until a `---` line or the next section."""
    parts = ISSUE_HEADING.split(markdown)
    issues = []
    for number, section in zip(parts[1::2], parts[2::2], strict=True):
        title = TITLE.search(section)
        if title is None or BODY_MARKER not in section:
            raise ValueError(f"issue {number} needs a **Title:** line and a **Body:** part")
        body = section.split(BODY_MARKER, 1)[1]
        body = re.split(r"^---\s*$", body, maxsplit=1, flags=re.MULTILINE)[0].strip()
        if not body:
            raise ValueError(f"issue {number} has an empty body")
        issues.append(DemoIssue(int(number), title.group(1).strip(), body))
    if not issues:
        raise ValueError("no '## Issue N' sections found")
    numbers = [i.number for i in issues]
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"duplicate issue numbers: {numbers}")
    return issues


def fix_files(fix_dir: Path) -> list[Path]:
    """The fix's files, relative to `fix_dir` (which mirrors the checkout's layout)."""
    files = sorted(
        p.relative_to(fix_dir)
        for p in fix_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    if not files:
        raise FileNotFoundError(f"no fix files in {fix_dir}")
    return files


def check_against_fix(checkout: Path, fix_dir: Path, test_path: str) -> list[str]:
    """Copy the fix into the checkout, rerun the test, then restore the checkout's files."""
    files = fix_files(fix_dir)
    for rel in files:
        if not (checkout / rel).is_file():
            raise FileNotFoundError(f"fix file {rel} does not exist in the checkout")
    try:
        for rel in files:
            shutil.copyfile(fix_dir / rel, checkout / rel)
        return list(rerun_test(str(checkout), test_path)["runs"])
    finally:
        git = ["git", "-C", str(checkout), "checkout", "--", *map(str, files)]
        subprocess.run(git, check=True, capture_output=True)


def run_issue(
    repo: str,
    issue: DemoIssue,
    fix_dir: Path,
    prepare: PrepareIssue,
    run_prompt: RunPrompt,
    settings: Settings,
) -> DemoResult:
    started = time.monotonic()
    checkout = prepare(repo, issue.number)
    prompt = issue_prompt(f"{repo}#{issue.number}", issue.title, issue.body, checkout)
    run = run_prompt(prompt, settings)
    attempts = [r["result"] for r in run.repro_results if r.get("status") == "ok"]
    last = attempts[-1] if attempts else None
    fix_runs = None
    if last is not None and last["verdict"] == "reproduced":
        fix_runs = check_against_fix(checkout, fix_dir, last["test_path"])
    return DemoResult(
        issue=issue.number,
        title=issue.title,
        verdict=last["verdict"] if last else "no_attempt",
        attempts=len(attempts),
        fail_to_pass=None if fix_runs is None else all(r == "passed" for r in fix_runs),
        fix_runs=fix_runs,
        test_path=last["test_path"] if last else None,
        test_code=(checkout / last["test_path"]).read_text(encoding="utf-8") if last else None,
        llm_calls=run.llm_calls,
        tokens=run.prompt_tokens + run.output_tokens,
        latency_s=round(time.monotonic() - started, 1),
        stopped=run.stopped,
        models=f"{settings.coordinator_model}/{settings.worker_model}",
        report=run.final_text[:MAX_REPORT_CHARS],
        trace=run.trace[:MAX_TRACE_STEPS],
    )


def run_demo(
    repo: str,
    issues: list[DemoIssue],
    fix_dir: Path,
    out: Path,
    prepare: PrepareIssue,
    run_prompt: RunPrompt,
    settings: Settings,
) -> list[DemoResult]:
    """Run each issue not already in `out`, appending one JSON line per issue."""
    done = {row["issue"] for row in load_results(out)} if out.exists() else set()
    fix_files(fix_dir)  # fail before spending model calls if the fix is missing
    results = []
    for issue in issues:
        if issue.number in done:
            continue
        result = run_issue(repo, issue, fix_dir, prepare, run_prompt, settings)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(result)) + "\n")
        results.append(result)
    return results


def load_results(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def outcome(row: dict[str, Any]) -> str:
    if row["fail_to_pass"]:
        return "verified: fails now, passes with the fix"
    if row["fail_to_pass"] is False:
        return f"reproduced, but the fixed run went {row['fix_runs']}"
    if row["verdict"] == "no_attempt":
        return "no test written"
    return str(row["verdict"])


def render_markdown(rows: list[dict[str, Any]], repo: str, title: str) -> str:
    verified = sum(1 for r in rows if r["fail_to_pass"])
    tokens = sum(r["tokens"] for r in rows)
    models = sorted({r["models"] for r in rows})
    lines = [
        f"# {title}",
        "",
        f"{verified} of {len(rows)} issues verified · {tokens:,} tokens · models: "
        + ", ".join(models),
        "",
        "| Issue | Result | Model calls | Tokens | Time |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda row: row["issue"]):
        link = f"[#{r['issue']}](https://github.com/{repo}/issues/{r['issue']})"
        cells = [f"{link} {r['title']}", outcome(r), str(r["llm_calls"]), f"{r['tokens']:,}"]
        lines.append("| " + " | ".join([*cells, f"{r['latency_s']:.0f}s"]) + " |")
    return "\n".join(lines) + "\n"
