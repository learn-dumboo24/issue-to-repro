# Click backtest: Claude Haiku 5.5 with semantic retrieval (12 cases)

**Verified reproductions: 10/12 (83%)**: the agents' test fails on the buggy commit and passes once the real fix is applied.

| Metric | Value |
|---|---|
| Models (coordinator/worker) | claude-haiku-5-5/claude-haiku-5-5 |
| Cases | 12 |
| Sandbox said "reproduced" | 11 |
| ...confirmed by the real fix (precision) | 10 (91%) |
| Outcomes | reproduced: 11, no_attempt: 1 |
| Tokens, total / per case | 1,034,210 / 86,184 |
| Latency per case, p50 / p95 | 30s / 33s |

## Cases

| Case | Verdict | Fail→pass | Attempts | LLM calls | Tokens | Time | Stopped |
|---|---|---|---|---|---|---|---|
| pallets/click#3145 | reproduced | ✅ | 1 | 8 | 53,883 | 30s |  |
| pallets/click#3121 | reproduced | ✅ | 1 | 10 | 90,903 | 29s |  |
| pallets/click#3298 | reproduced | ✅ | 1 | 8 | 39,145 | 30s |  |
| pallets/click#2790 | reproduced | ✅ | 1 | 8 | 53,092 | 30s |  |
| pallets/click#3403 | reproduced | ❌ | 5 | 20 | 333,470 | 98s |  |
| pallets/click#3360 | reproduced | ✅ | 1 | 11 | 55,589 | 27s |  |
| pallets/click#2983 | no_attempt | – | 0 | 8 | 43,920 | 18s |  |
| pallets/click#2877 | reproduced | ✅ | 1 | 8 | 37,176 | 27s |  |
| pallets/click#3572 | reproduced | ✅ | 1 | 10 | 84,229 | 30s |  |
| pallets/click#3571 | reproduced | ✅ | 1 | 11 | 106,553 | 30s |  |
| pallets/click#2869 | reproduced | ✅ | 1 | 9 | 55,906 | 29s |  |
| pallets/click#3362 | reproduced | ✅ | 1 | 10 | 80,344 | 33s |  |

## Compared with keyword-only retrieval (same model, cases and limits)

| Haiku 5.5 | `RETRIEVAL=keyword` ([report](click-haiku.md)) | `RETRIEVAL=semantic` |
|---|---|---|
| Verified | 9 / 12 | 10 / 12 |
| Precision (verified / claimed) | 100% | 91% |
| Tokens per case (mean) | 71,991 | 86,184 |
| Latency p50 / p95 | 29s / 30s | 30s / 33s |
| Estimated cost, 12 cases | ≤ $0.11 | ≤ $0.13 |

**Reading: no measurable end-to-end effect on Click.** The two cases that changed are explained
by other things than retrieval:

- **#2869** ("support `pathlib.Path` in `edit`"): the classifier labelled it a *bug* in this run
  and a *feature request* in the keyword run. With the bug label, Haiku wrote a valid
  fail-to-pass test (a `Path` filename is rejected before the fix and accepted after). The flip
  is classifier run-to-run variation on a borderline issue.
- **#3403** is not reproducible as filed (`datasets/README.md`); the claimed reproduction was
  rejected by the real-fix check, which is why precision is below 100%.
- The retriever called `semantic_search_tool` in only 5 of 12 cases: Click's issues usually name
  the functions involved, so keyword search already finds them.

Semantic search clearly ranks files better on its own ([`retrieval-click.md`](retrieval-click.md):
right file first 87% vs 52%), but with 12 cases and one run each, that does not show up as more
reproductions here, and it costs about 20% more tokens. **Hypothesis, not yet tested:** it should
matter more on larger codebases and for issues that describe behaviour without naming code.

## Setup

Pipeline at `4c3be6e`, `RETRIEVAL=semantic`, `MODEL_PROVIDER=anthropic`, both models
`claude-haiku-5-5`, `SANDBOX=docker`, `BACKTEST_MAX_USD=1.50`. Embeddings `gemini-embedding-2`
from the on-disk cache (no embedding errors during the run).
