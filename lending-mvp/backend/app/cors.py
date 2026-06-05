"""
Centralised CORS configuration for the FastAPI app.

`cors_origins()` reads the `CORS_ORIGINS` env var (a JSON list) and falls
back to a localhost dev default. The main app calls this when registering
CORSMiddleware.
"""
from __future__ import annotations

import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)

# Restricted to common dev frontends in non-production. Production
# deployments MUST set CORS_ORIGINS explicitly.
DEFAULT_ORIGINS: List[str] = [
    "http://localhost:3010",
    "http://localhost:3000",
    "http://localhost:5173",
]


def cors_origins() -> List[str]:
    """Return the list of allowed CORS origins.

    Reads the `CORS_ORIGINS` env var as a JSON list. If unset, empty, or
    malformed, returns the dev defaults. Never returns ["*"].
    """
    raw = os.getenv("CORS_ORIGINS")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                # Defensive: filter out the literal "*" so we never
                # accidentally open the API to every origin.
                cleaned = [o for o in parsed if isinstance(o, str) and o != "*"]
                if cleaned:
                    return cleaned
                logger.warning("CORS_ORIGINS contained only '*' or non-strings; using defaults")
        except json.JSONDecodeError:
            logger.warning("CORS_ORIGINS is not valid JSON; falling back to defaults")
    return list(DEFAULT_ORIGINS)


# Restricted methods + headers for the banking-grade surface.
CORS_ALLOW_METHODS: List[str] = ["GET", "POST", "OPTIONS"]
CORS_ALLOW_HEADERS: List[str] = ["Authorization", "Content-Type"]
