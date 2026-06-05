"""
TDD tests for Task A1: JWT secret rotation + remove hard-coded default.

Goals:
- When JWT_SECRET_KEY env is unset, instantiating Settings raises ValidationError.
- When JWT_SECRET_KEY is shorter than 32 chars, raise ValidationError.
- When JWT_SECRET_KEY is exactly 32+ chars, instantiation succeeds.
"""
import os
import pytest
from pydantic import ValidationError


def test_settings_missing_jwt_secret_raises(monkeypatch):
    """When JWT_SECRET_KEY env is unset, Settings() should raise ValidationError."""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    # The lazy `settings` module-level instance may already be constructed and
    # cached. Re-instantiate fresh to validate the new validator.
    from app.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_short_jwt_secret_raises(monkeypatch):
    """JWT_SECRET_KEY shorter than 32 chars should raise ValidationError."""
    monkeypatch.setenv("JWT_SECRET_KEY", "tooshort")
    from app.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_exactly_32_chars_accepted(monkeypatch):
    """JWT_SECRET_KEY of exactly 32 chars should be accepted."""
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 32)
    from app.config import Settings
    s = Settings(_env_file=None)
    assert len(s.JWT_SECRET_KEY) == 32


def test_settings_long_jwt_secret_accepted(monkeypatch):
    """JWT_SECRET_KEY of 64 chars (typical) should be accepted."""
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.JWT_SECRET_KEY == "a" * 64
