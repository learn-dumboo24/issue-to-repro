"""Runtime settings, read from environment variables (or a local .env file)."""

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
    # A reproduction must fail on every one of these runs to count (flakiness guard).
    repro_runs: int = 3
    test_timeout_s: int = 120
    # Reproducer <-> verifier rounds before giving up on an issue.
    max_repro_attempts: int = 4

    # Hard per-case limits for backtests (Google Cloud billing has no automatic spending cap).
    backtest_max_llm_calls: int = 40
    backtest_max_tokens: int = 400_000

    # Optional; raises GitHub's API rate limit. Public issues work without it.
    github_token: SecretStr | None = None


def get_settings() -> Settings:
    return Settings()
