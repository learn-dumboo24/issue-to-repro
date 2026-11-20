"""Command line: `issue-to-repro reproduce | dataset build | backtest run | backtest report`."""

import argparse
import asyncio
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from google.adk.agents import BaseAgent

ISSUE_REF = re.compile(r"^(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<number>\d+)$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="issue-to-repro")
    commands = parser.add_subparsers(dest="command", required=True)

    reproduce = commands.add_parser("reproduce", help="Reproduce one GitHub issue")
    reproduce.add_argument("issue", help="GitHub issue, e.g. owner/name#123")
    reproduce.add_argument(
        "--checkout", required=True, help="Local checkout of the repo (under WORKSPACE_ROOT)"
    )
    reproduce.add_argument(
        "--dry-run", action="store_true", help="Build the agents without calling Gemini"
    )

    dataset = commands.add_parser("dataset", help="Backtest datasets")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    build = dataset_commands.add_parser("build", help="Mine fixed issues into a JSONL dataset")
    build.add_argument("--repo", required=True, help="owner/name of the mined repository")
    build.add_argument("--checkout", required=True, help="Clone of --repo with full history")
    build.add_argument("--since", default="2019-01-01", help="Only fixes after this date")
    build.add_argument("--out", required=True, help="Output .jsonl path")

    backtest = commands.add_parser("backtest", help="Replay a dataset and score the agents")
    backtest_commands = backtest.add_subparsers(dest="backtest_command", required=True)
    run = backtest_commands.add_parser("run", help="Run the agents on dataset cases (calls Gemini)")
    run.add_argument("--dataset", required=True, help="Dataset .jsonl")
    run.add_argument("--source", required=True, help="Full clone of the dataset's repository")
    run.add_argument("--out", required=True, help="Results .jsonl (appended; reruns resume)")
    run.add_argument("--issues", help="Comma-separated issue numbers to run (default: all)")
    run.add_argument("--limit", type=int, help="Run at most this many cases")
    run.add_argument("--trace", help="Write OpenTelemetry spans here (JSON lines)")
    report = backtest_commands.add_parser("report", help="Summarise a results file as Markdown")
    report.add_argument("--results", required=True, help="Results .jsonl")
    report.add_argument("--title", default="Backtest results")
    report.add_argument("--out", help="Write Markdown here instead of printing it")

    trace_cmd = commands.add_parser("trace", help="Analyse OpenTelemetry span files")
    trace_commands = trace_cmd.add_subparsers(dest="trace_command", required=True)
    trace_report = trace_commands.add_parser("report", help="Per-agent / per-case breakdown")
    trace_report.add_argument("--trace", required=True, help="Span file from backtest run --trace")
    trace_report.add_argument("--title", default="Trace report")
    trace_report.add_argument("--out", help="Write Markdown here instead of printing it")

    dash = commands.add_parser("dashboard", help="Render an HTML dashboard from results")
    dash.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=RESULTS.jsonl",
        help="A backtest results file and its label; repeat for each run",
    )
    dash.add_argument("--retrieval", help="Rows from retrieval benchmark (.jsonl)")
    dash.add_argument("--trace", help="Span file to show the per-agent breakdown for")
    dash.add_argument("--out", required=True, help="Output .html")

    retrieval = commands.add_parser("retrieval", help="Code retrieval")
    retrieval_commands = retrieval.add_subparsers(dest="retrieval_command", required=True)
    bench = retrieval_commands.add_parser(
        "benchmark", help="Keyword vs semantic vs hybrid search against real fixes (embeds code)"
    )
    bench.add_argument("--dataset", required=True, help="Dataset .jsonl")
    bench.add_argument("--source", required=True, help="Full clone of the dataset's repository")
    bench.add_argument("--out", required=True, help="Rows .jsonl (appended; reruns resume)")
    bench.add_argument("--report", help="Also write the Markdown summary here")
    bench.add_argument("--since", default="", help="Only cases fixed on or after this date")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "reproduce":
        match = ISSUE_REF.match(args.issue)
        if not match:
            parser.error("issue must look like owner/name#123")
        _reproduce(match["repo"], int(match["number"]), args.checkout, args.dry_run)
    elif args.command == "dataset":
        _dataset_build(args.repo, args.checkout, args.since, args.out)
    elif args.command == "dashboard":
        _dashboard(args.run, args.retrieval, args.trace, args.out)
    elif args.command == "trace":
        _trace_report(args.trace, args.title, args.out)
    elif args.command == "retrieval":
        _retrieval_benchmark(args.dataset, args.source, args.out, args.report, args.since)
    elif args.backtest_command == "run":
        _backtest_run(args.dataset, args.source, args.out, args.issues, args.limit, args.trace)
    else:
        _backtest_report(args.results, args.title, args.out)


def _reproduce(repo: str, number: int, checkout: str, dry_run: bool) -> None:
    from .agents import build_agents

    root = build_agents()
    print(f"Coordinator '{root.name}' -> {[a.name for a in root.sub_agents]}")
    if not dry_run:
        prompt = (
            f"Reproduce GitHub issue {repo}#{number}. The repository is checked out at {checkout}."
        )
        asyncio.run(_run(root, prompt))


