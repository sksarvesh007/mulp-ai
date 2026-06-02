"""Application configuration via pydantic-settings. Reads ``backend/.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = .../mulp-ai ; this file = backend/app/core/config.py
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_POLICY = _REPO_ROOT / "docs" / "policy_terms.json"
_DEFAULT_TEST_CASES = _REPO_ROOT / "docs" / "test_cases.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM / vision provider ────────────────────────────────────────────────
    llm_provider: str = "openai"  # "openai" — multimodal base model reads images directly

    # OpenAI (multimodal). The base model (gpt-5.5) reads document images directly, so the
    # live pipeline has no OCR step — the upload is sent straight to the model as an image.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.5"

    # Per-request LLM timeout (seconds) + retries. Without this the OpenAI SDK default is
    # ~10 minutes, so a slow/stuck call can hang a node (and the SSE stream) for minutes;
    # bounding it lets a stuck call fail fast and degrade into a clean decision. Vision +
    # reasoning is slower than text, so give it more headroom than the old text-only path.
    llm_timeout_s: float = 90.0
    llm_max_retries: int = 2

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = "local"
    log_level: str = "INFO"
    policy_file: Path = _DEFAULT_POLICY
    test_cases_file: Path = _DEFAULT_TEST_CASES
    # Claims persistence. SQLite by default; set to a Postgres URL in production.
    db_url: str = "sqlite:///claims.db"

    # ── Supabase claims ledger (REST/PostgREST) ──────────────────────────────
    # Records every LIVE submission and powers the history-aware fraud velocity rules
    # (same-day / monthly limits). Reads the frontend-style NEXT_PUBLIC_* env names too.
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_url", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"),
    )
    supabase_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "supabase_key",
            "SUPABASE_KEY",
            "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        ),
    )
    supabase_claims_table: str = "claims"

    # ── Observability ────────────────────────────────────────────────────────
    # Langfuse (GenAI tracing + eval scores)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"
    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "claims-backend"
    enable_observability: bool = False

    # Opt-in: run an OpenAI-Agents-SDK reviewer (with policy tools) as an advisory node.
    # Off by default so the deterministic pipeline is unchanged; never affects the decision.
    enable_agentic_review: bool = False

    @field_validator("policy_file", "test_cases_file", mode="after")
    @classmethod
    def _resolve_relative(cls, value: Path) -> Path:
        """Resolve relative paths against the repo root so config works from any cwd."""
        return value if value.is_absolute() else (_REPO_ROOT / value).resolve()

    @property
    def claims_ledger_enabled(self) -> bool:
        """Whether the Supabase claims ledger is configured (URL + key present)."""
        return bool(self.supabase_url and self.supabase_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def supports_vision(self) -> bool:
        """The OpenAI base model reads document images directly (no OCR step)."""
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
