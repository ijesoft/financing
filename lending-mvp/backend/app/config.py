from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── PostgreSQL (primary database) ─────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://lending_user:lending_secret@localhost:5433/lending_db"

    # PostgreSQL 16 support (upgrade from 15)
    # Use postgres:16-alpine in docker-compose.yml

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://:lending_redis_pass@redis:6379/0"

    # ── JWT ───────────────────────────────────────────────────────────────────
    # No hard-coded default — must be supplied via env, minimum 32 chars.
    # Generate with:  python -c "import secrets; print(secrets.token_urlsafe(64))"
    JWT_SECRET_KEY: str = Field(..., min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480         # 8-hour access tokens
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30            # Long-lived refresh tokens
    TOTP_TEMP_TOKEN_EXPIRE_MINUTES: int = 5        # Temp token issued during 2FA step

    # ── Session Management ────────────────────────────────────────────────────
    MAX_CONCURRENT_SESSIONS: int = 20              # Max simultaneous logins per user

    # ── File Uploads (KYC docs) ───────────────────────────────────────────────
    UPLOAD_DIR: str = "/tmp/kyc_uploads"

    # ── Banking-grade mode ────────────────────────────────────────────────────
    # When true, the database engine pool uses conservative banking-grade
    # settings: pool_recycle=1800, pool_timeout=10, pool_pre_ping=True.
    # Default off to preserve existing behavior.
    banking_grade_mode: bool = False


settings = Settings()
