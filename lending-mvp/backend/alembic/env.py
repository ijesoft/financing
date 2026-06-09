import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool, create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Import our models so metadata is populated ────────────────────────────────
# Add backend root to sys.path so `app.*` imports resolve, then import the
# SQLAlchemy `Base` (and the model modules that register their tables on it).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.database.pg_models import Base  # noqa: E402
import app.database.pg_core_models  # noqa: E402,F401  - registers tables on Base.metadata
import app.database.pg_loan_models  # noqa: E402,F401
import app.database.pg_accounting_models  # noqa: E402,F401

# Use the populated Base.metadata so `alembic revision --autogenerate`
# can detect model drift against the live DB schema.
target_metadata = Base.metadata

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config

# Override sqlalchemy.url from environment (used in Docker)
pool_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://lending_user:lending_password@localhost:5432/lending_db",
)
# Use sync psycopg2 for Alembic (Alembic uses sync engine for migrations)
sync_url = pool_url.replace("postgresql+asyncpg://", "postgresql://")
config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use empty metadata since we're using declarative migrations
# target_metadata = Base.metadata


# ── Offline migrations ────────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (sync) ─────────────────────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with sync psycopg2."""
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, echo=False)
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
