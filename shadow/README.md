# Shadow mode

Shadow mode runs the agents on **real, open bug reports** in other people's repositories and keeps
the results for review. **Nothing is posted** to those repositories. A person reviews each
reproduction, and only then is it shared with the maintainers, by hand and with credit to the
reporter.

This is the test that backtests can't give: whether the tool helps on issues nobody has fixed yet.

## Targets

[`config.json`](config.json) lists the repositories, how many issues to try per repository
(`per_repo`) and how old an issue may be (`max_age_days`). Targets are well-known Python projects
whose test dependencies the installer understands (a `tests`/`test` dependency group or a test
requirements file): Click, Jinja, attrs and Typer.

## Which issues are tried

The newest open issues that look like concrete bug reports:

- not a pull request, and filed within `max_age_days`;
- no label suggesting it isn't a bug (feature, enhancement, question, docs, discussion,
  duplicate, invalid, wontfix);
- a body of at least 100 characters (and not truncated) that contains code: a code block,
  `>>>` prompt or traceback;
- not already in the results file, so reruns try new issues.

## What "reproduced" means here

There is no fix yet, so there is no fail-to-pass check. "Reproduced" means the agents' test
**failed on the repository's default branch in every sandbox run**, at the commit recorded in the
results. That is weaker than a backtest's verified reproduction: the test can fail for a reason
unrelated to the issue. Hence the review step.

## Review before sharing

For each reproduced issue in the report:

1. Read the issue and the test. Does the test check exactly the behaviour the reporter describes?
2. Run it yourself on the recorded commit and on the current default branch.
3. Check the issue's latest comments: it may have been fixed, answered or rejected meanwhile.
4. Only then offer it on the issue, written by you, e.g. "Here's a minimal failing test for this,
   in case it helps", with the test inline.

Record what maintainers say. Whether they find the tests useful is the result of this phase.

## Running it

From the Actions tab: **Shadow run → Run workflow** (inputs: issues per repository, a subset of
repositories, the Gemini model). It needs a `GOOGLE_API_KEY` repository secret. Results are pushed
to a `shadow/run-<id>` branch as `results/shadow/shadow-<id>.jsonl` plus a Markdown report, and the
report also appears on the run's summary page.

Locally (needs Docker):

```bash
SANDBOX=docker uv run issue-to-repro shadow run --config shadow/config.json \
  --out results/shadow/local.jsonl --per-repo 1
uv run issue-to-repro shadow report --results results/shadow/local.jsonl
```

## Safety

| Risk | Handling |
|---|---|
| Issue text is untrusted and may contain prompt injection | The agents are told to treat it as data; their tools only search and read the checkout and write `test_issue_repro*.py` files |
| Agent-written tests (shaped by that text) run code | Only in the Docker sandbox: no network, user nobody, read-only, no credentials, resource limits. `shadow run` refuses to start without `SANDBOX=docker` |
| Installing a target runs its build backend on the runner | Accepted for allowlisted, well-known projects only: the same trust as `pip install` from their main branch. Issue text never reaches the install step |
| Leaking the write token or the model key | The job that holds the Gemini key has a read-only token; the job that pushes results holds no key and runs no outside code |
| Untrusted text in the report | Issue titles are reduced to plain text; tests are shown in code fences long enough not to be broken out of |
| Spending | Free-tier Gemini by default; per-issue caps on model calls and tokens (`BACKTEST_MAX_LLM_CALLS`, `BACKTEST_MAX_TOKENS`) |
