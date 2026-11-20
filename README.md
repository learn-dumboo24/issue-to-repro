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
| Tracing and LLM metrics (cost per verified fix, latency, tokens per agent) | ADK OpenTelemetry → JSON-lines spans + dashboard now; Cloud Trace on Cloud Run |

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

### Tracing and dashboard

`backtest run --trace spans.jsonl` records OpenTelemetry spans (ADK's agent, model and tool spans
plus each case's prepare / agents / fix-check stages). `trace report --trace spans.jsonl` breaks
them down per agent and per stage. **[Dashboard](https://learn-dumboo24.github.io/issue-to-repro/)** (all runs side by side):

```bash
uv run issue-to-repro dashboard \
  --run "Gemini 3.1 Flash-Lite=results/click-flash-lite-budget.jsonl" \
  --run "Claude Haiku 5.5=results/click-haiku.jsonl" \
  --run "Claude Haiku 5.5 + semantic search=results/click-haiku-semantic.jsonl" \
  --retrieval results/retrieval-click.jsonl \
  --trace results/traces/click-3362-flash-lite.jsonl --out docs/index.html
```

To host it, enable GitHub Pages for the `docs/` folder on `main` (Settings → Pages).

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
Haiku verified 9 and Flash-Lite 8.

**Retrieval** (31 Click issues): semantic search puts the file the real fix changed first for
87% of issues, keyword search for 52%. End to end, it did not measurably change reproductions on
Click ([`results/click-haiku-semantic.md`](results/click-haiku-semantic.md)). Details in
[`results/`](results/).

### End-to-end demo

[learn-dumboo24/issue-to-repro-demo](https://github.com/learn-dumboo24/issue-to-repro-demo) is a
small expense-splitting package with four planted bugs and one feature request, each filed as a
GitHub issue. `demo run` gives the agents each issue's frozen text (`demo/issues.md`) and checks
every reproduction against reference fixes (`demo/fix/`): a test counts only if it fails on the
shipped code and passes once the fix is copied in.

```bash
uv run issue-to-repro demo run --repo learn-dumboo24/issue-to-repro-demo \
  --issues demo/issues.md --fix demo/fix --out results/demo-flash-lite.jsonl
uv run issue-to-repro demo report --repo learn-dumboo24/issue-to-repro-demo \
  --results results/demo-flash-lite.jsonl
```

On Gemini 3.1 Flash-Lite (free tier) all four bugs were verified and the feature request was
classified as such, with no test written: 6–9 model calls and 11k–25k tokens per issue
([`results/demo-flash-lite.md`](results/demo-flash-lite.md)).

## Roadmap

Built in phases; each phase lands as one pull request and a tagged release
(see [CHANGELOG.md](CHANGELOG.md)).

| Phase | Scope | Status |
|---|---|---|
| 1. Foundation | Agents, verified reproduction runner, CI, typing, coverage gate | ✅ v0.1.0 |
| 2. Backtest harness | Replay fixed bugs; score against the real fix. **8/10 Click bugs verified** | ✅ v0.2.0 |
| 3. Sandbox | Reproductions in a locked-down container; isolation tested in CI | ✅ v0.3.0 |
| 4. Retrieval | Gemini-embedding code search; right file first 87% vs 52% for keyword search | ✅ v0.4.0 |
| 5. Observability | OpenTelemetry spans, per-agent cost/latency breakdown, [dashboard](https://learn-dumboo24.github.io/issue-to-repro/) | ✅ v0.5.0 |
| 6. Production | Webhook service, comment-only GitHub App with maintainer approval, [end-to-end demo](#end-to-end-demo) (4/4 planted bugs verified); next: Cloud Run, Cloud Trace export | 🚧 Part 1 merged |
| 7. Real users | Shadow-mode reports for 2–3 open-source projects; public write-up | Planned |
| 8. Benchmarks | Export fixed issues as verified fail-to-pass agent benchmark tasks | Planned |

Public repositories only.

## License

Apache-2.0. See [LICENSE](LICENSE).
