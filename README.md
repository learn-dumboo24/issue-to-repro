# issue-to-repro

**Turns GitHub bug reports into verified failing tests, so maintainers stop spending their
time reproducing issues.**

A new issue comes in. A team of Gemini agents reads it, finds the relevant code, decides
whether it is a reproducible bug, and writes the smallest test that fails because of it. That
test is run several times in a sandbox and accepted only if it fails *for the reported reason*
on every run. The maintainer gets a ready-to-commit failing test and approves anything before
it is posted.

When the bug is later fixed, issue + failing test + fix form a verified fail-to-pass benchmark
task, so the project doubles as a generator of real-world evals for coding agents.

## Architecture

```
coordinator (ADK LlmAgent, Gemini)
├── retriever   reads the issue, searches the code      tools: fetch_issue, search_code
├── classifier  bug / question / feature / duplicate / needs-info
└── repro_loop  (ADK LoopAgent: self-reflection)
    ├── reproducer  writes + runs a failing test        tool: run_reproduction
    └── verifier    accepts only genuine reproductions  tool: exit_loop
```

| Piece | Google stack |
|---|---|
| Multi-agent, hierarchical delegation, self-reflection loop | Agent Development Kit (ADK) + Gemini |
| Retrieval over code, docs, closed issues, commits | keyword baseline now → Vertex AI embeddings + vector search |
| Sandboxed test runs | local runner now → Cloud Run jobs |
| GitHub webhook service | Cloud Run |
| Tracing and LLM metrics (cost per issue, latency, tokens/sec) | ADK OpenTelemetry → Cloud Trace, BigQuery |

**How a reproduction is verified** (`src/issue_to_repro/tools/sandbox.py`): the test runs
`REPRO_RUNS` times (default 3). Import errors, missing fixtures, collection errors and
"no tests" count as an *invalid* test, not a reproduction. Mixed pass/fail results count as
*flaky*. Only a test that fails on every run is *reproduced*, and the verifier agent then checks
that it fails for the reason the issue describes.

## Quick start

```bash
uv sync
uv run pytest
uv run issue-to-repro owner/name#123 --checkout workspace/name --dry-run
```

To run the agents for real, set Gemini credentials (see `.env.example`), clone the target repo
under `workspace/`, and drop `--dry-run`. `uv run adk web src` opens the ADK dev UI.

> **Security:** until the Cloud Run sandbox lands, reproductions execute the target repo's code
> on your machine. Only use trusted repositories.

## Roadmap

- [x] ADK agent hierarchy with a reproducer/verifier self-reflection loop
- [x] Reproduction runner with invalid/flaky detection, keyword code search, GitHub issue reader
- [ ] Backtest harness: replay closed issues that have a linked fix, measure reproduction rate
- [ ] Vector retrieval over code, docs, closed issues and commits (Vertex AI)
- [ ] Docker / Cloud Run job sandbox; per-repo dependency setup
- [ ] Cloud Run webhook service + comment-only GitHub App with maintainer approval
- [ ] Tracing and metrics dashboard: reproduction rate, cost per issue, p50/p95 latency
- [ ] Shadow-mode report for 2–3 open-source projects, then opt-in live runs
- [ ] Export fixed issues as verified fail-to-pass benchmark tasks

Public repositories only.
