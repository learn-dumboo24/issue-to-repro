# Benchmark tasks

Each task is one real, already-fixed bug from a public repository, packaged so that an agent can be
evaluated on it: the issue as filed, the buggy commit, a test that fails there, and the
maintainers' fix that makes it pass. Tasks are a by-product of the backtest: only reproductions
that were already **verified against the real fix** become tasks, and CI re-proves every task in
the Docker sandbox ([`.github/workflows/bench.yml`](../.github/workflows/bench.yml)) without any
model.

| File | Tasks | Repository | Issues filed |
|---|---|---|---|
| [`click.jsonl`](click.jsonl) | 10 | [pallets/click](https://github.com/pallets/click) | Oct 2024 – Jun 2026 |

## Fields

| Field | Meaning |
|---|---|
| `instance_id` | `owner__repo-<issue>`, e.g. `pallets__click-3362` |
| `repo`, `issue_number`, `issue_url`, `created_at` | The issue and when it was filed |
| `base_commit` | The buggy commit (the fix's parent) |
| `fix_commit` | The maintainers' fix |
| `problem_statement` | Issue title and body exactly as filed. Comments are left out: they often reveal the fix |
| `gold_patch` | `git diff base fix` of the fix's source files |
| `test_path`, `test_code` | The fail-to-pass test: fails at `base_commit`, passes with `gold_patch` |
| `upstream_test_patch` | The maintainers' own test changes in the fix, for reference |
| `test_source` | The backtest run that wrote the test (results file and models) |
| `schema_version` | `1` |

## Evaluating a fixing agent

1. Check out `repo` at `base_commit` and give the agent `problem_statement`. Keep `test_code` and
   `gold_patch` hidden.
2. Apply the agent's patch, write `test_code` to `test_path` and run it. The task is solved if it
   passes; run it more than once to catch flaky passes.

`issue-to-repro bench verify` runs the same check with `gold_patch` in place of an agent's patch.

## How tasks are built

```bash
uv run issue-to-repro bench export --dataset datasets/click.jsonl \
  --source workspace/_sources/click \
  --results results/click-haiku.jsonl --results results/click-flash-lite-budget.jsonl \
  --results results/click-haiku-semantic.jsonl --out bench/click.jsonl
uv run issue-to-repro bench verify --tasks bench/click.jsonl --source workspace/_sources/click
```

For each issue the first verified reproduction across the results files is used (earlier files
win). Of the 10 tests, 9 come from the Claude Haiku 5.5 run and 1 (#2869) from the Haiku run with
semantic search.

## Limitations

- **Small:** 10 tasks from one repository. It is a seed set for the pipeline, not a leaderboard.
- **Fail-to-pass only:** a task checks that the reported bug is fixed, not that the rest of the
  test suite still passes.
- **Model-written tests:** each test checks the behaviour the issue reports and was verified
  against the real fix, but it can be narrower than the maintainers' tests
  (`upstream_test_patch`).
- **Possible contamination:** the issues and fixes are public, so models trained after they were
  published may have seen them. `created_at` lets you keep only issues filed after a model's
  training cutoff.

## License

The tasks contain code, patches and issue text from pallets/click (BSD-3-Clause); issue text
belongs to its authors and each task links to the original issue. Public repositories only.
