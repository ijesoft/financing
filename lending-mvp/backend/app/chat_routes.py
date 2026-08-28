"""
REST API endpoints for the AI Chat Assistant.

Endpoints
─────────
  POST   /api/chat/stream           — SSE streaming chat
  GET    /api/chat/sessions          — List active sessions for current user
  DELETE /api/chat/sessions/{id}     — Delete a specific session
  GET    /api/chat/models            — List available AI models

All endpoints require a valid JWT (``Authorization: Bearer <token>``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .auth.dependencies import get_current_user
from .chat_assistant import (
    ChatAssistantService,
    check_rate_limit,
    get_chat_service,
)
from .config import settings
from .database.pg_core_models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat Assistant"])


# ── Request / Response models ─────────────────────────────────────────────────


class ChatStreamRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The user's message to the AI assistant.",
    )
    session_id: str | None = Field(
        default=None,
        description="Existing session ID to continue, or null for a new session.",
    )
    page_context: str | None = Field(
        default=None,
        description="Current page path for context-aware prompts (e.g. '/loans').",
    )


class SessionItem(BaseModel):
    session_id: str
    user_id: str
    user_role: str
    created_at: str
    message_count: int


class SessionListResponse(BaseModel):
    success: bool
    sessions: list[SessionItem]


class DeleteSessionResponse(BaseModel):
    success: bool
    message: str


class ModelItem(BaseModel):
    id: str
    provider: str
    display_name: str


class ModelListResponse(BaseModel):
    success: bool
    models: list[ModelItem]


# ── SSE serialisation helpers ─────────────────────────────────────────────────


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a dict as a Server-Sent Events message."""
    lines = [f"event: {event}", f"data: {json.dumps(data, default=str)}", ""]
    return "\n".join(lines)


async def _event_stream(
    service: ChatAssistantService,
    session_id: str,
    user_message: str,
    page_context: str | None,
) -> AsyncGenerator[str, None]:
    """Wrap the service's ``stream_response`` as SSE-formatted strings."""
    try:
        async for event in service.stream_response(session_id, user_message, page_context):
            event_type = event.get("type", "")
            if event_type == "token":
                yield _sse_event("token", {"token": event["content"]})
            elif event_type == "done":
                yield _sse_event("done", {
                    "session_id": event["session_id"],
                    "usage": {
                        "prompt_tokens": event.get("usage", {}).get("prompt_tokens", 0),
                        "completion_tokens": event.get("usage", {}).get("completion_tokens", 0),
                        "total_tokens": event.get("usage", {}).get("total_tokens", 0),
                    },
                })
            elif event_type == "error":
                yield _sse_event("error", {"message": event["message"]})
            elif event_type == "info":
                yield _sse_event("info", {"message": event["message"]})
    except asyncio.CancelledError:
        logger.info("Client disconnected from chat stream")
        yield _sse_event("done", {"session_id": session_id, "usage": {}})
    except Exception:
        logger.exception("Unexpected error in chat event stream")
        yield _sse_event("error", {"message": "An unexpected error occurred."})


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/api/chat/stream")
async def chat_stream(
    body: ChatStreamRequest,
    current_user: User = Depends(get_current_user),
):
    """Stream an AI chat response using Server-Sent Events.

    The response is a text/event-stream with these event types:

    - ``token`` — a single content token::

          event: token
          data: {"token": "the"}

    - ``done`` — streaming complete::

          event: done
          data: {"session_id": "abc-123", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}

    - ``error`` — a (possibly recoverable) error occurred::

          event: error
          data: {"message": "Rate limit exceeded"}
    """
    user_id = str(current_user.uuid or current_user.id)
    user_role = current_user.role

    # ── Rate limiting ──────────────────────────────────────────────────────
    allowed, retry_after = await check_rate_limit(user_id)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded. Please wait before sending another message."},
            headers={"Retry-After": str(retry_after)},
        )

    # ── Session management ─────────────────────────────────────────────────
    service = get_chat_service()
    try:
        session_id = await service.get_or_create_session(
            session_id=body.session_id,
            user_id=user_id,
            user_role=user_role,
        )
    except Exception as exc:
        logger.exception("Failed to create/get session for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialise chat session.",
        ) from exc

    # ── Streaming response ─────────────────────────────────────────────────
    return StreamingResponse(
        _event_stream(service, session_id, body.message, body.page_context),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        },
    )