def _dataset_build(repo: str, checkout: str, since: str, out: str) -> None:
    from .backtest.dataset import build_dataset, write_jsonl

    cases, skipped = build_dataset(repo, checkout, since=since)
    written = write_jsonl(cases, out)
    for skip in skipped:
        print(f"skipped #{skip.issue_number}: {skip.reason}", file=sys.stderr)
    print(f"wrote {written} cases to {out} ({len(skipped)} skipped)")


def _backtest_run(
    dataset: str,
    source: str,
    out: str,
    issues: str | None,
    limit: int | None,
    trace_path: str | None = None,
) -> None:
    from .backtest.dataset import read_jsonl
    from .backtest.runner import default_prepare, run_backtest
    from .config import get_settings

    cases = read_jsonl(dataset)
    if issues:
        wanted = {int(n) for n in issues.split(",")}
        cases = [c for c in cases if c.issue_number in wanted]
    cases = cases[:limit] if limit else cases
    workspace = get_settings().workspace_root
    provider = None
    if trace_path:
        from .observability.tracing import configure_tracing

        provider = configure_tracing(trace_path)
    try:
        run_backtest(cases, out, default_prepare(source, workspace))
    finally:
        if provider is not None:
            provider.shutdown()


def _backtest_report(results: str, title: str, out: str | None) -> None:
    from pathlib import Path

    from .backtest.report import load_results, render_markdown

    markdown = render_markdown(load_results(results), title)
    if out:
        Path(out).write_text(markdown, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(markdown, end="")


def _dashboard(runs: list[str], retrieval: str | None, trace_path: str | None, out: str) -> None:
    import json
    from pathlib import Path

    from .backtest.report import load_results
    from .observability.dashboard import Run, render
    from .observability.tracing import load_spans

    parsed = []
    for item in runs:
        label, sep, path = item.partition("=")
        if not sep or not label or not path:
            raise SystemExit(f"--run must look like LABEL=results.jsonl, got {item!r}")
        parsed.append(Run(label, load_results(path)))
    retrieval_rows = (
        [json.loads(line) for line in Path(retrieval).read_text().splitlines() if line.strip()]
        if retrieval
        else None
    )
    spans = load_spans(trace_path) if trace_path else None
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(render(parsed, retrieval_rows, spans), encoding="utf-8")
    print(f"wrote {out}")


def _trace_report(trace_path: str, title: str, out: str | None) -> None:
    from pathlib import Path

    from .observability.analyze import render_markdown
    from .observability.tracing import load_spans

    markdown = render_markdown(load_spans(trace_path), title)
    if out:
        Path(out).write_text(markdown, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(markdown, end="")


def _retrieval_benchmark(
    dataset: str, source: str, out: str, report: str | None, since: str
) -> None:
    import json
    from pathlib import Path

    from .backtest.dataset import read_jsonl
    from .config import get_settings
    from .retrieval import benchmark
    from .retrieval.embedding import CachedEmbedder, GeminiEmbedder

    settings = get_settings()
    embedder = CachedEmbedder(
        GeminiEmbedder(
            settings.embedding_model,
            settings.embedding_dims,
            requests_per_minute=settings.embedding_requests_per_minute,
        ),
        settings.embedding_cache_dir,
    )
    out_path = Path(out)
    done = {json.loads(line)["case_id"] for line in _nonempty_lines(out_path)}
    snapshots = Path(settings.workspace_root) / "_snapshots"
    # Newest first: recent versions share most code with each other, so the embedding cache
    # covers more of each case and a daily quota goes further.
    cases = sorted(read_jsonl(dataset), key=lambda c: c.committed_at, reverse=True)
    for case in cases:
        if case.committed_at < since or case.case_id in done:
            continue
        row = benchmark.evaluate_case(
            case, benchmark.snapshot(source, case.base_commit, snapshots), embedder
        )
        if row is None:
            print(f"{case.case_id}: no changed file exists at the buggy commit, skipped")
            continue
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        ranks = {m: row[m]["first_relevant_rank"] for m in ("keyword", "semantic", "hybrid")}
        print(f"{case.case_id}: first relevant file rank {ranks} (cache hits {embedder.hits})")
    rows = [json.loads(line) for line in _nonempty_lines(out_path)]
    if report and rows:
        title = f"Retrieval benchmark: {Path(dataset).stem}"
        Path(report).write_text(
            benchmark.render_markdown(rows, title, embedder.name), encoding="utf-8"
        )
        print(f"wrote {report}")


def _nonempty_lines(path: "Path") -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def _run(root: "BaseAgent", prompt: str) -> None:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=root, app_name="issue-to-repro")
    session = await runner.session_service.create_session(app_name="issue-to-repro", user_id="cli")
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(user_id="cli", session_id=session.id, new_message=message):
        if event.content and event.content.parts:
            text = "".join(part.text or "" for part in event.content.parts)
            if text.strip():
                print(f"[{event.author}] {text}")
