import pytest

from issue_to_repro.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep tests independent of the machine: no stray env vars, no local .env file."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A workspace root containing one tiny 'repository' with a known bug in add()."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("REPRO_RUNS", "2")
    repo = tmp_path / "demo"
    (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "__init__.py").write_text("def add(a, b):\n    return a - b  # bug\n")
    (repo / "README.md").write_text("Demo package. add() should add numbers.\n")
    return repo
