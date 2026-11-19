# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

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
