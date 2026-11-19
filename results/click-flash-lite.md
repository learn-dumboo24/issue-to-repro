# Click backtest: gemini-3.1-flash-lite (12 cases)

**Verified reproductions: 8/12 (67%)**: the agents' test fails on the buggy commit and passes once the real fix is applied.

| Metric | Value |
|---|---|
| Models (coordinator/worker) | gemini-3.1-flash-lite/gemini-3.1-flash-lite |
| Cases | 12 |
| Sandbox said "reproduced" | 9 |
| ...confirmed by the real fix (precision) | 8 (89%) |
| Outcomes | reproduced: 9, no_attempt: 2, not_reproduced: 1 |
| Tokens, total / per case | 1,585,508 / 132,126 |
| Latency per case, p50 / p95 | 103s / 136s |

## Cases

| Case | Verdict | Fail→pass | Attempts | LLM calls | Tokens | Time | Stopped |
|---|---|---|---|---|---|---|---|
| pallets/click#3145 | reproduced | ✅ | 1 | 10 | 38,589 | 76s |  |
| pallets/click#3121 | reproduced | ✅ | 1 | 30 | 276,156 | 103s | llm_call_limit |
| pallets/click#3298 | reproduced | ✅ | 2 | 9 | 29,229 | 126s |  |
| pallets/click#2790 | reproduced | ✅ | 1 | 30 | 237,505 | 111s |  |
| pallets/click#3403 | reproduced | ❌ | 9 | 30 | 280,742 | 125s | llm_call_limit |
| pallets/click#3360 | reproduced | ✅ | 1 | 10 | 23,594 | 38s |  |
| pallets/click#2983 | no_attempt | – | 0 | 22 | 115,936 | 156s |  |
| pallets/click#2877 | not_reproduced | – | 12 | 20 | 123,833 | 91s |  |
| pallets/click#3572 | reproduced | ✅ | 1 | 26 | 174,581 | 82s |  |
| pallets/click#3571 | reproduced | ✅ | 1 | 9 | 55,827 | 69s |  |
| pallets/click#2869 | no_attempt | – | 0 | 7 | 17,382 | 35s |  |
| pallets/click#3362 | reproduced | ✅ | 1 | 30 | 212,134 | 136s |  |

## Notes

- **Cases:** 10 bug reports and 2 feature requests (#2983, #2869) from `datasets/click.jsonl`.
  Both feature requests were correctly left without a reproduction attempt, so on bug reports
  alone the agents produced a verified reproduction for **8 of 10**.
- **Not counted as verified:** #3403's test failed on the buggy commit but also after the real
  fix, so it was detecting something other than the reported bug. #2877 (a `BytesWarning`
  under `python -bb`) was not reproduced in 12 attempts.
- **Setup:** pipeline at commit `018268b`, both models `gemini-3.1-flash-lite` (free tier, chosen
  because `gemini-3.8-flash` was returning 503 overloads), 30 model calls max per case,
  3 sandbox runs per verdict.
- **Reproduce:** `uv run issue-to-repro backtest run --dataset datasets/click.jsonl
  --source workspace/_sources/click --out results/click-flash-lite.jsonl
  --issues 3362,3360,3403,3572,3571,2877,3298,3121,3145,2790,2983,2869`
