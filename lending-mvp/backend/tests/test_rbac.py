"""
TDD tests for Task A3+A4: RBAC on createUser and updateUser.

A3: createUser must require admin role; non-admin -> exception with "admin role required".
A4: updateUser must block non-admin role change; admin self-role-change blocked too.

These tests mock the Strawberry `info` context and the UserCRUD layer
to focus on the authorization decision in isolation.

NOTE: We patch broken sibling modules (services.accounting_service has a
schema mismatch fixed in task A8) before importing app.user so the import
chain succeeds in this isolated test.
"""
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Stub broken sibling modules so app.user can be imported cleanly.
# (A8 fixes accounting_service properly; this stub keeps the import chain alive
# until that lands.)
# ---------------------------------------------------------------------------
def _install_audit_log_stub():
    mod = types.ModuleType("app.services.accounting_service")
    async def post_transaction(*args, **kwargs):  # noqa: D401
        return None
    async def get_ledger_entries_for_account(*args, **kwargs):
        return []
    async def get_journal_entries_for_account(*args, **kwargs):
        return []
    mod.post_transaction = post_transaction
    mod.get_ledger_entries_for_account = get_ledger_entries_for_account
    mod.get_journal_entries_for_account = get_journal_entries_for_account
    sys.modules.setdefault("app.services.accounting_service", mod)


_install_audit_log_stub()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_info(current_user):
    info = MagicMock()
    info.context = {"current_user": current_user}
    return info


def make_user(role: str, user_id: str = "u-1", username: str = "u1"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.role = role
    u.email = f"{username}@example.com"
    return u


# ---------------------------------------------------------------------------
# A3: createUser auth check
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_user_non_admin_raises():
    """Non-admin calling createUser must raise with 'admin role required'."""
    from app.user import Mutation
    from app.schema import UserCreateInput

    non_admin = make_user("customer", user_id="42")
    info = make_info(non_admin)
    payload = UserCreateInput(
        email="new@example.com",
        username="newuser",
        full_name="New User",
        password="Sup3rSecret!",
        role="customer",
    )

    with patch("app.user.get_users_collection", create=True) as mock_get_coll:
        mock_get_coll.return_value = MagicMock()
        with pytest.raises(Exception) as exc_info:
            await Mutation().create_user(info, input=payload)
    assert "admin role required" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_create_user_admin_succeeds():
    """Admin calling createUser should NOT raise the auth error."""
    from app.user import Mutation
    from app.schema import UserCreateInput
    from app.models import UserCreate as UserCreateModel

    admin = make_user("admin", user_id="99")
    info = make_info(admin)
    payload = UserCreateInput(
        email="new2@example.com",
        username="newuser2",
        full_name="New User 2",
        password="Sup3rSecret!",
        role="customer",
    )

    # Patch all the CRUD + Mongo bits so the test does not touch the DB.
    with patch("app.user.get_users_collection", create=True) as mock_get_coll, \
         patch("app.user.get_async_session_local") as mock_session_local, \
         patch("app.user.UserCRUD") as MockUserCRUD:
        mock_get_coll.return_value = MagicMock()
        crud_instance = MagicMock()
        crud_instance.get_user_by_email = AsyncMock(return_value=None)
        crud_instance.get_user_by_username = AsyncMock(return_value=None)
        created = MagicMock()
        created.id = "new-id"
        created.hashed_password = "hashed"
        crud_instance.create_user = AsyncMock(return_value=created)
        MockUserCRUD.return_value = crud_instance

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_session_local.return_value = mock_session

        # Should not raise "admin role required"
        try:
            result = await Mutation().create_user(info, input=payload)
        except Exception as exc:
            assert "admin role required" not in str(exc).lower(), \
                f"Admin was blocked: {exc}"


# ---------------------------------------------------------------------------
# A4: updateUser self-role-escalation guard
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_update_user_non_admin_cannot_change_role():
    """Non-admin passing role='admin' to updateUser must raise."""
    from app.user import Mutation
    from app.schema import UserUpdateInput

    me = make_user("customer", user_id="42")
    info = make_info(me)
    payload = UserUpdateInput(role="admin")

    with pytest.raises(Exception) as exc_info:
        await Mutation().update_user(info, user_id="42", input=payload)
    assert "role" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_update_user_admin_self_role_change_blocked():
    """Admin trying to set their OWN role must raise."""
    from app.user import Mutation
    from app.schema import UserUpdateInput

    me = make_user("admin", user_id="99")
    info = make_info(me)
    payload = UserUpdateInput(role="customer")

    with pytest.raises(Exception) as exc_info:
        await Mutation().update_user(info, user_id="99", input=payload)
    msg = str(exc_info.value).lower()
    assert "self" in msg or "own role" in msg


@pytest.mark.asyncio
async def test_update_user_admin_changes_other_role_succeeds_auth():
    """Admin changing another user's role must pass the auth check."""
    from app.user import Mutation
    from app.schema import UserUpdateInput

    me = make_user("admin", user_id="99")
    other_id = "55"
    info = make_info(me)
    payload = UserUpdateInput(role="customer")

    with patch("app.user.get_users_collection", create=True) as mock_get_coll, \
         patch("app.user.get_async_session_local") as mock_session_local, \
         patch("app.user.UserCRUD") as MockUserCRUD:
        mock_get_coll.return_value = MagicMock()
        crud_instance = MagicMock()
        updated = MagicMock()
        updated.id = other_id
        updated.hashed_password = "h"
        crud_instance.update_user = AsyncMock(return_value=updated)
        MockUserCRUD.return_value = crud_instance

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock()))
        )
        mock_session_local.return_value = mock_session

        try:
            result = await Mutation().update_user(info, user_id=other_id, input=payload)
        except Exception as exc:
            assert "self" not in str(exc).lower() or "own role" not in str(exc).lower(), \
                f"Admin was blocked from updating another user: {exc}"
