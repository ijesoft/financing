import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import strawberry
from fastapi import HTTPException, status
from sqlalchemy import select, desc
from strawberry.types import Info

from .auth.security import (
    check_password_complexity,
    check_password_history,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from .auth.totp import generate_qr_base64, generate_totp_secret, get_totp_uri, verify_totp
from .config import settings
from .database.pg_user_crud import UserCRUD
from .database.pg_models import AuditLog, PasswordHistory, UserSession, UserBranchAssignment
from .database import get_async_session_local
from .database.redis_client import get_redis
from .models import PyObjectId, UserCreate, UserInDB, UserUpdate
from .schema import LoginInput, LoginResponse, UserCreateInput, UserResponse, UsersResponse, UserType, UserUpdateInput


# ── Audit Log GraphQL Types ───────────────────────────────────────────────────

@strawberry.type
class AuditLogType:
    id: int
    user_id: Optional[str] = strawberry.field(name="userId", default=None)
    username: Optional[str] = None
    role: Optional[str] = None
    action: str
    entity: Optional[str] = None
    entity_id: Optional[str] = strawberry.field(name="entityId", default=None)
    ip_address: Optional[str] = strawberry.field(name="ipAddress", default=None)
    status: str
    detail: Optional[str] = None
    created_at: datetime = strawberry.field(name="createdAt")


@strawberry.type
class AuditLogsResponse:
    success: bool
    message: str
    logs: List[AuditLogType]
    total: int

# ── Available roles ───────────────────────────────────────────────────────────
VALID_ROLES = {"admin", "loan_officer", "teller", "branch_manager", "auditor", "customer", "book_keeper"}

def convert_user_db_to_user_type(user_db: UserInDB) -> UserType:
    """Convert UserInDB to UserType schema"""
    return UserType(
        id=str(user_db.id),
        email=user_db.email,
        username=user_db.username,
        full_name=user_db.full_name,
        is_active=user_db.is_active,
        role=user_db.role,
        branch_id=getattr(user_db, 'branch_id', None),
        branch_code=getattr(user_db, 'branch_code', None),
        created_at=user_db.created_at,
        updated_at=user_db.updated_at
    )

@strawberry.type
class Query:
    @strawberry.field
    async def users(self, info: Info, skip: int = 0, limit: int = 100) -> UsersResponse:
        """Get all users"""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise Exception("Not authorized")

        try:
            users_collection = get_users_collection()
            user_crud = UserCRUD(users_collection)
            
            users_db = await user_crud.get_users(skip=skip, limit=limit)
            total = await user_crud.count_users()
            
            users = [convert_user_db_to_user_type(user_db) for user_db in users_db]
            
            return UsersResponse(
                success=True,
                message="Users retrieved successfully",
                users=users,
                total=total
            )
        except Exception as e:
            return UsersResponse(
                success=False,
                message=f"Error retrieving users: {str(e)}",
                users=[],
                total=0
            )

    @strawberry.field
    async def user(self, info: Info, user_id: str) -> UserResponse:
        """Get user by ID"""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or (current_user.role != "admin" and str(current_user.id) != user_id):
            raise Exception("Not authorized")

        try:
            users_collection = get_users_collection()
            user_crud = UserCRUD(users_collection)
            
            user_db = await user_crud.get_user_by_id(user_id)
            if not user_db:
                return UserResponse(
                    success=False,
                    message="User not found"
                )
            
            user = convert_user_db_to_user_type(user_db)
            return UserResponse(
                success=True,
                message="User retrieved successfully",
                user=user
            )
        except Exception as e:
            return UserResponse(
                success=False,
                message=f"Error retrieving user: {str(e)}"
            )

    @strawberry.field
    async def audit_logs(
        self,
        info: Info,
        skip: int = 0,
        limit: int = 100,
        search_term: Optional[str] = None,
    ) -> AuditLogsResponse:
        """Get audit logs from PostgreSQL. Admin and Auditor only."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "auditor"):
            raise Exception("Not authorized — admin or auditor role required")

        try:
            async with get_async_session_local()() as session:
                stmt = select(AuditLog).order_by(desc(AuditLog.created_at))
                if search_term:
                    from sqlalchemy import or_, cast, String
                    pattern = f"%{search_term}%"
                    stmt = stmt.where(
                        or_(
                            AuditLog.username.ilike(pattern),
                            AuditLog.action.ilike(pattern),
                            AuditLog.entity.ilike(pattern),
                            AuditLog.ip_address.ilike(pattern),
                        )
                    )
                count_stmt = select(AuditLog)
                if search_term:
                    count_stmt = count_stmt.where(
                        or_(
                            AuditLog.username.ilike(f"%{search_term}%"),
                            AuditLog.action.ilike(f"%{search_term}%"),
                            AuditLog.entity.ilike(f"%{search_term}%"),
                        )
                    )
                total_result = await session.execute(count_stmt)
                total = len(total_result.scalars().all())

                stmt = stmt.offset(skip).limit(limit)
                result = await session.execute(stmt)
                rows = result.scalars().all()

            logs = [
                AuditLogType(
                    id=row.id,
                    user_id=row.user_id,
                    username=row.username,
                    role=row.role,
                    action=row.action,
                    entity=row.entity,
                    entity_id=row.entity_id,
                    ip_address=row.ip_address,
                    status=row.status,
                    detail=row.detail,
                    created_at=row.created_at,
                )
                for row in rows
            ]
            return AuditLogsResponse(success=True, message="OK", logs=logs, total=total)
        except Exception as e:
            return AuditLogsResponse(success=False, message=f"Error: {str(e)}", logs=[], total=0)


@strawberry.type
class Mutation:
    @strawberry.field
    async def login(self, input: LoginInput) -> LoginResponse:
        """User login — returns access + refresh tokens. If 2FA enabled, requires a second step."""
        users_collection = get_users_collection()
        user_crud = UserCRUD(users_collection)


        user_db = await user_crud.get_user_by_username(input.username)
        if not user_db:
            user_db = await user_crud.get_user_by_email(input.username)

        if not user_db or not verify_password(input.password, user_db.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Incorrect username or password")

        if not user_db.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

        user_id = str(user_db.id)

        # ── 2FA gate ──────────────────────────────────────────────────────────
        totp_secret = (user_db.model_extra or {}).get("totp_secret") if hasattr(user_db, "model_extra") else None
        totp_enabled = bool(getattr(user_db, "totp_enabled", False))
        if totp_enabled and input.totp_code:
            if not totp_secret or not verify_totp(totp_secret, input.totp_code):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")
        elif totp_enabled and not input.totp_code:
            # Issue a short-lived temp token so the client can submit OTP
            temp_token = create_access_token(
                {"sub": user_id, "requires_2fa": True},
                expires_delta=timedelta(minutes=settings.TOTP_TEMP_TOKEN_EXPIRE_MINUTES),
            )
            return LoginResponse(access_token=temp_token, token_type="temp_2fa", user=convert_user_db_to_user_type(user_db))

        # ── Session limit ─────────────────────────────────────────────────────
        redis = await get_redis()
        session_count_key = f"sessions:count:{user_id}"
        count = await redis.incr(session_count_key)
        if count == 1:
            await redis.expire(session_count_key, 86400 * 30)
        if count > settings.MAX_CONCURRENT_SESSIONS:
            await redis.decr(session_count_key)
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail=f"Max {settings.MAX_CONCURRENT_SESSIONS} concurrent sessions reached. Please logout from another device.")

        # ── Issue tokens ──────────────────────────────────────────────────────
        access_token = create_access_token({"sub": user_id})
        refresh_token, jti = create_refresh_token({"sub": user_id})

        # Store refresh token in Redis (TTL = 30 days in seconds)
        await redis.setex(
            f"refresh:{user_id}:{jti}",
            settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
            "valid",
        )

        user = convert_user_db_to_user_type(user_db)
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user=user,
        )

    @strawberry.field
    async def refresh_access_token(self, refresh_token: str) -> LoginResponse:
        """Exchange a valid refresh token for a new access token."""
        try:
            payload = verify_token(refresh_token)
        except HTTPException:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

        user_id = payload.get("sub")
        jti = payload.get("jti")
        redis = await get_redis()
        if not await redis.get(f"refresh:{user_id}:{jti}"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

        # Rotate: revoke old, issue new
        await redis.delete(f"refresh:{user_id}:{jti}")
        new_access = create_access_token({"sub": user_id})
        new_refresh, new_jti = create_refresh_token({"sub": user_id})
        await redis.setex(
            f"refresh:{user_id}:{new_jti}",
            settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
            "valid",
        )

        users_collection = get_users_collection()
        user_crud = UserCRUD(users_collection)
        user_db = await user_crud.get_user_by_id(user_id)
        user = convert_user_db_to_user_type(user_db) if user_db else None

        return LoginResponse(access_token=new_access, refresh_token=new_refresh, token_type="bearer", user=user)

    @strawberry.field
    async def logout(self, info: Info, refresh_token: Optional[str] = None) -> bool:
        """Revoke the current session / refresh token."""
        current_user = info.context.get("current_user")
        if not current_user:
            return False
        user_id = str(current_user.id)
        redis = await get_redis()
        if refresh_token:
            try:
                payload = verify_token(refresh_token)
                jti = payload.get("jti")
                if jti:
                    await redis.delete(f"refresh:{user_id}:{jti}")
            except Exception:
                pass
        # Decrement session counter
        await redis.decr(f"sessions:count:{user_id}")
        return True

    # ── 2FA mutations ─────────────────────────────────────────────────────────
    @strawberry.field
    async def enroll_2fa(self, info: Info) -> str:
        """Generate a TOTP secret + QR code for the current user. Returns base64 PNG."""
        current_user = info.context.get("current_user")
        if not current_user:
            raise Exception("Not authenticated")
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, current_user.username)
        qr_b64 = generate_qr_base64(uri)
        # Persist secret to MongoDB (requires model field update)
        users_collection = get_users_collection()
        await users_collection.update_one(
            {"_id": current_user.id},
            {"$set": {"totp_secret": secret, "totp_enabled": False}}
        )
        return qr_b64

    @strawberry.field
    async def verify_2fa(self, info: Info, otp_code: str) -> bool:
        """Confirm the OTP during enrollment → marks 2FA as active."""
        current_user = info.context.get("current_user")
        if not current_user:
            raise Exception("Not authenticated")
        users_collection = get_users_collection()
        user_doc = await users_collection.find_one({"_id": current_user.id})
        secret = (user_doc or {}).get("totp_secret")
        if not secret:
            raise Exception("No TOTP secret found. Call enroll2fa first.")
        if not verify_totp(secret, otp_code):
            raise Exception("Invalid OTP code")
        await users_collection.update_one(
            {"_id": current_user.id},
            {"$set": {"totp_enabled": True}}
        )
        return True

    @strawberry.field
    async def disable_2fa(self, info: Info, otp_code: str) -> bool:
        """Disable 2FA after verifying current OTP."""
        current_user = info.context.get("current_user")
        if not current_user:
            raise Exception("Not authenticated")
        users_collection = get_users_collection()
        user_doc = await users_collection.find_one({"_id": current_user.id})
        secret = (user_doc or {}).get("totp_secret")
        if not secret or not verify_totp(secret, otp_code):
            raise Exception("Invalid OTP code")
        await users_collection.update_one(
            {"_id": current_user.id},
            {"$unset": {"totp_secret": "", "totp_enabled": ""}}
        )
        return True

    @strawberry.field
    async def create_user(self, info: Info, input: UserCreateInput) -> UserResponse:
        """Create a new user. Admin only."""
        # AuthZ: admin role required. Raise BEFORE the try/except so the
        # broad exception handler in this resolver cannot swallow it.
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise Exception("admin role required")

        # Validate role
        if input.role not in VALID_ROLES:
            return UserResponse(success=False, message=f"Invalid role. Choose from: {', '.join(sorted(VALID_ROLES))}")

        # Password complexity
        ok, reason = check_password_complexity(input.password)
        if not ok:
            return UserResponse(success=False, message=reason)

        try:
            users_collection = get_users_collection()
            user_crud = UserCRUD(users_collection)

            if await user_crud.get_user_by_email(input.email):
                return UserResponse(success=False, message="User with this email already exists")
            if await user_crud.get_user_by_username(input.username):
                return UserResponse(success=False, message="User with this username already exists")

            user_create = UserCreate(
                email=input.email,
                username=input.username,
                full_name=input.full_name,
                password=input.password,
                role=input.role,
                branch_id=input.branch_id,
                branch_code=input.branch_code,
            )
            user_db = await user_crud.create_user(user_create)

            # Store initial password in history
            async with get_async_session_local()() as session:
                session.add(PasswordHistory(
                    user_id=str(user_db.id),
                    hashed_password=user_db.hashed_password,
                ))
                # Persist branch assignment if provided
                if input.branch_id or input.branch_code:
                    # Upsert branch assignment
                    from sqlalchemy import select as sa_select
                    existing_ba = await session.execute(
                        sa_select(UserBranchAssignment).where(
                            UserBranchAssignment.user_id == str(user_db.id)
                        )
                    )
                    ba_row = existing_ba.scalar_one_or_none()
                    if ba_row:
                        ba_row.branch_id = input.branch_id
                        ba_row.branch_code = input.branch_code
                    else:
                        session.add(UserBranchAssignment(
                            user_id=str(user_db.id),
                            branch_id=input.branch_id,
                            branch_code=input.branch_code,
                        ))
                await session.commit()

            return UserResponse(success=True, message="User created", user=convert_user_db_to_user_type(user_db))
        except Exception as exc:
            return UserResponse(success=False, message=f"Error creating user: {exc}")

    @strawberry.field
    async def update_user(self, info: Info, user_id: str, input: UserUpdateInput) -> UserResponse:
        """Update a user. Admins can update any user; others can only update themselves."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or (current_user.role != "admin" and str(current_user.id) != user_id):
            raise Exception("Not authorized")

        # AuthZ: only admins can change role, and admins cannot promote
        # (or demote) themselves — that escalation must be done by a
        # second admin to maintain the principle of two-person control.
        if input.role is not None:
            if current_user.role != "admin":
                raise Exception("not authorized: only admins can change role")
            if str(current_user.id) == user_id:
                raise Exception("not authorized: cannot change your own role")

        # Validate role if being changed
        if input.role and input.role not in VALID_ROLES:
            return UserResponse(success=False, message=f"Invalid role. Choose from: {', '.join(sorted(VALID_ROLES))}")

        # Password policy check if password is being changed
        if input.password:
            ok, reason = check_password_complexity(input.password)
            if not ok:
                return UserResponse(success=False, message=reason)

            # Check history
            async with get_async_session_local()() as session:
                result = await session.execute(
                    select(PasswordHistory)
                    .where(PasswordHistory.user_id == user_id)
                    .order_by(PasswordHistory.created_at.desc())
                    .limit(5)
                )
                history_rows = result.scalars().all()
                history_hashes = [r.hashed_password for r in history_rows]
            if not check_password_history(input.password, history_hashes):
                return UserResponse(success=False, message="Cannot reuse one of your last 5 passwords.")

        try:
            users_collection = get_users_collection()
            user_crud = UserCRUD(users_collection)
            user_update = UserUpdate(
                email=input.email,
                username=input.username,
                full_name=input.full_name,
                is_active=input.is_active,
                role=input.role,
                password=input.password,
            )
            user_db = await user_crud.update_user(user_id, user_update)
            if not user_db:
                return UserResponse(success=False, message="User not found")

            # Persist new password to history
            if input.password and user_db:
                async with get_async_session_local()() as session:
                    session.add(PasswordHistory(
                        user_id=str(user_db.id),
                        hashed_password=user_db.hashed_password,
                    ))
                    await session.commit()

            # Persist branch assignment changes
            if input.branch_id is not None or input.branch_code is not None:
                async with get_async_session_local()() as session:
                    from sqlalchemy import select as sa_select
                    existing_ba = await session.execute(
                        sa_select(UserBranchAssignment).where(
                            UserBranchAssignment.user_id == user_id
                        )
                    )
                    ba_row = existing_ba.scalar_one_or_none()
                    if ba_row:
                        if input.branch_id is not None:
                            ba_row.branch_id = input.branch_id
                        if input.branch_code is not None:
                            ba_row.branch_code = input.branch_code
                    else:
                        session.add(UserBranchAssignment(
                            user_id=user_id,
                            branch_id=input.branch_id,
                            branch_code=input.branch_code,
                        ))
                    await session.commit()

            return UserResponse(success=True, message="User updated", user=convert_user_db_to_user_type(user_db))
        except Exception as exc:
            return UserResponse(success=False, message=f"Error updating user: {exc}")

    @strawberry.field
    async def delete_user(self, info: Info, user_id: str) -> UserResponse:
        """Delete a user"""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise Exception("Not authorized")

        try:
            users_collection = get_users_collection()
            user_crud = UserCRUD(users_collection)

            success = await user_crud.delete_user(user_id)
            if not success:
                return UserResponse(
                    success=False,
                    message="User not found"
                )

            return UserResponse(
                success=True,
                message="User deleted successfully"
            )
        except Exception as e:
            return UserResponse(
                success=False,
                message=f"Error deleting user: {str(e)}"
            )