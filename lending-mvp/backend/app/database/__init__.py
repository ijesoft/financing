"""
PostgreSQL-only database initialization.
Replaces MongoDB-based database initialization.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import models to register with Base - but DON'T create engine yet
from .base import Base
from .pg_core_models import (
    User, Customer, SavingsAccount, SavingsTransaction, StandingOrder
)
from .pg_loan_models import (
    PGLoanProduct, LoanApplication, LoanCollateral, LoanGuarantor,
    CreditScore, LoanApplicationDocument, DisbursementChecklist, LoanTranche, PromiseToPay, LoanRestructureLog
)
from .pg_models import (
    Branch, UserBranchAssignment, AuditLog, UserSession, KYCDocument,
    Beneficiary, CustomerActivity, PasswordHistory, AMLAlert, PEPRecord
)
from .pg_accounting_models import GLAccount, JournalEntry, JournalLine

# Lazy initialization - don't create engine until it's actually needed
_engine = None
_AsyncSessionLocal = None

def get_engine():
    """Get or create the async engine."""
    global _engine
    if _engine is None:
        from ..config import settings
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine

def get_async_session_local():
    """Get or create the AsyncSessionLocal factory."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        engine = get_engine()
        _AsyncSessionLocal = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    return _AsyncSessionLocal

# Module-level attributes that use lazy initialization
class _LazyAttribute:
    """Lazy attribute accessor."""
    def __init__(self, factory):
        self._factory = factory
        self._value = None
    
    def _get(self):
        if self._value is None:
            self._value = self._factory()
        return self._value

# Keep backwards compatible module-level "engine" and "AsyncSessionLocal"
# But make them lazy so they don't get created at import time
# This is a workaround for Alembic imports

async def get_db_session():
    """FastAPI dependency that yields a PostgreSQL async session."""
    session_factory = get_async_session_local()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """Create all PostgreSQL tables (skip if they already exist)."""
    engine_obj = get_engine()
    async with engine_obj.begin() as conn:
        try:
            await conn.run_sync(Base.metadata.create_all)
            print("PostgreSQL tables created successfully.")
        except Exception as e:
            print(f"Table creation warning (tables may already exist): {e}")


async def drop_tables():
    """Drop all PostgreSQL tables (use with caution!)."""
    engine_obj = get_engine()
    async with engine_obj.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("PostgreSQL tables dropped successfully.")


def get_db():
    """Sync wrapper for async get_db_session (for use in sync contexts if needed)."""
    return get_db_session()

# Lazy module attributes - override __getattr__ at module level
# This is a hack but necessary for backwards compatibility with Alembic
import sys

class _ModuleWithLazyAttributes(sys.modules[__name__].__class__):
    @property
    def engine(self):
        return get_engine()
    
    @property
    def AsyncSessionLocal(self):
        return get_async_session_local()

sys.modules[__name__].__class__ = _ModuleWithLazyAttributes
