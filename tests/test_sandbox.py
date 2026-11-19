import pytest

from issue_to_repro.tools import run_reproduction_tool
from issue_to_repro.tools.sandbox import (
    RunOutcome,
    Verdict,
    classify_run,
    combine,
    run_reproduction,
)

FAILING = "from demo import add\n\ndef test_add():\n    assert add(2, 2) == 4\n"
PASSING = "from demo import add\n\ndef test_add_zero():\n    assert add(1, 0) == 1\n"
BROKEN_IMPORT = "from demo import multiply\n\ndef test_x():\n    assert multiply(2, 2) == 4\n"
MISSING_FIXTURE = "def test_x(no_such_fixture):\n    assert True\n"


@pytest.mark.parametrize(
    ("code", "verdict"),
    [
        (FAILING, "reproduced"),
        (PASSING, "not_reproduced"),
        (BROKEN_IMPORT, "invalid"),
        (MISSING_FIXTURE, "invalid"),
    ],
)
def test_run_reproduction_verdicts(workspace, code, verdict):
    result = run_reproduction(str(workspace), "tests/test_issue_repro_1.py", code)
    assert result["verdict"] == verdict, result["last_output_tail"]


def test_invalid_run_stops_early(workspace):
    result = run_reproduction(str(workspace), "test_issue_repro_2.py", BROKEN_IMPORT)
    assert result["runs"] == ["invalid"]


@pytest.mark.parametrize(
    "bad", ["../escape/test_issue_repro_1.py", "tests/test_other.py", "conftest.py"]
)
def test_rejects_paths_outside_naming_rule(workspace, bad):
    with pytest.raises(ValueError):
        run_reproduction(str(workspace), bad, FAILING)


def test_rejects_checkout_outside_workspace(workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    with pytest.raises(ValueError, match="outside the workspace"):
        run_reproduction(str(outside), "test_issue_repro_1.py", FAILING)


def test_tool_wrapper_reports_errors_instead_of_raising(workspace):
    result = run_reproduction_tool(str(workspace), "../x/test_issue_repro_1.py", FAILING)
    assert result["status"] == "error"
    assert "ValueError" in result["error"]


def test_classify_run_exit_codes():
    assert classify_run(0, "") is RunOutcome.PASSED
    assert classify_run(1, "1 failed") is RunOutcome.FAILED
    assert classify_run(1, "E   ModuleNotFoundError: No module named 'x'") is RunOutcome.INVALID
    assert classify_run(2, "error during collection") is RunOutcome.INVALID
    assert classify_run(5, "no tests ran") is RunOutcome.INVALID
    assert classify_run(3, "INTERNALERROR") is RunOutcome.ERROR


def test_combine():
    F, P = RunOutcome.FAILED, RunOutcome.PASSED
    assert combine([F, F, F]) is Verdict.REPRODUCED
    assert combine([P, P]) is Verdict.NOT_REPRODUCED
    assert combine([F, P]) is Verdict.FLAKY
    assert combine([F, RunOutcome.TIMEOUT]) is Verdict.ERROR
    with pytest.raises(ValueError):
        combine([])
