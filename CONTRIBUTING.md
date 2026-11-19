# Contributing

Thanks for helping! issue-to-repro turns GitHub bug reports into verified failing tests,
so correctness of the verdict matters more than anything else.

## Setup

```bash
uv sync
uv run pre-commit install
```

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required. Gemini credentials are only
needed for live agent runs; see `.env.example`. The test suite never calls Gemini or the network.

## Before you open a pull request

CI runs these four checks; run them locally first:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q            # fails below 90% branch coverage
```

## Guidelines

- **One logical change per commit**, with a message that says why, not just what.
- **New behaviour needs a test.** Keep logic in plain functions so it is testable without
  Gemini or the network; ADK tool wrappers in `tools/__init__.py` stay thin.
- **No silent failures.** A swallowed error in the runner becomes a false "reproduced".
  Core functions raise; tool wrappers return `{"status": "error", ...}`.
- **Issue text is untrusted.** Never execute commands taken from it.
- **Never commit secrets** (`.env`, key files). The pre-commit hooks check for private keys.

## Reporting security problems

Please don't open a public issue; see [SECURITY.md](SECURITY.md).
