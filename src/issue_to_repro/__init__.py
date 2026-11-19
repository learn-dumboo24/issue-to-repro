"""issue-to-repro: turn GitHub bug reports into verified failing tests for maintainers."""

import argparse
import asyncio
import re

ISSUE_REF = re.compile(r"^(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<number>\d+)$")


def main() -> None:
    parser = argparse.ArgumentParser(prog="issue-to-repro")
    parser.add_argument("issue", help="GitHub issue, e.g. owner/name#123")
    parser.add_argument(
        "--checkout", required=True, help="Local checkout of the repo (under WORKSPACE_ROOT)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Build the agents without calling Gemini"
    )
    args = parser.parse_args()
    match = ISSUE_REF.match(args.issue)
    if not match:
        parser.error("issue must look like owner/name#123")

    from .agents import build_agents

    root = build_agents()
    print(f"Coordinator '{root.name}' -> {[a.name for a in root.sub_agents]}")
    if args.dry_run:
        return
    asyncio.run(_run(root, match["repo"], int(match["number"]), args.checkout))


async def _run(root, repo: str, number: int, checkout: str) -> None:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=root, app_name="issue-to-repro")
    session = await runner.session_service.create_session(app_name="issue-to-repro", user_id="cli")
    prompt = f"Reproduce GitHub issue {repo}#{number}. The repository is checked out at {checkout}."
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(user_id="cli", session_id=session.id, new_message=message):
        if event.content and event.content.parts:
            text = "".join(part.text or "" for part in event.content.parts)
            if text.strip():
                print(f"[{event.author}] {text}")
