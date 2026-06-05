"""
TDD tests for Task A5: Authenticate GET /api/users.

Goals:
- No auth -> 401
- Admin cookie -> 200
- Customer cookie -> 403
"""
import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from unittest.mock import MagicMock


@pytest.fixture
def app_with_overrides():
    """Build a FastAPI test app including rest_api.router only."""
    from app import rest_api

    app = FastAPI()
    app.include_router(rest_api.router, prefix="")
    return app


def test_get_users_no_auth_returns_401(app_with_overrides):
    app = app_with_overrides
    client = TestClient(app)
    resp = client.get("/api/users")
    assert resp.status_code == 401, resp.text


def test_get_users_admin_returns_200(app_with_overrides):
    app = app_with_overrides
    client = TestClient(app)
    from app import rest_api

    async def fake_get_current_user(request=None):
        u = MagicMock()
        u.role = "admin"
        u.id = 1
        u.uuid = "uuid-1"
        u.email = "a@x"
        u.username = "admin"
        u.full_name = "Admin"
        u.is_active = True
        u.branch_code = None
        u.created_at = "2024-01-01"
        u.updated_at = "2024-01-01"
        return u

    async def fake_get_db():
        class _S:
            async def execute(self_inner, stmt):
                class _R:
                    def scalars(self_inner2):
                        return self_inner2
                    def all(self_inner2):
                        return []
                return _R()
        yield _S()

    app.dependency_overrides[rest_api.get_current_user] = fake_get_current_user
    app.dependency_overrides[rest_api.get_db_session] = fake_get_db
    try:
        resp = client.get("/api/users")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()


def test_get_users_customer_returns_403(app_with_overrides):
    app = app_with_overrides
    client = TestClient(app)
    from app import rest_api

    async def fake_get_current_user(request=None):
        u = MagicMock()
        u.role = "customer"
        u.id = 2
        u.uuid = "uuid-2"
        u.email = "c@x"
        u.username = "customer"
        u.full_name = "Customer"
        u.is_active = True
        u.branch_code = None
        u.created_at = "2024-01-01"
        u.updated_at = "2024-01-01"
        return u

    async def fake_get_db():
        class _S:
            async def execute(self_inner, stmt):
                class _R:
                    def scalars(self_inner2):
                        return self_inner2
                    def all(self_inner2):
                        return []
                return _R()
        yield _S()

    app.dependency_overrides[rest_api.get_current_user] = fake_get_current_user
    app.dependency_overrides[rest_api.get_db_session] = fake_get_db
    try:
        resp = client.get("/api/users")
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
