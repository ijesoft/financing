"""
AI Chat Assistant — session management, system prompt building,
and provider-agnostic LLM streaming for the in-app chat assistant.

Architecture
────────────
  AIProviderConfig   → Pydantic model for provider settings
  LLMProvider        → Abstract base class (provider-agnostic interface)
  OpenAIProvider     → OpenAI implementation (extensible for Anthropic, Gemini, etc.)
  ChatAssistantService → High-level service: sessions, history, streaming, audit

Redis key layout
────────────────
  chat:session:{session_id}              → List of JSON-encoded messages
  chat:session:{session_id}:meta         → Hash with user_id, user_role, created_at
  chat:user:{user_id}:sessions           → Set of active session IDs for the user
  ratelimit:chat:{user_id}               → Counter string (with TTL for rate limiting)
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from pydantic import BaseModel, Field

from .config import settings
from .database.redis_client import get_redis

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SESSION_TTL = 604_800  # 7 days (in seconds)
MAX_HISTORY_TURNS = 50  # maximum conversation turns stored in Redis
RATE_LIMIT_WINDOW = 60  # rate-limit window (seconds)
RATE_LIMIT_MAX_REQUESTS = 30  # max requests per window per user

# ── Pydantic models ───────────────────────────────────────────────────────────


class AIProviderConfig(BaseModel):
    """Configuration for an LLM provider."""

    provider: str = Field(
        default="openai",
        description="One of: openai, anthropic, gemini, ollama",
    )
    api_key: str | None = Field(
        default=None,
        description="API key. Falls back to env var (e.g. OPENAI_API_KEY).",
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="Model identifier (e.g. gpt-4o-mini, claude-3-haiku).",
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0 = deterministic).",
    )
    max_tokens: int = Field(
        default=1024,
        ge=1,
        le=16_384,
        description="Maximum tokens in the generated response.",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL for OpenAI-compatible APIs (e.g. Ollama).",
    )


class MessageModel(BaseModel):
    """A single conversation turn stored in Redis."""

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str  # ISO-8601 string


# ── Abstract provider ─────────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Provider-agnostic interface for streaming chat completions.

    Implementations must be async generators that yield content tokens
    as they are produced by the underlying model.
    """

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        config: AIProviderConfig,
    ) -> AsyncGenerator[str, None]:
        """Yield content tokens as they are generated.

        Args:
            messages: Conversation history in OpenAI-format
                      ``[{"role": "system"|"user"|"assistant", "content": "..."}]``.
            config:  Provider configuration overrides (model, temperature, etc.).

        Yields:
            Content tokens (strings) as they stream from the LLM.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying resources (HTTP clients, etc.)."""
        ...


# ── OpenAI provider ───────────────────────────────────────────────────────────


