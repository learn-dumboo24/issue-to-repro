# Click backtest in the Docker sandbox: gemini-3.1-flash-lite (3 cases)

**Verified reproductions: 2/3 (67%)**: the agents' test fails on the buggy commit and passes once the real fix is applied.

| Metric | Value |
|---|---|
| Models (coordinator/worker) | gemini-3.1-flash-lite/gemini-3.1-flash-lite |
| Cases | 3 |
| Sandbox said "reproduced" | 3 |
| ...confirmed by the real fix (precision) | 2 (67%, 95% CI 21%–94%) |
| Outcomes | reproduced: 3 |
| Tokens, total / per case | 311,490 / 103,830 |
| Latency per case, p50 / p95 | 52s / 58s |

## Cases

| Case | Verdict | Fail→pass | Attempts | LLM calls | Tokens | Time | Stopped |
|---|---|---|---|---|---|---|---|
| pallets/click#3145 | reproduced | ✅ | 1 | 14 | 51,265 | 58s |  |
| pallets/click#3571 | reproduced | ✅ | 2 | 12 | 103,830 | 28s |  |
| pallets/click#3362 | reproduced | ❌ | 1 | 14 | 156,395 | 52s |  |

## Notes

- **Every test run happened in the locked-down container** (`SANDBOX=docker`): no network,
  `nobody`, read-only checkout and interpreter, resource limits. Checkouts were prepared on uv's
  standalone Python. No containers were left behind.
- **#3362 is a model error, caught by the real-fix check.** The test ends with
  `assert "--max-" not in output`, but the correct output contains `--max-retry-count`, so the
  test can never pass. It failed at the buggy commit (counted as "reproduced" by the sandbox)
  and still failed with the real fix, so it is not counted as verified. The sandbox itself is not
  the cause: a correct #3362 test fails 3/3 in the same container at the buggy commit and passes
  3/3 with the fix (see PR #3).
- **Setup:** pipeline at `4b26628`, both models `gemini-3.1-flash-lite` (free tier), 30 model
  calls max per case, 3 sandbox runs per verdict.
