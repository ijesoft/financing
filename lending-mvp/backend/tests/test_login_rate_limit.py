"""
TDD tests for Task A7: Login rate-limit + account lockout.

Goals:
- 5 failed logins with the same username still return 401.
- The 6th attempt returns 429.
- Both username-based and IP-based rate limits are checked.
- When BANKING_GRADE_MODE is OFF, the rate-limit is bypassed (old behavior).
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# In-memory stand-in for Redis' INCR + EXPIRE
# ---------------------------------------------------------------------------
class FakeRedis:
    def __init__(self):
        self._store: dict[str, int] = {}
        self._ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    async def expire(self, key: str, ttl: int) -> None:
        self._ttls[key] = ttl

    async def aclose(self):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_login_app():
    """Build a small FastAPI app that exposes the /api-login/ route only,
    with `app.login_endpoint.rate_limit_check` and friends monkey-patched."""
    from app import login_endpoint
    app = FastAPI()
    app.include_router(login_endpoint.router, prefix="")
    return app, login_endpoint


def _patch_db(monkeypatch, login_endpoint):
    """Make UserCRUD return None so login fails (no DB required)."""

    class _UserCRUD:
        def __init__(self, db):
            self.db = db
        async def get_user_by_username(self, username):
            return None
        async def get_user_by_email(self, email):
            return None

    monkeypatch.setattr(login_endpoint, "UserCRUD", _UserCRUD)

    @login_endpoint.get_async_session_local.register
    def _factory():
        class _S:
            async def __aenter__(self_inner):
                return self_inner
            async def __aexit__(self_inner, *args):
                return False
        return _S()
    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_login_rate_limit_5_failures_6th_returns_429(monkeypatch):
    """5 failed logins -> 401, 6th -> 429."""
    app, login_endpoint = _build_login_app()

    fake = FakeRedis()
    # Patch at the source: redis_client.get_redis is the function actually
    # called by rate_limit_check.
    monkeypatch.setattr("app.database.redis_client.get_redis", AsyncMock(return_value=fake))
    monkeypatch.setattr(login_endpoint, "get_async_session_local", lambda: _noop_session_factory())

    # Bypass the old UserCRUD (no DB): always return None → 401.
    class _UserCRUD:
        def __init__(self, db):
            self.db = db
        async def get_user_by_username(self, username):
            return None
        async def get_user_by_email(self, email):
            return None
    monkeypatch.setattr(login_endpoint, "UserCRUD", _UserCRUD)

    # Force the banking-grade flag ON for the test.
    monkeypatch.setattr("app.feature_flags.flags.banking_grade_mode", True)

    client = TestClient(app)
    payload = {"username": "alice", "password": "wrong"}

    for i in range(5):
        r = client.post("/api-login/", json=payload)
        assert r.status_code == 401, f"Attempt {i+1}: expected 401, got {r.status_code}: {r.text}"

    r6 = client.post("/api-login/", json=payload)
    assert r6.status_code == 429, f"Attempt 6: expected 429, got {r6.status_code}: {r6.text}"


def test_login_rate_limit_per_username_isolated(monkeypatch):
    """Locking alice does not lock bob — independent rate-limit buckets."""
    app, login_endpoint = _build_login_app()
    fake = FakeRedis()
    monkeypatch.setattr("app.database.redis_client.get_redis", AsyncMock(return_value=fake))
    monkeypatch.setattr(login_endpoint, "get_async_session_local", lambda: _noop_session_factory())
    monkeypatch.setattr("app.feature_flags.flags.banking_grade_mode", True)

    class _UserCRUD:
        def __init__(self, db):
            self.db = db
        async def get_user_by_username(self, username):
            return None
        async def get_user_by_email(self, email):
            return None
    monkeypatch.setattr(login_endpoint, "UserCRUD", _UserCRUD)

    client = TestClient(app)

    # Burn alice's bucket
    for _ in range(5):
        client.post("/api-login/", json={"username": "alice", "password": "x"})
    r = client.post("/api-login/", json={"username": "alice", "password": "x"})
    assert r.status_code == 429

    # bob's bucket should still be fresh
    r_bob = client.post("/api-login/", json={"username": "bob", "password": "x"})
    assert r_bob.status_code == 401, f"Bob should not be locked: {r_bob.text}"


def test_login_rate_limit_disabled_when_flag_off(monkeypatch):
    """When BANKING_GRADE_MODE is off, the limit is NOT enforced."""
    app, login_endpoint = _build_login_app()
    fake = FakeRedis()
    monkeypatch.setattr("app.database.redis_client.get_redis", AsyncMock(return_value=fake))
    monkeypatch.setattr(login_endpoint, "get_async_session_local", lambda: _noop_session_factory())
    monkeypatch.setattr("app.feature_flags.flags.banking_grade_mode", False)

    class _UserCRUD:
        def __init__(self, db):
            self.db = db
        async def get_user_by_username(self, username):
            return None
        async def get_user_by_email(self, email):
            return None
    monkeypatch.setattr(login_endpoint, "UserCRUD", _UserCRUD)

    client = TestClient(app)
    payload = {"username": "carol", "password": "x"}
    for _ in range(10):
        r = client.post("/api-login/", json=payload)
        assert r.status_code == 401, r.text
    # 11th still 401, never 429, because the flag is off
    r = client.post("/api-login/", json=payload)
    assert r.status_code == 401, r.text


def test_login_rate_limit_calls_username_and_ip_keys(monkeypatch):
    """The login handler should consult rate_limit_check for both
    username and client IP."""
    app, login_endpoint = _build_login_app()
    fake = FakeRedis()
    monkeypatch.setattr("app.database.redis_client.get_redis", AsyncMock(return_value=fake))
    monkeypatch.setattr(login_endpoint, "get_async_session_local", lambda: _noop_session_factory())
    monkeypatch.setattr("app.feature_flags.flags.banking_grade_mode", True)

    class _UserCRUD:
        def __init__(self, db):
            self.db = db
        async def get_user_by_username(self, username):
            return None
        async def get_user_by_email(self, email):
            return None
    monkeypatch.setattr(login_endpoint, "UserCRUD", _UserCRUD)

    client = TestClient(app)
    r = client.post(
        "/api-login/",
        json={"username": "dave", "password": "x"},
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    assert r.status_code == 401, r.text

    keys = list(fake._store.keys())
    assert any("dave" in k for k in keys), f"No username-based key in {keys}"
    assert any("203.0.113.7" in k for k in keys), f"No IP-based key in {keys}"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
class _NoopSession:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False


class _NoopSessionFactory:
    def __call__(self):
        return _NoopSession()


def _noop_session_factory():
    return _NoopSessionFactory()
