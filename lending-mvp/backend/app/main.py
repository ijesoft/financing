from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import os

from .cors import cors_origins, CORS_ALLOW_METHODS, CORS_ALLOW_HEADERS
from .database import create_tables
from .database.postgres import engine
from .database.redis_client import get_redis, close_redis
from .audit_middleware import AuditMiddleware
# Import the PostgreSQL-only enhanced seeder
try:
    from .utils.demo_seeder_enhanced import seed_demo_data_enhanced
    DEMO_SEEDER_AVAILABLE = True
except ImportError:
    DEMO_SEEDER_AVAILABLE = False
    seed_demo_data_enhanced = None

# Import all routers to register routes
from . import login_endpoint
from . import rest_api  # REST API endpoints for frontend
from . import chat_routes  # AI chat assistant endpoints
# from . import teller  # Disabled: MongoDB not configured  # Teller endpoints
from . import graphql as graphql_module  # Real Strawberry GraphQL endpoint

logger = logging.getLogger(__name__)


def _should_seed_demo_data() -> bool:
    """Return True iff SEED_DEMO_DATA=true AND ENVIRONMENT is unset or 'development'."""
    seed_demo = os.getenv("SEED_DEMO_DATA", "false").lower() == "true"
    environment = os.getenv("ENVIRONMENT", "development")
    if seed_demo and environment != "development":
        logger.warning(
            "SEED_DEMO_DATA=true but ENVIRONMENT=%s — refusing to seed demo data",
            environment,
        )
    return seed_demo and environment == "development"


# --- Pydantic Models for REST ---
class LoginRequest(BaseModel):
    username: str
    password: str


# --- App lifecycle ------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up — creating PostgreSQL tables...")
    await create_tables()
    logger.info("PostgreSQL tables ensured.")
    
    # Seed Chart of Accounts
    try:
        from .chart_of_accounts import seed_chart_of_accounts
        await seed_chart_of_accounts()
        logger.info("Chart of Accounts seeded.")
    except Exception as exc:
        logger.warning("CoA seeding failed (non-fatal): %s", exc)
    
    # Seed Demo Data (if enabled) - PostgreSQL-only
    try:
        if not _should_seed_demo_data():
            logger.info("Demo data seeding disabled (set SEED_DEMO_DATA=true to enable)")
        elif DEMO_SEEDER_AVAILABLE:
            logger.info("🌱 Seeding demo data (PostgreSQL-enhanced)...")
            await seed_demo_data_enhanced()
            logger.info("✅ Demo data seeded successfully")
        else:
            logger.warning("Demo data seeding requested but enhanced seeder not available. Install pymongo or use demo_seeder_enhanced.py")
    except Exception as exc:
        logger.warning("Demo data seeding failed (non-fatal): %s", exc)
    
    # Warm up Redis connection
    try:
        await get_redis()
        logger.info("Redis connection established.")
    except Exception as exc:
        logger.warning("Redis connection failed (non-fatal): %s", exc)
    yield
    # Shutdown
    try:
        await chat_routes.shutdown_chat_service()
    except Exception:
        pass
    await close_redis()
    await engine.dispose()
    logger.info("Shutdown complete.")


# --- Build app ---------------------------------------------------------------

app = FastAPI(title="Lending MVP API — Phase 2", lifespan=lifespan)

# Include login endpoint
app.include_router(login_endpoint.router, prefix="")

# Include REST API endpoints
app.include_router(rest_api.router, prefix="")
app.include_router(chat_routes.router, prefix="")
# app.include_router(teller.router, prefix="")  # Disabled

# Mount the real Strawberry GraphQL router
from strawberry.fastapi import GraphQLRouter

graphql_app = GraphQLRouter(graphql_module.schema, context_getter=graphql_module.get_context)
app.include_router(graphql_app, prefix="/graphql")

# Audit middleware (must be added before CORS so it runs on all requests)
app.add_middleware(AuditMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=CORS_ALLOW_HEADERS,
)


@app.get("/")
async def root():
    return {"message": "Lending MVP API — Phase 2", "version": "2.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}