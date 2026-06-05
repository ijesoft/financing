from typing import Any, Optional, List
from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.auth.security import verify_password, create_access_token, create_refresh_token
from app.database import get_async_session_local
from app.database.pg_core_models import User
from app.database.redis_client import get_redis, rate_limit_check
from app.feature_flags import flags

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Rate-limit configuration ────────────────────────────────────────────────
# Number of *failed* attempts allowed per window before lockout.
LOGIN_RL_MAX_REQUESTS = 5
LOGIN_RL_WINDOW_SECONDS = 300  # 5 minutes
LOGIN_RL_IP_MAX_REQUESTS = 20
LOGIN_RL_IP_WINDOW_SECONDS = 60


class UserCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, user: Any) -> Any: ...
    async def get_user_by_id(self, user_id: str) -> Optional[Any]:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[Any]:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> Optional[Any]:
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_users(self, skip: int = 0, limit: int = 100) -> List[Any]:
        result = await self.db.execute(
            select(User).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def count_users(self) -> int:
        result = await self.db.execute(select(func.count(User.id)))
        return result.scalar_one()

    async def update_user(self, user_id: str, user_update: Any) -> Optional[Any]:
        db_user = await self.get_user_by_id(user_id)
        if not db_user:
            return None
        for field, value in user_update.model_dump(exclude_none=True).items():
            setattr(db_user, field, value)
        await self.db.commit()
        await self.db.refresh(db_user)
        return db_user

    async def delete_user(self, user_id: str) -> bool:
        db_user = await self.get_user_by_id(user_id)
        if not db_user:
            return False
        await self.db.delete(db_user)
        await self.db.commit()
        return True


class LoginRequest(BaseModel):
    username: str
    password: str


def _client_ip(request: Request) -> str:
    """Extract the client IP, honouring X-Forwarded-For when present."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/api-login/")
async def api_login(login_request: LoginRequest, request: Request):
    """Login endpoint that uses PostgreSQL directly without MongoDB dependencies.

    When `BANKING_GRADE_MODE` is enabled, a per-username and per-IP
    rate-limit is enforced via Redis. Five failed logins per username
    inside a 5-minute window -> 429.
    """
    # ── Rate-limit gate (BANKING_GRADE_MODE only) ───────────────────────────
    if flags.banking_grade_mode:
        try:
            r = await get_redis()
            username_key = f"login:user:{login_request.username.lower()}"
            allowed_user = await rate_limit_check(
                username_key, LOGIN_RL_MAX_REQUESTS, LOGIN_RL_WINDOW_SECONDS
            )
            ip = _client_ip(request)
            ip_key = f"login:ip:{ip}"
            allowed_ip = await rate_limit_check(
                ip_key, LOGIN_RL_IP_MAX_REQUESTS, LOGIN_RL_IP_WINDOW_SECONDS
            )
            if not allowed_user or not allowed_ip:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many failed login attempts. Please try again later.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            # Fail OPEN: a Redis outage must not lock legitimate users out.
            logger.warning("Login rate-limit check failed (fail-open): %s", exc)

    try:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            user_crud = UserCRUD(session)

            user_db = await user_crud.get_user_by_username(login_request.username)
            if not user_db:
                user_db = await user_crud.get_user_by_email(login_request.username)

            if not user_db or not verify_password(login_request.password, user_db.hashed_password):
                logger.warning("Login failed for user: %s", login_request.username)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail="Incorrect username or password")

            if not user_db.is_active:
                logger.warning("Login blocked: user %s is inactive", login_request.username)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

            user_id = str(user_db.uuid if user_db.uuid is not None else user_db.id)

            access_token = create_access_token({"sub": user_id})
            refresh_token, jti = create_refresh_token({"sub": user_id})

            return {
                "accessToken": access_token,
                "tokenType": "bearer",
                "refreshToken": refresh_token,
                "user": {
                    "id": str(user_db.id),
                    "username": user_db.username,
                    "email": user_db.email,
                    "fullName": user_db.full_name,
                    "isActive": user_db.is_active,
                    "role": user_db.role,
                },
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login error: {str(e)}"
        )
