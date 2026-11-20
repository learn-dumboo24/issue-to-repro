# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.4.0] - Phase 4: Retrieval, model providers and cost control

### Added
- Semantic code retrieval: AST chunks (functions, methods, class headers), `gemini-embedding-2`
  vectors cached on disk by content hash, a cosine index, and a rate limiter that keeps embedding
  requests under the per-minute quota.
- `retrieval benchmark`: keyword (BM25) vs semantic vs hybrid search, scored on whether each
  surfaces the files the real fix changed. On 31 Click issues, semantic search ranks the right
  file first 87% of the time vs 52% for keyword search (MRR 0.92 vs 0.70).
- `semantic_search_tool` for the retriever (`RETRIEVAL=semantic`); embedding failures come back as
  an error result so the agent falls back to keyword search.
- `MODEL_PROVIDER=anthropic`: Claude via ADK's `AnthropicLlm` and the official Anthropic SDK.
- `BACKTEST_MAX_USD`: a run-wide spend cap from published prices; each result records its
  estimated cost.
- Cross-model results on the same 12 Click cases: Gemini 3.1 Flash-Lite 8/12, Claude Haiku 5.5
  9/12 (≤ $0.11), Claude Sonnet 5.5 0/1 on the case both missed.

### Found
- `pallets/click#3403` is not reproducible as filed: the issue's snippet already behaves as the
  reporter asked at the buggy commit. On the 9 reproducible bug reports, Haiku verified 9/9.
- Semantic retrieval did not measurably change end-to-end reproductions on Click (one run, 12
  cases); see `results/click-haiku-semantic.md`.

### Fixed
- `gemini-embedding-2` merged a plain list of strings into one embedding; texts are now sent as
  separate `Content` items, with a count check.
- A setting named `anthropic_base_url` was filled from a sandbox's own `ANTHROPIC_BASE_URL`; it is
  now `CLAUDE_API_BASE_URL`.

## [0.3.0] - Phase 3: Docker sandbox

### Added
- `SANDBOX=docker`: reproduction tests run in a container with no network, as `nobody` with all
  capabilities dropped and `no-new-privileges`, on a read-only filesystem with read-only mounts,
  under memory/CPU/process limits and an in-container timeout. Containers left behind after a
  host-side timeout are force-removed. `SANDBOX=local` remains the default for development.
- Checkouts for the docker sandbox are built on uv's standalone Python (`PYTHON_INSTALL_DIR`),
  so nothing is installed inside the container.
- Real-container integration tests (`pytest -m docker`) and a "Docker sandbox" CI job: a bug
  reproduces, the network is unreachable, the checkout is read-only.
- A live backtest in the sandbox (`results/click-docker.md`): 2 of 3 verified; the third was a
  model error rejected by the real-fix check.

### Fixed
- Inside `uv run`, uv returned the active project venv instead of the standalone Python; the
  lookup now ignores `VIRTUAL_ENV` and refuses interpreters outside the install dir.

## [0.2.0] - Phase 2: Backtest harness

### Added
- `dataset build`: mines commits that close exactly one issue and change both source and tests,
  and freezes each issue's title and body as JSONL. Built in CI from `datasets/sources.json`;
  `datasets/click.jsonl` has 36 cases from `pallets/click`.
- Per-case checkouts: a git worktree at the buggy commit with its own uv virtualenv.
- `backtest run`: replays cases offline on the frozen issue text and scores each one against the
  real fix. A reproduction is *verified* only if the agents' test fails before the fix and
  passes after it. Per-case limits on model calls and tokens; results append and resume.
- `backtest report`: verified rate, precision, outcomes, tokens, p50/p95 latency, models used,
  and a per-step trace of every agent action.
- `read_file` tool for agents, with checkout path checks and a 200-line limit.
- **First results:** 8 of 10 Click bug reports verified on `gemini-3.1-flash-lite`, precision
  89%, both feature requests correctly left alone (`results/click-flash-lite.md`).

### Changed
- Agents run as a fixed `SequentialAgent` pipeline (retriever → classifier → repro_loop →
  reporter). Model-driven hand-offs ended runs early or looped to the call limit.
- The retriever's tool calls are capped in code (`RETRIEVER_MAX_TOOL_CALLS`, default 8): on
  click#3362, 30 → 17 model calls and 212k → 71k tokens with the same verified result.
- Gemini calls retry 429/5xx with exponential backoff; transient failures rerun on resume.

### Fixed
- Sandboxed test runs disable bytecode caching: a same-size source edit within the same second
  ran from a stale `.pyc` and made a genuine fix look ineffective.

## [0.1.0] - Phase 1: Foundation

### Added
- ADK agent hierarchy: coordinator delegating to retriever, classifier and a
  reproducer/verifier self-reflection loop (`LoopAgent`), on Gemini 3.8 Flash.
- Reproduction runner that accepts a test only if it fails, for a real reason, on every
  run: import, fixture and collection errors are *invalid*; mixed results are *flaky*.
- Keyword code search and a GitHub issue reader, restricted to a workspace directory.
- CI on every push and pull request: ruff lint and format check, strict mypy, pytest.
- Branch coverage gate at 90% (currently 92%).
- pre-commit hooks, Apache-2.0 license, contributing guide, security policy,
  issue forms and pull request template.
