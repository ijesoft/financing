"""
Test that the banking-grade engine pool config is honored.

BANKING_GRADE_MODE=true (env) must enable:
  - pool_recycle = 1800
  - pool_timeout = 10
  - pool_pre_ping = True

Default mode keeps the safe defaults from app/database/__init__.py
(pool_pre_ping=True, pool_size=10, max_overflow=20) but pool_recycle/pool_timeout
must differ from the banking-grade values.
"""
import importlib
import os


def _fresh_settings():
    """Read env vars into a fresh Settings instance."""
    from app.config import Settings
    return Settings()


def test_banking_grade_mode_default_is_false():
    """When BANKING_GRADE_MODE is not set, settings.banking_grade_mode is False."""
    os.environ.pop("BANKING_GRADE_MODE", None)
    settings = _fresh_settings()
    assert settings.banking_grade_mode is False, (
        "BANKING_GRADE_MODE default must be False to preserve current behavior"
    )


def test_banking_grade_mode_can_be_enabled(monkeypatch):
    """Setting BANKING_GRADE_MODE=true must surface as settings.banking_grade_mode == True."""
    monkeypatch.setenv("BANKING_GRADE_MODE", "true")
    settings = _fresh_settings()
    assert settings.banking_grade_mode is True

    monkeypatch.setenv("BANKING_GRADE_MODE", "1")
    settings = _fresh_settings()
    assert settings.banking_grade_mode is True


def test_banking_grade_mode_can_be_disabled(monkeypatch):
    """Setting BANKING_GRADE_MODE=false must surface as settings.banking_grade_mode == False."""
    monkeypatch.setenv("BANKING_GRADE_MODE", "false")
    settings = _fresh_settings()
    assert settings.banking_grade_mode is False


def test_engine_pool_config_banking_grade_enabled(monkeypatch):
    """With BANKING_GRADE_MODE=true, get_engine() must return an engine
    whose pool has pool_recycle=1800, pool_timeout=10, pool_pre_ping=True.
    """
    monkeypatch.setenv("BANKING_GRADE_MODE", "true")
    from app.config import settings
    settings.banking_grade_mode = True  # ensure field reflects env

    from app import database as db_mod
    db_mod._engine = None  # reset cached engine

    engine = db_mod.get_engine()
    pool = engine.pool
    assert pool._recycle == 1800, (
        f"banking-grade mode must set pool_recycle=1800, got {pool._recycle}"
    )
    assert pool._timeout == 10, (
        f"banking-grade mode must set pool_timeout=10, got {pool._timeout}"
    )
    assert pool._pre_ping is True, (
        f"banking-grade mode must set pool_pre_ping=True, got {pool._pre_ping}"
    )

    db_mod._engine = None  # reset for other tests


def test_engine_pool_config_banking_grade_disabled_default(monkeypatch):
    """With BANKING_GRADE_MODE unset, pool_recycle/pool_timeout must NOT be
    the banking-grade values (1800/10).
    """
    monkeypatch.delenv("BANKING_GRADE_MODE", raising=False)
    from app.config import settings
    settings.banking_grade_mode = False

    from app import database as db_mod
    db_mod._engine = None

    engine = db_mod.get_engine()
    pool = engine.pool
    # In non-banking-grade mode, recycle and timeout should not be the
    # banking-grade values.
    assert pool._recycle != 1800 or pool._timeout != 10, (
        "Non-banking-grade mode should NOT use pool_recycle=1800 / pool_timeout=10"
    )

    db_mod._engine = None
