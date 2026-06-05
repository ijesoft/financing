"""
FastAPI authentication dependencies.

`get_current_user` reads the access_token cookie (with a Bearer-token
fallback from the Authorization header) and returns the User row.

`require_admin` builds on top — 403 unless the user has the admin role.

The cookie name (`access_token`) is the same one `login_endpoint.api_login`
sets via `Set-Cookie`. We accept the value in either of two forms:

    "Bearer <jwt>"      (recommended)
    "<jwt>"             (legacy — old login_endpoint format)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db_session
from ..database.pg_core_models import User
from .security import verify_token

logger = logging.getLogger(__name__)


def _extract_token(request: Request) -> Optional[str]:
    """Pull the raw JWT from the request — cookie first, then Authorization header."""
    raw = request.cookies.get("access_token")
    if raw:
        return raw
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve the JWT to a User row.

    Raises 401 on missing / malformed / invalid / expired tokens.
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_token(token)
    except HTTPException:
        raise
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    # Accept either the numeric id or the uuid.
    stmt = select(User).where(
        or_(
            User.uuid == str(user_id),
            User.id == int(user_id) if str(user_id).isdigit() else False,
        )
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """403 unless the current user is an admin."""
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user
