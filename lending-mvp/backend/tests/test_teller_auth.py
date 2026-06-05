"""
Tests for teller route authentication.

The teller routes in app/teller.py previously had `Depends(...)` (the
literal Python Ellipsis) as the auth dependency. Ellipsis is truthy and
non-None, so the routes were effectively public. These tests verify the
routes are properly protected by inspecting the route definitions.

The app.teller module cannot be imported in this test environment
because of several pre-existing bugs in dependencies owned by other
subagents (accounting_service imports, graphql Loan import, etc.).
We therefore test the route definitions at the source-text level.
"""

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


TELLER_PY = Path(__file__).resolve().parent.parent / "app" / "teller.py"


# Pre-mock broken modules so we can import app.teller if we ever need to.
_services_mock = MagicMock()
sys.modules.setdefault("app.services", _services_mock)
sys.modules.setdefault("app.services.accounting_service", _services_mock)
sys.modules.setdefault("app.services.loan_service", _services_mock)

import app.database as _db_module
for _missing in ("LedgerEntry", "JournalEntry", "JournalLine", "GLAccount"):
    if not hasattr(_db_module, _missing):
        setattr(_db_module, _missing, MagicMock())


def _read_teller_source() -> str:
    return TELLER_PY.read_text()


def _route_dependencies(source: str) -> dict[str, str]:
    """
    Return a mapping of route function name -> the Depends(...) expression
    on its `current_user` parameter.
    """
    pattern = re.compile(
        r"async\s+def\s+(\w+)\s*\([^)]*?current_user:\s*dict\s*=\s*Depends\(([^)]+)\)",
        re.DOTALL,
    )
    return {m.group(1): m.group(2).strip() for m in pattern.finditer(source)}


class TestTellerAuthDependency:
    """The Depends(...) ellipsis placeholders must be replaced with a real auth dep."""

    def test_no_ellipsis_depends_anywhere(self):
        """No route may still use `Depends(...)` (the literal Ellipsis)."""
        source = _read_teller_source()
        # After our fix the only `Depends(` calls should reference a name.
        bare_ellipsis = re.findall(r"Depends\(\s*\.\.\.\s*\)", source)
        assert bare_ellipsis == [], (
            f"Found {len(bare_ellipsis)} unguarded `Depends(...)` placeholders in teller.py: "
            f"{bare_ellipsis}"
        )

    def test_all_five_routes_use_auth_dependency(self):
        """All five teller routes must depend on get_current_user."""
        source = _read_teller_source()
        deps = _route_dependencies(source)
        expected_routes = {
            "open_cash_drawer",
            "close_cash_drawer",
            "process_cash_transaction",
            "get_cash_drawer_balance",
            "set_transaction_limits",
        }
        assert expected_routes.issubset(deps.keys()), (
            f"Missing routes: {expected_routes - set(deps.keys())}"
        )
        for route, dep in deps.items():
            assert dep == "get_current_user", (
                f"Route {route!r} uses Depends({dep!r}) instead of get_current_user"
            )

    def test_get_current_user_is_imported(self):
        """teller.py must import get_current_user from app.auth.authentication."""
        source = _read_teller_source()
        assert (
            "from app.auth.authentication import get_current_user" in source
            or "from app.auth.authentication import" in source
            and "get_current_user" in source
        ), "teller.py must import get_current_user"


# ---------------------------------------------------------------------------
# Runtime tests — these use FastAPI dependency overrides so we don't need
# the real `app.teller` module to be importable. We construct a minimal
# duplicate of one route that exercises the same auth dependency contract.
# ---------------------------------------------------------------------------

from app.auth.authentication import get_current_user  # noqa: E402


@pytest.fixture
def teller_user():
    return {
        "id": "507f1f77bcf86cd799439011",
        "username": "test_teller",
        "role": "teller",
        "branch_code": "HQ",
    }


def test_get_current_user_raises_401_without_cookie():
    """get_current_user must raise 401 when no access_token cookie is present."""
    from fastapi import HTTPException
    mock_request = MagicMock()
    mock_request.cookies = {}
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(mock_request)
    assert exc_info.value.status_code == 401


def test_get_current_user_raises_401_with_invalid_token():
    """get_current_user must raise 401 when the cookie has a bad token."""
    from fastapi import HTTPException
    mock_request = MagicMock()
    mock_request.cookies = {"access_token": "Bearer not-a-real-jwt"}
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(mock_request)
    assert exc_info.value.status_code == 401


@pytest.fixture
def app_for_override():
    """A tiny FastAPI app that requires get_current_user."""
    app = FastAPI()

    @app.get("/__protected")
    def protected(user: dict = __import__("fastapi").Depends(get_current_user)):
        return {"role": user["role"], "id": user["id"]}

    return app


def test_dependency_override_returns_teller_user(app_for_override, teller_user):
    """When overridden, get_current_user returns the fake teller user."""
    app_for_override.dependency_overrides[get_current_user] = lambda: teller_user
    with TestClient(app_for_override) as client:
        resp = client.get("/__protected")
        assert resp.status_code == 200
        assert resp.json()["role"] == "teller"


def test_unprotected_endpoint_returns_401(app_for_override):
    """Without an override, get_current_user raises 401."""
    with TestClient(app_for_override) as client:
        resp = client.get("/__protected")
    assert resp.status_code == 401
