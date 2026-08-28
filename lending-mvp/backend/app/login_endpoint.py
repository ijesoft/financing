from typing import Any, Optional, List
from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from .auth.security import verify_password, create_access_token, create_refresh_token
from .database import get_async_session_local
from .database.pg_core_models import User

logger = logging.getLogger(__name__)

router = APIRouter()


class UserCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, user: Any) -> Any: ...
    async def get_user_by_id(self, user_id: str) -> Optional[Any]:
        from sqlalchemy import or_
        if str(user_id).isdigit():
            stmt = select(User).where(or_(User.id == int(user_id), User.uuid == str(user_id)))
        else:
            stmt = select(User).where(User.uuid == str(user_id))
        result = await self.db.execute(stmt)
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

_LOGIN_MAX_FAILS = 5
_LOGIN_WINDOW_SEC = 900  # 15 min

async def _check_login_rate_limit(identifier: str):
    """Return True if allowed, False if blocked (5 fails / 15 min). Uses Redis, falls back to allow if Redis unavailable."""
    try:
        from .database.redis_client import get_redis
        r = await get_redis()
        key = f"login:fail:{identifier}"
        cnt = await r.get(key)
        if cnt and int(cnt) >= _LOGIN_MAX_FAILS:
            return False
        return True
    except Exception:
        return True

async def _record_login_failure(identifier: str):
    try:
        from .database.redis_client import get_redis
        r = await get_redis()
        key = f"login:fail:{identifier}"
        cnt = await r.incr(key)
        if cnt == 1:
            await r.expire(key, _LOGIN_WINDOW_SEC)
    except Exception:
        pass

async def _clear_login_failures(identifier: str):
    try:
        from .database.redis_client import get_redis
        r = await get_redis()
        await r.delete(f"login:fail:{identifier}")
    except Exception:
        pass

@router.post("/api-login/")
async def api_login(login_request: LoginRequest, request: Request):
    """Login endpoint that uses PostgreSQL directly without MongoDB dependencies."""
    # Rate-limit by username (banking-grade brute-force protection)
    if not await _check_login_rate_limit(login_request.username):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed login attempts. Try again in 15 minutes.")
    try:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            user_crud = UserCRUD(session)
            
            user_db = await user_crud.get_user_by_username(login_request.username)
            if not user_db:
                user_db = await user_crud.get_user_by_email(login_request.username)
            
            if not user_db or not verify_password(login_request.password, user_db.hashed_password):
                await _record_login_failure(login_request.username)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail="Incorrect username or password")
            
            if not user_db.is_active:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
            
            # Success — clear rate-limit counter
            await _clear_login_failures(login_request.username)
            
            user_id = str(user_db.uuid if user_db.uuid is not None else user_db.id)
            
            token_payload = {
                "sub": user_id,
                "username": user_db.username,
                "role": user_db.role,
                "branch_code": getattr(user_db, "branch_code", None),
            }
            access_token = create_access_token(token_payload)
            refresh_token, jti = create_refresh_token(token_payload)
            
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
                    "branchCode": getattr(user_db, "branch_code", None),
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login error: {str(e)}"
        )
