"""AgentForge AI — Configuration (Pydantic Settings)

Includes startup validation and security checks.
"""

import os
import secrets
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache

logger = logging.getLogger(__name__)

_DEFAULT_JWT_SECRET = "dev-secret-change-in-production"


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://agentforge:agentforge_dev@localhost:5432/agentforge_db"

    # Claude API
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"

    # Gemini API (fallback / alternative)
    gemini_api_key: str = ""
    # Optional extra Gemini keys (comma-separated) from other accounts. The service
    # round-robins across all of them to multiply free-tier throughput and fail over
    # on per-key rate limits (429).
    gemini_api_keys: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Groq API (fast Llama inference)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile was retired by Groq

    # Local model via Ollama (free, offline, no rate limits). Used when AI_PROVIDER=ollama,
    # or in "auto" mode when no cloud key is set and the Ollama server is running.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_num_ctx: int = 16384  # qwen2.5:3b at 16k ctx ≈ 2.5 GB VRAM — fits a 4 GB GPU
    ollama_timeout: float = 600.0

    # Phantom Hunter: a fast model for high-volume extraction (the deterministic
    # verifier guards its output) and a stronger one for reasoning (debate, chat).
    phantom_extract_model: str = "qwen2.5:3b"
    phantom_reason_model: str = ""  # empty → OLLAMA_MODEL
    phantom_auto_seed: bool = True  # fill empty Phantom tables from seed/phantom_seed.json.gz on startup

    # AI Provider: "groq" | "claude" | "gemini" | "ollama" | "auto" (auto picks whichever is available)
    ai_provider: str = "auto"

    # Minimum seconds between live LLM calls (0 = no throttle). Set this on free
    # tiers with tight RPM limits (e.g. 6 for Gemini Flash free) to avoid 429s.
    ai_min_call_interval: float = 0.0

    # Mock Mode — OFF by default so a real LLM is used out of the box.
    # When True (or when no API key is available), agents return clearly-labelled
    # simulated data instead of calling a live model. The UI surfaces this as a
    # "DEMO DATA" badge so mock output is never mistaken for real analysis.
    mock_mode: bool = False

    # Agents that run the 3-step generate → self-critique → refine loop
    # (comma-separated keys: ceo,research,marketing,developer,finance,analytics,operations).
    # Each adds 2 LLM calls, so keep this short on free tiers with daily token caps.
    self_critique_agents: str = "ceo"

    # Brave Search
    brave_search_api_key: str = ""

    # Deployment environment: "development" | "production".
    # Only "production" enforces a real JWT secret — dev/demo auto-generates one.
    environment: str = "development"

    # JWT Auth
    jwt_secret_key: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 1440  # 24 hours

    # CORS
    frontend_url: str = "http://localhost:5180"

    # AWS (Phase 4)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-south-1"

    # n8n Integration (400+ external integrations)
    n8n_base_url: str = ""
    n8n_api_key: str = ""

    # Redis (task queue + caching)
    redis_url: str = "redis://localhost:6379/0"
    s3_bucket_name: str = "agentforge-reports"

    # Rate Limiting
    rate_limit_login: str = "10/minute"
    rate_limit_register: str = "5/minute"
    rate_limit_global: str = "100/minute"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # tolerate documented-but-unused env vars (e.g. SERVER_MODE)
    )

    def validate_on_startup(self):
        """Run validation checks after settings are loaded.
        Called manually after settings are created.
        """
        warnings = []
        errors = []
        is_production = self.environment.lower() == "production"

        # JWT secret check — strict only in production; dev/demo auto-generates.
        if self.jwt_secret_key == _DEFAULT_JWT_SECRET:
            if is_production:
                errors.append(
                    "JWT_SECRET_KEY is still the default! Set a secure value in .env for production."
                )
            else:
                # Auto-generate a secure secret for dev/demo (tokens reset on restart — fine for a demo)
                self.jwt_secret_key = secrets.token_urlsafe(32)
                warnings.append(
                    "JWT_SECRET_KEY was default — auto-generated a random secret for this session."
                )

        # API key checks — no key means agents will run in clearly-labelled DEMO (mock) mode.
        has_key = bool(
            self.anthropic_api_key or self.gemini_api_key or self.groq_api_key
            or self.ai_provider.lower() == "ollama"
        )
        if not self.mock_mode and not has_key:
            if is_production:
                errors.append(
                    "No AI API key is set in production! Set GROQ_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY."
                )
            else:
                warnings.append(
                    "No AI API key set — agents will fall back to DEMO (mock) data, shown as a badge in the UI. "
                    "Set a free GROQ_API_KEY for real LLM output."
                )

        if not has_key and (not self.anthropic_api_key or self.anthropic_api_key.startswith("sk-ant-xxxx")):
            warnings.append("ANTHROPIC_API_KEY is not set — mock mode will be used for AI generation.")

        if not self.brave_search_api_key or self.brave_search_api_key.startswith("BSAxxxx"):
            warnings.append("BRAVE_SEARCH_API_KEY is not set — web search will use the keyless Wikipedia API.")

        # Log all issues
        for w in warnings:
            logger.warning(f"⚠ CONFIG: {w}")
        for e in errors:
            logger.error(f"✗ CONFIG: {e}")

        # errors are only raised in production (collected above under is_production)
        if errors:
            raise ValueError(
                "Critical configuration errors found:\n" + "\n".join(f"  - {e}" for e in errors)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_on_startup()
    return settings
