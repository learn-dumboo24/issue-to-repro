# Click #3403 on Claude Sonnet 5.5 (the case neither cheaper model verified)

**Verified reproductions: 0/1 (0%)**: the agents' test fails on the buggy commit and passes once the real fix is applied.

| Metric | Value |
|---|---|
| Models (coordinator/worker) | claude-sonnet-5-5/claude-sonnet-5-5 |
| Cases | 1 |
| Sandbox said "reproduced" | 1 |
| ...confirmed by the real fix (precision) | 0 (0%) |
| Outcomes | reproduced: 1 |
| Tokens, total / per case | 156,661 / 156,661 |
| Latency per case, p50 / p95 | 78s / 78s |

## Cases

| Case | Verdict | Fail→pass | Attempts | LLM calls | Tokens | Time | Stopped |
|---|---|---|---|---|---|---|---|
| pallets/click#3403 | reproduced | ❌ | 3 | 13 | 156,661 | 78s | token_budget |

## Notes

- **Why only this case:** it is the one bug report in the 12-case set that neither Gemini 3.1
  Flash-Lite nor Claude Haiku 5.5 verified ([`click-haiku.md`](click-haiku.md)). Running the
  stronger model only where the cheap ones fail answers "does the bigger model fix what the
  cheaper ones can't?" for a fraction of the cost of rerunning everything.
- **Outcome: not verified.** Sonnet's test failed only with the two decorators in the opposite
  order from the issue's example. The verifier rejected it because the order the issue
  describes passed at the buggy commit, and the real-fix check agreed: the test still failed
  after the fix.
- **Open question:** #3403 may not be reproducible from its issue text at its base commit.
  Next step: run the issue's own snippet at the buggy commit to tell a model limitation from
  a dataset-quality issue.
- **Setup:** pipeline at `d07e9a7`, both models `claude-sonnet-5-5`, `SANDBOX=docker`,
  `BACKTEST_MAX_TOKENS=150000`, `BACKTEST_MAX_USD=2.00`. Estimated cost ≤ $0.37 (upper bound).
