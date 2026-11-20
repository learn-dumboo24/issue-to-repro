# Retrieval benchmark: click

31 cases. Query: the issue's title and body. Relevant: the source files the real fix changed. Semantic search: `gemini-embedding-2@768`; keyword search: BM25 over the same chunks; hybrid: reciprocal rank fusion of both.

| Method | hit@1 | hit@3 | hit@5 | hit@10 | recall@5 | MRR |
|---|---|---|---|---|---|---|
| keyword | 52% | 87% | 97% | 100% | 93% | 0.70 |
| semantic | 87% | 97% | 100% | 100% | 98% | 0.92 |
| hybrid | 87% | 97% | 100% | 100% | 99% | 0.93 |

hit@k: a changed file is among the top k files. recall@5: share of changed files in the top 5. MRR: mean of 1/rank of the first changed file.

## Cases

| Case | Changed files | keyword rank | semantic rank | hybrid rank |
|---|---|---|---|---|
| pallets/click#3362 | src/click/_textwrap.py, src/click/formatting.py | 2 | 1 | 1 |
| pallets/click#2110 | src/click/testing.py | 1 | 1 | 1 |
| pallets/click#3822 | src/click/types.py | 1 | 1 | 1 |
| pallets/click#3802 | src/click/core.py | 3 | 4 | 5 |
| pallets/click#2869 | src/click/_termui_impl.py, src/click/termui.py | 2 | 1 | 1 |
| pallets/click#3571 | src/click/_termui_impl.py | 3 | 1 | 1 |
| pallets/click#3700 | src/click/testing.py | 1 | 1 | 1 |
| pallets/click#3572 | src/click/termui.py | 2 | 1 | 1 |
| pallets/click#2877 | src/click/types.py | 2 | 1 | 1 |
| pallets/click#3242 | src/click/termui.py | 2 | 2 | 1 |
| pallets/click#2983 | src/click/core.py | 1 | 1 | 2 |
| pallets/click#3059 | src/click/core.py | 1 | 1 | 1 |
| pallets/click#3043 | src/click/shell_completion.py | 3 | 1 | 1 |
| pallets/click#3360 | src/click/formatting.py | 5 | 1 | 1 |
| pallets/click#3384 | src/click/testing.py | 1 | 1 | 1 |
| pallets/click#3403 | src/click/core.py | 3 | 1 | 1 |
| pallets/click#2745 | src/click/core.py | 1 | 1 | 1 |
| pallets/click#2790 | src/click/exceptions.py | 10 | 2 | 2 |
| pallets/click#2012 | src/click/core.py | 1 | 1 | 1 |
| pallets/click#2865 | src/click/testing.py | 1 | 3 | 1 |
| pallets/click#654 | src/click/testing.py | 1 | 1 | 1 |
| pallets/click#3298 | src/click/core.py | 1 | 1 | 1 |
| pallets/click#3121 | src/click/core.py | 1 | 1 | 1 |
| pallets/click#3145 | src/click/core.py | 4 | 1 | 1 |
| pallets/click#3084 | src/click/core.py | 1 | 1 | 1 |
| pallets/click#3069 | src/click/core.py | 4 | 1 | 1 |
| pallets/click#3071 | src/click/core.py | 1 | 1 | 1 |
| pallets/click#1992 | src/click/core.py, src/click/parser.py, src/click/termui.py | 2 | 1 | 1 |
| pallets/click#3019 | src/click/termui.py | 1 | 1 | 1 |
| pallets/click#2939 | src/click/testing.py | 1 | 1 | 1 |
| pallets/click#2832 | src/click/__init__.py, src/click/core.py, src/click/decorators.py | 2 | 1 | 2 |

## Notes

- **Read hit@1 and MRR, not hit@10.** Click has only 17 Python source files, so the
  top 10 files cover most of the package and every method reaches 100% there. Putting the right
  file *first* is where the methods differ: semantic search does it for 87% of issues against 52%
  for keyword search.
- **Ground truth is the fix's changed source files that exist at the buggy commit.** A fix can
  touch more than the file an issue is "about", so these numbers are a lower bound on how often a
  method finds a relevant file.
- **Setup:** 31 Click cases fixed since 2025-01-01, newest first; query = issue title + body;
  chunks = functions, methods and class headers (tests excluded); embeddings
  `gemini-embedding-2` at 768 dimensions, cached by content hash; hybrid = reciprocal rank fusion
  (k=60). Pipeline at `52bf0e9`.
