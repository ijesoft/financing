"""
Test that dead models (Loan, Transaction, LedgerEntry, InterestLedger) have been
removed from app.database.pg_core_models.

These models were unused or only referenced by broken code paths.
"""
import pytest


def test_loan_model_removed():
    """Loan model in pg_core_models is unused; should be removed."""
    with pytest.raises(ImportError):
        from app.database.pg_core_models import Loan  # noqa: F401


def test_transaction_model_removed():
    """Transaction model in pg_core_models is referenced only by broken code; should be removed."""
    with pytest.raises(ImportError):
        from app.database.pg_core_models import Transaction  # noqa: F401


def test_ledger_entry_model_removed():
    """LedgerEntry model in pg_core_models is referenced only by broken code; should be removed."""
    with pytest.raises(ImportError):
        from app.database.pg_core_models import LedgerEntry  # noqa: F401


def test_interest_ledger_model_removed():
    """InterestLedger model in pg_core_models is unused; should be removed."""
    with pytest.raises(ImportError):
        from app.database.pg_core_models import InterestLedger  # noqa: F401


def test_surviving_models_still_present():
    """The surviving models in pg_core_models must still be importable."""
    from app.database.pg_core_models import (  # noqa: F401
        User,
        Customer,
        SavingsAccount,
        SavingsTransaction,
        StandingOrder,
    )


def test_app_database_init_imports_clean():
    """app/database/__init__.py must still import successfully after removals."""
    import importlib
    import app.database as db_pkg
    importlib.reload(db_pkg)
    # If we got here, the package imported without ImportError
    assert hasattr(db_pkg, "Base")


def test_base_metadata_has_surviving_tables():
    """Base.metadata must contain the surviving tables."""
    from app.database.base import Base
    # Force model registration
    from app.database import pg_core_models  # noqa: F401
    table_names = set(Base.metadata.tables.keys())
    # surviving tables
    assert "users" in table_names
    assert "customers" in table_names
    assert "savings_accounts" in table_names
    assert "savings_transactions" in table_names
    assert "standing_orders" in table_names
    # dead tables should be GONE
    assert "loans" not in table_names
    assert "transactions" not in table_names
    assert "ledger_entries" not in table_names
    assert "interest_ledger" not in table_names
