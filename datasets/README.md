# Backtest datasets

Each `<name>.jsonl` file is a frozen list of past bug fixes, built from `sources.json` by the
**Build datasets** workflow (`.github/workflows/datasets.yml`) using
`issue-to-repro dataset build`. One line per case:

- the issue's title and body, as written by its reporter (comments are left out because they
  often reveal the fix)
- `base_commit`: the buggy parent; `fix_commit`: the commit that closed the issue
- `source_files` / `test_files` changed by the fix; the fix's tests are the ground truth

Datasets are committed so every backtest runs on exactly the same inputs. To add a repository,
add it to `sources.json`; the workflow runs on push and uploads the files as an artifact.
