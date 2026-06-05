"""
Audit middleware — logs every GraphQL POST mutation to the PostgreSQL audit_logs table.
Registered as a Starlette middleware in main.py.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .database import get_async_session_local
from .database.pg_models import AuditLog

logger = logging.getLogger(__name__)


# ── Canonical audit-log writer ───────────────────────────────────────────────
async def audit_log(
    user_id: str | None,
    action: str,
    entity: str | None = None,
    entity_id: str | None = None,
    status: str = "success",
    detail: str | None = None,
    branch_code: str | None = None,
    ip_address: str | None = None,
    role: str | None = None,
    username: str | None = None,
    session: Any = None,
) -> None:
    """
    Canonical writer for the audit_logs table.

    Parameters mirror the AuditLog model columns. Missing context
    (user/role/branch) is stored as NULL; rows are still written so that
    authentication failures and unauthenticated traffic remain auditable.

    A *session* may be passed in (useful for tests sharing a transaction).
    When omitted, the function opens its own short-lived session and
    commits before returning.
    """
    if session is not None:
        session.add(
            AuditLog(
                user_id=user_id,
                username=username,
                role=role,
                branch_code=branch_code,
                action=action,
                entity=entity,
                entity_id=entity_id,
                ip_address=ip_address,
                status=status,
                detail=detail,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return

    session_factory = get_async_session_local()
    async with session_factory() as own_session:
        own_session.add(
            AuditLog(
                user_id=user_id,
                username=username,
                role=role,
                branch_code=branch_code,
                action=action,
                entity=entity,
                entity_id=entity_id,
                ip_address=ip_address,
                status=status,
                detail=detail,
                created_at=datetime.now(timezone.utc),
            )
        )
        await own_session.commit()


# GraphQL mutations to track (parsed from operation name or body)
_MUTATION_KEYWORD = "mutation"


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Intercepts POST requests to /graphql, reads the operation name,
    and writes an audit row to PostgreSQL after the response is sent.

    Notes:
    - Only mutations are logged (queries are read-only).
    - The request body is read once and cached on the request state.
    - PG errors are swallowed so they never break the API.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only audit GraphQL POST requests
        if request.url.path != "/graphql" or request.method != "POST":
            return await call_next(request)

        # Read + cache body (Starlette body can only be read once)
        body_bytes = await request.body()

        # Monkey-patch receive so downstream can still read body
        async def receive():
            return {"type": "http.request", "body": body_bytes}

        request._receive = receive  # type: ignore[attr-defined]

        # Parse operation details before calling next
        action = "graphql_mutation"
        try:
            payload: dict[str, Any] = json.loads(body_bytes or b"{}")
            query_str: str = payload.get("query", "")
            # Only log mutations
            if _MUTATION_KEYWORD not in query_str.lower():
                return await call_next(request)
            # Extract first operation name if present
            op_name = payload.get("operationName") or _extract_operation(query_str)
            if op_name:
                action = op_name
        except Exception:
            pass

        start = time.monotonic()
        response: Response = await call_next(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Write audit record via the canonical writer.
        try:
            current_user = getattr(request.state, "current_user", None)
            user_id = str(getattr(current_user, "id", "")) if current_user else None
            username = getattr(current_user, "username", None) if current_user else None
            role = getattr(current_user, "role", None) if current_user else None
            branch_code = getattr(current_user, "branch_code", None) if current_user else None

            ip = _get_client_ip(request)
            status_str = "success" if response.status_code < 400 else "failure"
            detail = json.dumps({"elapsed_ms": elapsed_ms, "status_code": response.status_code})

            await audit_log(
                user_id=user_id,
                username=username,
                role=role,
                branch_code=branch_code,
                action=action,
                entity="graphql",
                entity_id=None,
                ip_address=ip,
                status=status_str,
                detail=detail,
            )
        except Exception as exc:
            logger.warning("AuditMiddleware: failed to write audit log — %s", exc)

        return response


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_operation(query: str) -> str | None:
    """Extract the first word after 'mutation' keyword."""
    try:
        lower = query.strip().lower()
        if lower.startswith("mutation"):
            rest = query[len("mutation"):].strip()
            # Handle named mutations: "mutation CreateCustomer { ... }"
            if rest and rest[0].isalpha():
                return rest.split("{")[0].split("(")[0].strip()
    except Exception:
        pass
    return None