@router.get("/api/chat/sessions", response_model=SessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
):
    """List all active chat sessions for the current user."""
    user_id = str(current_user.uuid or current_user.id)
    service = get_chat_service()

    try:
        sessions = await service.list_user_sessions(user_id)
    except Exception as exc:
        logger.exception("Failed to list sessions for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list chat sessions.",
        ) from exc

    return SessionListResponse(
        success=True,
        sessions=[
            SessionItem(
                session_id=s["session_id"],
                user_id=s["user_id"],
                user_role=s["user_role"],
                created_at=s["created_at"],
                message_count=s["message_count"],
            )
            for s in sessions
        ],
    )


@router.delete("/api/chat/sessions/{session_id}", response_model=DeleteSessionResponse)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """Delete a specific chat session and its history."""
    user_id = str(current_user.uuid or current_user.id)
    service = get_chat_service()

    # Verify ownership
    try:
        meta = await service._get_session_meta(session_id)
    except Exception as exc:
        logger.exception("Failed to read session meta %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to access session data.",
        ) from exc

    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    if meta.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this session.",
        )

    try:
        await service.clear_session(session_id)
    except Exception as exc:
        logger.exception("Failed to delete session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete chat session.",
        ) from exc

    return DeleteSessionResponse(
        success=True,
        message="Chat session deleted.",
    )


@router.get("/api/chat/models", response_model=ModelListResponse)
async def list_models(
    current_user: User = Depends(get_current_user),
):
    """List the AI models that are currently available.

    Returns the model configured in the backend settings plus any
    additional known models for the configured provider.
    """
    provider = settings.ai_provider
    configured_model = settings.ai_model

    # Known model catalog per provider
    provider_models: dict[str, list[dict[str, str]]] = {
        "openai": [
            {"id": "gpt-4o", "display_name": "GPT-4o"},
            {"id": "gpt-4o-mini", "display_name": "GPT-4o Mini"},
            {"id": "gpt-4-turbo", "display_name": "GPT-4 Turbo"},
            {"id": "gpt-4", "display_name": "GPT-4"},
            {"id": "gpt-3.5-turbo", "display_name": "GPT-3.5 Turbo"},
        ],
        "anthropic": [
            {"id": "claude-3-opus", "display_name": "Claude 3 Opus"},
            {"id": "claude-3-sonnet", "display_name": "Claude 3 Sonnet"},
            {"id": "claude-3-haiku", "display_name": "Claude 3 Haiku"},
        ],
        "gemini": [
            {"id": "gemini-pro", "display_name": "Gemini Pro"},
            {"id": "gemini-ultra", "display_name": "Gemini Ultra"},
        ],
        "ollama": [
            {"id": "llama3.2", "display_name": "Llama 3.2 (3B)"},
            {"id": "llama3.1", "display_name": "Llama 3.1 (8B)"},
            {"id": "mistral", "display_name": "Mistral (7B)"},
            {"id": "phi3", "display_name": "Phi-3 Mini (3.8B)"},
            {"id": "codellama", "display_name": "Code Llama (7B)"},
            {"id": "qwen2.5", "display_name": "Qwen 2.5 (7B)"},
            {"id": "deepseek-coder", "display_name": "DeepSeek Coder (6.7B)"},
        ],
    }

    known = provider_models.get(provider, [])
    # Ensure the configured model is first in the list
    configured_entry = next((m for m in known if m["id"] == configured_model), None)
    models: list[ModelItem] = []
    if configured_entry:
        models.append(ModelItem(
            id=configured_entry["id"],
            provider=provider,
            display_name=configured_entry["display_name"],
        ))
    for m in known:
        if m["id"] != configured_model:
            models.append(ModelItem(
                id=m["id"],
                provider=provider,
                display_name=m["display_name"],
            ))
    # If configured model is unknown, still include it
    if not configured_entry:
        models.insert(0, ModelItem(
            id=configured_model,
            provider=provider,
            display_name=configured_model,
        ))

    return ModelListResponse(success=True, models=models)


# ── Hook for app shutdown ─────────────────────────────────────────────────────

async def shutdown_chat_service() -> None:
    """Call from the app's lifespan shutdown to release provider resources."""
    from .chat_assistant import close_chat_service
    await close_chat_service()
