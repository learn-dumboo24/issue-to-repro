# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

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
