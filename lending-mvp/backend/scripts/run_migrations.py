#!/usr/bin/env python
"""
Migration runner script for PostgreSQL database.
Runs all pending Alembic migrations before starting the application.
"""

import os
import sys
import logging
from pathlib import Path

# Setup logging BEFORE importing anything that uses settings
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get database URL from environment
database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://lending_user:lending_password@localhost:5432/lending_db"
)
alembic_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
logger.info(f"Using database URL for migrations: {alembic_url.split('@')[1] if '@' in alembic_url else 'unknown'}")

# NOW add backend to path and import
sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic.config import Config
from alembic import command
from sqlalchemy import inspect, text, create_engine


def run_migrations():
    """
    Run Alembic migrations.
    Uses sync approach to avoid event loop issues.
    """
    try:
        # Get the database URL from environment
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://lending_user:lending_password@localhost:5432/lending_db"
        )
        
        # Replace asyncpg with psycopg2 for Alembic (Alembic doesn't support async drivers)
        alembic_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        
        logger.info(f"Starting database migrations...")
        logger.info(f"   Database: {alembic_url.split('@')[1] if '@' in alembic_url else 'unknown'}")
        
        # Create Alembic config
        alembic_cfg = Config(Path(__file__).parent.parent / "alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", alembic_url)
        
        # Run migrations - this will NOT raise an exception on success
        logger.info("   Running: alembic upgrade head")
        try:
            result = command.upgrade(alembic_cfg, "head")
            logger.info(f"Migrations completed successfully! (Result: {result})")
            return True
        except Exception as e:
            logger.error(f"Alembic upgrade failed: {e}", exc_info=True)
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
            
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


def main():
    """
    Main entry point: run migrations.
    """
    try:
        # Run migrations directly (no async needed for this)
        logger.info("Running Alembic migrations...")
        if not run_migrations():
            logger.error("Migrations failed")
            raise Exception("Migrations failed")
        
        logger.info("Database is ready.")
        return 0
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = main()
    if exit_code == 0:
        print("\nMigration script completed successfully")
    else:
        print(f"\nMigration script failed with code {exit_code}")