class OpenAIProvider(LLMProvider):
    """OpenAI / OpenAI-compatible provider via the ``openai`` SDK."""

    def __init__(self, config: AIProviderConfig) -> None:
        import openai

        self._config = config
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=2,
            timeout=30.0,
        )

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        config: AIProviderConfig,
    ) -> AsyncGenerator[str, None]:
        import openai

        model = config.model or self._config.model
        temperature = config.temperature if config.temperature is not None else self._config.temperature
        max_tokens = config.max_tokens or self._config.max_tokens

        # The usage information is included in the final chunk when
        # ``stream_options={"include_usage": True}`` is set.
        stream_kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )

        attempt = 0
        max_attempts = 3

        while attempt < max_attempts:
            try:
                response = await self._client.chat.completions.create(**stream_kwargs)
                async for chunk in response:
                    # Standard content delta
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

                    # Usage metadata arrives in the final chunk (no choices)
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        # We stash usage on the provider instance so the
                        # caller can inspect it after iteration completes.
                        self._last_usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens or 0,
                            "completion_tokens": chunk.usage.completion_tokens or 0,
                            "total_tokens": chunk.usage.total_tokens or 0,
                        }
                # Success — break out of retry loop
                return

            except openai.RateLimitError as exc:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                import asyncio
                wait = 2 ** attempt  # exponential back-off: 2, 4, 8 seconds
                logger.warning("OpenAI rate limited, retry %d/%d after %ds", attempt, max_attempts, wait)
                await asyncio.sleep(wait)
                continue

            except openai.APITimeoutError:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                import asyncio
                wait = 2 ** attempt
                logger.warning("OpenAI timeout, retry %d/%d after %ds", attempt, max_attempts, wait)
                await asyncio.sleep(wait)
                continue

            except openai.APIConnectionError:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                import asyncio
                wait = 2 ** attempt
                logger.warning("OpenAI connection error, retry %d/%d after %ds", attempt, max_attempts, wait)
                await asyncio.sleep(wait)
                continue

    async def close(self) -> None:
        await self._client.close()

    @property
    def last_usage(self) -> dict[str, int]:
        """Return the usage from the most recent stream, or zeros."""
        return getattr(self, "_last_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})


# ── Ollama provider ──────────────────────────────────────────────────────────


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider via the native Ollama API.

    Uses ``httpx`` to call the Ollama ``/api/chat`` endpoint with streaming.
    """

    def __init__(self, config: AIProviderConfig) -> None:
        import httpx

        self._config = config
        base_url = (config.base_url or "http://localhost:11434").rstrip("/")
        self._api_url = f"{base_url}/api/chat"
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        self._last_usage: dict[str, int] = {}

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        config: AIProviderConfig,
    ) -> AsyncGenerator[str, None]:
        import httpx

        model = config.model or self._config.model or "llama3.2"
        temperature = config.temperature if config.temperature is not None else self._config.temperature
        max_tokens = config.max_tokens or self._config.max_tokens

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        attempt = 0
        max_attempts = 2

        while attempt < max_attempts:
            try:
                async with self._client.stream("POST", self._api_url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            import json as _json
                            chunk = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue

                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content

                        if chunk.get("done"):
                            # Capture usage if available
                            self._last_usage = {
                                "prompt_tokens": chunk.get("prompt_eval_count", 0) or 0,
                                "completion_tokens": chunk.get("eval_count", 0) or 0,
                                "total_tokens": (chunk.get("prompt_eval_count", 0) or 0) + (chunk.get("eval_count", 0) or 0),
                            }
                # Success
                return

            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                import asyncio
                wait = 2 ** attempt
                logger.warning("Ollama request failed (attempt %d/%d), retrying in %ds: %s", attempt, max_attempts, wait, exc)
                await asyncio.sleep(wait)
                continue

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def last_usage(self) -> dict[str, int]:
        return self._last_usage


# ── Provider factory ──────────────────────────────────────────────────────────


def _create_provider(config: AIProviderConfig) -> LLMProvider:
    """Return the correct provider for *config.provider*.

    Raises:
        ValueError: If *provider* is not supported.
    """
    provider_map: dict[str, type[LLMProvider]] = {
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
        # Future providers can be registered here:
        # "anthropic": AnthropicProvider,
        # "gemini": GeminiProvider,
    }
    cls = provider_map.get(config.provider)
    if cls is None:
        supported = ", ".join(provider_map)
        raise ValueError(f"Unsupported provider '{config.provider}'. Supported: {supported}")
    return cls(config)


# ── System prompt builder ─────────────────────────────────────────────────────


_ROLE_DESCRIPTIONS = {
    "admin": (
        "You are a **system administrator** with full access to all modules, "
        "reports, and configuration settings."
    ),
    "loan_officer": (
        "You are a **loan officer** responsible for processing loan applications, "
        "reviewing customer profiles, and managing disbursements."
    ),
    "teller": (
        "You are a **teller** responsible for cash drawer operations, payment "
        "collection, and basic customer transactions."
    ),
    "branch_manager": (
        "You are a **branch manager** who oversees all branch operations, "
        "approves loans, and reviews performance reports."
    ),
    "auditor": (
        "You are an **auditor** with read-only access to all data, focused on "
        "reviewing transactions, journal entries, and reports for compliance."
    ),
    "customer": (
        "You are a **customer** accessing the customer portal to view your "
        "accounts, apply for loans, and manage payments."
    ),
}

_FEATURES_BY_CATEGORY: dict[str, list[str]] = {
    "Customer Management": [
        "Customers page — browse and search all customers",
        "New customer — create an individual or corporate customer record",
        "Edit customer — update customer details and KYC status",
        "Customer detail — view full profile, accounts, and transaction history",
    ],
    "Savings": [
        "Savings accounts — list and manage savings accounts",
        "Savings detail — view account balance and transaction history",
        "Savings transactions — deposit, withdraw, and transfer between accounts",
    ],
    "Loans": [
        "Loans list — view all loans with status, balance, and collection info",
        "Loan detail — full loan profile including amortization schedule",
        "Loan products — configure product types, interest rates, and terms",
        "Amortization schedule — view payment plan with due dates and amounts",
        "Payment history — record payments and view past transactions",
    ],
    "Transactions": [
        "Transactions page — view and search all financial transactions",
    ],
    "Collections": [
        "Collections dashboard — overview of overdue and pending collections",
        "Due collections — list of loans requiring collection action",
    ],
    "Accounting": [
        "Chart of accounts — manage the GL account hierarchy",
        "Journal entries — view posted journal entries",
        "Create journal entry — record manual GL entries",
    ],
    "Reports": [
        "Trial balance — period-end trial balance report",
        "Income statement — profit and loss statement",
        "Balance sheet — assets, liabilities, and equity report",
        "AR aging — accounts receivable aging (5 buckets)",
        "AP aging — accounts payable aging (5 buckets)",
    ],
    "Teller Operations": [
        "Cash drawer — manage teller cash drawer balances",
        "Payment gateway — process customer payments",
        "Transaction limits — configure per-teller transaction limits",
        "QR code — generate QR codes for payment reference",
    ],
    "Customer Portal": [
        "My portal — customer dashboard with account overview",
        "New loan application — apply for a loan online",
        "Repayment history — view past loan payments",
        "Transfer funds — transfer between own accounts",
        "Notifications — view system notifications and alerts",
    ],
    "Administration": [
        "Branches — manage branch locations and details",
        "Users — create and manage system users with role-based permissions",
        "Audit logs — view detailed audit trail of all system actions",
    ],
}


def _build_features_section() -> str:
    """Render the full feature catalogue as a markdown string."""
    lines = ["## System Features\n"]
    for category, items in _FEATURES_BY_CATEGORY.items():
        lines.append(f"### {category}")
        for item in items:
            lines.append(f"- **{item}**")
        lines.append("")
    return "\n".join(lines)


def build_system_prompt(
    user_role: str,
    page_context: str | None = None,
) -> str:
    """Build a dynamic system prompt tailored to the current user.

    Args:
        user_role:    The user's role string (e.g. ``"admin"``, ``"teller"``).
        page_context: The current page path (e.g. ``"/loans"``) or ``None``.

    Returns:
        A complete system prompt string.
    """
    role_description = _ROLE_DESCRIPTIONS.get(
        user_role,
        f"You are a user with the role **{user_role}**.",
    )

    context_hint = ""
    if page_context and page_context != "unknown":
        context_hint = f"\nThe user is currently on the page: **{page_context}**.\n"

    features_section = _build_features_section()

    prompt = f"""You are the official AI assistant for **LendingMVP — Lending & Savings Management System**.

{role_description}
{context_hint}
## Your Responsibilities
- Answer questions about how to use the LendingMVP system.
- Guide users to the correct pages and features based on their needs.
- Explain financial concepts, reports, and workflows relevant to lending and savings.
- Provide concise, actionable answers. Avoid lengthy disclaimers.
- If you do not know the answer, suggest the user contact their system administrator.

## Response Guidelines
- Be **helpful**, **concise**, and **professional**.
- When guiding users to a page, mention the page name and navigation path.
- Use **bold** for UI elements and page names.
- If the user asks about something outside the system's scope, politely redirect them.
- Do NOT reveal sensitive information such as API keys, passwords, or database credentials.
- Do NOT make specific guarantees about loan approvals, interest rates, or financial outcomes.

---

{features_section}

---

Remember: The user's role is **{user_role}**. Tailor your answers to their permissions and
responsibilities. If a feature is not available to their role, mention that politely and
suggest they contact an administrator if they need access.
"""
    return prompt.strip()


# ── Rate limiter ──────────────────────────────────────────────────────────────


async def check_rate_limit(user_id: str) -> tuple[bool, int]:
    """Check whether *user_id* has exceeded the chat rate limit.

    Uses a fixed-window counter in Redis with TTL.

    Returns:
        ``(allowed, retry_after_seconds)``.
        ``allowed`` is ``True`` if the request should proceed.
    """
    r = await get_redis()
    key = f"ratelimit:chat:{user_id}"
    current = await r.incr(key)
    if current == 1:
        await r.expire(key, RATE_LIMIT_WINDOW)
    remaining_ttl = await r.ttl(key)
    if current > RATE_LIMIT_MAX_REQUESTS:
        return False, max(1, remaining_ttl)
    return True, 0


# ── Chat assistant service ────────────────────────────────────────────────────


class ChatAssistantService:
    """High-level service for chat session management and LLM interaction.

    Usage::

        service = ChatAssistantService()
        async for event in service.stream_response(session_id, "Hello!"):
            ...
    """

    def __init__(self, config: AIProviderConfig | None = None) -> None:
        self._config = config or AIProviderConfig(
            provider=settings.ai_provider,
            model=settings.ai_model,
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_tokens,
            base_url=settings.ai_base_url,
        )
        self._provider: LLMProvider | None = None

    # ── Provider (lazily initialised) ──────────────────────────────────────

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = _create_provider(self._config)
        return self._provider

    # ── Session management ─────────────────────────────────────────────────

    async def get_or_create_session(
        self,
        session_id: str | None,
        user_id: str,
        user_role: str,
    ) -> str:
        """Return an existing or newly created session ID.

        If *session_id* is provided and exists in Redis, it is returned
        as-is (meta is refreshed). Otherwise a new UUID is generated.

        Args:
            session_id: Existing session ID, or ``None`` to create a new one.
            user_id:    The user's unique identifier.
            user_role:  The user's role string.

        Returns:
            The (possibly new) session ID.
        """
        r = await get_redis()
        now = datetime.now(timezone.utc).isoformat()

        if session_id:
            meta_key = f"chat:session:{session_id}:meta"
            exists = await r.exists(meta_key)
            if exists:
                # Refresh TTL on the session
                await r.expire(f"chat:session:{session_id}", SESSION_TTL)
                await r.expire(meta_key, SESSION_TTL)
                return session_id

        # Create a new session
        new_id = str(uuid.uuid4())
        session_key = f"chat:session:{new_id}"
        meta_key = f"chat:session:{new_id}:meta"

        # Store metadata as a hash
        await r.hset(meta_key, mapping={
            "user_id": user_id,
            "user_role": user_role,
            "created_at": now,
        })
        await r.expire(meta_key, SESSION_TTL)

        # Initialise empty message list
        await r.rpush(session_key, json.dumps({
            "role": "system",
            "content": "Session started",
            "timestamp": now,
        }))
        await r.expire(session_key, SESSION_TTL)

        # Track in user's session set
        user_sessions_key = f"chat:user:{user_id}:sessions"
        await r.sadd(user_sessions_key, new_id)
        await r.expire(user_sessions_key, SESSION_TTL)

        logger.info("Created new chat session %s for user %s (role=%s)", new_id, user_id, user_role)
        return new_id

    async def get_conversation_history(
        self,
        session_id: str,
        max_turns: int = 20,
    ) -> list[dict[str, str]]:
        """Load the last *max_turns* conversation turns from Redis.

        Returns messages in OpenAI-compatible format
        ``[{"role": "user"|"assistant", "content": "..."}]``.

        The initial ``system`` marker message is excluded.
        """
        r = await get_redis()
        session_key = f"chat:session:{session_id}"
        raw_messages = await r.lrange(session_key, -max_turns * 2 - 1, -1)

        messages: list[dict[str, str]] = []
        for raw in raw_messages:
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if msg.get("role") == "system":
                # Skip internal marker messages
                if msg.get("content") == "Session started":
                    continue
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })
        return messages

    async def _append_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append a single message to the Redis conversation list."""
        r = await get_redis()
        session_key = f"chat:session:{session_id}"
        msg = json.dumps({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await r.rpush(session_key, msg)
        # Trim to prevent unbounded growth
        await r.ltrim(session_key, -MAX_HISTORY_TURNS * 2, -1)
        await r.expire(session_key, SESSION_TTL)

    async def _get_session_meta(
        self,
        session_id: str,
    ) -> dict[str, str] | None:
        """Return the metadata hash for a session, or ``None``."""
        r = await get_redis()
        meta_key = f"chat:session:{session_id}:meta"
        meta = await r.hgetall(meta_key)
        return meta if meta else None

    async def clear_session(self, session_id: str) -> None:
        """Delete a chat session and all its data from Redis."""
        r = await get_redis()
        session_key = f"chat:session:{session_id}"
        meta_key = f"chat:session:{session_id}:meta"

        # Read meta to remove from user's session set
        meta = await r.hgetall(meta_key)
        if meta and "user_id" in meta:
            user_sessions_key = f"chat:user:{meta['user_id']}:sessions"
            await r.srem(user_sessions_key, session_id)

        await r.delete(session_key, meta_key)
        logger.info("Cleared chat session %s", session_id)

    async def list_user_sessions(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """List all active sessions for a given user."""
        r = await get_redis()
        user_sessions_key = f"chat:user:{user_id}:sessions"
        session_ids = await r.smembers(user_sessions_key)

        sessions: list[dict[str, Any]] = []
        for sid in session_ids:
            meta_key = f"chat:session:{sid}:meta"
            meta = await r.hgetall(meta_key)
            if not meta:
                # Orphaned reference — clean it up
                await r.srem(user_sessions_key, sid)
                continue
            session_key = f"chat:session:{sid}"
            msg_count = await r.llen(session_key)
            sessions.append({
                "session_id": sid,
                "user_id": meta.get("user_id"),
                "user_role": meta.get("user_role"),
                "created_at": meta.get("created_at"),
                "message_count": msg_count,
            })
        return sessions

    # ── Streaming ─────────────────────────────────────────────────────────

    async def stream_response(
        self,
        session_id: str,
        user_message: str,
        page_context: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Core streaming method.

        Yields structured event dicts that the HTTP layer serialises as SSE::

            {"type": "token",    "content": "the"}
            {"type": "done",     "session_id": "...", "usage": {...}}
            {"type": "error",    "message": "..."}
            {"type": "info",     "message": "..."}

        Args:
            session_id:   The chat session ID.
            user_message: The user's current message.
            page_context: Optional page path for context-aware prompts.

        Yields:
            Event dictionaries (see above).

        Raises:
            asyncio.CancelledError: If the client disconnects mid-stream.
        """
        session_meta = await self._get_session_meta(session_id)
        if not session_meta:
            yield {"type": "error", "message": "Session not found or expired."}
            return

        user_role = session_meta.get("user_role", "unknown")
        system_prompt = build_system_prompt(user_role, page_context)

        # Build the message list for the LLM
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Append conversation history
        history = await self.get_conversation_history(session_id)
        messages.extend(history)

        # Append the new user message
        messages.append({"role": "user", "content": user_message})

        # Persist user message to Redis *before* streaming
        await self._append_message(session_id, "user", user_message)

        collected_content: list[str] = []
        usage: dict[str, int] = {}

        try:
            # Stream tokens from the LLM provider
            async for token in self.provider.stream_chat(messages, self._config):
                collected_content.append(token)
                yield {"type": "token", "content": token}

            # Capture usage from the provider
            if hasattr(self.provider, "last_usage"):
                usage = self.provider.last_usage

        except Exception as exc:
            logger.exception("LLM streaming error for session %s", session_id)
            yield {
                "type": "error",
                "message": f"I'm sorry, I encountered an error while generating a response. Please try again. ({type(exc).__name__})",
            }
            return

        # Persist assistant response to Redis
        full_response = "".join(collected_content)
        if full_response.strip():
            await self._append_message(session_id, "assistant", full_response)

        yield {
            "type": "done",
            "session_id": session_id,
            "usage": usage,
        }

    async def close(self) -> None:
        """Release provider resources (HTTP client)."""
        if self._provider is not None:
            await self._provider.close()
            self._provider = None


# ── Module-level singleton (lazy) ─────────────────────────────────────────────

_service: ChatAssistantService | None = None


def get_chat_service() -> ChatAssistantService:
    """Return the module-level ``ChatAssistantService`` singleton."""
    global _service
    if _service is None:
        _service = ChatAssistantService()
    return _service


async def close_chat_service() -> None:
    """Close the module-level service (call on app shutdown)."""
    global _service
    if _service is not None:
        await _service.close()
        _service = None
