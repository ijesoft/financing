"""
FastAPI authentication dependency.

Provides `get_current_user` — a FastAPI dependency that reads the
`access_token` cookie, decodes the JWT, and returns the authenticated
user as a dict.

This module replaces the previous MongoDB-backed authentication module
that was deleted. It uses the new PostgreSQL-backed JWT utilities from
`app.auth.security`.
"""

import logging
from typing import Optional

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from .security import settings as _settings
from .security import verify_token

logger = logging.getLogger(__name__)


def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency: extract and validate the JWT from the
    `access_token` cookie, then return a user dict.

    Raises 401 if the token is missing, invalid, or expired.

    The user dict contains at minimum:
        - id: str
        - username: str
        - role: str
        - branch_code: Optional[str]
    """
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Accept either "Bearer <token>" or raw token
    if token.startswith("Bearer "):
        token = token[len("Bearer "):]

    try:
        payload = jwt.decode(
            token,
            _settings.JWT_SECRET_KEY,
            algorithms=[_settings.ALGORITHM],
        )
    except JWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    return {
        "id": str(user_id),
        "username": payload.get("username", str(user_id)),
        "role": payload.get("role", "customer"),
        "branch_code": payload.get("branch_code"),
    }
