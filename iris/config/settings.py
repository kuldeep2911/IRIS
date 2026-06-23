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
    # AES-256-at-rest passphrase (the key is derived in-memory, never stored).
    # In prod, source this from the keychain/Vault, not .env.
    IRIS_PASSPHRASE: str = ""
    IRIS_CRYPTO_SALT: str = "iris-v5-default-salt"  # override per deployment

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

    # ── Screen intelligence (Phase 7.2) — OPT-IN, privacy-first, OFF default ──
    # In-memory only (never persisted); only allow-listed apps are captured and
    # sensitive apps (banking/passwords) are never captured.
    SCREEN_INTEL_ENABLED: bool = False
    SCREEN_ALLOWLIST: list[str] = [
        "code", "visual studio", "pycharm", "intellij", "sublime", "vim",
        "terminal", "powershell", "cmd", "iterm", "chrome", "firefox", "edge",
        "notepad", "word", "excel", "obsidian", "notion", "figma",
    ]
    SCREEN_BLOCKLIST: list[str] = [
        "bank", "banking", "paypal", "password", "keepass", "1password",
        "bitwarden", "lastpass", "wallet", "crypto", "metamask", "authenticator",
        "login", "sign in",
    ]

    # ── Proactive alerts (Phase 7.2) — all OFF by default ─────────────────
    PROACTIVE_MEETING_ALERTS: bool = False
    PROACTIVE_EMAIL_ALERTS: bool = False
    PROACTIVE_DAILY_BRIEFING: bool = False
    DAILY_BRIEFING_TIME: str = "08:00"      # HH:MM local
    MEETING_ALERT_LEAD_MINUTES: int = 10

    # ── Filesystem sandbox (filesystem/shell MCP may only touch this) ─────
    WORKSPACE_DIR: str = "./workspace"

    # ── Voice (Phase 5) — provider-agnostic adapters, FREE/open-source defaults ──
    # STT default: faster-whisper (MIT, fully local, no API key). Sarvam is an
    # optional paid swap (set STT_PROVIDER=sarvam + SARVAM_API_KEY).
    STT_PROVIDER: str = "whisper"         # whisper (free/local) | sarvam (paid)
    WHISPER_MODEL: str = "base"           # faster-whisper size: tiny|base|small|...
    STT_LANGUAGE: str = "en"              # whisper lang hint (en handles Indian English)
    SARVAM_API_KEY: str = ""              # optional; read here only (GOLDEN RULE #8)

    # TTS default: Kokoro-82M (Apache-2.0, local). Gemini TTS is the fallback.
    TTS_PROVIDER: str = "kokoro"          # kokoro (free/local) | gemini
    TTS_VOICE: str = "af_heart"           # Kokoro female voice
    TTS_SAMPLE_RATE: int = 24000
    KOKORO_MODEL_PATH: str | None = None  # path to kokoro onnx model (optional)
    KOKORO_VOICES_PATH: str | None = None # path to kokoro voices bin (optional)
    GEMINI_TTS_VOICE: str = "Aoede"       # female prebuilt voice (Gemini fallback)

    # Wake word: openWakeWord (Apache-2.0, fully local, no API key, no trial).
    # Default uses a pretrained model; train a custom "Hey IRIS" .onnx and point
    # WAKE_MODEL_PATH at it (see README).
    WAKE_WORD: str = "hey iris"
    WAKE_MODEL: str = "hey_jarvis"        # pretrained openWakeWord model name
    WAKE_MODEL_PATH: str | None = None    # custom-trained "Hey IRIS" model (optional)
    WAKE_THRESHOLD: float = 0.5
    VOICE_CHAT_URL: str = "http://localhost:8000/chat"

    # ── Connectors (Phase 9) ──────────────────────────────────────────────
    # ONE exact redirect URI used everywhere (authorize + token exchange). This
    # EXACT string must be registered in each provider's OAuth app config.
    CONNECTOR_REDIRECT_URI: str = "http://localhost:8000/connectors/callback"
    # HMAC secret for signing the OAuth `state` (CSRF protection). Falls back to
    # the crypto passphrase/salt if unset.
    CONNECTOR_STATE_SECRET: str = ""

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
