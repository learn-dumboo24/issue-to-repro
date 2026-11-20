"""Runtime settings, read from environment variables (or a local .env file)."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Gemini backend. With Vertex AI, auth comes from Application Default Credentials;
    # without it, google-genai reads GOOGLE_API_KEY (AI Studio).
    google_genai_use_vertexai: bool = True
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"

    # Model ids are configurable so they can follow Gemini releases without code changes.
    # Flash for both: gemini-2.5-* is closed to new users, and Pro models have no free-tier
    # quota. Set COORDINATOR_MODEL to a Pro model once billing is enabled.
    coordinator_model: str = "gemini-3.8-flash"
    worker_model: str = "gemini-3.8-flash"

    # Retries with exponential backoff on overload / rate-limit / server errors (429, 5xx).
    model_retry_attempts: int = 6

    # Only checkouts under this directory may be searched or have tests run in them.
    workspace_root: str = "workspace"
    # Hard cap on the retriever's tool calls per run (it over-searched when only instructed).
    retriever_max_tool_calls: int = 8
    # Where reproduction tests run. "docker": a container with no network, a non-root user,
    # read-only mounts and resource limits (see tools/isolation.py). "local": this machine.
    sandbox: Literal["local", "docker"] = "local"
    sandbox_image: str = "mirror.gcr.io/library/debian:bookworm-slim"
    sandbox_memory: str = "1g"
    sandbox_cpus: str = "1"
    sandbox_pids: int = 256
    # uv's standalone Python builds live here; checkouts for the docker sandbox are built on
    # them so the container needs nothing installed (UV_PYTHON_INSTALL_DIR).
    python_install_dir: str = "/opt/uv-python"
    # A reproduction must fail on every one of these runs to count (flakiness guard).
    repro_runs: int = 3
    test_timeout_s: int = 120
    # Reproducer <-> verifier rounds before giving up on an issue.
    max_repro_attempts: int = 4

    # Semantic code search (retrieval/): Gemini embeddings, cached on disk by content hash.
    embedding_model: str = "gemini-embedding-2"
    embedding_dims: int = 768
    embedding_cache_dir: str = "workspace/_embeddings"
    # Texts embedded per minute; the free tier allows 100 for gemini-embedding-2.
    embedding_requests_per_minute: int = 90

    # Hard per-case limits for backtests (Google Cloud billing has no automatic spending cap).
    backtest_max_llm_calls: int = 40
    backtest_max_tokens: int = 400_000

    # Optional; raises GitHub's API rate limit. Public issues work without it.
    github_token: SecretStr | None = None


def get_settings() -> Settings:
    return Settings()
