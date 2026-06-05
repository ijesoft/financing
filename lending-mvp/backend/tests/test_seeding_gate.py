"""
Tests for SEED_DEMO_DATA gating.

The demo seeder must only run when BOTH:
  1. SEED_DEMO_DATA=true
  2. ENVIRONMENT is unset or "development"

In production-like environments, even if SEED_DEMO_DATA=true is set by
accident, the seeder must NOT be called.
"""

import importlib
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


# Pre-mock the broken graphql module so app.main can be imported in this
# test environment (graphql.py has a pre-existing import error we must not
# fix as part of this task).
_fake_graphql = MagicMock()
_fake_graphql.schema = MagicMock()
sys.modules.setdefault("app.graphql", _fake_graphql)

# Ensure DATABASE_URL uses asyncpg before app.main is imported (the .env
# ships a psycopg2 URL that breaks app.database.postgres at import time).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://lending_user:lending_secret@localhost:5433/lending_test_db",
)


@pytest.fixture
def fresh_main(monkeypatch):
    """
    Reload app.main with the requested env-var overrides applied first.
    Yields the reloaded module.
    """
    def _load(env: dict):
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        import app.main as m
        importlib.reload(m)
        return m
    return _load


def test_seeder_not_called_in_production_with_seed_flag(monkeypatch, fresh_main):
    """SEED_DEMO_DATA=true + ENVIRONMENT=production must NOT call the seeder."""
    main_module = fresh_main({"SEED_DEMO_DATA": "true", "ENVIRONMENT": "production"})
    monkeypatch.setattr(main_module, "seed_demo_data_enhanced", AsyncMock())
    assert main_module._should_seed_demo_data() is False


def test_seeder_not_called_in_staging_with_seed_flag(monkeypatch, fresh_main):
    """SEED_DEMO_DATA=true + ENVIRONMENT=staging must NOT call the seeder."""
    main_module = fresh_main({"SEED_DEMO_DATA": "true", "ENVIRONMENT": "staging"})
    monkeypatch.setattr(main_module, "seed_demo_data_enhanced", AsyncMock())
    assert main_module._should_seed_demo_data() is False


def test_seeder_called_in_development_with_seed_flag(monkeypatch, fresh_main):
    """SEED_DEMO_DATA=true + ENVIRONMENT=development must call the seeder."""
    main_module = fresh_main({"SEED_DEMO_DATA": "true", "ENVIRONMENT": "development"})
    monkeypatch.setattr(main_module, "seed_demo_data_enhanced", AsyncMock())
    assert main_module._should_seed_demo_data() is True


def test_seeder_called_with_default_env(monkeypatch, fresh_main):
    """SEED_DEMO_DATA=true with ENVIRONMENT unset must call the seeder (default = dev)."""
    main_module = fresh_main({"SEED_DEMO_DATA": "true"})
    monkeypatch.setattr(main_module, "seed_demo_data_enhanced", AsyncMock())
    assert main_module._should_seed_demo_data() is True


def test_seeder_not_called_when_seed_flag_false_dev(monkeypatch, fresh_main):
    """SEED_DEMO_DATA=false + dev must never call the seeder."""
    main_module = fresh_main({"SEED_DEMO_DATA": "false", "ENVIRONMENT": "development"})
    monkeypatch.setattr(main_module, "seed_demo_data_enhanced", AsyncMock())
    assert main_module._should_seed_demo_data() is False


def test_seeder_not_called_when_seed_flag_false_production(monkeypatch, fresh_main):
    """SEED_DEMO_DATA=false + production must never call the seeder."""
    main_module = fresh_main({"SEED_DEMO_DATA": "false", "ENVIRONMENT": "production"})
    monkeypatch.setattr(main_module, "seed_demo_data_enhanced", AsyncMock())
    assert main_module._should_seed_demo_data() is False
