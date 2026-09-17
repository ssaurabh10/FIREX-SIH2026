"""
FIREX v2 Core Configuration (Clean Pydantic V2 Settings)

This module is committed to the repository and therefore holds **no
credentials**. Every secret lives in the gitignored ``.env`` beside it; the
committed template is ``.env.example``.

A fresh clone resolves settings in this order:

1. real environment variables (highest precedence)
2. ``v2/backend/.env`` -- loaded by absolute path, so it is found no matter
   which directory the server is started from
3. the defaults below, all of which are safe to publish

If ``FIRMS_MAP_KEY`` or the OpenRouter keys are unset, ingestion and the AI
provider degrade explicitly rather than silently using a baked-in key. See
``has_firms_key`` / ``has_ai_keys``.
"""
import os
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ENV_FILE = os.path.join(_BACKEND_DIR, ".env")
_DEFAULT_DB_FILE = os.path.join(_BACKEND_DIR, "data", "firex_v2.db").replace("\\", "/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Absolute path: ``.env`` used to be resolved against the CWD, so
        # ``python run.py serve`` from v2/ silently ignored it and fell back to
        # the built-in defaults (including the database path).
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "FIREX-SIH2026"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api"
    ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Database Configuration (PostgreSQL/PostGIS or local SQLite fallback)
    DATABASE_URL: str = f"sqlite:///{_DEFAULT_DB_FILE}"

    # NASA FIRMS Ingestion
    FIRMS_BASE_URL: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    FIRMS_MAP_KEY: str = ""  # set in .env -- never commit a live key
    FIRMS_REGION: str = "68.7,8.4,97.4,37.6"  # Sovereign India bounding box: W, S, E, N
    FIRMS_DAYS: int = 2
    FIRMS_DEFAULT_PRODUCTS: List[str] = [
        "VIIRS_NOAA20_NRT",
        "VIIRS_SNPP_NRT",
        "MODIS_NRT",
    ]

    # AI Investigation / Multimodal Provider Configuration (Stage 6)
    AI_PROVIDER: str = "openrouter"  # "openrouter", "mock"
    # AI_MODEL is the single source of truth for the vision model id. The old
    # AI_MODEL_NAME field is exposed as a read-only alias below; it used to be a
    # second, independent setting that /status reported while the provider
    # called AI_MODEL, so the two could name different models.
    AI_MODEL: str = "dots-studio/dots-3-note-preview:free"
    AI_API_BASE_URL: str = "https://openrouter.ai/api/v1"
    AI_TIMEOUT_SECONDS: int = 45
    AI_MAX_RETRIES: int = 4
    AI_TEMPERATURE: float = 0.1
    OPENROUTER_API_KEYS: List[str] = []  # set in .env -- never commit live keys

    # Rotation policy for the multimodal provider key pool (Section 6.3).
    # A key that returns 429 is quarantined for AI_KEY_COOLDOWN_SECONDS; a key
    # that returns 401/402/403 (revoked or out of credit) for
    # AI_KEY_QUARANTINE_SECONDS.
    AI_KEY_COOLDOWN_SECONDS: int = 60
    AI_KEY_QUARANTINE_SECONDS: int = 3600

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    # Security & Hardening (Stage 10)
    API_KEY_AUTH_ENABLED: bool = False  # disabled by default for local UI demo
    API_KEY_HEADER: str = "X-FIREX-KEY"
    ADMIN_API_KEY: str = ""  # set in .env -- never commit a live key
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 120  # 120 requests/minute per client IP
    RATE_LIMIT_BURST: int = 30        # Burst limit

    # Performance & In-Memory Cache (Stage 10)
    CACHE_ENABLED: bool = True
    CACHE_DEFAULT_TTL_SECONDS: int = 60

    @field_validator("DATABASE_URL")
    @classmethod
    def _resolve_relative_sqlite_path(cls, value: str) -> str:
        """Resolve a relative SQLite path against v2/backend, not the CWD.

        ``.env`` ships ``sqlite:///./data/firex_v2.db``. Resolved naively that
        depends on the working directory, so ``python run.py serve`` from v2/
        opened ``v2/data/firex_v2.db`` (471 KB, empty) while the documented
        queue and every pre-computed baseline lived in
        ``v2/backend/data/firex_v2.db`` (1.28 GB).
        """
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        path = value[len(prefix):]
        if path.startswith(":memory:") or os.path.isabs(path):
            return value
        resolved = os.path.abspath(os.path.join(_BACKEND_DIR, path))
        return prefix + resolved.replace("\\", "/")

    @property
    def AI_MODEL_NAME(self) -> str:
        """Deprecated alias for :attr:`AI_MODEL`.

        Retained so existing callers keep working; it now reports the model the
        provider actually calls instead of a separately-settable value.
        """
        return self.AI_MODEL

    @property
    def has_firms_key(self) -> bool:
        return bool(self.FIRMS_MAP_KEY.strip())

    @property
    def has_ai_keys(self) -> bool:
        return bool(self.OPENROUTER_API_KEYS) or self.AI_PROVIDER == "mock"


settings = Settings()
