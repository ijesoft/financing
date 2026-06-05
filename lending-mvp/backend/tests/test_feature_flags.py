"""
Tests for the feature_flags module.

Verifies the BANKING_GRADE_MODE flag can be toggled via environment variable
and that the module imports cleanly.
"""

import importlib
import os


def test_feature_flags_module_imports():
    """from app.feature_flags import flags should succeed."""
    from app.feature_flags import flags
    assert flags is not None


def test_banking_grade_mode_default_is_false(monkeypatch):
    """With no env var, banking_grade_mode should be False."""
    monkeypatch.delenv("BANKING_GRADE_MODE", raising=False)
    import app.feature_flags as ff
    importlib.reload(ff)
    assert ff.flags.banking_grade_mode is False


def test_banking_grade_mode_true_when_env_set(monkeypatch):
    """BANKING_GRADE_MODE=true should make banking_grade_mode True."""
    monkeypatch.setenv("BANKING_GRADE_MODE", "true")
    import app.feature_flags as ff
    importlib.reload(ff)
    assert ff.flags.banking_grade_mode is True
