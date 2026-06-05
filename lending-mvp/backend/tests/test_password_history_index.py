"""
Test that password_history has a composite index on (user_id, created_at DESC).

The check_password_history flow in app/auth/security.py does:
    SELECT hashed_password FROM password_history
    WHERE user_id = :uid
    ORDER BY created_at DESC
    LIMIT :n
A composite (user_id, created_at DESC) index makes that an index-only scan
instead of a heap sort.
"""
import pytest
from sqlalchemy import text


INDEX_NAME = "ix_password_history_user_created"


def test_password_history_composite_index_is_declared():
    """app/database/pg_models.py PasswordHistory table must declare
    __table_args__ containing the composite Index on (user_id, created_at DESC).
    """
    from app.database.pg_models import PasswordHistory
    args = PasswordHistory.__table_args__ or ()
    matches = []
    for arg in args:
        if hasattr(arg, "name") and getattr(arg, "name", None) == INDEX_NAME:
            matches.append(arg)
    assert matches, (
        f"PasswordHistory is missing composite index {INDEX_NAME}. "
        f"Got __table_args__ = {args!r}"
    )
    idx = matches[0]
    cols = [c.name for c in idx.columns]
    assert "user_id" in cols, f"{INDEX_NAME} must include user_id, got {cols}"
    assert "created_at" in cols, f"{INDEX_NAME} must include created_at, got {cols}"


@pytest.mark.asyncio
async def test_password_history_composite_index_present_in_db(db_session):
    """After create_all, the composite index must exist in PostgreSQL."""
    from app.database.pg_core_models import Base  # noqa: F401  (registers tables)
    from app.database.pg_models import PasswordHistory  # noqa: F401

    res = await db_session.execute(text(
        "SELECT indexname FROM pg_indexes "
        "WHERE tablename = 'password_history' AND indexname = :name"
    ), {"name": INDEX_NAME})
    row = res.first()
    assert row is not None, (
        f"Index {INDEX_NAME} is not present in the live schema"
    )
