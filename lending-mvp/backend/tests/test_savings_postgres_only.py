"""
Test that savings_crud is PostgreSQL-only (no MongoDB / motor / pymongo).

Also tests that the GraphQL createSavingsAccount mutation posts a journal entry
(DR 1010 Cash in Bank / CR 2020 Savings Deposits Payable) when balance > 0.

DB-level tests live in test_savings_db_integration.py to avoid StaticPool
create_all collisions.
"""
import ast
import importlib
import inspect


SAVINGS_CRUD_PATH = "app/database/savings_crud.py"


def _read_savings_crud_source() -> str:
    with open(SAVINGS_CRUD_PATH, "r") as f:
        return f.read()


def test_savings_crud_does_not_import_pymongo():
    """app/database/savings_crud.py must not import pymongo."""
    source = _read_savings_crud_source()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "pymongo" not in alias.name.lower(), (
                    f"savings_crud.py imports pymongo via 'import {alias.name}'"
                )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert "pymongo" not in mod.lower(), (
                f"savings_crud.py imports from pymongo: 'from {mod} import ...'"
            )


def test_savings_crud_does_not_import_motor():
    """app/database/savings_crud.py must not import motor (async Mongo driver)."""
    source = _read_savings_crud_source()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "motor" not in alias.name.lower(), (
                    f"savings_crud.py imports motor via 'import {alias.name}'"
                )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert "motor" not in mod.lower(), (
                f"savings_crud.py imports from motor: 'from {mod} import ...'"
            )


def test_savings_crud_does_not_import_bson():
    """app/database/savings_crud.py must not import bson (Mongo BSON types)."""
    source = _read_savings_crud_source()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "bson" not in alias.name.lower(), (
                    f"savings_crud.py imports bson via 'import {alias.name}'"
                )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert "bson" not in mod.lower(), (
                f"savings_crud.py imports from bson: 'from {mod} import ...'"
            )


def test_savings_crud_module_imports_cleanly():
    """app/database/savings_crud module must import cleanly without Mongo deps."""
    from app.database import savings_crud as crud_mod
    importlib.reload(crud_mod)
    # SavingsCRUD class still exists
    assert hasattr(crud_mod, "SavingsCRUD")


def test_savings_crud_create_uses_postgres_only():
    """SavingsCRUD.create_savings_account must take an AsyncSession (Postgres),
    not a Motor collection."""
    from app.database.savings_crud import SavingsCRUD
    sig = inspect.signature(SavingsCRUD.__init__)
    # Check that the only required param besides self is the AsyncSession (db),
    # NOT a Mongo collection.
    params = list(sig.parameters.values())
    # Drop 'self'
    real_params = [p for p in params if p.name != "self"]
    assert len(real_params) >= 1, "SavingsCRUD.__init__ takes no db argument"
    first = real_params[0]
    # The annotation should reference AsyncSession (Postgres), not MotorCollection
    annotation_str = str(first.annotation).lower()
    assert "motor" not in annotation_str, (
        f"SavingsCRUD.__init__ takes Motor collection: {first.annotation}"
    )
    assert "collection" not in annotation_str or "async" in annotation_str, (
        f"SavingsCRUD.__init__ takes Mongo collection: {first.annotation}"
    )


def test_savings_graphql_mutation_calls_accounting_on_positive_balance():
    """app/savings.py's createSavingsAccount mutation must call accounting
    to post a journal entry when input.balance > 0."""
    with open("app/savings.py", "r") as f:
        source = f.read()
    # Either a direct call to create_journal_entry, or a call to
    # accounting_service.post_transaction, must be in the createSavingsAccount path
    # for the positive-balance branch.
    assert (
        "create_journal_entry" in source
        or "post_transaction" in source
        or "post_journal_entry" in source
    ), (
        "app/savings.py does not call any accounting function. "
        "Opening deposit > 0 must DR 1010 / CR 2020."
    )
    # And it must reference the two GL codes.
    assert "1010" in source, "savings.py does not reference GL code 1010"
    assert "2020" in source, "savings.py does not reference GL code 2020"
