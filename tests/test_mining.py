import subprocess

import pytest

from issue_to_repro.backtest.mining import find_fix_commits, split_changed_files


def test_finds_only_unambiguous_fixes_with_source_and_tests(history):
    repo, base, fix = history
    cases = find_fix_commits(repo, since="2020-01-01")
    assert [c.issue_number for c in cases] == [12]
    case = cases[0]
    assert (case.fix_commit, case.base_commit) == (fix, base)
    assert case.subject == "Fix rounding"
    assert case.source_files == ("pkg/core.py",)
    assert case.test_files == ("tests/test_core.py",)


def test_since_filters_old_history(history):
    repo, _, _ = history
    assert find_fix_commits(repo, since="2021-01-01") == []


def test_split_changed_files():
    source, tests = split_changed_files(
        ["src/a.py", "tests/test_a.py", "docs/x.py", "CHANGES.rst", "setup.cfg", "test/b.py"]
    )
    assert source == ("src/a.py",)
    assert tests == ("tests/test_a.py", "test/b.py")


def test_reports_git_errors(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        find_fix_commits(tmp_path)
