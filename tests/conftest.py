import pytest


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
