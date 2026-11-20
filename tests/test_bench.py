import json
import sys
from dataclasses import replace

import pytest
from conftest import git, git_only
from test_checkout import make_case

import issue_to_repro
from issue_to_repro.backtest.checkout import prepare_worktree
from issue_to_repro.bench.tasks import (
    SCHEMA_VERSION,
    export_tasks,
    instance_id,
    read_tasks,
    verified_rows,
    write_tasks,
)
from issue_to_repro.bench.verify import verify_task, verify_tasks

FIXED_BEHAVIOUR = "from pkg.core import x\n\ndef test_x():\n    assert x == 2\n"
ALWAYS_PASSES = "def test_ok():\n    assert True\n"
NEVER_PASSES = "from pkg.core import x\n\ndef test_x():\n    assert x == 3\n"
TEST_PATH = "tests/test_issue_repro_12.py"


def result_row(number=12, fail_to_pass=True, code=FIXED_BEHAVIOUR, models="m/w"):
    return {
        "issue_number": number,
        "fail_to_pass": fail_to_pass,
        "test_path": TEST_PATH,
        "test_code": code,
        "models": models,
    }


def write_results(path, *rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + "\n")
    return path


@pytest.fixture
def bench_setup(history, tmp_path, monkeypatch):
    repo, base, fix = history
    monkeypatch.setenv("REPRO_RUNS", "2")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))  # the sandbox only runs here
    case = make_case(base, fix)

    def prepare(task):
        return prepare_worktree(
            repo, task.base_commit, tmp_path / "ws" / task.instance_id, run=git_only
        )

    return repo, case, prepare


def test_export_builds_a_task_from_the_first_verified_run(bench_setup, tmp_path):
    repo, case, _ = bench_setup
    first = write_results(tmp_path / "a.jsonl", result_row(fail_to_pass=False, code="nope"))
    second = write_results(tmp_path / "b.jsonl", result_row(models="m2/w2"))
    third = write_results(tmp_path / "c.jsonl", result_row(code=ALWAYS_PASSES))
    [task] = export_tasks([case], [first, second, third], repo)
    assert task.instance_id == "o__proj-12" == instance_id("o/proj", 12)
    assert (task.base_commit, task.fix_commit) == (case.base_commit, case.fix_commit)
    assert task.problem_statement.startswith(case.issue_title + "\n\n")
    assert "-x = 1\n+x = 2" in task.gold_patch and "pkg/core.py" in task.gold_patch
    assert "+# t" in task.upstream_test_patch
    assert (task.test_path, task.test_code) == (TEST_PATH, FIXED_BEHAVIOUR)
    assert task.test_source == "b.jsonl (m2/w2)"
    assert task.schema_version == SCHEMA_VERSION


def test_export_skips_unverified_issues_and_rejects_unknown_ones(bench_setup, tmp_path):
    repo, case, _ = bench_setup
    none_verified = write_results(tmp_path / "a.jsonl", result_row(fail_to_pass=None))
    assert export_tasks([case], [none_verified], repo) == []
    unknown = write_results(tmp_path / "b.jsonl", result_row(number=99))
    with pytest.raises(ValueError, match="#99 is not in the dataset"):
        export_tasks([case], [unknown], repo)


def test_export_rejects_a_verified_row_without_a_test(tmp_path):
    bad = write_results(tmp_path / "a.jsonl", result_row(code=None))
    with pytest.raises(ValueError, match="has no test"):
        verified_rows([bad])


def test_export_rejects_a_fix_that_changes_no_source_file(bench_setup, tmp_path):
    repo, case, _ = bench_setup
    results = write_results(tmp_path / "a.jsonl", result_row())
    with pytest.raises(ValueError, match="changes none of its source files"):
        export_tasks([replace(case, source_files=("docs/none.md",))], [results], repo)
    with pytest.raises(ValueError, match="changes none of its source files"):
        export_tasks([replace(case, source_files=())], [results], repo)


def test_tasks_round_trip_and_unknown_schemas_are_rejected(bench_setup, tmp_path):
    repo, case, _ = bench_setup
    [task] = export_tasks([case], [write_results(tmp_path / "a.jsonl", result_row())], repo)
    out = tmp_path / "tasks.jsonl"
    assert write_tasks([task], out) == 1
    assert read_tasks(out) == [task]
    data = json.loads(out.read_text())
    data["schema_version"] = 99
    out.write_text(json.dumps(data) + "\n")
    with pytest.raises(ValueError, match="unsupported task schema"):
        read_tasks(out)


