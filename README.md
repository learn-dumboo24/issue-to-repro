# issue-to-repro

[![CI](https://github.com/learn-dumboo24/issue-to-repro/actions/workflows/ci.yml/badge.svg)](https://github.com/learn-dumboo24/issue-to-repro/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

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
coordinator (ADK SequentialAgent: fixed order)
├── retriever   reads the issue, searches the code      tools: fetch_issue, search_code
├── classifier  bug / question / feature / duplicate / needs-info
├── repro_loop  (ADK LoopAgent: self-reflection)
│   ├── reproducer  writes + runs a failing test        tools: run_reproduction, exit_loop
│   └── verifier    accepts only genuine reproductions  tool: exit_loop
└── reporter    short report for the maintainer
```

| Piece | Google stack |
|---|---|
| Multi-agent pipeline with hierarchical delegation and a self-reflection loop | Agent Development Kit (ADK) + Gemini |
| Retrieval over code, docs, closed issues, commits | keyword baseline now → Vertex AI embeddings + vector search |
| Sandboxed test runs | Docker: no network, non-root, read-only (`SANDBOX=docker`) → Cloud Run jobs |
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
uv run pytest               # never calls Gemini or the network
uv run issue-to-repro reproduce owner/name#123 --checkout workspace/name --dry-run
```

To run the agents for real, set Gemini credentials (see `.env.example`), clone the target repo
under `workspace/`, and drop `--dry-run`. `uv run adk web src` opens the ADK dev UI.

## Sandbox

Reproductions run the target repository's own code, so they run in a container
(`SANDBOX=docker`; `local` is the default for development on trusted repos):

| Control | Setting |
|---|---|
| Network | none (`--network none`) |
| User | `nobody`, all capabilities dropped, `no-new-privileges` |
| Filesystem | read-only root, read-only mounts of the checkout and interpreter, 64 MB `/tmp` |
| Resources | 1 GB memory, 1 CPU, 256 processes (configurable) |
| Time | in-container `timeout`; a container left behind is force-removed |

Nothing is installed inside the container. The checkout's virtualenv is built beforehand (with
network access, by trusted code) on uv's standalone Python, and both are mounted read-only at the
same paths. CI checks the isolation with real containers (`uv run pytest -m docker`).

```bash
SANDBOX=docker uv run issue-to-repro backtest run ...   # needs Docker
```

## Backtesting

How well does it work? The backtest replays bugs that were already fixed and checks the
agents' tests against the real fix:

1. **Dataset** (`datasets/`): `issue-to-repro dataset build` mines commits that close exactly one
   issue and change both source and tests, and freezes each issue's title and body (comments
   are left out because they often reveal the fix). CI builds datasets from `datasets/sources.json`.
2. **Run**: for each case, a git worktree at the buggy commit gets its own virtualenv; the agents
   see only the frozen issue text and the checkout.
3. **Score**: a case is a *verified reproduction* only if the agents' test fails on the buggy
   commit **and passes once the real fix is applied**. The verdict comes from the sandbox, never
   from model text.

```bash
git clone --filter=blob:none https://github.com/pallets/click workspace/_sources/click
uv run issue-to-repro backtest run --dataset datasets/click.jsonl \
  --source workspace/_sources/click --out results/click.jsonl --limit 10
uv run issue-to-repro backtest report --results results/click.jsonl --title "Click backtest"
```

Runs are capped per case (`BACKTEST_MAX_LLM_CALLS`, `BACKTEST_MAX_TOKENS`) and per run
(`BACKTEST_MAX_USD`, an upper-bound estimate from published prices), append to the results file,
and resume where they stopped.

### Models and retrieval

| Setting | Values |
|---|---|
| `MODEL_PROVIDER` | `gemini` (default) or `anthropic` (Claude via ADK's `AnthropicLlm`; needs `ANTHROPIC_API_KEY`) |
| `COORDINATOR_MODEL`, `WORKER_MODEL` | e.g. `gemini-3.8-flash`, `claude-haiku-5-5`, `claude-sonnet-5-5` |
| `RETRIEVAL` | `keyword` (default) or `semantic`: adds hybrid BM25 + Gemini-embedding code search |

### Results so far (12 Click cases)

| Model | Verified | Tokens / case | p50 latency | Cost |
|---|---|---|---|---|
| Gemini 3.1 Flash-Lite | 8 / 12 | 109k | 53s | free tier |
| Claude Haiku 5.5 | **9 / 12** | 72k | 29s | ≤ $0.11 total |

Precision was 100% for both: every claimed reproduction was confirmed by the real fix. One case
(#3403) is not reproducible as filed (`datasets/README.md`); on the 9 reproducible bug reports,
Haiku verified 9 and Flash-Lite 8. Details in [`results/`](results/).

## Roadmap

Built in phases; each phase lands as one pull request and a tagged release
(see [CHANGELOG.md](CHANGELOG.md)).

| Phase | Scope | Status |
|---|---|---|
| 1. Foundation | Agents, verified reproduction runner, CI, typing, coverage gate | ✅ v0.1.0 |
| 2. Backtest harness | Replay fixed bugs; score against the real fix. **8/10 Click bugs verified** | ✅ v0.2.0 |
| 3. Sandbox | Reproductions in a locked-down container; isolation tested in CI | ✅ v0.3.0 |
| 4. Retrieval | Vertex AI embeddings + vector search, measured against keyword search | Next |
| 5. Observability | ADK OpenTelemetry → Cloud Trace; cost and latency per issue | Planned |
| 6. Production | Cloud Run webhook + comment-only GitHub App with maintainer approval | Planned |
| 7. Real users | Shadow-mode reports for 2–3 open-source projects; public write-up | Planned |
| 8. Benchmarks | Export fixed issues as verified fail-to-pass agent benchmark tasks | Planned |

Public repositories only.

## License

Apache-2.0. See [LICENSE](LICENSE).
