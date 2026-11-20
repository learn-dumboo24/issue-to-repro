# Click backtest: gemini-3.1-flash-lite with the retriever tool budget (12 cases)

**Verified reproductions: 8/12 (67%)**: the agents' test fails on the buggy commit and passes once the real fix is applied.

| Metric | Value |
|---|---|
| Models (coordinator/worker) | gemini-3.1-flash-lite/gemini-3.1-flash-lite |
| Cases | 12 |
| Sandbox said "reproduced" | 8 |
| ...confirmed by the real fix (precision) | 8 (100%, 95% CI 68%–100%) |
| Outcomes | reproduced: 8, not_reproduced: 2, no_attempt: 2 |
| Tokens, total / per case | 1,307,761 / 108,980 |
| Latency per case, p50 / p95 | 53s / 109s |

## Cases

| Case | Verdict | Fail→pass | Attempts | LLM calls | Tokens | Time | Stopped |
|---|---|---|---|---|---|---|---|
| pallets/click#3145 | reproduced | ✅ | 1 | 9 | 33,145 | 41s |  |
| pallets/click#3121 | reproduced | ✅ | 2 | 15 | 114,098 | 58s |  |
| pallets/click#3298 | reproduced | ✅ | 2 | 15 | 84,109 | 42s |  |
| pallets/click#2790 | reproduced | ✅ | 1 | 14 | 76,921 | 66s |  |
| pallets/click#3403 | not_reproduced | – | 14 | 26 | 421,279 | 109s | token_budget |
| pallets/click#3360 | reproduced | ✅ | 1 | 14 | 40,016 | 22s |  |
| pallets/click#2983 | no_attempt | – | 0 | 13 | 56,050 | 51s |  |
| pallets/click#2877 | not_reproduced | – | 19 | 30 | 239,415 | 148s | llm_call_limit |
| pallets/click#3572 | reproduced | ✅ | 1 | 14 | 58,030 | 26s |  |
| pallets/click#3571 | reproduced | ✅ | 1 | 11 | 87,986 | 20s |  |
| pallets/click#2869 | no_attempt | – | 0 | 6 | 19,925 | 56s |  |
| pallets/click#3362 | reproduced | ✅ | 4 | 17 | 76,787 | 53s |  |

## Compared with the run before the budget

Same 12 cases, same model, same limits; the only change is the retriever's hard cap of 8 tool
calls (`RETRIEVER_MAX_TOOL_CALLS`, commit `65ac27c`). Before: [`click-flash-lite.md`](click-flash-lite.md).

| | Before | With the budget |
|---|---|---|
| Verified reproductions | 8 / 12 | **8 / 12** |
| Precision (verified / claimed) | 89% | **100%** |
| Tokens per case (mean) | 132,126 | **108,980** (−18%) |
| Latency p50 / p95 | 103s / 136s | **53s / 109s** |

## Notes

- **Bug reports:** 8 of 10 verified, as before. Both feature requests (#2983, #2869) were again
  left without an attempt, now in fewer calls (22 → 13 and 7 → 6).
- **#3403** no longer ends in a false "reproduced" claim. It stopped at the token budget
  (421k against a 400k cap: the check runs after each model call, so it can overshoot by one call).
- **#2877** (`BytesWarning` under `python -bb`) is still not reproduced.
- **Setup:** pipeline at `65ac27c`, both models `gemini-3.1-flash-lite` (free tier), 30 model
  calls max per case, 3 sandbox runs per verdict, `SANDBOX=local`.