def exported(bench_setup, tmp_path, code=FIXED_BEHAVIOUR):
    repo, case, prepare = bench_setup
    results = write_results(tmp_path / "r.jsonl", result_row(code=code))
    [task] = export_tasks([case], [results], repo)
    return task, prepare


def test_verify_proves_fail_to_pass_and_reverts_the_fix(bench_setup, tmp_path):
    task, prepare = exported(bench_setup, tmp_path)
    [check] = verify_tasks([task], prepare)
    assert (check.ok, check.error) == (True, None)
    assert (check.before, check.before_runs) == ("reproduced", ["failed", "failed"])
    assert check.after_runs == ["passed", "passed"]
    checkout = tmp_path / "ws" / task.instance_id
    assert (checkout / "pkg" / "core.py").read_text() == "x = 1\n"  # fix reverted


def test_verify_fails_a_test_that_passes_at_base(bench_setup, tmp_path):
    task, prepare = exported(bench_setup, tmp_path, code=ALWAYS_PASSES)
    check = verify_task(task, prepare)
    assert not check.ok and check.error == "test does not fail at base: not_reproduced"
    assert check.after_runs is None


def test_verify_fails_a_test_the_fix_does_not_make_pass(bench_setup, tmp_path):
    task, prepare = exported(bench_setup, tmp_path, code=NEVER_PASSES)
    check = verify_task(task, prepare)
    assert (check.ok, check.error) == (False, "test does not pass with the fix")
    assert check.after_runs == ["failed", "failed"]


def test_verify_fails_when_the_gold_patch_does_not_apply(bench_setup, tmp_path):
    task, prepare = exported(bench_setup, tmp_path)
    broken = replace(task, gold_patch=task.gold_patch.replace("-x = 1", "-x = 9"))
    check = verify_task(broken, prepare)
    assert not check.ok and check.error.startswith("gold patch does not apply")


def test_verify_fails_when_the_checkout_is_at_the_wrong_commit(bench_setup, tmp_path, history):
    task, prepare = exported(bench_setup, tmp_path)
    check = verify_task(replace(task, base_commit=history[2]), lambda t: prepare(task))
    assert not check.ok and check.error.startswith("checkout is at ")
    assert check.before == "not_run"


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["issue-to-repro", *args])
    issue_to_repro.main()


def test_bench_cli_exports_and_verifies(bench_setup, tmp_path, monkeypatch, capsys):
    repo, case, _ = bench_setup
    from issue_to_repro.backtest import checkout as checkout_module

    dataset = tmp_path / "dataset.jsonl"
    from issue_to_repro.backtest.dataset import write_jsonl

    write_jsonl([case], dataset)
    results = write_results(tmp_path / "r.jsonl", result_row())
    tasks = tmp_path / "tasks.jsonl"
    common = ["--source", str(repo)]
    run_cli(
        monkeypatch,
        "bench",
        "export",
        "--dataset",
        str(dataset),
        *common,
        "--results",
        str(results),
        "--out",
        str(tasks),
    )
    assert "wrote 1 tasks" in capsys.readouterr().out

    real = checkout_module.prepare_worktree
    monkeypatch.setattr(
        checkout_module, "prepare_worktree", lambda s, c, t: real(s, c, t, run=git_only)
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    out = tmp_path / "checks.jsonl"
    run_cli(monkeypatch, "bench", "verify", "--tasks", str(tasks), *common, "--out", str(out))
    assert "o__proj-12: ok" in capsys.readouterr().out
    assert json.loads(out.read_text())["ok"] is True

    with pytest.raises(SystemExit) as exit_info:  # no task matches: nothing verified is a failure
        run_cli(monkeypatch, "bench", "verify", "--tasks", str(tasks), *common, "--only", "7")
    assert exit_info.value.code == 1
    assert "0/0 tasks verified" in capsys.readouterr().out


def test_bench_verify_exits_nonzero_when_a_task_fails(bench_setup, tmp_path, monkeypatch, capsys):
    task, _ = exported(bench_setup, tmp_path, code=ALWAYS_PASSES)
    from issue_to_repro.backtest import checkout as checkout_module

    tasks = tmp_path / "tasks.jsonl"
    write_tasks([task], tasks)
    real = checkout_module.prepare_worktree
    monkeypatch.setattr(
        checkout_module, "prepare_worktree", lambda s, c, t: real(s, c, t, run=git_only)
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    with pytest.raises(SystemExit):
        run_cli(
            monkeypatch,
            "bench",
            "verify",
            "--tasks",
            str(tasks),
            "--source",
            str(bench_setup[0]),
            "--only",
            "12",
        )
    assert "o__proj-12: FAILED: test does not fail at base" in capsys.readouterr().out
    assert git(bench_setup[0], "status", "--porcelain") == ""
