"""
Regression test for alembic env.py target_metadata.

Bug: alembic/env.py declares `target_metadata = MetaData()` (empty), so
alembic's autogenerate cannot detect any model changes. This test asserts
that target_metadata is `Base.metadata` (not an empty MetaData) and that
it contains the tables defined in the SQLAlchemy models.
"""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_ENV_PATH = BACKEND_ROOT / "alembic" / "env.py"


def _install_alembic_context_mock():
    """
    Mock the `alembic.context` module so env.py can be imported in a
    test without a real alembic command. We do not care about alembic's
    own context — we only care about the side effect on `target_metadata`.
    """
    fake_alembic = types.ModuleType("alembic")
    fake_context = MagicMock()
    # Force offline mode so env.py does not try to open a real DB connection
    fake_context.is_offline_mode.return_value = True
    fake_context.config = MagicMock()
    fake_context.config.config_file_name = None
    fake_context.config.get_main_option.return_value = (
        "postgresql://lending_user:lending_secret@localhost:5433/lending_test_db"
    )
    fake_alembic.context = fake_context
    sys.modules.setdefault("alembic", fake_alembic)
    sys.modules["alembic.context"] = fake_context
    return fake_context


def _load_alembic_env():
    """Load alembic/env.py as a module after mocking alembic.context."""
    _install_alembic_context_mock()
    # Make sure app.* imports work
    sys.path.insert(0, str(BACKEND_ROOT))

    spec = importlib.util.spec_from_file_location("alembic_env_test", ALEMBIC_ENV_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_target_metadata_is_base_metadata():
    """alembic/env.py must set target_metadata to Base.metadata (not empty MetaData)."""
    env = _load_alembic_env()

    # 1. target_metadata must be defined
    assert hasattr(env, "target_metadata"), (
        "alembic/env.py must define `target_metadata`"
    )

    # 2. It must be the same object as Base.metadata, not a fresh empty MetaData
    from app.database.pg_models import Base

    assert env.target_metadata is Base.metadata, (
        "target_metadata must be Base.metadata (not a fresh empty MetaData). "
        "This is required for `alembic revision --autogenerate` to detect model changes."
    )

    # 3. The metadata must contain at least one table — proof that model
    #    modules were imported and the metadata is populated.
    assert len(Base.metadata.tables) > 0, (
        "Base.metadata should be populated by importing app.database.pg_models. "
        "If empty, the import line in env.py is missing."
    )


def test_target_metadata_contains_known_tables():
    """Spot-check that key tables from the models are registered in target_metadata."""
    from app.database.pg_models import Base

    env = _load_alembic_env()
    assert env.target_metadata is Base.metadata

    expected_tables = {
        "aml_alerts",
        "collections",
        "loan_transactions",
        "journal_lines",
        "journal_entries",
        "customers",
        "savings_accounts",
        "gl_accounts",
    }
    actual_tables = set(Base.metadata.tables.keys())
    missing = expected_tables - actual_tables
    assert not missing, f"Base.metadata is missing expected tables: {missing}"
