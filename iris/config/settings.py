"""IRIS settings — the SINGLE source of configuration and secrets.

GOLDEN RULE #8: secrets are read ONLY here (and via security/secrets.py for the
OS keychain). No other module reads os.environ for credentials directly.

Pydantic v2 BaseSettings: values load from environment variables and an optional
`.env` file. Model thresholds live here (tunable without a code change) so the
model router can tighten routing later without a redeploy.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from env + .env (env wins)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ── Core / environment ────────────────────────────────────────────────
    ENV: Literal["local", "dev", "staging", "prod"] = "local"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Multi-tenancy (single-user uses the default tenant) ───────────────
    DEFAULT_TENANT_ID: str = "local"

    # ── Secrets / providers (read here only) ──────────────────────────────
    GEMINI_API_KEY: str = Field(
        default="",
        description="Google Gemini API key. Read here only; never elsewhere.",
    )

    # ── Data stores ───────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./iris.db"
    REDIS_URL: str | None = None

    # ── Model router thresholds (tunable knobs, no code change) ───────────
    # The router classifies each request into a RequestClass using these.
    ROUTER_SIMPLE_MAX_TOKENS: int = 600
    ROUTER_STANDARD_MAX_TOKENS: int = 4_000
    ROUTER_LONG_CONTEXT_TOKENS: int = 200_000
    ROUTER_DEFAULT_MAX_OUTPUT_TOKENS: int = 2_048
    ROUTER_FORCE_MODEL: str | None = None  # e.g. force a tier for debugging

    # ── Daily cost guards (per-tenant + global token budgets) ─────────────
    DAILY_TOKEN_BUDGET: int = 5_000_000

    # ── Filesystem sandbox (filesystem/shell MCP may only touch this) ─────
    WORKSPACE_DIR: str = "./workspace"

    # ── Browser mesh (Phase 2) ────────────────────────────────────────────
    # Real Chrome profile dir so logged-in sessions (Gmail/WhatsApp/etc) are
    # reused by the browser MCP servers. Empty -> servers use their own profile.
    BROWSER_USER_DATA_DIR: str | None = None
    BROWSER_USE_SSE_URL: str = "http://localhost:7801/sse"
    BROWSER_MCP_SSE_URL: str = "http://localhost:7802/sse"

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the whole app shares one settings instance."""
    return Settings()
