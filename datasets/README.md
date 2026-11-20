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

## Known issues

- **pallets/click#3403 is not reproducible as filed.** The issue's snippet already prints the
  behaviour the reporter asked for (`enable_xyz = False` with no arguments) at the buggy commit,
  and the real fix changes it to `True` to respect `default=True`. A test that follows the issue
  text cannot fail before the fix and pass after it. Results keep the case for transparency;
  read reproduction rates as "of the cases reproducible as filed" where this matters. Gemini 3.1
  Flash-Lite, Claude Haiku 5.5 and Claude Sonnet 5.5 all failed it; Sonnet's verifier rejected
  its own test for exactly this reason.
