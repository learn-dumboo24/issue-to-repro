# Click backtest: Claude Haiku 5.5 (12 cases, Docker sandbox)

**Verified reproductions: 9/12 (75%)**: the agents' test fails on the buggy commit and passes once the real fix is applied.

| Metric | Value |
|---|---|
| Models (coordinator/worker) | claude-haiku-5-5/claude-haiku-5-5 |
| Cases | 12 |
| Sandbox said "reproduced" | 9 |
| ...confirmed by the real fix (precision) | 9 (100%) |
| Outcomes | reproduced: 9, no_attempt: 2, not_reproduced: 1 |
| Tokens, total / per case | 863,895 / 71,991 |
| Latency per case, p50 / p95 | 29s / 30s |

## Cases

| Case | Verdict | Fail→pass | Attempts | LLM calls | Tokens | Time | Stopped |
|---|---|---|---|---|---|---|---|
| pallets/click#3145 | reproduced | ✅ | 1 | 8 | 54,584 | 29s |  |
| pallets/click#3121 | reproduced | ✅ | 1 | 9 | 75,344 | 28s |  |
| pallets/click#3298 | reproduced | ✅ | 1 | 8 | 42,186 | 28s |  |
| pallets/click#2790 | reproduced | ✅ | 1 | 8 | 51,779 | 29s |  |
| pallets/click#3403 | not_reproduced | – | 2 | 17 | 203,796 | 64s |  |
| pallets/click#3360 | reproduced | ✅ | 1 | 13 | 71,854 | 29s |  |
| pallets/click#2983 | no_attempt | – | 0 | 8 | 44,062 | 20s |  |
| pallets/click#2877 | reproduced | ✅ | 1 | 8 | 37,789 | 28s |  |
| pallets/click#3572 | reproduced | ✅ | 1 | 10 | 84,434 | 30s |  |
| pallets/click#3571 | reproduced | ✅ | 1 | 10 | 85,018 | 30s |  |
| pallets/click#2869 | no_attempt | – | 0 | 9 | 46,468 | 17s |  |
| pallets/click#3362 | reproduced | ✅ | 1 | 8 | 66,581 | 28s |  |

## Compared with Gemini 3.1 Flash-Lite on the same 12 cases

Same pipeline settings as [`click-flash-lite-budget.md`](click-flash-lite-budget.md): 30 model calls
max per case, retriever capped at 8 tool calls, 3 sandbox runs per verdict.

| | Gemini 3.1 Flash-Lite | Claude Haiku 5.5 |
|---|---|---|
| Verified reproductions | 8 / 12 | **9 / 12** (9 of 10 bug reports) |
| Precision (verified / claimed) | 100% | 100% |
| Tokens per case (mean) | 108,980 | **71,991** |
| Latency p50 / p95 | 53s / 109s | **29s / 30s** |
| Estimated cost, all 12 cases | free tier | **≤ $0.11** |

- Haiku verified every case Flash-Lite did, plus **#2877** (`BytesWarning` under `python -bb`),
  which Flash-Lite never reproduced.
- Both models correctly left the two feature requests (#2983, #2869) without an attempt.
- **#3403** is the one bug report neither model verified, and it turned out not to be
  reproducible as filed (see `datasets/README.md` → Known issues). On the 9 cases that are
  reproducible bug reports, Haiku verified **9 of 9** and Flash-Lite 8 of 9.
- Costs are upper bounds from `backtest/pricing.py` (all prompt tokens priced as uncached input).

## Setup

Pipeline at `aeb9d7c`, `MODEL_PROVIDER=anthropic`, both models `claude-haiku-5-5`,
`SANDBOX=docker` (no network, read-only, non-root), `BACKTEST_MAX_USD=1.50`.
