from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── PostgreSQL (primary database) ─────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://lending_user:lending_password@localhost:5432/lending_db"
    # Note: Using asyncpg (async driver) instead of psycopg2 for async compatibility
    
    # PostgreSQL 16 support (upgrade from 15)
    # Use postgres:16-alpine in docker-compose.yml

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://:lending_redis_pass@redis:6379/0"

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15          # Short-lived access tokens
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30            # Long-lived refresh tokens
    TOTP_TEMP_TOKEN_EXPIRE_MINUTES: int = 5        # Temp token issued during 2FA step

    # ── Session Management ────────────────────────────────────────────────────
    MAX_CONCURRENT_SESSIONS: int = 20              # Max simultaneous logins per user

    # ── File Uploads (KYC docs) ───────────────────────────────────────────────
    UPLOAD_DIR: str = "/tmp/kyc_uploads"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

