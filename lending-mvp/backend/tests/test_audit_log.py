"""
TDD tests for Task A2: Fix broken `audit_log` import in payment_gateway.py.

Goals:
- `from app.audit_middleware import audit_log` succeeds.
- `audit_log` is an async function accepting the canonical signature:
  (user_id, action, entity, entity_id, status, detail).
- Calling `audit_log(...)` persists a row in the audit_logs table.
"""
import pytest
from sqlalchemy import select


def test_audit_log_import_succeeds():
    """`from app.audit_middleware import audit_log` should work."""
    from app.audit_middleware import audit_log
    assert audit_log is not None


def test_audit_log_is_callable():
    """`audit_log` must be callable with the canonical signature."""
    from app.audit_middleware import audit_log
    import inspect
    assert callable(audit_log)
    sig = inspect.signature(audit_log)
    params = list(sig.parameters.keys())
    # Required signature: user_id, action, entity, entity_id, status, detail
    for required in ("user_id", "action", "entity", "entity_id", "status", "detail"):
        assert required in params, f"Missing parameter: {required}"


@pytest.mark.asyncio
async def test_audit_log_persists_row(db_session):
    """Calling audit_log writes a row to audit_logs (uses provided session)."""
    from app.audit_middleware import audit_log
    from app.database.pg_models import AuditLog

    await audit_log(
        user_id="user-123",
        action="test_action",
        entity="customer",
        entity_id="cust-999",
        status="success",
        detail="unit-test row",
        session=db_session,
    )

    # audit_log commits via the provided session, so refresh the connection
    # and assert the row landed in audit_logs.
    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "test_action")
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == "user-123"
    assert row.entity == "customer"
    assert row.entity_id == "cust-999"
    assert row.status == "success"
    assert row.detail == "unit-test row"
