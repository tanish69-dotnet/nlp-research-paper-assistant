"""Centralized configuration.

All runtime knobs come from environment variables / ``.env`` using the keys
documented in ``.env.example``. No secrets are hard-coded in source; provider
API keys are read from the environment only and never logged (SECURITY.md §5).

Model *names* are configuration too: the source tree contains no model names,
so swapping Ollama models (or a future provider) never touches agent code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved from this file, never hard-coded as an absolute path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_ROOT = PROJECT_ROOT / "app" / "prompts" / "versions"

Environment = Literal["local", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["json", "console"]
ProviderName = Literal["ollama", "openai_compat", "mock"]
EvidenceMode = Literal["embedded", "http"]


class Settings(BaseSettings):
    """Typed, validated application settings (pydantic-settings).

    ``extra="ignore"`` so unrelated environment variables never break startup,
    while *known* keys are still strictly type-checked and range-checked.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),  # fields such as `model_provider` are ours, not pydantic's
    )

    # --- runtime ------------------------------------------------------------
    reasoning_env: Environment = "local"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8001, ge=1, le=65535)
    app_version: str = "0.1.0"
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"
    enable_eval_api: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # allow env value to be comma-separated or JSON
    _cors_origins_raw: str = ""

    # --- model provider -----------------------------------------------------
    model_provider: ProviderName = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    openai_compat_base_url: str | None = None
    openai_compat_api_key: SecretStr | None = None

    # Role -> model. Empty means "not configured" (reported via /api/v1/models).
    analyzer_model: str = "qwen2.5:1.5b"
    text_model: str = "qwen2.5:1.5b"
    table_model: str = "qwen2.5:1.5b"
    vision_model: str = "qwen2.5vl:3b"
    judge_model: str = "qwen2.5:1.5b"
    generator_model: str = "qwen2.5:1.5b"

    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    model_max_tokens: int = Field(default=2048, ge=1)

    # --- timeouts / retries / concurrency -----------------------------------
    request_timeout_ms: int = Field(default=120_000, ge=1_000)
    agent_timeout_ms: int = Field(default=60_000, ge=1_000)
    provider_timeout_ms: int = Field(default=45_000, ge=100)
    model_max_retries: int = Field(default=2, ge=0, le=10)
    provider_max_concurrency: int = Field(default=2, ge=1)

    # --- evidence -----------------------------------------------------------
    evidence_mode: EvidenceMode = "embedded"
    rag_base_url: str = ""
    evidence_root: str = "./evidence"
    max_evidence_items: int = Field(default=40, ge=1)
    max_evidence_chars: int = Field(default=120_000, ge=1_000)
    max_evidence_item_chars: int = Field(default=8_000, ge=100)
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_image_pixels: int = Field(default=20_000_000, ge=1_024)
    max_request_bytes: int = Field(default=4 * 1024 * 1024, ge=128)
    max_context_tokens: int = Field(default=7_000, ge=256)

    # --- retrieval (Person 2 service, Phase 8 /ask) --------------------------
    retrieval_mode: Literal["disabled", "mock", "http"] = "disabled"
    retrieval_base_url: str = "http://localhost:8000"
    retrieval_timeout_s: float = Field(default=30.0, gt=0.0, le=300.0)
    retrieval_top_k: int = Field(default=5, ge=1, le=50)

    # --- pipeline behaviour (consumed from Phase 2/4 onward) -----------------
    include_agent_outputs: bool = True
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    judge_enabled: bool = True

    # --- validators ---------------------------------------------------------
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept ``CORS_ORIGINS=a,b`` as well as a JSON/YAML list."""
        if isinstance(value, str):
            # Try JSON first (for complex lists), fall back to comma-split
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(part).strip() for part in parsed if str(part).strip()]
                except json.JSONDecodeError:
                    pass
            # Fallback: comma-separated
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("api_host")
    @classmethod
    def _host_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("api_host must not be empty")
        if "://" in value:
            raise ValueError("api_host must be a bare host (use API_PORT, not a URL)")
        return value.strip()

    @field_validator("ollama_base_url")
    @classmethod
    def _url_scheme(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("ollama_base_url must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("openai_compat_base_url", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return None if value == "" else value

    # --- derived paths ------------------------------------------------------
    @property
    def evidence_root_path(self) -> Path:
        """Absolute, resolved evidence root used to confine image paths."""
        path = Path(self.evidence_root).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @property
    def prompts_path(self) -> Path:
        """Directory holding versioned prompt templates."""
        return PROMPTS_ROOT
