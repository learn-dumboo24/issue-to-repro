"""Turn verified backtest reproductions into self-contained benchmark tasks.

A task is one real bug: the issue text, the buggy commit, a test that fails there, and the
maintainers' fix (as a patch) that makes it pass. Tasks come only from reproductions the backtest
already verified against the real fix; `bench verify` re-proves each one without any model.
"""

import json
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..backtest.dataset import Case

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BenchTask:
    instance_id: str  # e.g. "pallets__click-3362"
    repo: str
    issue_number: int
    issue_url: str
    created_at: str  # when the issue was filed
    base_commit: str  # the buggy commit the test fails on
    fix_commit: str  # the maintainers' fix
    problem_statement: str  # issue title and body, exactly as filed (no comments)
    gold_patch: str  # `git diff base fix` of the fix's source files
    test_path: str  # where the fail-to-pass test goes, relative to the repository root
    test_code: str  # the test: fails at base_commit, passes once gold_patch is applied
    upstream_test_patch: str  # the maintainers' own test changes in the fix, for reference
    test_source: str  # which run produced the test: "<results file> (<models>)"
    schema_version: int = SCHEMA_VERSION


def instance_id(repo: str, issue_number: int) -> str:
    return f"{repo.replace('/', '__')}-{issue_number}"


def problem_statement(case: Case) -> str:
    return f"{case.issue_title}\n\n{case.issue_body}".replace("\r\n", "\n").strip() + "\n"


def git_diff(source: str | Path, base: str, fix: str, paths: Iterable[str]) -> str:
    paths = list(paths)
    if not paths:
        return ""
    command = ["git", "-C", str(source), "diff", "--no-color", "--no-ext-diff", base, fix, "--"]
    return subprocess.run([*command, *paths], check=True, capture_output=True, text=True).stdout


def verified_rows(results_files: list[Path]) -> dict[int, tuple[dict[str, Any], Path]]:
    """For each issue, the first verified reproduction across `results_files`, in order."""
    chosen: dict[int, tuple[dict[str, Any], Path]] = {}
    for path in results_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("fail_to_pass") is True and row["issue_number"] not in chosen:
                if not row.get("test_path") or not row.get("test_code"):
                    raise ValueError(f"{path}: verified row #{row['issue_number']} has no test")
                chosen[row["issue_number"]] = (row, path)
    return chosen


def export_tasks(
    cases: list[Case], results_files: list[Path], source: str | Path
) -> list[BenchTask]:
    """One task per case with a verified reproduction; cases without one are left out."""
    by_number = {case.issue_number: case for case in cases}
    tasks = []
    for number, (row, path) in sorted(verified_rows(results_files).items()):
        case = by_number.get(number)
        if case is None:
            raise ValueError(f"{path}: issue #{number} is not in the dataset")
        gold = git_diff(source, case.base_commit, case.fix_commit, case.source_files)
        if not gold.strip():
            raise ValueError(f"#{number}: the fix changes none of its source files")
        tasks.append(
            BenchTask(
                instance_id=instance_id(case.repo, number),
                repo=case.repo,
                issue_number=number,
                issue_url=case.issue_url,
                created_at=case.issue_created_at,
                base_commit=case.base_commit,
                fix_commit=case.fix_commit,
                problem_statement=problem_statement(case),
                gold_patch=gold,
                test_path=row["test_path"],
                test_code=row["test_code"],
                upstream_test_patch=git_diff(
                    source, case.base_commit, case.fix_commit, case.test_files
                ),
                test_source=f"{path.name} ({row.get('models') or 'unknown model'})",
            )
        )
    return tasks


def write_tasks(tasks: list[BenchTask], out: str | Path) -> int:
    lines = [json.dumps(asdict(task), ensure_ascii=False) for task in tasks]
    Path(out).write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return len(lines)


def read_tasks(path: str | Path) -> list[BenchTask]:
    tasks = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported task schema: {data.get('schema_version')!r}")
        tasks.append(BenchTask(**data))
    return tasks
