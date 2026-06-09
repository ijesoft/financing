"""
Seed default admin user for testing/development.
Run after migrations to ensure users table exists.
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from app.database.pg_core_models import User
from app.database.pg_models import Branch
from passlib.context import CryptContext
from uuid import uuid4

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed_admin_user():
    """
    Create a default admin user if one doesn't exist.
    Default credentials:
    - username: admin
    - password: admin123
    """
    try:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://lending_user:lending_password@localhost:5432/lending_db"
        )
        
        logger.info("🌱 Starting admin user seed...")
        
        # Create async engine
        engine = create_async_engine(database_url, echo=False)
        
        try:
            # Create session
            async_session = sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            
            async with async_session() as session:
                # Check if admin user already exists
                result = await session.execute(
                    select(User).where(User.username == "admin")
                )
                existing_user = result.scalar_one_or_none()
                
                if existing_user:
                    logger.info("✅ Admin user already exists")
                    return True
                
                # Check if default branch exists, create if not
                result = await session.execute(
                    select(Branch).where(Branch.code == "HQ")
                )
                default_branch = result.scalar_one_or_none()
                
                if not default_branch:
                    logger.info("📍 Creating default branch (HQ)...")
                    default_branch = Branch(
                        code="HQ",
                        name="Headquarters",
                        is_active=True
                    )
                    session.add(default_branch)
                    await session.flush()  # Get the ID
                
                # Create admin user
                hashed_password = pwd_context.hash("admin123")
                admin_user = User(
                    uuid=str(uuid4()),
                    email="admin@lending.local",
                    username="admin",
                    full_name="Administrator",
                    hashed_password=hashed_password,
                    role="admin",
                    branch_id=default_branch.id if default_branch else None,
                    branch_code=default_branch.code if default_branch else None,
                    is_active=True,
                    is_superuser=True
                )
                
                session.add(admin_user)
                await session.commit()
                
                logger.info("✅ Admin user created successfully")
                logger.info("   - Username: admin")
                logger.info("   - Password: admin123")
                logger.info("   - Email: admin@lending.local")
                logger.info("   ⚠️  Change this password in production!")
                return True
                
        finally:
            await engine.dispose()
            
    except Exception as e:
        logger.error(f"❌ Seeding failed: {e}", exc_info=True)
        return False


async def main():
    """Main entry point."""
    try:
        success = await seed_admin_user()
        if not success:
            sys.exit(1)
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
