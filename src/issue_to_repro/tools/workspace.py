"""Path checks shared by every tool that touches a repository checkout."""

from pathlib import Path

from ..config import get_settings


def resolve_checkout(repo_dir: str) -> Path:
    """Return `repo_dir` resolved, or raise ValueError if it is outside the workspace root."""
    root = Path(get_settings().workspace_root).resolve()
    path = Path(repo_dir).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"{repo_dir!r} is outside the workspace root {str(root)!r}")
    if not path.is_dir():
        raise ValueError(f"{repo_dir!r} is not a directory")
    return path
