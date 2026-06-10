"""
REST API endpoints for frontend integration.
This module provides REST endpoints that the frontend can use instead of GraphQL.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from .database import get_async_session_local, get_db_session
from .database.pg_core_models import User, Customer
from .auth.dependencies import get_current_user, require_admin
from .auth.security import verify_password, create_access_token, create_refresh_token
from .auth.rbac import get_sql_branch_filter
from .ai_service import ask_ai

logger = logging.getLogger(__name__)

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api-login/")


# ── Response Models ──────────────────────────────────────────────────────────
class UserResponseModel(BaseModel):
    id: str
    email: str
    username: str
    fullName: str
    isActive: bool
    role: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class UsersListResponse(BaseModel):
    success: bool
    message: str
    users: List[UserResponseModel]
    total: int


# ── Auth Endpoints (legacy; re-enabled in main.py via login_endpoint) ────────
# Kept disabled here — login_endpoint.py owns /api-login/ in the new stack.
# @router.post("/api-login/")
# async def api_login(username: str, password: str, totp_code: Optional[str] = None):
#     """Login endpoint."""
#     ...


# ── Users Endpoints ──────────────────────────────────────────────────────────
@router.get("/api/users", response_model=UsersListResponse)
async def get_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Get all users. Admin only."""
    result = await db.execute(
        select(User).offset(skip).limit(limit)
    )
    users = result.scalars().all()
    return UsersListResponse(
        success=True,
        message="Users retrieved successfully",
        users=[
            UserResponseModel(
                id=str(u.uuid if u.uuid is not None else u.id),
                email=u.email,
                username=u.username,
                fullName=u.full_name,
                isActive=u.is_active,
                role=u.role,
                createdAt=str(u.created_at) if u.created_at else None,
                updatedAt=str(u.updated_at) if u.updated_at else None,
            )
            for u in users
        ],
        total=len(users),
    )


@router.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "Lending MVP API is running"}


@router.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Lending MVP API — Phase 2", "version": "2.0.0"}


# ── AI Endpoints ────────────────────────────────────────────────────────────
class AIAskRequest(BaseModel):
    question: str


class AIAskResponse(BaseModel):
    success: bool
    answer: str
    message: str = ""


@router.post("/api/ai/ask", response_model=AIAskResponse)
async def ai_ask(
    body: AIAskRequest,
    current_user: User = Depends(get_current_user),
):
    """Ask the AI assistant a question. Requires collections_officer, loan_officer, branch_manager, or admin role."""
    allowed_roles = ("collections_officer", "loan_officer", "branch_manager", "admin")
    if current_user.role not in allowed_roles:
        return AIAskResponse(success=False, answer="", message="Not authorized")

    if not body.question or not body.question.strip():
        return AIAskResponse(success=False, answer="", message="Question cannot be empty")

    if len(body.question) > 2000:
        return AIAskResponse(success=False, answer="", message="Question is too long (max 2000 characters)")

    answer = await ask_ai(body.question.strip())
    return AIAskResponse(success=True, answer=answer, message="")
