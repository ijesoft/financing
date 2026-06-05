"""
TDD tests for Task A6: Restrict CORS to an explicit allowlist.

Goals:
- OPTIONS preflight from http://evil.com must NOT receive `Access-Control-Allow-Origin: *`.
- OPTIONS preflight from http://localhost:3010 (allowed) must receive the
  correct `Access-Control-Allow-Origin: http://localhost:3010` (not `*`).
"""
import json
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware


def _build_app(cors_origins):
    """Build a tiny FastAPI app with the project's CORS configuration
    so we can test preflight responses without booting the full app."""
    app = FastAPI()

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    return app


def test_cors_blocks_evil_origin():
    """OPTIONS preflight from http://evil.com must not return ACAO=*."""
    app = _build_app(["http://localhost:3010"])
    client = TestClient(app)
    resp = client.options(
        "/probe",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao != "*", f"ACAO must not be wildcard, got {acao!r}"
    # No ACAO header at all = blocked.
    # (FastAPI returns no ACAO for disallowed origins; we just check it's not *.)
    assert "evil.com" not in acao, f"ACAO leaked evil.com: {acao!r}"


def test_cors_allows_configured_origin():
    """OPTIONS preflight from http://localhost:3010 echoes the origin."""
    app = _build_app(["http://localhost:3010"])
    client = TestClient(app)
    resp = client.options(
        "/probe",
        headers={
            "Origin": "http://localhost:3010",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao == "http://localhost:3010", f"Expected echoed origin, got {acao!r}"
    assert acao != "*"


def test_cors_origins_helper_reads_env(monkeypatch):
    """The helper that main.py uses must read CORS_ORIGINS as JSON list."""
    monkeypatch.setenv("CORS_ORIGINS", json.dumps(["http://x:3010", "http://y:3010"]))
    from app.cors import cors_origins
    origins = cors_origins()
    assert origins == ["http://x:3010", "http://y:3010"]


def test_cors_origins_helper_default(monkeypatch):
    """When CORS_ORIGINS is unset, default to localhost:3010."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    from app.cors import cors_origins
    origins = cors_origins()
    assert "http://localhost:3010" in origins
    assert origins != ["*"]


def test_cors_origins_helper_rejects_wildcard_only(monkeypatch):
    """CORS_ORIGINS=['*'] must not silently enable the wildcard."""
    monkeypatch.setenv("CORS_ORIGINS", json.dumps(["*"]))
    from app.cors import cors_origins
    origins = cors_origins()
    assert origins != ["*"]

