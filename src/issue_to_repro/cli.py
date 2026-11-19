"""Command line: `issue-to-repro reproduce ...` and `issue-to-repro dataset build ...`."""

import argparse
import asyncio
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "reproduce":
        match = ISSUE_REF.match(args.issue)
        if not match:
            parser.error("issue must look like owner/name#123")
        _reproduce(match["repo"], int(match["number"]), args.checkout, args.dry_run)
    else:
        _dataset_build(args.repo, args.checkout, args.since, args.out)


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
